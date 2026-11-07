"""Read-only access to another process's memory on Windows (ctypes, no extra packages).

Only PROCESS_VM_READ and PROCESS_QUERY_INFORMATION are requested: the helper never writes
to the game.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Iterator


class MemoryAccessError(Exception):
    """The game process could not be found, opened, or read."""


class ProcessNotFound(MemoryAccessError):
    pass


IS_WINDOWS = sys.platform == "win32"

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = 0x02 | 0x04 | 0x08 | 0x20 | 0x40 | 0x80  # R, RW, WC, XR, XRW, XWC
WRITABLE = 0x04 | 0x08 | 0x40 | 0x80
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


if IS_WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k32.VirtualQueryEx.restype = ctypes.c_size_t
    _k32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
    ]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
STILL_ACTIVE = 259


def find_process_id(exe_name: str) -> int:
    if not IS_WINDOWS:
        raise MemoryAccessError("Reading game memory is only supported on Windows.")
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise MemoryAccessError(f"Could not list processes (error {ctypes.get_last_error()}).")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                return entry.th32ProcessID
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    raise ProcessNotFound(f"{exe_name} is not running.")


class ProcessMemory:
    """Handle to a running process opened for reading."""

    def __init__(self, pid: int):
        if not IS_WINDOWS:
            raise MemoryAccessError("Reading game memory is only supported on Windows.")
        self.pid = pid
        self._handle = _k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self._handle:
            err = ctypes.get_last_error()
            hint = " Try running the helper as administrator." if err == 5 else ""
            raise MemoryAccessError(f"Could not open the game process (error {err}).{hint}")

    @classmethod
    def open_by_name(cls, exe_name: str) -> "ProcessMemory":
        return cls(find_process_id(exe_name))

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None

    def is_alive(self) -> bool:
        code = wintypes.DWORD()
        if not self._handle or not _k32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE

    def read(self, address: int, size: int) -> bytes:
        """Read exactly `size` bytes or raise MemoryAccessError."""
        if address <= 0 or size <= 0:
            raise MemoryAccessError(f"Invalid read at 0x{address:X} ({size} bytes).")
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not _k32.ReadProcessMemory(self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)) \
                or got.value != size:
            raise MemoryAccessError(f"Could not read {size} bytes at 0x{address:X}.")
        return buf.raw

    def regions(self, writable_only: bool = False, private_only: bool = False) -> Iterator[tuple[int, int]]:
        """Yield (base, size) of committed, readable memory regions."""
        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0
        while _k32.VirtualQueryEx(self._handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            protect = mbi.Protect
            if (mbi.State == MEM_COMMIT and protect & READABLE and not protect & (PAGE_GUARD | PAGE_NOACCESS)
                    and (not writable_only or protect & WRITABLE)
                    and (not private_only or mbi.Type == MEM_PRIVATE)):
                yield base, size
            next_addr = base + size
            if next_addr <= addr:
                break
            addr = next_addr

    def __enter__(self) -> "ProcessMemory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
