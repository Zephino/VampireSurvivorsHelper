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
from .evolutions import format_suggestions, suggest
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


def run(output: Path = Path("vshelper-diagnose.txt")) -> int:
    db, _warning = load_best_database()
    gmap = load_game_map()
    out: list[str] = ["Vampire Survivors Helper - diagnostic report", ""]

    try:
        mem = ProcessMemory.open_by_name(gmap.process_name)
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
        result = reader.poll()
        out.append("")
        out.append("== Detection result ==")
        out.append(f"  state: {result.state}")
        out.append(f"  message: {result.message}")
        out.append(f"  items: {', '.join(sorted(db.name(i) for i in result.owned)) or '(none)'}")
        if result.owned:
            out.append("")
            out.append(format_suggestions(db, suggest(db, set(result.owned))))
        session = reader._session
        if session:
            roots = reader.root_objects(session)
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
            out.extend(f"  {n}" for n in names[:400])

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
        for result, c in sorted(checks.items()):
            if c.status == "mismatch":
                wiki = next(e for e in db.evolutions if e.result == result)
                out.append(f"  MISMATCH {db.name(result)}: wiki {' + '.join(db.name(r) for r in wiki.requires)}"
                           f" / game {' + '.join(db.name(r) for r in c.game_requires)}")

    output.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Detection: {result.state} - {result.message}")
    print(f"Report written to {output.resolve()}")
    return 0
