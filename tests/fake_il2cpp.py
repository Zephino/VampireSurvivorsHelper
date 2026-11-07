"""Builds a fake IL2CPP process image in memory for testing the reader without the game."""

from __future__ import annotations

import struct

from vshelper.memory.il2cpp import (
    FIELD_ATTRIBUTE_LITERAL, FIELD_ATTRIBUTE_STATIC, METADATA_MAGIC, TYPE_CLASS, TYPE_GENERICINST,
    TYPE_I4, TYPE_SZARRAY, TYPE_VALUETYPE,
)
from vshelper.memory.winapi import MemoryAccessError

HEAP = 0x1000_0000
META = 0x2000_0000


class FakeMemory:
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
    """A tiny object graph shaped like a Unity game manager -> player -> equipment lists."""

    def __init__(self, root_name="GM", root_field="Core", player_field="_player",
                 weapons_field="_activeEquipment", enum_names=("WHIP", "MAGIC_MISSILE", "POWER", "MAXHEALTH")):
        self.m = FakeMemory()
        self._pending_names: list[tuple[int, int]] = []  # (address to patch, string offset)
        self.enum_names = list(enum_names)

        self.list_cls = self.make_class("List`1", [("_items", TYPE_SZARRAY, 0x10, 0), ("_size", TYPE_I4, 0x18, 0)])
        self.array_cls = self.make_class("Equipment[]", [])
        self.equip_cls = self.make_class("Equipment", [("_type", TYPE_VALUETYPE, 0x10, 0)])
        self.enum_cls = self.make_class(
            "WeaponType",
            [("value__", TYPE_I4, 0x10, 0)] + [(n, TYPE_VALUETYPE, 0, FIELD_ATTRIBUTE_LITERAL | FIELD_ATTRIBUTE_STATIC)
                                              for n in self.enum_names],
        )
        self.wm_cls = self.make_class("WeaponsManager", [(weapons_field, TYPE_GENERICINST, 0x10, 0)])
        self.am_cls = self.make_class("AccessoriesManager", [(weapons_field, TYPE_GENERICINST, 0x10, 0)])
        self.player_cls = self.make_class("CharacterController", [
            ("_weaponsManager", TYPE_CLASS, 0x10, 0), ("_accessoriesManager", TYPE_CLASS, 0x18, 0)])
        self.gm_obj_cls = self.make_class("GameManager", [(player_field, TYPE_CLASS, 0x10, 0)])
        self.root_cls = self.make_class(root_name, [(root_field, TYPE_CLASS, 0x0, FIELD_ATTRIBUTE_STATIC)])

        self.weapon_list = self.make_list([])
        self.passive_list = self.make_list([])
        wm = self.obj(self.wm_cls, 0x18)
        self.m.w64(wm + 0x10, self.weapon_list)
        am = self.obj(self.am_cls, 0x18)
        self.m.w64(am + 0x10, self.passive_list)
        self.player = self.obj(self.player_cls, 0x20)
        self.m.w64(self.player + 0x10, wm)
        self.m.w64(self.player + 0x18, am)
        self.gm = self.obj(self.gm_obj_cls, 0x18)
        self.m.w64(self.gm + 0x10, self.player)
        statics = self.m.alloc(0x10)
        self.m.w64(statics, self.gm)
        self.m.w64(self.root_cls + 0xB8, statics)

        self.m.finish()
        for addr, off in self._pending_names:
            self.m.w64(addr, self.m.meta_addr(off))

    def make_class(self, name: str, fields: list[tuple[str, int, int, int]], parent: int = 0) -> int:
        klass = self.m.alloc(0x120)
        self._pending_names.append((klass + 0x10, self.m.string(name)))
        self._pending_names.append((klass + 0x18, self.m.string("Game")))
        for off in (0x40, 0x48, 0x78):
            self.m.w64(klass + off, klass)
        self.m.w64(klass + 0x58, parent)
        if fields:
            arr = self.m.alloc(0x20 * len(fields))
            for i, (fname, tcode, offset, attrs) in enumerate(fields):
                entry = arr + i * 0x20
                typ = self.m.alloc(0x10)
                self.m.w32(typ + 8, attrs | (tcode << 16))
                self._pending_names.append((entry, self.m.string(fname)))
                self.m.w64(entry + 8, typ)
                self.m.w64(entry + 0x10, klass)
                self.m.w32(entry + 0x18, offset)
            self.m.w64(klass + 0x80, arr)
        return klass

    def obj(self, klass: int, size: int) -> int:
        o = self.m.alloc(size)
        self.m.w64(o, klass)
        return o

    def make_list(self, values: list[int], capacity: int = 8) -> int:
        arr = self.obj(self.array_cls, 0x20 + 8 * capacity)
        self.m.w64(arr + 0x18, capacity)
        lst = self.obj(self.list_cls, 0x20)
        self.m.w64(lst + 0x10, arr)
        self.set_list(lst, values)
        return lst

    def set_list(self, lst: int, values: list[int]) -> None:
        arr = struct.unpack_from("<Q", self.m.heap, lst + 0x10 - HEAP)[0]
        for i, v in enumerate(values):
            e = self.obj(self.equip_cls, 0x18)
            self.m.w32(e + 0x10, v)
            self.m.w64(arr + 0x20 + 8 * i, e)
        self.m.w32(lst + 0x18, len(values))
