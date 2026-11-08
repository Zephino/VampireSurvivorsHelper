"""Where the helper reads its bundled files from and where it saves its own files.

Running from source: both are the project folder (as before).
Running as the built .exe: bundled files come from inside the exe; settings, the picture cache
and wiki data are saved in %LOCALAPPDATA%\\VampireSurvivorsHelper (an exe can't write into itself).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    USER_ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VampireSurvivorsHelper"
else:
    RESOURCE_ROOT = Path(__file__).resolve().parents[1]
    USER_ROOT = RESOURCE_ROOT


def desktop_dir() -> Path:
    """The user's Desktop folder (also when Windows has moved it, e.g. into OneDrive).

    Falls back to ~/Desktop, then to USER_ROOT if there is no Desktop at all.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            import uuid
            folder_id = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")  # FOLDERID_Desktop
            guid = (ctypes.c_byte * 16).from_buffer_copy(folder_id.bytes_le)
            path_ptr = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32
            shell32.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE,
                                                     ctypes.POINTER(ctypes.c_wchar_p)]
            if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)) == 0:
                desktop = Path(path_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                if desktop.is_dir():
                    return desktop
        except (OSError, AttributeError, ValueError):
            pass  # fall back below
    home_desktop = Path.home() / "Desktop"
    return home_desktop if home_desktop.is_dir() else USER_ROOT
