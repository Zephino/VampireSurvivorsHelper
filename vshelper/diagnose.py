"""Writes a report of what the helper can see in the game's memory.

Run with the game open and a run in progress:  python -m vshelper diagnose
The report (vshelper-diagnose.txt) contains only class/field names and item names from the
game, no personal data, and is meant to be shared if detection does not work.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import gamedata, icons
from .data import CACHE_ROOT, load_best_database
from .evolutions import format_plan
from .memory.game import POINTER_TYPES, GameReader, load_game_map
from .memory.il2cpp import TYPE_STRING, Il2Cpp
from .memory.winapi import MemoryAccessError, ProcessMemory

KEYWORDS = re.compile(rb"[A-Za-z_]*(Weapon|Accessor|Equipment|GameManager|PlayerCharacter|CharacterController|Inventory)[A-Za-z_`0-9]*")


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


def _dump_object(il2: Il2Cpp, obj: int, out: list[str], indent: str = "  ") -> None:
    try:
        klass = il2.object_class(obj)
    except MemoryAccessError as exc:
        out.append(f"{indent}{exc}")
        return
    out.append(f"{indent}object 0x{obj:X} : {il2.full_name(klass)}")
    for f in il2.fields(klass):
        if f.is_static or f.is_literal:
            continue
        out.append(f"{indent}  {f.name} (+0x{f.offset:X}, type 0x{f.type_code:02X}) = {_describe_value(il2, obj, f)}")


def _walk_inventory_paths(il2: Il2Cpp, reader: GameReader, gmap, found: dict, out: list[str]) -> None:
    """Follow each configured inventory path, dumping every object on the way."""
    for root in gmap.roots:
        klass = found.get(root["class"])
        if not klass:
            continue
        try:
            start = il2.read_static_ptr(klass, root["static_field"])
        except MemoryAccessError as exc:
            out.append(f"  {root['class']}: {exc}")
            continue
        for kind, path in gmap.inventories.items():
            out.append("")
            out.append(f"== Walking the {kind} path from {root['class']} ==")
            obj = start
            for candidates in path:
                if not obj:
                    out.append("  (null - is a run in progress?)")
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
                    out.append(f"  !! none of these fields exist here: {', '.join(candidates)}")
                    obj = 0
                    break
                out.append(f"  --> following {step}")
                try:
                    obj = reader._step(il2, obj, step)
                except MemoryAccessError as exc:
                    out.append(f"  !! {exc}")
                    obj = 0
                    break
            if obj:
                _dump_object(il2, obj, out, "  ")
                try:
                    for n, el in enumerate(il2.collection_elements(obj)[:6]):
                        _dump_object(il2, el, out, "    ")
                        if n == 0:  # show the item's data objects (e.g. WeaponData) once
                            klass = il2.object_class(el)
                            for f in il2.fields(klass):
                                child = il2.try_ptr(el + f.offset) if f.type_code in POINTER_TYPES else 0
                                if child and il2.is_class(il2.try_ptr(child)) and \
                                        il2.class_name(il2.try_ptr(child)).endswith("Data"):
                                    out.append(f"      data object {f.name}:")
                                    _dump_object(il2, child, out, "        ")
                        raw = reader.identify(reader._session, el) if reader._session else None
                        lv = reader.read_levels(il2, el)
                        out.append(f"      identified as: {raw}" + (f" (level {lv[0]}/{lv[1]})" if lv else ""))
                except MemoryAccessError as exc:
                    out.append(f"  !! {exc}")
        break


def run(output: Path = Path("vshelper-diagnose.txt"), open_memory=ProcessMemory.open_by_name) -> int:
    db, _warning = load_best_database()
    gmap = load_game_map()
    out: list[str] = ["Vampire Survivors Helper - diagnostic report", ""]

    try:
        mem = open_memory(gmap.process_name)
    except MemoryAccessError as exc:
        print(f"Error: {exc}")
        return 1

    with mem:
        il2 = Il2Cpp(mem)
        meta = il2.find_metadata()
        out.append(f"Process id: {mem.pid}")
        out.append(f"Metadata mapping: {'found' if meta else 'NOT found'}")

        print("Searching memory for game classes (this can take a little while)...")
        wanted = [(r["class"], r.get("namespace")) for r in gmap.roots] + [(e, None) for e in gmap.enum_classes]
        found = il2.find_classes(wanted)
        out.append("")
        out.append("== Classes ==")
        for name, _ in wanted:
            out.append(f"{name}: {'0x%X %s' % (found[name], il2.full_name(found[name])) if name in found else 'not found'}")

        for root in gmap.roots:
            klass = found.get(root["class"])
            if not klass:
                continue
            out.append("")
            out.append(f"== Static fields of {il2.full_name(klass)} ==")
            try:
                base = il2.static_base(klass)
            except MemoryAccessError as exc:
                out.append(f"  {exc}")
                continue
            for f in il2.fields(klass):
                if f.is_static and not f.is_literal:
                    out.append(f"  {f.name} (+0x{f.offset:X}) = {_describe_value(il2, base, f)}")
                    if f.type_code in POINTER_TYPES:
                        target = il2.try_ptr(base + f.offset)
                        if target:
                            _dump_object(il2, target, out, "    ")

        for name in gmap.enum_classes:
            if name in found:
                out.append("")
                out.append(f"== Enum {name} (declaration order) ==")
                out.append("  " + ", ".join(f"{i}:{n}" for i, n in enumerate(il2.enum_names(found[name]))))

        reader = GameReader(db, gmap, open_memory=lambda _name: mem)
        game = gamedata.load(CACHE_ROOT)
        if game is not None:
            reader.matcher.add_aliases(gamedata.internal_to_item(db, game))
        result = reader.poll()
        _walk_inventory_paths(il2, reader, gmap, found, out)
        out.append("")
        out.append("== Detection result ==")
        out.append(f"  state: {result.state}")
        out.append(f"  message: {result.message}")
        out.append(f"  items: {', '.join(sorted(db.name(i) for i in result.owned)) or '(none)'}")
        if result.owned:
            out.append("")
            out.append(format_plan(db, set(result.owned)))
        session = reader._session
        if session:
            roots = reader.root_objects(session)
            out.append("")
            out.append("== Lists with recognisable items (highest score is used; <= 0 rejected) ==")
            for c in sorted(reader.find_candidates(session, roots), key=lambda c: -c.score):
                out.append(f"  {c.score:7.1f} {c.kind:8} {gmap.roots[c.chain.root_index]['class']} -> "
                           f"{' -> '.join(c.chain.fields)}: {', '.join(db.name(i) for i in c.items)}")
            out.append("")
            for kind, chain in session.chains.items():
                out.append(f"  {kind}: root {gmap.roots[chain.root_index]['class']} -> {' -> '.join(chain.fields)}")
                obj = roots.get(chain.root_index)
                if obj:
                    try:
                        coll = reader._follow(il2, obj, chain.fields)
                        for el in il2.collection_elements(coll)[:20] if coll else []:
                            _dump_object(il2, el, out, "    ")
                    except MemoryAccessError as exc:
                        out.append(f"    {exc}")

        strings = il2.metadata_strings()
        if strings:
            names = sorted({m.group(0).decode() for m in KEYWORDS.finditer(strings[1])})
            out.append("")
            out.append(f"== Related names in metadata ({len(names)}) ==")
            out.extend(f"  {n}" for n in names[:3000])

    out.append("")
    out.append("== Item pictures ==")
    manifest = icons.read_manifest()
    if manifest is None:
        out.append("  not extracted yet")
    else:
        out.append(f"  game folder: {manifest.get('game_dir')}")
        out.append(f"  sprites in game files: {manifest.get('sprite_count')}")
        out.append(f"  found: {len(manifest.get('found', {}))}, missing: {', '.join(manifest.get('missing', [])) or 'none'}")

    out.append("")
    out.append("== Wiki data vs game files ==")
    out.append(f"  evolution data: {db.source} {db.generated}".rstrip())
    game = gamedata.load(CACHE_ROOT)
    if game is None:
        out.append("  game files not read yet (happens with the picture extraction)")
    else:
        checks = gamedata.compare(db, game)
        matches = sum(1 for c in checks.values() if c.status == "match")
        out.append(f"  game recipes found: {len(game.recipes)}; compared: {len(checks)}; match: {matches}")
        for evolved, c in sorted(checks.items()):
            if c.status == "mismatch":
                wiki = next(e for e in db.evolutions if e.result == evolved)
                out.append(f"  MISMATCH {db.name(evolved)}: wiki {' + '.join(db.name(r) for r in wiki.requires)}"
                           f" / game {' + '.join(db.name(r) for r in c.game_requires)}")

    output.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Detection: {result.state} - {result.message}")
    print(f"Report written to {output.resolve()}")
    return 0
