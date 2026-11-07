"""Find Unity IL2CPP classes, fields and objects in a running game by *name*.

Nothing here uses hard-coded addresses. Classes are located by searching memory for the
class-name string and then for the Il2CppClass structure that points at it. Field offsets
come from the class's own FieldInfo table, so they stay correct across game updates as long
as the game's class/field names stay the same.

Assumes a 64-bit IL2CPP build (Unity 2019+), which is what Vampire Survivors ships.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Protocol

from .winapi import MemoryAccessError

METADATA_MAGIC = 0xFAB11BAF
CHUNK = 16 * 1024 * 1024

# Il2CppClass / FieldInfo layout (64-bit). Offsets that vary between Unity versions are
# detected at runtime in _detect_layout; these are the defaults they are checked against.
CLASS_NAME = 0x10
CLASS_NAMESPACE = 0x18
DEFAULT_PARENT = 0x58
DEFAULT_FIELDS = 0x80
STATIC_AFTER_FIELDS = 0x38  # static_fields sits 7 pointers after fields
FIELDINFO_SIZE = 0x20
FIELD_ATTRIBUTE_STATIC = 0x10
FIELD_ATTRIBUTE_LITERAL = 0x40

# Il2CppTypeEnum codes we care about
TYPE_I4 = 0x08
TYPE_U4 = 0x09
TYPE_STRING = 0x0E
TYPE_VALUETYPE = 0x11
TYPE_CLASS = 0x12
TYPE_GENERICINST = 0x15
TYPE_SZARRAY = 0x1D

# Managed object layouts (64-bit IL2CPP)
STRING_LENGTH = 0x10
STRING_CHARS = 0x14
ARRAY_LENGTH = 0x18
ARRAY_DATA = 0x20

MAX_FIELDS = 1024
MAX_ELEMENTS = 256


class Il2CppError(MemoryAccessError):
    """A class, field or object could not be resolved."""


class Memory(Protocol):
    def read(self, address: int, size: int) -> bytes: ...
    def regions(self, writable_only: bool = False, private_only: bool = False) -> Iterable[tuple[int, int]]: ...


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    attrs: int
    type_code: int
    owner: int  # Il2CppClass* that declares it

    @property
    def is_static(self) -> bool:
        return bool(self.attrs & FIELD_ATTRIBUTE_STATIC)

    @property
    def is_literal(self) -> bool:
        return bool(self.attrs & FIELD_ATTRIBUTE_LITERAL)


def normalize_name(name: str) -> str:
    """'<Player>k__BackingField', '_player', 'm_Player' -> 'player'."""
    n = name.lower()
    if n.startswith("<") and ">k__backingfield" in n:
        n = n[1:n.index(">")]
    if n.startswith("m_"):
        n = n[2:]
    return n.replace("_", "")


class Il2Cpp:
    def __init__(self, mem: Memory):
        self.mem = mem
        self._fields_off: int | None = None
        self._parent_off = DEFAULT_PARENT
        self._field_cache: dict[int, list[Field]] = {}
        self._metadata: tuple[int, int, int] | None = None  # base, string_off, string_size

    # ---- primitive reads -------------------------------------------------
    def u32(self, addr: int) -> int:
        return struct.unpack("<I", self.mem.read(addr, 4))[0]

    def i32(self, addr: int) -> int:
        return struct.unpack("<i", self.mem.read(addr, 4))[0]

    def ptr(self, addr: int) -> int:
        return struct.unpack("<Q", self.mem.read(addr, 8))[0]

    def try_ptr(self, addr: int) -> int:
        try:
            return self.ptr(addr)
        except MemoryAccessError:
            return 0

    def cstr(self, addr: int, max_len: int = 256) -> str | None:
        """Read a NUL-terminated ASCII/UTF-8 string, or None if unreadable or not text."""
        if not addr:
            return None
        out = b""
        step = 64
        while len(out) < max_len:
            try:
                block = self.mem.read(addr + len(out), step)
            except MemoryAccessError:
                if step == 1:
                    return None
                step = 1  # string may end right before an unreadable page
                continue
            end = block.find(b"\0")
            if end >= 0:
                out += block[:end]
                break
            out += block
        else:
            return None
        try:
            text = out.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return text if text.isprintable() else None

    # ---- metadata --------------------------------------------------------
    def find_metadata(self) -> tuple[int, int, int] | None:
        """Locate the mapped global-metadata.dat (base, string table offset, size)."""
        if self._metadata:
            return self._metadata
        for base, size in self.mem.regions():
            if size < 0x100:
                continue
            try:
                head = self.mem.read(base, 0x20)
            except MemoryAccessError:
                continue
            magic, version = struct.unpack_from("<Ii", head, 0)
            if magic == METADATA_MAGIC and 16 <= version <= 64:
                str_off, str_size = struct.unpack_from("<II", head, 0x18)
                self._metadata = (base, str_off, str_size)
                return self._metadata
        return None

    def metadata_strings(self) -> tuple[int, bytes] | None:
        """(address, bytes) of the metadata identifier string table (type/field names)."""
        meta = self.find_metadata()
        if not meta:
            return None
        base, off, size = meta
        data = bytearray()
        pos = 0
        while pos < size:
            n = min(CHUNK, size - pos)
            data += self.mem.read(base + off + pos, n)
            pos += n
        return base + off, bytes(data)

    # ---- scanning --------------------------------------------------------
    def _scan(self, patterns: list[bytes], regions: Iterable[tuple[int, int]], align: int = 1) -> dict[bytes, list[int]]:
        hits: dict[bytes, list[int]] = {p: [] for p in patterns}
        if not patterns:
            return hits
        overlap = max(len(p) for p in patterns) - 1
        for base, size in regions:
            pos = 0
            while pos < size:
                n = min(CHUNK, size - pos)
                try:
                    data = self.mem.read(base + pos, min(n + overlap, size - pos))
                except MemoryAccessError:
                    pos += n
                    continue
                for p in patterns:
                    i = data.find(p)
                    while i != -1:
                        addr = base + pos + i
                        if i < n and addr % align == 0:
                            hits[p].append(addr)
                        i = data.find(p, i + 1)
                pos += n
        return hits

    def _string_addresses(self, names: list[str]) -> dict[str, list[int]]:
        patterns = {n: b"\0" + n.encode() + b"\0" for n in names}
        strings = self.metadata_strings()
        found: dict[str, list[int]] = {n: [] for n in names}
        if strings:
            start, blob = strings
            for n, p in patterns.items():
                if blob.startswith(p[1:]):
                    found[n].append(start)
                i = blob.find(p)
                while i != -1:
                    found[n].append(start + i + 1)
                    i = blob.find(p, i + 1)
        missing = [n for n in names if not found[n]]
        if missing:  # no metadata mapping found: fall back to searching everything
            hits = self._scan([patterns[n] for n in missing], self.mem.regions())
            for n in missing:
                found[n] = [a + 1 for a in hits[patterns[n]]]
        return found

    def find_classes(self, wanted: list[tuple[str, str | None]]) -> dict[str, int]:
        """Find Il2CppClass* for each (name, namespace or None) in one memory pass.

        Returns {name: klass}; names that were not found are left out.
        """
        names = sorted({n for n, _ in wanted})
        string_addrs = self._string_addresses(names)
        pointer_patterns: dict[bytes, str] = {}
        for name, addrs in string_addrs.items():
            for a in addrs:
                pointer_patterns[struct.pack("<Q", a)] = name
        hits = self._scan(list(pointer_patterns), self.mem.regions(writable_only=True, private_only=True), align=8)

        namespaces = {n: ns for n, ns in wanted}
        result: dict[str, int] = {}
        for pattern, addrs in hits.items():
            name = pointer_patterns[pattern]
            for hit in addrs:
                klass = hit - CLASS_NAME
                if not self.is_class(klass) or self.class_name(klass) != name:
                    continue
                ns = namespaces.get(name)
                if ns is not None and self.class_namespace(klass) != ns:
                    continue
                if name not in result or (ns is None and self.fields(klass) and not self.fields(result[name])):
                    result[name] = klass
        return result

    def find_class(self, name: str, namespace: str | None = None) -> int:
        found = self.find_classes([(name, namespace)])
        if name not in found:
            where = f"{namespace}.{name}" if namespace else name
            raise Il2CppError(f"Class '{where}' was not found in game memory.")
        return found[name]

    # ---- classes and fields ----------------------------------------------
    def is_class(self, klass: int) -> bool:
        """Heuristic: valid name string and at least one self-pointer in the header."""
        if not klass:
            return False
        try:
            header = self.mem.read(klass, 0x100)
        except MemoryAccessError:
            return False
        name_ptr = struct.unpack_from("<Q", header, CLASS_NAME)[0]
        name = self.cstr(name_ptr, 512)
        if not name:
            return False
        return any(struct.unpack_from("<Q", header, off)[0] == klass for off in range(0x40, 0x100, 8))

    def class_name(self, klass: int) -> str:
        return self.cstr(self.try_ptr(klass + CLASS_NAME), 512) or "?"

    def class_namespace(self, klass: int) -> str:
        return self.cstr(self.try_ptr(klass + CLASS_NAMESPACE), 512) or ""

    def full_name(self, klass: int) -> str:
        ns = self.class_namespace(klass)
        return f"{ns}.{self.class_name(klass)}" if ns else self.class_name(klass)

    def parent(self, klass: int) -> int:
        p = self.try_ptr(klass + self._parent_off)
        return p if p and p != klass and self.is_class(p) else 0

    def _fields_array_valid(self, klass: int, arr: int) -> bool:
        return bool(arr) and self.try_ptr(arr + 0x10) == klass

    def _detect_fields_offset(self, klass: int) -> int | None:
        if self._fields_array_valid(klass, self.try_ptr(klass + DEFAULT_FIELDS)):
            return DEFAULT_FIELDS
        for off in range(0x60, 0x140, 8):
            if self._fields_array_valid(klass, self.try_ptr(klass + off)):
                return off
        return None

    def own_fields(self, klass: int) -> list[Field]:
        if klass in self._field_cache:
            return self._field_cache[klass]
        if self._fields_off is None:
            detected = self._detect_fields_offset(klass)
            if detected is None:
                return []  # no fields (or not yet set up); don't cache a guess
            self._fields_off = detected
        arr = self.try_ptr(klass + self._fields_off)
        fields: list[Field] = []
        if self._fields_array_valid(klass, arr):
            for i in range(MAX_FIELDS):
                entry = arr + i * FIELDINFO_SIZE
                try:
                    raw = self.mem.read(entry, FIELDINFO_SIZE)
                except MemoryAccessError:
                    break
                name_ptr, type_ptr, owner, offset = struct.unpack_from("<QQQi", raw, 0)
                if owner != klass:
                    break
                name = self.cstr(name_ptr) or f"<field{i}>"
                try:
                    bits = self.u32(type_ptr + 8)
                except MemoryAccessError:
                    bits = 0
                fields.append(Field(name, offset, bits & 0xFFFF, (bits >> 16) & 0xFF, klass))
        self._field_cache[klass] = fields
        return fields

    def fields(self, klass: int) -> list[Field]:
        """Fields of the class and all of its parents (own fields first)."""
        out: list[Field] = []
        seen = set()
        while klass and klass not in seen and len(seen) < 32:
            seen.add(klass)
            out.extend(self.own_fields(klass))
            klass = self.parent(klass)
        return out

    def find_field(self, klass: int, candidates: str | list[str]) -> Field:
        if isinstance(candidates, str):
            candidates = [candidates]
        fields = self.fields(klass)
        for cand in candidates:
            for f in fields:
                if f.name == cand:
                    return f
        wanted = {normalize_name(c) for c in candidates}
        for f in fields:
            if normalize_name(f.name) in wanted:
                return f
        raise Il2CppError(
            f"{self.full_name(klass)} has no field named {' / '.join(candidates)}. "
            f"Fields: {', '.join(f.name for f in fields) or '(none)'}"
        )

    def static_base(self, klass: int) -> int:
        if self._fields_off is None:
            self.own_fields(klass)
        base = self.try_ptr(klass + (self._fields_off or DEFAULT_FIELDS) + STATIC_AFTER_FIELDS)
        if not base:
            raise Il2CppError(f"{self.full_name(klass)} has no static data yet (is a run in progress?).")
        return base

    def read_static_ptr(self, klass: int, candidates: str | list[str]) -> int:
        f = self.find_field(klass, candidates)
        if not f.is_static:
            raise Il2CppError(f"{self.full_name(klass)}.{f.name} is not a static field.")
        return self.try_ptr(self.static_base(klass) + f.offset)

    # ---- objects ---------------------------------------------------------
    def object_class(self, obj: int) -> int:
        klass = self.try_ptr(obj)
        if not self.is_class(klass):
            raise Il2CppError(f"0x{obj:X} does not look like a managed object.")
        return klass

    def read_field_ptr(self, obj: int, candidates: str | list[str]) -> int:
        f = self.find_field(self.object_class(obj), candidates)
        return self.try_ptr(obj + f.offset)

    def read_string(self, obj: int) -> str:
        length = self.i32(obj + STRING_LENGTH)
        if not 0 <= length <= 4096:
            raise Il2CppError(f"0x{obj:X} is not a valid string (length {length}).")
        return self.mem.read(obj + STRING_CHARS, length * 2).decode("utf-16-le", errors="replace")

    def array_elements(self, arr: int, count: int | None = None) -> list[int]:
        length = self.ptr(arr + ARRAY_LENGTH)
        if count is None:
            count = length
        if not 0 <= count <= min(length, MAX_ELEMENTS):
            raise Il2CppError(f"Unexpected array size {count} (capacity {length}).")
        if count == 0:
            return []
        raw = self.mem.read(arr + ARRAY_DATA, count * 8)
        return list(struct.unpack(f"<{count}Q", raw))

    def collection_elements(self, obj: int) -> list[int]:
        """Elements of a List<T> or T[] holding object references (nulls dropped)."""
        klass = self.object_class(obj)
        name = self.class_name(klass)
        if name.endswith("[]"):
            items = self.array_elements(obj)
        else:
            items_arr = self.read_field_ptr(obj, ["_items", "items"])
            size = self.i32(obj + self.find_field(klass, ["_size", "size"]).offset)
            if not items_arr:
                return []
            items = self.array_elements(items_arr, size)
        return [p for p in items if p]

    MAX_DICT_ENTRIES = 4096

    def dictionary_items(self, obj: int) -> list[tuple[int, int]]:
        """(int key, object value) pairs of a Dictionary<int-or-enum, object>.

        Entries are structs {hashCode, next, key, value}; their size isn't recorded anywhere we
        read, so the common layouts are tried and the one whose values are real objects is used.
        """
        klass = self.object_class(obj)
        entries = self.read_field_ptr(obj, ["_entries", "entries"])
        count = self.i32(obj + self.find_field(klass, ["_count", "count"]).offset)
        if not entries or not 0 < count <= self.MAX_DICT_ENTRIES:
            return []
        length = self.ptr(entries + ARRAY_LENGTH)
        count = min(count, length)
        for stride in (24, 16, 32):
            try:
                raw = self.mem.read(entries + ARRAY_DATA, count * stride)
            except MemoryAccessError:
                continue
            pairs = []
            for i in range(count):
                _hash, nxt, key = struct.unpack_from("<iii", raw, i * stride)
                value = struct.unpack_from("<Q", raw, i * stride + stride - 8)[0]
                if nxt < -1 or not value:  # free slot
                    continue
                pairs.append((key, value))
            sample = pairs[:8]
            if sample and all(self.is_class(self.try_ptr(v)) for _, v in sample):
                return pairs
        raise Il2CppError("Could not read the dictionary's entries.")

    def enum_names(self, klass: int) -> list[str]:
        """Constant names of an enum class in declaration order (value__ excluded)."""
        return [f.name for f in self.own_fields(klass) if f.is_literal]
