"""User settings, saved to settings.json in the project folder (kept out of git)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.json"


@dataclass
class Settings:
    # Expansions the user switched off; everything else is shown (so new DLC is on by default).
    hidden_expansions: list[str] = field(default_factory=list)


def load(path: Path | None = None) -> tuple[Settings, str | None]:
    """Return (settings, warning). A missing file gives defaults; a broken one gives defaults plus a warning."""
    path = path or SETTINGS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings(), None
    except (OSError, ValueError) as exc:
        return Settings(), f"Could not read {path.name}, using defaults ({exc})."
    if not isinstance(raw, dict):
        return Settings(), f"{path.name} is not a settings object, using defaults."
    hidden = raw.get("hidden_expansions", [])
    if not isinstance(hidden, list):
        hidden = []
    return Settings(hidden_expansions=[h for h in hidden if isinstance(h, str)]), None


def save(settings: Settings, path: Path | None = None) -> str | None:
    """Write settings; returns an error message instead of raising so the UI can show it."""
    path = path or SETTINGS_PATH
    try:
        path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    except OSError as exc:
        return f"Could not save settings to {path} ({exc})."
    return None
