"""Builds a fake IL2CPP process image in memory for testing the reader without the game."""

from __future__ import annotations

import struct

from vshelper.memory.il2cpp import (
    FIELD_ATTRIBUTE_LITERAL, FIELD_ATTRIBUTE_STATIC, METADATA_MAGIC, TYPE_CLASS, TYPE_GENERICINST,
    TYPE_I4, TYPE_STRING, TYPE_SZARRAY, TYPE_VALUETYPE,
)
from vshelper.memory.winapi import MemoryAccessError

HEAP = 0x1000_0000
META = 0x2000_0000


class FakeMemory:
    pid = 1234

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def __init__(self) -> None:
        self.heap = bytearray(0x10000)
        self.top = 0x100
        self.meta_strings = bytearray(b"\0")
        self.meta: bytes = b""

    # -- Memory protocol --
    def read(self, address: int, size: int) -> bytes:
        for base, data in ((HEAP, self.heap), (META, self.meta)):
            if base <= address and address + size <= base + len(data):
                return bytes(data[address - base:address - base + size])
        raise MemoryAccessError(f"unmapped 0x{address:X}")

    def regions(self, writable_only: bool = False, private_only: bool = False):
        if not writable_only and not private_only:
            yield META, len(self.meta)
        yield HEAP, len(self.heap)

    # -- builders --
    def alloc(self, size: int) -> int:
        addr = HEAP + self.top
        self.top += (size + 15) & ~15
        return addr

    def w64(self, addr: int, value: int) -> None:
        struct.pack_into("<Q", self.heap, addr - HEAP, value)

    def w32(self, addr: int, value: int) -> None:
        struct.pack_into("<i", self.heap, addr - HEAP, value)

    def string(self, text: str) -> int:
        """Identifier string inside the metadata string table; returns its future address."""
        off = len(self.meta_strings)
        self.meta_strings += text.encode() + b"\0"
        return off  # resolved to an address in finish()

    def finish(self) -> None:
        header = bytearray(0x100)
        struct.pack_into("<Ii", header, 0, METADATA_MAGIC, 29)
        struct.pack_into("<II", header, 0x18, 0x100, len(self.meta_strings))
        self.meta = bytes(header + self.meta_strings)

    def meta_addr(self, string_off: int) -> int:
        return META + 0x100 + string_off


class FakeGame:
    """A tiny object graph shaped like the real game (from a diagnose report):
    GM.Core -> GameManager._mainCharacters[0] -> CharacterController
            -> WeaponsManager / AccessoriesManager -> ActiveEquipment (List of Equipment)."""

    def __init__(self, root_name="GM", root_field="Core", player_field="_mainCharacters",
                 weapons_field="ActiveEquipment", enum_names=("VOID", "WHIP", "MAGIC_MISSILE", "POWER", "MAXHEALTH")):
        self.m = FakeMemory()
        self._pending_names: list[tuple[int, int]] = []  # (address to patch, string offset)
        self.enum_names = list(enum_names)

        self.list_cls = self.make_class("List`1", [("_items", TYPE_SZARRAY, 0x10, 0), ("_size", TYPE_I4, 0x18, 0)])
        self.array_cls = self.make_class("Equipment[]", [])
        # Like the real game: an enum id, a *Data object holding the name, and level fields.
        self.equip_cls = self.make_class("Equipment", [
            ("_equipmentType", TYPE_VALUETYPE, 0x10, 0), ("_currentWeaponData", TYPE_CLASS, 0x18, 0),
            ("<Level>k__BackingField", TYPE_I4, 0x20, 0), ("<LevelsNumber>k__BackingField", TYPE_I4, 0x24, 0)])
        self.data_cls = self.make_class("WeaponData", [
            ("<name>k__BackingField", TYPE_STRING, 0x10, 0), ("<frameName>k__BackingField", TYPE_STRING, 0x18, 0),
            ("<evoInto>k__BackingField", TYPE_STRING, 0x20, 0)])
        # The game's item catalogue: DataManager.AllWeaponData = Dictionary<WeaponType, List<WeaponData>>
        self.dict_cls = self.make_class("Dictionary`2", [("_entries", TYPE_SZARRAY, 0x10, 0), ("_count", TYPE_I4, 0x18, 0)])
        self.entry_arr_cls = self.make_class("Entry[]", [])
        self.datamanager_cls = self.make_class("DataManager", [("<AllWeaponData>k__BackingField", TYPE_GENERICINST, 0x10, 0)])
        self.string_cls = self.make_class("String", [])
        self.enum_cls = self.make_class(
            "WeaponType",
            [("value__", TYPE_I4, 0x10, 0)] + [(n, TYPE_VALUETYPE, 0, FIELD_ATTRIBUTE_LITERAL | FIELD_ATTRIBUTE_STATIC)
                                              for n in self.enum_names],
        )
        self.wm_cls = self.make_class("WeaponsManager", [(weapons_field, TYPE_GENERICINST, 0x10, 0)])
        self.am_cls = self.make_class("AccessoriesManager", [(weapons_field, TYPE_GENERICINST, 0x10, 0)])
        self.player_cls = self.make_class("CharacterController", [
            ("_weaponsManager", TYPE_CLASS, 0x10, 0), ("_accessoriesManager", TYPE_CLASS, 0x18, 0)])
        self.gm_obj_cls = self.make_class("GameManager", [(player_field, TYPE_GENERICINST, 0x10, 0),
                                                          ("_dataManager", TYPE_CLASS, 0x18, 0)])
        self.root_cls = self.make_class(root_name, [(root_field, TYPE_CLASS, 0x0, FIELD_ATTRIBUTE_STATIC)],
                                        namespace="VampireSurvivors.Framework")

        self.weapon_list = self.make_list([])
        self.passive_list = self.make_list([])
        wm = self.obj(self.wm_cls, 0x18)
        self.m.w64(wm + 0x10, self.weapon_list)
        am = self.obj(self.am_cls, 0x18)
        self.m.w64(am + 0x10, self.passive_list)
        self.player = self.obj(self.player_cls, 0x20)
        self.m.w64(self.player + 0x10, wm)
        self.m.w64(self.player + 0x18, am)
        self.gm = self.obj(self.gm_obj_cls, 0x20)
        self.players = self.make_list([])
        self.set_objects(self.players, [self.player])
        self.m.w64(self.gm + 0x10, self.players)
        statics = self.m.alloc(0x10)
        self.m.w64(statics, self.gm)
        self.m.w64(self.root_cls + 0xB8, statics)

        self.m.finish()
        for addr, off in self._pending_names:
            self.m.w64(addr, self.m.meta_addr(off))
        self._finished = True

    def make_class(self, name: str, fields: list[tuple[str, int, int, int]], parent: int = 0,
                   namespace: str = "Game") -> int:
        klass = self.m.alloc(0x120)
        self._set_name(klass + 0x10, name)
        self._set_name(klass + 0x18, namespace)
        for off in (0x40, 0x48, 0x78):
            self.m.w64(klass + off, klass)
        self.m.w64(klass + 0x58, parent)
        if fields:
            arr = self.m.alloc(0x20 * len(fields))
            for i, (fname, tcode, offset, attrs) in enumerate(fields):
                entry = arr + i * 0x20
                typ = self.m.alloc(0x10)
                self.m.w32(typ + 8, attrs | (tcode << 16))
                self._set_name(entry, fname)
                self.m.w64(entry + 8, typ)
                self.m.w64(entry + 0x10, klass)
                self.m.w32(entry + 0x18, offset)
            self.m.w64(klass + 0x80, arr)
        return klass

    def _set_name(self, addr: int, text: str) -> None:
        """Point addr at a C string: in the metadata while building, on the heap afterwards."""
        if getattr(self, "_finished", False):
            raw = text.encode() + b"\0"
            where = self.m.alloc(len(raw))
            self.m.heap[where - HEAP:where - HEAP + len(raw)] = raw
            self.m.w64(addr, where)
        else:
            self._pending_names.append((addr, self.m.string(text)))

    def obj(self, klass: int, size: int) -> int:
        o = self.m.alloc(size)
        self.m.w64(o, klass)
        return o

    def make_list(self, values: list[int], capacity: int = 32) -> int:
        arr = self.obj(self.array_cls, 0x20 + 8 * capacity)
        self.m.w64(arr + 0x18, capacity)
        lst = self.obj(self.list_cls, 0x20)
        self.m.w64(lst + 0x10, arr)
        self.set_list(lst, values)
        return lst

    def set_list(self, lst: int, values: list[int]) -> None:
        """Equipment identified only by its enum number (no data object, no levels)."""
        arr = struct.unpack_from("<Q", self.m.heap, lst + 0x10 - HEAP)[0]
        for i, v in enumerate(values):
            e = self.obj(self.equip_cls, 0x28)
            self.m.w32(e + 0x10, v)
            self.m.w64(arr + 0x20 + 8 * i, e)
        self.m.w32(lst + 0x18, len(values))

    def make_string(self, text: str) -> int:
        raw = text.encode("utf-16-le")
        o = self.obj(self.string_cls, 0x14 + len(raw) + 2)
        self.m.w32(o + 0x10, len(text))
        self.m.heap[o + 0x14 - HEAP:o + 0x14 - HEAP + len(raw)] = raw
        return o

    def set_named(self, lst: int, items: list[tuple[str, int, int]], enum_value: int = 1433) -> None:
        """Equipment like the real game: enum number that doesn't match the enum order, a
        WeaponData object with the item's name, and level / max level."""
        arr = struct.unpack_from("<Q", self.m.heap, lst + 0x10 - HEAP)[0]
        for i, (name, level, max_level) in enumerate(items):
            e = self.obj(self.equip_cls, 0x28)
            self.m.w32(e + 0x10, enum_value)
            data = self.make_data(name)
            self.m.w64(e + 0x18, data)
            self.m.w32(e + 0x20, level)
            self.m.w32(e + 0x24, max_level)
            self.m.w64(arr + 0x20 + 8 * i, e)
        self.m.w32(lst + 0x18, len(items))

    def set_objects(self, lst: int, objects: list[int]) -> None:
        """Fill a list with existing object pointers (e.g. the players list)."""
        arr = struct.unpack_from("<Q", self.m.heap, lst + 0x10 - HEAP)[0]
        for i, o in enumerate(objects):
            self.m.w64(arr + 0x20 + 8 * i, o)
        self.m.w32(lst + 0x18, len(objects))

    def make_data(self, name: str, frame: str = "", evo_into: str = "") -> int:
        data = self.obj(self.data_cls, 0x28)
        self.m.w64(data + 0x10, self.make_string(name))
        if frame:
            self.m.w64(data + 0x18, self.make_string(frame))
        if evo_into:
            self.m.w64(data + 0x20, self.make_string(evo_into))
        return data

    def set_catalog(self, items: list[tuple[int, str, str, str]]) -> None:
        """Fill DataManager.AllWeaponData with (enum value, name, frame, evoInto) entries, each a
        List<WeaponData> like the game (24-byte entries: hash, next, key, padding, value)."""
        stride = 24
        arr = self.obj(self.entry_arr_cls, 0x20 + stride * (len(items) + 1))
        self.m.w64(arr + 0x18, len(items) + 1)
        for i, (key, name, frame, evo) in enumerate(items):
            levels = self.make_list([])
            self.set_objects(levels, [self.make_data(name, frame, evo)])
            entry = arr + 0x20 + i * stride
            self.m.w32(entry, key * 7919)  # hash
            self.m.w32(entry + 4, -1)      # next: end of chain
            self.m.w32(entry + 8, key)
            self.m.w64(entry + 16, levels)
        d = self.obj(self.dict_cls, 0x20)
        self.m.w64(d + 0x10, arr)
        self.m.w32(d + 0x18, len(items))
        dm = self.obj(self.datamanager_cls, 0x18)
        self.m.w64(dm + 0x10, d)
        self.m.w64(self.gm + 0x18, dm)

    def add_player(self, class_name: str = "CharacterController") -> tuple[int, int]:
        """Add another co-op player; returns (weapon list, passive list) to fill."""
        cls = self.player_cls if class_name == "CharacterController" else self.make_class(
            class_name, [], parent=self.player_cls)
        weapons, passives = self.make_list([]), self.make_list([])
        wm = self.obj(self.wm_cls, 0x18)
        self.m.w64(wm + 0x10, weapons)
        am = self.obj(self.am_cls, 0x18)
        self.m.w64(am + 0x10, passives)
        player = self.obj(cls, 0x20)
        self.m.w64(player + 0x10, wm)
        self.m.w64(player + 0x18, am)
        arr = struct.unpack_from("<Q", self.heap_bytes(), self.players + 0x10 - HEAP)[0]
        count = struct.unpack_from("<i", self.heap_bytes(), self.players + 0x18 - HEAP)[0]
        self.m.w64(arr + 0x20 + 8 * count, player)
        self.m.w32(self.players + 0x18, count + 1)
        return weapons, passives

    def heap_bytes(self) -> bytearray:
        return self.m.heap

