"""Reads the player's current weapons and passive items from Vampire Survivors' memory."""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..data import Database
from .il2cpp import (
    TYPE_CLASS, TYPE_GENERICINST, TYPE_I4, TYPE_STRING, TYPE_SZARRAY, TYPE_U4, TYPE_VALUETYPE,
    Il2Cpp, Il2CppError, Memory,
)
from .winapi import MemoryAccessError, ProcessMemory, ProcessNotFound

from ..paths import RESOURCE_ROOT

DEFAULT_GAME_MAP = RESOURCE_ROOT / "config" / "game_map.json"
POINTER_TYPES = (TYPE_CLASS, TYPE_GENERICINST, TYPE_SZARRAY)
INDEXED_STEP = re.compile(r"(.+)\[(\d+)\]")
LIST_ELEMENTS_TO_EXPLORE = 4  # e.g. the players in _mainCharacters
REDISCOVER_SECONDS = 5.0
REATTACH_SECONDS = 30.0  # a failed class search is slow; don't repeat it every poll


class GameMapError(Exception):
    pass


@dataclass
class GameMap:
    process_name: str
    roots: list[dict]
    inventories: dict[str, list[list[str]]]
    type_field: list[str]
    enum_classes: list[str]
    enum_aliases: dict[str, str]
    id_map: dict[str, str]
    search_depth: int = 4
    search_max_objects: int = 3000
    # Paths from an equipment object to its name (each step: candidate field names).
    name_paths: list[list[list[str]]] = field(default_factory=list)
    level_field: list[str] = field(default_factory=list)
    max_level_field: list[str] = field(default_factory=list)
    # Path from the root to the game's item catalogue (a dictionary of item type -> item data).
    catalog_path: list[list[str]] = field(default_factory=list)


def load_game_map(path: Path | str = DEFAULT_GAME_MAP) -> GameMap:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return GameMap(
            process_name=raw["process_name"],
            roots=raw["roots"],
            inventories={k: v["path"] for k, v in raw.get("inventories", {}).items()},
            type_field=raw["type_field"],
            enum_classes=raw.get("enum_classes", []),
            enum_aliases={k.upper(): v for k, v in raw.get("enum_aliases", {}).items()},
            id_map=raw.get("id_map", {}),
            search_depth=int(raw.get("search_depth", 4)),
            search_max_objects=int(raw.get("search_max_objects", 3000)),
            name_paths=raw.get("name_paths", []),
            level_field=raw.get("level_field", []),
            max_level_field=raw.get("max_level_field", []),
            catalog_path=raw.get("catalog_path", []),
        )
    except FileNotFoundError as exc:
        raise GameMapError(f"Game map not found: {path}") from exc
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GameMapError(f"Game map {path} is invalid: {exc!r}") from exc


def _canon(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class ItemMatcher:
    """Maps a value read from the game (enum name, id string, display name) to a database item id."""

    def __init__(self, db: Database, aliases: dict[str, str], id_map: dict[str, str]):
        self.db = db
        self.aliases = aliases
        self.id_map = id_map
        self._canon: dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        """Re-read the item names (e.g. after items were added from a wiki lookup)."""
        canon: dict[str, str] = {}
        for item in list(self.db.items.values()):
            canon.setdefault(_canon(item.id), item.id)
            canon.setdefault(_canon(item.name), item.id)
        self._canon = canon  # swapped in one step: the reader thread may be using it

    def add_aliases(self, aliases: dict[str, str]) -> None:
        """Add internal-name -> item id pairs (e.g. read from the game files)."""
        for k, v in aliases.items():
            if v in self.db.items:
                self.aliases.setdefault(k.upper(), v)

    FUZZY_CUTOFF = 0.9  # "Sinistro Custos" still finds "Sinestro Custos"; unrelated names don't

    def match(self, raw: str, fuzzy: bool = False) -> str | None:
        """fuzzy: also accept a near-identical spelling (only used for names of held items)."""
        if raw in self.id_map:
            return self.id_map[raw] if self.id_map[raw] in self.db.items else None
        alias = self.aliases.get(raw.upper())
        if alias in self.db.items:
            return alias
        key = _canon(raw)
        found = self._canon.get(key)
        if found or not fuzzy or raw.startswith("#") or len(key) < 6:
            return found
        close = difflib.get_close_matches(key, list(self._canon), n=1, cutoff=self.FUZZY_CUTOFF)
        return self._canon[close[0]] if close else None


@dataclass(frozen=True)
class PlayerInventory:
    """What one player holds (co-op games have several)."""
    index: int                                   # 0 = player 1
    character: str                               # e.g. "Rinaldo" (from the character's class name)
    owned: frozenset[str] = frozenset()
    levels: tuple[tuple[str, int, int], ...] = ()

    @property
    def label(self) -> str:
        return f"Player {self.index + 1}" + (f" ({self.character})" if self.character else "")

    def level_of(self, item_id: str) -> tuple[int, int] | None:
        for i, lvl, mx in self.levels:
            if i == item_id:
                return lvl, mx
        return None


@dataclass(frozen=True)
class ReadResult:
    state: str  # not_running | waiting | ok | error
    message: str
    owned: frozenset[str] = frozenset()
    unrecognized: tuple[str, ...] = ()
    levels: tuple[tuple[str, int, int], ...] = ()  # (item id, level, max level) when the game exposes them
    players: tuple[PlayerInventory, ...] = ()      # every player in the game, player 1 first

    def level_of(self, item_id: str) -> tuple[int, int] | None:
        for i, lvl, mx in self.levels:
            if i == item_id:
                return lvl, mx
        return None


@dataclass
class Chain:
    root_index: int
    fields: tuple[str, ...]
    trusted: bool = False  # came from the game map, not from the automatic search


@dataclass
class _Session:
    mem: Memory
    il2: Il2Cpp
    root_classes: dict[int, int] = field(default_factory=dict)  # root index -> klass
    enums: list[list[str]] = field(default_factory=list)
    chains: dict[str, Chain] = field(default_factory=dict)
    last_discovery: float = 0.0
    rejected: set[tuple[str, ...]] = field(default_factory=set)  # paths that turned out not to be the inventory
    catalog_done: bool = False
    held_seen: set[str] = field(default_factory=set)  # held items whose picture name was collected


class GameReader:
    def __init__(self, db: Database, game_map: GameMap,
                 open_memory: Callable[[str], Memory] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 on_catalog: Callable[[dict], None] | None = None):
        self.db = db
        self.map = game_map
        self.matcher = ItemMatcher(db, dict(game_map.enum_aliases), game_map.id_map)
        self._open = open_memory or ProcessMemory.open_by_name
        self._clock = clock
        self.on_catalog = on_catalog  # called with the game's item catalogue once per session
        self._session: _Session | None = None
        self._attach_failed: tuple[float, str] | None = None

    # ---- lifecycle -------------------------------------------------------
    def close(self) -> None:
        if self._session and hasattr(self._session.mem, "close"):
            self._session.mem.close()
        self._session = None

    def _attach(self) -> _Session:
        mem = self._open(self.map.process_name)
        il2 = Il2Cpp(mem)
        wanted = [(r["class"], r.get("namespace")) for r in self.map.roots]
        wanted += [(name, None) for name in self.map.enum_classes]
        found = il2.find_classes(wanted)
        session = _Session(mem, il2)
        for i, root in enumerate(self.map.roots):
            if root["class"] in found:
                session.root_classes[i] = found[root["class"]]
        if not session.root_classes:
            mem_close = getattr(mem, "close", None)
            if mem_close:
                mem_close()
            names = ", ".join(r["class"] for r in self.map.roots)
            raise Il2CppError(
                f"Found the game, but not its main class ({names}). The game may have been updated; "
                "run 'python -m vshelper diagnose' and share the report."
            )
        for name in self.map.enum_classes:
            if name in found:
                session.enums.append(il2.enum_names(found[name]))
        return session

    # ---- polling ---------------------------------------------------------
    def poll(self) -> ReadResult:
        """Read the current inventory. Slow the first time (searches memory), fast afterwards."""
        try:
            if self._session is None:
                if self._attach_failed and self._clock() - self._attach_failed[0] < REATTACH_SECONDS:
                    return ReadResult("error", self._attach_failed[1])
                try:
                    self._session = self._attach()
                except Il2CppError as exc:
                    self._attach_failed = (self._clock(), str(exc))
                    raise
                self._attach_failed = None
            s = self._session
            if hasattr(s.mem, "is_alive") and not s.mem.is_alive():
                self.close()
                return ReadResult("not_running", f"{self.map.process_name} closed.")
            return self._read(s)
        except ProcessNotFound as exc:
            self.close()
            return ReadResult("not_running", str(exc))
        except Il2CppError as exc:
            if self._session is None:
                return ReadResult("error", str(exc))
            return ReadResult("waiting", f"Waiting for a run to start. ({exc})")
        except MemoryAccessError as exc:
            self.close()
            return ReadResult("error", str(exc))

    def root_objects(self, s: _Session) -> dict[int, int]:
        objs = {}
        for i, klass in s.root_classes.items():
            try:
                obj = s.il2.read_static_ptr(klass, self.map.roots[i]["static_field"])
            except Il2CppError:
                continue
            if obj:
                objs[i] = obj
        return objs

    def _read(self, s: _Session) -> ReadResult:
        roots = self.root_objects(s)
        if not roots:
            return ReadResult("waiting", "Game found. Waiting for a run to start.")

        for kind, path in self.map.inventories.items():
            if kind in s.chains:
                continue
            for i, obj in roots.items():
                names = self._follow_candidates(s.il2, obj, path)
                if names:
                    s.chains[kind] = Chain(i, names, trusted=True)
                    break

        if len(s.chains) < len(self.map.inventories) and self._clock() - s.last_discovery >= REDISCOVER_SECONDS:
            s.last_discovery = self._clock()
            for kind, chain in self.discover(s, roots).items():
                s.chains.setdefault(kind, chain)

        owned: set[str] = set()
        levels: dict[str, tuple[int, int]] = {}
        unknown: list[str] = []
        unreadable = 0
        new_catalog: dict[str, dict] = {}
        found_any = False
        for kind, chain in list(s.chains.items()):
            obj = roots.get(chain.root_index)
            try:
                if not obj:
                    raise Il2CppError("root object missing")
                coll = self._follow(s.il2, obj, chain.fields)
                if not coll:
                    continue  # e.g. no player yet
                elements = s.il2.collection_elements(coll)
                if len(elements) > MAX_SLOTS and not chain.trusted:
                    s.rejected.add(chain.fields)
                    del s.chains[kind]
                    continue
                for el in elements:
                    raw = self.identify(s, el)
                    if raw is None:
                        unreadable += 1  # no name or type found on this item: say so, don't hide it
                        continue
                    item = self.matcher.match(raw, fuzzy=True)
                    if item and item not in s.held_seen:
                        s.held_seen.add(item)
                        entry = self._held_catalog_entry(s.il2, el)
                        if entry:
                            new_catalog.update(entry)
                    if item:
                        owned.add(item)
                        lv = self.read_levels(s.il2, el)
                        if lv:
                            levels[item] = lv
                    elif raw not in unknown:
                        unknown.append(raw)
                found_any = True
            except MemoryAccessError:
                del s.chains[kind]  # path went stale; find it again next poll

        if not found_any:
            return ReadResult("waiting", "Game found. Waiting for a run to start.")
        if new_catalog and self.on_catalog is not None:
            self.on_catalog(new_catalog)  # picture names of newly held items (works without the full catalogue)
        if not s.catalog_done and self.on_catalog is not None:
            s.catalog_done = True  # once per game session; the catalogue doesn't change
            try:
                catalog = self.read_catalog(s, roots)
            except MemoryAccessError:
                catalog = {}
            if catalog:
                self.on_catalog(catalog)
        msg = f"Reading game: {len(owned)} item(s) detected."
        if unknown:
            msg += f" Unrecognized: {', '.join(unknown)}"
        if unreadable:
            msg += f" {unreadable} item(s) couldn't be identified - please send a diagnose report."
        level_list = tuple((i, lv, mx) for i, (lv, mx) in sorted(levels.items()))
        players = [PlayerInventory(0, self._character_name(s, roots, 0), frozenset(owned), level_list)]
        for index in range(1, MAX_PLAYERS):
            other = self._read_player(s, roots, index)
            if other is None:
                break
            players.append(other)
        if len(players) > 1:
            msg += f" {len(players)} players in the game."
        return ReadResult("ok", msg, frozenset(owned), tuple(unknown), level_list, tuple(players))

    # ---- other players (co-op) --------------------------------------------
    def _player_fields(self, chain: Chain, index: int) -> tuple[str, ...] | None:
        """The chain with player 1's index swapped for another player's ('_mainCharacters[0]' ->
        '_mainCharacters[1]'). None if the chain doesn't go through a list of players."""
        if not chain.fields:
            return None
        base, i = self._split_index(chain.fields[0])
        if i is None:
            return None
        return (f"{base}[{index}]", *chain.fields[1:])

    def _character_name(self, s: _Session, roots: dict[int, int], index: int) -> str:
        chain = next(iter(s.chains.values()), None)
        fields = self._player_fields(chain, index) if chain else None
        obj = roots.get(chain.root_index) if chain else None
        if not fields or not obj:
            return ""
        try:
            player = self._follow(s.il2, obj, fields[:1])
            name = s.il2.class_name(s.il2.object_class(player)) if player else ""
        except MemoryAccessError:
            return ""
        # "TP_Rinaldo_Character" -> "Rinaldo"; the generic controller class says nothing useful
        name = re.sub(r"^(?:[A-Z]{1,4}\d*_)+", "", name)
        name = re.sub(r"_?Character(Controller)?$", "", name).replace("_", " ").strip()
        return "" if name in ("", "CharacterController") else name

    def _read_player(self, s: _Session, roots: dict[int, int], index: int) -> PlayerInventory | None:
        owned: set[str] = set()
        levels: dict[str, tuple[int, int]] = {}
        found = False
        for chain in s.chains.values():
            fields = self._player_fields(chain, index)
            obj = roots.get(chain.root_index)
            if not fields or not obj:
                continue
            try:
                coll = self._follow(s.il2, obj, fields)
                if not coll:
                    continue
                found = True
                for el in s.il2.collection_elements(coll)[:64]:
                    raw = self.identify(s, el)
                    item = self.matcher.match(raw, fuzzy=True) if raw else None
                    if item:
                        owned.add(item)
                        lv = self.read_levels(s.il2, el)
                        if lv:
                            levels[item] = lv
            except MemoryAccessError:
                continue
        if not found:
            return None
        return PlayerInventory(index, self._character_name(s, roots, index), frozenset(owned),
                               tuple((i, lv, mx) for i, (lv, mx) in sorted(levels.items())))

    # ---- item catalogue ----------------------------------------------------
    def catalog_sources(self, s: _Session, roots: dict[int, int]) -> list[tuple[str, int]]:
        """(field name, object) of every item table found along catalog_path. The last step's
        candidates are all used (e.g. AllWeaponData, _weaponData and _dlcWeaponData)."""
        il2 = s.il2
        sources: list[tuple[str, int]] = []
        if not self.map.catalog_path:
            return sources
        *steps, last = self.map.catalog_path
        for obj in roots.values():
            try:
                for candidates in steps:
                    obj = il2.read_field_ptr(obj, candidates)
                    if not obj:
                        break
                if not obj:
                    continue
                klass = il2.object_class(obj)
            except MemoryAccessError:
                continue
            for name in last:
                try:
                    f = il2.find_field(klass, name)
                except MemoryAccessError:
                    continue
                table = il2.try_ptr(obj + f.offset)
                if table and all(table != t for _, t in sources):
                    sources.append((f.name, table))
            if sources:
                break
        return sources

    def _catalog_values(self, il2: Il2Cpp, table: int) -> list[int]:
        """Item data objects in a table: a Dictionary of (List of / array of / single) data,
        or a plain list/array of data."""
        name = il2.class_name(il2.object_class(table))
        if name.startswith("Dictionary`"):
            values = [v for _, v in il2.dictionary_items(table)]
        else:
            values = il2.collection_elements(table)
        out = []
        for value in values:
            try:
                vname = il2.class_name(il2.object_class(value))
                if vname.startswith("List`") or vname.endswith("[]"):
                    elements = il2.collection_elements(value)
                    if elements:
                        out.append(elements[0])  # level 1 holds the name and picture
                else:
                    out.append(value)
            except MemoryAccessError:
                continue
        return out

    def read_catalog(self, s: _Session, roots: dict[int, int]) -> dict[str, dict]:
        """Every item the game knows: {display name: {"frame": picture name, "evo_into": id}}.

        Read from the game's own data tables (DataManager.AllWeaponData / _weaponData /
        _dlcWeaponData), so it includes DLC items whose data isn't readable from the game files.
        """
        il2 = s.il2
        catalog: dict[str, dict] = {}
        for _field, table in self.catalog_sources(s, roots):
            try:
                values = self._catalog_values(il2, table)
            except MemoryAccessError:
                continue  # a table we can't read; the others may still work
            for data in values:
                try:
                    name = self._read_text(il2, data, ["name", "<name>k__BackingField"])
                    frame = self._read_text(il2, data, ["frameName", "<frameName>k__BackingField"])
                    evo = self._read_text(il2, data, ["evoInto", "<evoInto>k__BackingField"])
                except MemoryAccessError:
                    continue
                if name and name not in catalog:
                    catalog[name] = {"frame": frame or "", "evo_into": evo or ""}
        return catalog

    def _held_catalog_entry(self, il2: Il2Cpp, element: int) -> dict[str, dict]:
        """{name: {"frame", "evo_into"}} from a held item's own data object, if readable."""
        for path in self.map.name_paths:
            try:
                data = element
                for candidates in path[:-1]:
                    data = il2.read_field_ptr(data, candidates)
                    if not data:
                        break
                if not data:
                    continue
                name = self._read_text(il2, data, path[-1])
                frame = self._read_text(il2, data, ["frameName", "<frameName>k__BackingField"])
                evo = self._read_text(il2, data, ["evoInto", "<evoInto>k__BackingField"])
            except MemoryAccessError:
                continue
            if name and frame:
                return {name: {"frame": frame, "evo_into": evo or ""}}
        return {}

    @staticmethod
    def _read_text(il2: Il2Cpp, obj: int, candidates: list[str]) -> str | None:
        f = il2.find_field(il2.object_class(obj), candidates)
        ptr = il2.try_ptr(obj + f.offset)
        return il2.read_string(ptr) if ptr else None

    # ---- path helpers ----------------------------------------------------
    @staticmethod
    def _split_index(step: str) -> tuple[str, int | None]:
        """'_mainCharacters[0]' -> ('_mainCharacters', 0); '_player' -> ('_player', None)."""
        m = INDEXED_STEP.fullmatch(step)
        return (m.group(1), int(m.group(2))) if m else (step, None)

    def _step(self, il2: Il2Cpp, obj: int, step: str) -> int:
        """Follow one path step: a field, or 'field[i]' for element i of a list/array field."""
        name, index = self._split_index(step)
        obj = il2.read_field_ptr(obj, name)
        if index is not None and obj:
            elements = il2.collection_elements(obj)
            obj = elements[index] if index < len(elements) else 0
        return obj

    def _follow(self, il2: Il2Cpp, obj: int, names: tuple[str, ...]) -> int:
        for name in names:
            if not obj:
                return 0
            obj = self._step(il2, obj, name)
        return obj

    def _follow_candidates(self, il2: Il2Cpp, obj: int, path: list[list[str]]) -> tuple[str, ...] | None:
        names: list[str] = []
        for candidates in path:
            resolved = None
            for cand in candidates:
                base, index = self._split_index(cand)
                try:
                    f = il2.find_field(il2.object_class(obj), base)
                except MemoryAccessError:
                    continue
                resolved = f.name if index is None else f"{f.name}[{index}]"
                break
            if resolved is None:
                return None
            try:
                obj = self._step(il2, obj, resolved)
            except MemoryAccessError:
                return None
            names.append(resolved)
            if not obj:
                return None
        try:
            il2.collection_elements(obj)
        except MemoryAccessError:
            return None
        return tuple(names)

    def identify(self, s: _Session, element: int) -> str | None:
        """Return the raw identifier of an equipment object (its name, or an enum name), if any.

        Order: configured name paths (e.g. _currentWeaponData.name), then any text field on the
        object's *Data objects that matches a known item, then the item-type enum field.
        """
        il2 = s.il2
        try:
            klass = il2.object_class(element)
        except MemoryAccessError:
            return None
        name = None
        for path in self.map.name_paths:
            raw = self._read_text_path(il2, element, path)
            if raw and self.matcher.match(raw):
                return raw
            name = name or raw
        raw = self._search_data_strings(il2, element, klass)
        if raw:
            return raw
        by_enum = self._identify_by_enum(s, element, klass)
        if by_enum and self.matcher.match(by_enum):
            return by_enum
        # A readable name beats a bare number: it can still be matched by a near-identical
        # spelling (the game says "Sinistro Custos", the wiki "Sinestro Custos") or looked up.
        return name or by_enum

    def _read_text_path(self, il2: Il2Cpp, obj: int, path: list[list[str]]) -> str | None:
        try:
            for candidates in path[:-1]:
                obj = il2.read_field_ptr(obj, candidates)
                if not obj:
                    return None
            f = il2.find_field(il2.object_class(obj), path[-1])
            if f.type_code not in (TYPE_STRING, TYPE_CLASS):
                return None
            str_obj = il2.try_ptr(obj + f.offset)
            return il2.read_string(str_obj) if str_obj else None
        except MemoryAccessError:
            return None

    def _search_data_strings(self, il2: Il2Cpp, element: int, klass: int) -> str | None:
        """Look for a text field naming a known item, on the object or on objects it holds whose
        class name ends in 'Data' (e.g. WeaponData)."""
        targets = [(element, klass)]
        for f in il2.fields(klass):
            if f.is_static or f.type_code != TYPE_CLASS:
                continue
            child = il2.try_ptr(element + f.offset)
            if not child:
                continue
            try:
                ck = il2.object_class(child)
            except MemoryAccessError:
                continue
            if il2.class_name(ck).endswith("Data"):
                targets.append((child, ck))
        for obj, k in targets:
            for f in il2.fields(k):
                if f.is_static or f.type_code != TYPE_STRING:
                    continue
                str_obj = il2.try_ptr(obj + f.offset)
                if not str_obj:
                    continue
                try:
                    text = il2.read_string(str_obj)
                except MemoryAccessError:
                    continue
                if text and len(text) < 80 and self.matcher.match(text):
                    return text
        return None

    def _identify_by_enum(self, s: _Session, element: int, klass: int) -> str | None:
        il2 = s.il2
        try:
            f = il2.find_field(klass, self.map.type_field)
        except MemoryAccessError:
            return None
        addr = element + f.offset
        try:
            if f.type_code in (TYPE_STRING, TYPE_CLASS):
                str_obj = il2.try_ptr(addr)
                return il2.read_string(str_obj) if str_obj else None
            if f.type_code in (TYPE_I4, TYPE_U4, TYPE_VALUETYPE):
                value = il2.i32(addr)
                key = f"#{value}"
                if key in self.matcher.id_map:
                    return key
                # Enum names are only trusted when the values are plain 0, 1, 2... (not always true)
                for names in s.enums:
                    if 0 <= value < len(names) and self.matcher.match(names[value]):
                        return names[value]
                return key
        except MemoryAccessError:
            return None
        return None

    def read_levels(self, il2: Il2Cpp, element: int) -> tuple[int, int] | None:
        """(level, max level) of an equipment object, if the game map names those fields."""
        if not self.map.level_field or not self.map.max_level_field:
            return None
        try:
            klass = il2.object_class(element)
            lvl = il2.i32(element + il2.find_field(klass, self.map.level_field).offset)
            mx = il2.i32(element + il2.find_field(klass, self.map.max_level_field).offset)
        except MemoryAccessError:
            return None
        return (lvl, mx) if 0 < lvl <= mx <= 99 else None

    def discover(self, s: _Session, roots: dict[int, int]) -> dict[str, Chain]:
        """Breadth-first search from the root objects for the player's weapon and passive lists."""
        best: dict[str, tuple[float, Chain]] = {}
        for c in self.find_candidates(s, roots):
            if c.score <= 0 or c.chain.fields in s.rejected:
                continue
            if c.score > best.get(c.kind, (0.0,))[0]:
                best[c.kind] = (c.score, c.chain)
        return {kind: chain for kind, (_, chain) in best.items()}

    def find_candidates(self, s: _Session, roots: dict[int, int]) -> list["Candidate"]:
        """Every list reachable from the roots that holds recognisable items, scored by how
        likely it is to be the player's inventory (rather than e.g. pickups on the ground)."""
        il2 = s.il2
        found: list[Candidate] = []
        visited: set[int] = set()
        queue: list[tuple[int, int, tuple[str, ...]]] = [(obj, i, ()) for i, obj in roots.items()]
        budget = self.map.search_max_objects
        while queue and budget > 0:
            obj, root_i, path = queue.pop(0)
            if obj in visited:
                continue
            visited.add(obj)
            budget -= 1
            try:
                klass = il2.object_class(obj)
            except Il2CppError:
                continue
            cname = il2.class_name(klass)
            if cname.startswith("List`") or cname.endswith("[]"):
                try:
                    elements = il2.collection_elements(obj)[:64]
                except MemoryAccessError:
                    elements = []
                items = []
                for el in elements:
                    raw = self.identify(s, el)
                    item = self.matcher.match(raw) if raw else None
                    if item:
                        items.append(item)
                if items:
                    weapons = sum(1 for i in items if self.db.items[i].kind == "weapon")
                    kind = "weapons" if weapons >= len(items) - weapons else "passives"
                    score = score_inventory_path(path, len(elements), len(items))
                    found.append(Candidate(kind, Chain(root_i, path), score, tuple(items)))
                elif path and len(path) < self.map.search_depth and "[" not in path[-1]:
                    # a list of other objects (e.g. the players): look inside its first few elements
                    for i, el in enumerate(elements[:LIST_ELEMENTS_TO_EXPLORE]):
                        if el not in visited:
                            queue.append((el, root_i, path[:-1] + (f"{path[-1]}[{i}]",)))
                continue
            if len(path) >= self.map.search_depth:
                continue
            for f in il2.fields(klass):
                if f.is_static or f.type_code not in POINTER_TYPES:
                    continue
                child = il2.try_ptr(obj + f.offset)
                if child and child not in visited:
                    queue.append((child, root_i, path + (f.name,)))
        return found


# The automatic search ignores bigger lists (item pools, pickups). Paths from the game map are
# trusted at any size: some characters and modes hold many more passives.
MAX_SLOTS = 12
MAX_PLAYERS = 4  # co-op: up to four players
GOOD_WORDS = ("player", "character", "equip", "weapon", "accessor", "inventory", "slot", "active", "owned")
BAD_WORDS = ("pool", "available", "pickup", "drop", "ground", "spawn", "unlock", "banish", "seen",
             "collection", "shop", "store", "reward", "treasure", "chest", "levelup", "choice", "offer",
             "allweapons", "allitems", "allaccessories", "enemy", "enemies", "factory", "prefab", "cache",
             "cheat", "stats", "tileset", "store", "weighted")


def score_inventory_path(path: tuple[str, ...], size: int, recognised: int) -> float:
    """Higher = more likely to be what the player is holding. 0 or less = rejected."""
    if size > MAX_SLOTS or recognised == 0:
        return 0.0
    names = [normalize(n) for n in path]
    score = recognised + recognised / max(size, 1)  # mostly-recognised lists beat noisy ones
    if any(w in n for n in names for w in BAD_WORDS):
        score -= 100
    score += 3 * sum(1 for n in names if any(w in n for w in GOOD_WORDS))
    return score


def normalize(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


@dataclass(frozen=True)
class Candidate:
    kind: str
    chain: Chain
    score: float
    items: tuple[str, ...]
