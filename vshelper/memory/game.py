"""Reads the player's current weapons and passive items from Vampire Survivors' memory."""

from __future__ import annotations

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

DEFAULT_GAME_MAP = Path(__file__).resolve().parents[2] / "config" / "game_map.json"
POINTER_TYPES = (TYPE_CLASS, TYPE_GENERICINST, TYPE_SZARRAY)
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
        for item in db.items.values():
            self._canon.setdefault(_canon(item.id), item.id)
            self._canon.setdefault(_canon(item.name), item.id)

    def add_aliases(self, aliases: dict[str, str]) -> None:
        """Add internal-name -> item id pairs (e.g. read from the game files)."""
        for k, v in aliases.items():
            if v in self.db.items:
                self.aliases.setdefault(k.upper(), v)

    def match(self, raw: str) -> str | None:
        if raw in self.id_map:
            return self.id_map[raw] if self.id_map[raw] in self.db.items else None
        alias = self.aliases.get(raw.upper())
        if alias in self.db.items:
            return alias
        return self._canon.get(_canon(raw))


@dataclass(frozen=True)
class ReadResult:
    state: str  # not_running | waiting | ok | error
    message: str
    owned: frozenset[str] = frozenset()
    unrecognized: tuple[str, ...] = ()


@dataclass
class Chain:
    root_index: int
    fields: tuple[str, ...]


@dataclass
class _Session:
    mem: Memory
    il2: Il2Cpp
    root_classes: dict[int, int] = field(default_factory=dict)  # root index -> klass
    enums: list[list[str]] = field(default_factory=list)
    chains: dict[str, Chain] = field(default_factory=dict)
    last_discovery: float = 0.0
    rejected: set[tuple[str, ...]] = field(default_factory=set)  # paths that turned out not to be the inventory


class GameReader:
    def __init__(self, db: Database, game_map: GameMap,
                 open_memory: Callable[[str], Memory] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.db = db
        self.map = game_map
        self.matcher = ItemMatcher(db, dict(game_map.enum_aliases), game_map.id_map)
        self._open = open_memory or ProcessMemory.open_by_name
        self._clock = clock
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
                    s.chains[kind] = Chain(i, names)
                    break

        if len(s.chains) < len(self.map.inventories) and self._clock() - s.last_discovery >= REDISCOVER_SECONDS:
            s.last_discovery = self._clock()
            for kind, chain in self.discover(s, roots).items():
                s.chains.setdefault(kind, chain)

        owned: set[str] = set()
        unknown: list[str] = []
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
                if len(elements) > MAX_SLOTS:
                    s.rejected.add(chain.fields)
                    del s.chains[kind]
                    continue
                for el in elements:
                    raw = self.identify(s, el)
                    if raw is None:
                        continue
                    item = self.matcher.match(raw)
                    if item:
                        owned.add(item)
                    elif raw not in unknown:
                        unknown.append(raw)
                found_any = True
            except MemoryAccessError:
                del s.chains[kind]  # path went stale; find it again next poll

        if not found_any:
            return ReadResult("waiting", "Game found. Waiting for a run to start.")
        msg = f"Reading game: {len(owned)} item(s) detected."
        if unknown:
            msg += f" Unrecognized: {', '.join(unknown)}"
        return ReadResult("ok", msg, frozenset(owned), tuple(unknown))

    # ---- path helpers ----------------------------------------------------
    def _follow(self, il2: Il2Cpp, obj: int, names: tuple[str, ...]) -> int:
        for name in names:
            if not obj:
                return 0
            obj = il2.read_field_ptr(obj, name)
        return obj

    def _follow_candidates(self, il2: Il2Cpp, obj: int, path: list[list[str]]) -> tuple[str, ...] | None:
        names: list[str] = []
        for candidates in path:
            try:
                f = il2.find_field(il2.object_class(obj), candidates)
            except Il2CppError:
                return None
            names.append(f.name)
            obj = il2.try_ptr(obj + f.offset)
            if not obj:
                return None
        try:
            il2.collection_elements(obj)
        except MemoryAccessError:
            return None
        return tuple(names)

    def identify(self, s: _Session, element: int) -> str | None:
        """Return the raw identifier of an equipment object (enum name or string), if any."""
        il2 = s.il2
        try:
            f = il2.find_field(il2.object_class(element), self.map.type_field)
        except MemoryAccessError:
            return None
        addr = element + f.offset
        try:
            if f.type_code in (TYPE_STRING, TYPE_CLASS):
                str_obj = il2.try_ptr(addr)
                return il2.read_string(str_obj) if str_obj else None
            if f.type_code in (TYPE_I4, TYPE_U4, TYPE_VALUETYPE):
                value = il2.i32(addr)
                for names in s.enums:
                    if 0 <= value < len(names) and self.matcher.match(names[value]):
                        return names[value]
                if s.enums and 0 <= value < len(s.enums[0]):
                    return s.enums[0][value]
                return f"#{value}"
        except MemoryAccessError:
            return None
        return None

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


MAX_SLOTS = 12  # inventories hold at most a dozen of each kind, even with extra slots
GOOD_WORDS = ("player", "character", "equip", "weapon", "accessor", "inventory", "slot", "active", "owned")
BAD_WORDS = ("pool", "available", "pickup", "drop", "ground", "spawn", "unlock", "banish", "seen",
             "collection", "shop", "store", "reward", "treasure", "chest", "levelup", "choice", "offer",
             "allweapons", "allitems", "allaccessories", "enemy", "enemies", "factory", "prefab", "cache")


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
