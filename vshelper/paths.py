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
