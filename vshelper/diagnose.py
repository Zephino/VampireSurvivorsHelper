"""Writes one report with everything needed to troubleshoot the helper.

Run with the game open and a run in progress:  python -m vshelper diagnose   (or Diagnose.bat)

The report (vshelper-diagnose.txt) contains the helper's setup, the game's class/field names,
your current items and the game's item data. It contains no personal data apart from the game's
install folder. Every section catches its own errors, so one failure doesn't stop the report.
"""

from __future__ import annotations

import ctypes
import platform
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from . import gamedata, icons
from . import settings as user_settings
from .data import CACHE_ROOT, Database, load_best_database
from .evolutions import format_plan
from .memory.game import POINTER_TYPES, GameMap, GameReader, ReadResult, load_game_map
from .memory.il2cpp import TYPE_STRING, Il2Cpp
from .memory.winapi import MemoryAccessError, ProcessMemory, process_exe_path

from .paths import FROZEN, RESOURCE_ROOT, USER_ROOT

PROJECT_ROOT = RESOURCE_ROOT
KEYWORDS = re.compile(rb"[A-Za-z_]*(Weapon|Accessor|Equipment|GameManager|PlayerCharacter|CharacterController|"
                      rb"Inventory|LevelUp|Evolution)[A-Za-z_`0-9]*")
# Classes whose field layout is worth knowing (looked up by name in one memory pass).
KEY_CLASSES = [
    "GameManager", "CharacterController", "CharacterWeaponsManager", "CharacterAccessoriesManager",
    "WeaponsManager", "AccessoriesManager", "Equipment", "Weapon", "Accessory", "WeaponData",
    "WeaponsFacade", "AccessoriesFacade", "LevelUpFactory", "DataManager", "GameSessionData",
    "PlayerOptions", "LimitBreakManager", "ArcanaManager",
]
MAX_ITEMS_DUMPED = 20
MAX_MISSING_PICTURE_HINTS = 400


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def section(self, title: str, func: Callable[[], None]) -> None:
        """Run one part of the report; record any error instead of stopping."""
        self.add("")
        self.add(f"== {title} ==")
        print(f"  {title}...")
        started = time.monotonic()
        try:
            func()
        except Exception:
            self.add("  !! this section failed:")
            self.lines.extend("     " + line for line in traceback.format_exc().rstrip().splitlines())
        took = time.monotonic() - started
        if took > 2:
            self.add(f"  (took {took:.0f}s)")


def _describe_value(il2: Il2Cpp, obj: int, f) -> str:
    addr = obj + f.offset
    try:
        if f.type_code == TYPE_STRING:
            p = il2.try_ptr(addr)
            return repr(il2.read_string(p)) if p else "null"
        if f.type_code in POINTER_TYPES:
            p = il2.try_ptr(addr)
            if not p:
                return "null"
            k = il2.try_ptr(p)
            return f"-> {il2.full_name(k)}" if il2.is_class(k) else f"0x{p:X}"
        return str(il2.i32(addr))
    except MemoryAccessError:
        return "<unreadable>"


def _dump_object(il2: Il2Cpp, obj: int, out: Report, indent: str = "  ") -> None:
    try:
        klass = il2.object_class(obj)
    except MemoryAccessError as exc:
        out.add(f"{indent}{exc}")
        return
    out.add(f"{indent}object 0x{obj:X} : {il2.full_name(klass)}")
    for f in il2.fields(klass):
        if f.is_static or f.is_literal:
            continue
        out.add(f"{indent}  {f.name} (+0x{f.offset:X}, type 0x{f.type_code:02X}) = {_describe_value(il2, obj, f)}")


def _dump_class_layout(il2: Il2Cpp, klass: int, out: Report) -> None:
    chain = []
    k = klass
    while k and len(chain) < 12:
        chain.append(il2.full_name(k))
        k = il2.parent(k)
    out.add(f"  {chain[0]}  (inherits: {' <- '.join(chain[1:]) or 'nothing'})")
    for f in il2.fields(klass):
        kind = "static " if f.is_static else ""
        kind = "const " if f.is_literal else kind
        out.add(f"    {kind}{f.name} (+0x{f.offset:X}, type 0x{f.type_code:02X}, declared in {il2.class_name(f.owner)})")


def _data_objects(il2: Il2Cpp, el: int) -> list[tuple[str, int]]:
    """Objects held by an equipment object whose class name ends in 'Data' (e.g. WeaponData)."""
    out = []
    for f in il2.fields(il2.object_class(el)):
        if f.is_static or f.type_code not in POINTER_TYPES:
            continue
        child = il2.try_ptr(el + f.offset)
        k = il2.try_ptr(child) if child else 0
        if child and il2.is_class(k) and il2.class_name(k).endswith("Data"):
            out.append((f.name, child))
    return out


# ---- sections that don't need the game -----------------------------------------
def _environment(out: Report, gmap: GameMap | None) -> None:
    version = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip() if (PROJECT_ROOT / "VERSION").exists() else "?"
    out.add(f"  helper version: {version}")
    out.add(f"  python: {sys.version.split()[0]} ({platform.architecture()[0]}) {sys.executable}")
    out.add(f"  running as: {'standalone exe' if FROZEN else 'Python source'}; saving files in {USER_ROOT}")
    out.add(f"  system: {platform.platform()}")
    if sys.platform == "win32":
        try:
            out.add(f"  running as administrator: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
        except (AttributeError, OSError):
            pass
    try:
        import UnityPy
        out.add(f"  UnityPy: {UnityPy.__version__}")
    except ImportError:
        out.add("  UnityPy: not installed (no item pictures)")
    if gmap:
        exe = process_exe_path(gmap.process_name)
        out.add(f"  game exe (running): {exe or 'not running'}")
        game_dir = icons.find_game_dir(Path(exe) if exe else None)
        out.add(f"  game folder: {game_dir or 'not found'}")
        if game_dir:
            for name in ("GameAssembly.dll", "VampireSurvivors.exe"):
                p = game_dir / name
                if p.exists():
                    st = p.stat()
                    out.add(f"  {name}: {st.st_size} bytes, modified {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}")


def _settings_and_cache(out: Report, db: Database) -> None:
    s, warning = user_settings.load()
    out.add(f"  hidden expansions: {', '.join(s.hidden_expansions) or 'none'}" + (f" ({warning})" if warning else ""))
    out.add(f"  evolution data: {db.source} {db.generated} - {len(db.evolutions)} recipes, {len(db.items)} items")
    out.add(f"  expansions in data: {', '.join(db.expansions())}")
    if CACHE_ROOT.exists():
        for p in sorted(CACHE_ROOT.iterdir()):
            if p.is_file():
                out.add(f"  cache/{p.name}: {p.stat().st_size} bytes, "
                        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}")
            elif p.is_dir():
                out.add(f"  cache/{p.name}/: {sum(1 for _ in p.iterdir())} files")
    else:
        out.add("  no cache folder yet")


def _game_files(out: Report, db: Database) -> None:
    game = gamedata.load(CACHE_ROOT)
    if game is None:
        out.add("  not read yet (happens together with the picture extraction)")
        return
    mapping = gamedata.internal_to_item(db, game)
    out.add(f"  internal names: {len(game.names)}, recipes: {len(game.recipes)}, picture names: {len(game.frames)}")
    out.add(f"  mapped to helper items: {len(mapping)}")
    checks = gamedata.compare(db, game)
    matches = sum(1 for c in checks.values() if c.status == "match")
    out.add(f"  wiki recipes checked against game: {len(checks)}; match: {matches}")
    for evolved, c in sorted(checks.items()):
        if c.status == "mismatch":
            wiki = next(e for e in db.evolutions if e.result == evolved)
            out.add(f"  MISMATCH {db.name(evolved)}: wiki {' + '.join(db.name(r) for r in wiki.requires)}"
                    f" / game {' + '.join(db.name(r) for r in c.game_requires)}")
    out.add("")
    out.add("  internal id = game name -> helper item | picture name")
    for key in sorted(set(game.names) | set(game.recipes) | set(game.frames)):
        item = mapping.get(key)
        out.add(f"  {key} = {game.names.get(key, '?')} -> {db.name(item) if item else 'UNMAPPED'}"
                f" | {game.frames.get(key, '-')}")


def _catalog(out: Report, db: Database) -> None:
    catalog = gamedata.load_catalog(CACHE_ROOT)
    if not catalog:
        out.add("  not read yet (it is read from the game's memory during a run)")
        return
    frames = gamedata.catalog_frames(db, catalog)
    by_name = {gamedata._canon(i.name): i.id for i in db.items.values()}
    out.add(f"  {len(catalog)} items; {len(frames)} matched to helper items with a picture name")
    out.add("  game name -> helper item | picture | evolves into")
    for name in sorted(catalog):
        entry = catalog[name]
        item = by_name.get(gamedata._canon(name))
        out.add(f"  {name} -> {item or 'UNMAPPED'} | {entry.get('frame', '')} | {entry.get('evo_into', '')}")


def _pictures(out: Report) -> None:
    manifest = icons.read_manifest()
    if manifest is None:
        out.add("  not extracted yet")
        return
    out.add(f"  extractor version: {manifest.get('extractor_version', 1)}")
    out.add(f"  game folder: {manifest.get('game_dir')}")
    out.add(f"  sprites in game files: {manifest.get('sprite_count')}")
    missing = manifest.get("missing", [])
    out.add(f"  found: {len(manifest.get('found', {}))}, missing: {len(missing)}")
    names_file = icons.CACHE_DIR / icons.SPRITE_NAMES
    if not names_file.exists():
        out.add("  (sprite name list not saved yet - it is created by the next picture extraction)")
        out.add(f"  missing: {', '.join(missing)}")
        return
    sprite_names = names_file.read_text(encoding="utf-8").splitlines()
    canon_names = [(icons.canon(n), n) for n in sprite_names]
    out.add("  missing item -> game sprite names that look similar")
    for item_id in missing[:MAX_MISSING_PICTURE_HINTS]:
        words = [w for w in item_id.split("_") if len(w) >= 4] or [item_id.replace("_", "")]
        word = max(words, key=len)
        similar = [n for c, n in canon_names if word in c][:6]
        out.add(f"  {item_id}: {', '.join(similar) or '(nothing similar)'}")


# ---- sections that read the game -------------------------------------------------
def _walk_inventory_paths(il2: Il2Cpp, reader: GameReader, gmap: GameMap, found: dict, out: Report) -> None:
    """Follow each configured inventory path, dumping every object on the way and every item."""
    for root in gmap.roots:
        klass = found.get(root["class"])
        if not klass:
            continue
        start = il2.read_static_ptr(klass, root["static_field"])
        for kind, path in gmap.inventories.items():
            out.add("")
            out.add(f"  ---- {kind} path from {root['class']} ----")
            obj = start
            for candidates in path:
                if not obj:
                    out.add("  (null - is a run in progress?)")
                    break
                _dump_object(il2, obj, out, "  ")
                step = None
                for cand in candidates:
                    base, _index = reader._split_index(cand)
                    try:
                        il2.find_field(il2.object_class(obj), base)
                        step = cand
                        break
                    except MemoryAccessError:
                        continue
                if step is None:
                    out.add(f"  !! none of these fields exist here: {', '.join(candidates)}")
                    obj = 0
                    break
                out.add(f"  --> following {step}")
                obj = reader._step(il2, obj, step)
            if not obj:
                continue
            _dump_object(il2, obj, out, "  ")
            for el in il2.collection_elements(obj)[:MAX_ITEMS_DUMPED]:
                _dump_object(il2, el, out, "    ")
                for name, child in _data_objects(il2, el):
                    out.add(f"      data object {name}:")
                    _dump_object(il2, child, out, "        ")
                raw = reader.identify(reader._session, el) if reader._session else None
                lv = reader.read_levels(il2, el)
                item = reader.matcher.match(raw) if raw else None
                out.add(f"      identified as: {raw} -> {item or 'NOT RECOGNISED'}"
                        + (f" (level {lv[0]}/{lv[1]})" if lv else ""))
        break


def _read_game(out: Report, db: Database, gmap: GameMap, open_memory) -> ReadResult | None:
    try:
        mem = open_memory(gmap.process_name)
    except MemoryAccessError as exc:
        out.add("")
        out.add("== Game ==")
        out.add(f"  could not open the game: {exc}")
        return None

    result: list[ReadResult] = []
    with mem:
        il2 = Il2Cpp(mem)
        found: dict[str, int] = {}
        reader = GameReader(db, gmap, open_memory=lambda _name: mem)

        def process() -> None:
            meta = il2.find_metadata()
            out.add(f"  process id: {mem.pid}")
            out.add(f"  metadata mapping: {'found' if meta else 'NOT found'}"
                    + (f" at 0x{meta[0]:X}" if meta else ""))

        def classes() -> None:
            wanted = [(r["class"], r.get("namespace")) for r in gmap.roots] + [(e, None) for e in gmap.enum_classes]
            wanted += [(name, None) for name in KEY_CLASSES]
            found.update(il2.find_classes(wanted))
            for name, _ in wanted:
                out.add(f"  {name}: {('0x%X %s' % (found[name], il2.full_name(found[name]))) if name in found else 'not found'}")

        def layouts() -> None:
            for name in KEY_CLASSES:
                if name in found:
                    _dump_class_layout(il2, found[name], out)

        def statics() -> None:
            for root in gmap.roots:
                klass = found.get(root["class"])
                if not klass:
                    out.add(f"  {root['class']}: not found")
                    continue
                base = il2.static_base(klass)
                for f in il2.fields(klass):
                    if f.is_static and not f.is_literal:
                        out.add(f"  {f.name} (+0x{f.offset:X}) = {_describe_value(il2, base, f)}")
                        target = il2.try_ptr(base + f.offset) if f.type_code in POINTER_TYPES else 0
                        if target:
                            _dump_object(il2, target, out, "    ")

        def enums() -> None:
            for name in gmap.enum_classes:
                if name in found:
                    names = il2.enum_names(found[name])
                    out.add(f"  {name}: {len(names)} names (declaration order; real values may differ)")
                    out.add("  " + ", ".join(f"{i}:{n}" for i, n in enumerate(names)))

        def detection() -> None:
            game = gamedata.load(CACHE_ROOT)
            if game is not None:
                reader.matcher.add_aliases(gamedata.internal_to_item(db, game))
            r = reader.poll()
            result.append(r)
            out.add(f"  state: {r.state}")
            out.add(f"  message: {r.message}")
            out.add(f"  items: {', '.join(sorted(db.name(i) for i in r.owned)) or '(none)'}")
            out.add(f"  levels: {', '.join(f'{db.name(i)} {lv}/{mx}' for i, lv, mx in r.levels) or '(none)'}")
            if reader._session:
                catalog = reader.read_catalog(reader._session, reader.root_objects(reader._session))
                if catalog:
                    total = gamedata.save_catalog(catalog, CACHE_ROOT)
                    out.add(f"  item catalogue read from the game: {len(catalog)} items (saved: {total})")
                else:
                    out.add("  item catalogue: not found in the game's memory")
                for kind, chain in reader._session.chains.items():
                    out.add(f"  {kind} read from: {gmap.roots[chain.root_index]['class']} -> {' -> '.join(chain.fields)}")
            if r.owned:
                out.add("")
                for line in format_plan(db, set(r.owned)).splitlines():
                    out.add("  " + line)

        def inventory() -> None:
            _walk_inventory_paths(il2, reader, gmap, found, out)

        def candidates() -> None:
            session = reader._session
            if not session:
                out.add("  (not attached)")
                return
            roots = reader.root_objects(session)
            for c in sorted(reader.find_candidates(session, roots), key=lambda c: -c.score):
                out.add(f"  {c.score:7.1f} {c.kind:8} {gmap.roots[c.chain.root_index]['class']} -> "
                        f"{' -> '.join(c.chain.fields)}: {', '.join(db.name(i) for i in c.items)}")

        def related_names() -> None:
            strings = il2.metadata_strings()
            if not strings:
                out.add("  metadata not found")
                return
            names = sorted({m.group(0).decode() for m in KEYWORDS.finditer(strings[1])})
            out.add(f"  {len(names)} names")
            out.lines.extend(f"  {n}" for n in names[:5000])

        out.section("Game process", process)
        out.section("Game classes (memory search, can take a minute)", classes)
        out.section("Class layouts (fields, offsets, types)", layouts)
        out.section("Static fields of the root classes", statics)
        out.section("Item type enums", enums)
        out.section("Detection result", detection)
        out.section("Your inventory, step by step", inventory)
        out.section("All lists with recognisable items (highest score is used; <= 0 rejected)", candidates)
        out.section("Related names in the game's metadata", related_names)
    return result[0] if result else None


REPORT_PATH = USER_ROOT / "vshelper-diagnose.txt"


def run(output: Path = REPORT_PATH, open_memory=ProcessMemory.open_by_name) -> int:
    out = Report()
    out.add("Vampire Survivors Helper - diagnostic report")
    out.add(time.strftime("created %Y-%m-%d %H:%M"))
    print("Writing diagnostic report:")

    db, db_warning = load_best_database()
    if db_warning:
        out.add(f"note: {db_warning}")
    gmap = None
    try:
        gmap = load_game_map()
    except Exception as exc:  # the report should still be written
        out.add(f"note: game map could not be loaded: {exc}")

    out.section("Setup", lambda: _environment(out, gmap))
    out.section("Settings, data and cache", lambda: _settings_and_cache(out, db))
    result = _read_game(out, db, gmap, open_memory) if gmap else None
    out.section("Game files: item names, recipes, pictures (and wiki check)", lambda: _game_files(out, db))
    out.section("Item catalogue from the game's memory", lambda: _catalog(out, db))
    out.section("Item pictures", lambda: _pictures(out))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(out.lines) + "\n", encoding="utf-8")
    if result is not None:
        print(f"Detection: {result.state} - {result.message}")
    print(f"Report written to {output.resolve()}")
    return 0
