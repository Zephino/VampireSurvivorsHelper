"""User settings, saved to settings.json in the project folder (kept out of git)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.json"


@dataclass
class Settings:
    # Expansions the user switched off; everything else is shown (so new DLC is on by default).
    hidden_expansions: list[str] = field(default_factory=list)
    dark_theme: bool = True
    check_updates_on_start: bool = True
    # What the main screen shows (Settings > Main screen)
    show_holding: bool = True
    show_ready: bool = True
    show_how_to: bool = True
    show_no_evolution: bool = True
    show_levels: bool = True
    show_details: bool = True
    show_game_check: bool = True
    show_pictures: bool = True


# Labels for the Main screen switches, in the order they appear in Settings.
MAIN_SCREEN_OPTIONS = [
    ("show_holding", "Overview: You're holding"),
    ("show_ready", "Overview: Ready to evolve"),
    ("show_how_to", "How to evolve tab"),
    ("show_no_evolution", "Items with no evolution"),
    ("show_levels", "Item levels (Lv 5/8, LEVEL UP)"),
    ("show_details", "Details (max level, notes)"),
    ("show_game_check", "Game-file check marks"),
    ("show_pictures", "Item pictures"),
]


def load(path: Path | None = None) -> tuple[Settings, str | None]:
    """Return (settings, warning). A missing file gives defaults; a broken one gives defaults plus a warning.

    Unknown or wrongly typed values fall back to their defaults one by one.
    """
    path = path or SETTINGS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings(), None
    except (OSError, ValueError) as exc:
        return Settings(), f"Could not read {path.name}, using defaults ({exc})."
    if not isinstance(raw, dict):
        return Settings(), f"{path.name} is not a settings object, using defaults."
    s = Settings()
    hidden = raw.get("hidden_expansions", [])
    if isinstance(hidden, list):
        s.hidden_expansions = [h for h in hidden if isinstance(h, str)]
    for f in fields(Settings):
        if f.type in ("bool", bool) and isinstance(raw.get(f.name), bool):
            setattr(s, f.name, raw[f.name])
    return s, None


def save(settings: Settings, path: Path | None = None) -> str | None:
    """Write settings; returns an error message instead of raising so the UI can show it."""
    path = path or SETTINGS_PATH
    try:
        path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    except OSError as exc:
        return f"Could not save settings to {path} ({exc})."
    return None
