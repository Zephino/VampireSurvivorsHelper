"""Starting Vampire Survivors through Steam, and checking whether it is already running."""

from __future__ import annotations

import os
import sys
import webbrowser

from .icons import STEAM_APP_ID
from .memory.winapi import MemoryAccessError, find_process_id

STEAM_URL = f"steam://rungameid/{STEAM_APP_ID}"


def is_running(process_name: str = "VampireSurvivors.exe") -> bool:
    try:
        find_process_id(process_name)
        return True
    except MemoryAccessError:  # not running (or not Windows)
        return False


def launch() -> str | None:
    """Ask Steam to start the game. Returns an error message, or None if the request was sent."""
    try:
        if sys.platform == "win32":
            os.startfile(STEAM_URL)  # opens the steam:// link with Steam
        elif not webbrowser.open(STEAM_URL):
            return "Couldn't start the game: no program is set up to open Steam links."
    except OSError as exc:
        return f"Couldn't start Vampire Survivors through Steam ({exc}). Is Steam installed?"
    return None
