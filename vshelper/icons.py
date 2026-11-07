"""Item pictures, extracted once from the player's own game files into cache/icons/.

The game's artwork is not shipped with this project. On first start (and after a game update)
the helper reads the sprites from the installed game with UnityPy and saves small PNGs locally.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .data import Database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "cache" / "icons"
MANIFEST = "manifest.json"
ICON_SIZE = 32
STEAM_APP_ID = "1794680"
GAME_FOLDER = "Vampire Survivors"
AFFIXES = ("icon", "item", "sprite", "weapon", "passive", "png", "frame")


class IconError(Exception):
    """Pictures could not be extracted; the message says why and what to do."""


@dataclass
class ExtractReport:
    found: dict[str, str] = field(default_factory=dict)  # item id -> sprite name
    missing: list[str] = field(default_factory=list)
    sprite_count: int = 0


def canon(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _strip_affixes(name: str) -> str:
    changed = True
    while changed:
        changed = False
        for a in AFFIXES:
            if name.endswith(a) and len(name) > len(a) + 2:
                name, changed = name[: -len(a)], True
            elif name.startswith(a) and len(name) > len(a) + 2:
                name, changed = name[len(a):], True
    return name


# ---- locating the game --------------------------------------------------
def _steam_root() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg
    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                return Path(winreg.QueryValueEx(k, value)[0])
        except OSError:
            continue
    return None


def steam_libraries(steam_root: Path) -> list[Path]:
    libs = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)
    return libs


def find_game_dir(running_exe: Path | None = None) -> Path | None:
    """Find the Vampire Survivors install folder (running game first, then Steam libraries)."""
    if running_exe and running_exe.exists():
        return running_exe.parent
    root = _steam_root()
    if not root:
        return None
    for lib in steam_libraries(root):
        folder = GAME_FOLDER
        manifest = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        try:
            m = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(encoding="utf-8", errors="replace"))
            if m:
                folder = m.group(1)
        except OSError:
            pass
        game = lib / "steamapps" / "common" / folder
        if game.is_dir():
            return game
    return None


def _data_dir(game_dir: Path) -> Path:
    for p in game_dir.glob("*_Data"):
        if p.is_dir():
            return p
    raise IconError(f"No Unity data folder (*_Data) found in {game_dir}.")


def _build_marker(game_dir: Path) -> str:
    for name in ("GameAssembly.dll", "VampireSurvivors.exe"):
        p = game_dir / name
        if p.exists():
            st = p.stat()
            return f"{name}:{st.st_size}:{int(st.st_mtime)}"
    return ""


# ---- matching sprites to items ------------------------------------------
def build_lookup(db: Database, aliases: dict[str, str]) -> dict[str, str]:
    """Canonical name -> item id, from item ids, display names and the game's internal names."""
    lookup: dict[str, str] = {}
    for item in db.items.values():
        lookup.setdefault(canon(item.id), item.id)
        lookup.setdefault(canon(item.name), item.id)
    for internal, item_id in aliases.items():
        if item_id in db.items:
            lookup.setdefault(canon(internal), item_id)
    return lookup


def frame_names_from_json(text: str, lookup: dict[str, str]) -> dict[str, str]:
    """Find {item id: sprite frame name} in game data JSON (entries with a name and frameName)."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    found: dict[str, str] = {}

    def visit(node, key: str | None) -> None:
        if isinstance(node, dict):
            frame = node.get("frameName") or node.get("frame") or node.get("sprite")
            if isinstance(frame, str):
                for label in (node.get("name"), key):
                    if isinstance(label, str) and canon(label) in lookup:
                        found.setdefault(lookup[canon(label)], frame)
            for k, v in node.items():
                visit(v, k if isinstance(k, str) else key)
        elif isinstance(node, list):
            for v in node:
                visit(v, key)

    visit(data, None)
    return found


def match_sprite(sprite_name: str, lookup: dict[str, str]) -> str | None:
    c = canon(sprite_name)
    return lookup.get(c) or lookup.get(_strip_affixes(c))


def _fit(image):
    """Scale to ICON_SIZE (pixel-art friendly) and centre on a transparent square."""
    from PIL import Image
    image = image.convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    w, h = image.size
    scale = ICON_SIZE / max(w, h)
    resample = Image.NEAREST if scale >= 1 else Image.LANCZOS
    image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))), resample)
    canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE))
    canvas.paste(image, ((ICON_SIZE - image.width) // 2, (ICON_SIZE - image.height) // 2))
    return canvas


def extract_icons(game_dir: Path, db: Database, aliases: dict[str, str], out_dir: Path | None = None,
                  progress: Callable[[str], None] = lambda _m: None) -> ExtractReport:
    out_dir = out_dir or CACHE_DIR
    try:
        import UnityPy
    except ImportError as exc:
        raise IconError("UnityPy is not installed. Start the helper with 'Start Helper.bat' "
                        "or run: python -m pip install -r requirements.txt") from exc

    data_dir = _data_dir(game_dir)
    progress("Reading game files for item pictures (first run only, may take a minute)...")
    try:
        env = UnityPy.load(str(data_dir))
    except Exception as exc:  # UnityPy raises many types for unreadable files
        raise IconError(f"Could not read the game files in {data_dir}: {exc!r}") from exc

    lookup = build_lookup(db, aliases)
    sprites, text_assets = [], []
    for obj in env.objects:
        if obj.type.name == "Sprite":
            sprites.append(obj)
        elif obj.type.name == "TextAsset":
            text_assets.append(obj)

    frames: dict[str, str] = {}
    for obj in text_assets:
        try:
            asset = obj.read()
            script = asset.m_Script
            text = script if isinstance(script, str) else bytes(script).decode("utf-8", "replace")
        except Exception:
            continue
        if '"frameName"' in text or '"frame"' in text:
            for item_id, frame in frame_names_from_json(text, lookup).items():
                frames.setdefault(item_id, frame)
    frame_lookup = {canon(Path(f).stem): item_id for item_id, f in frames.items()}

    report = ExtractReport(sprite_count=len(sprites))
    by_frame: dict[str, object] = {}
    by_name: dict[str, object] = {}
    for obj in sprites:
        try:
            name = obj.peek_name() or ""
        except Exception:
            continue
        c = canon(name)
        if c in frame_lookup:
            by_frame.setdefault(frame_lookup[c], (name, obj))
        item_id = match_sprite(name, lookup)
        if item_id:
            by_name.setdefault(item_id, (name, obj))

    out_dir.mkdir(parents=True, exist_ok=True)
    for item_id in db.items:
        entry = by_frame.get(item_id) or by_name.get(item_id)
        if not entry:
            report.missing.append(item_id)
            continue
        name, obj = entry
        try:
            _fit(obj.read().image).save(out_dir / f"{item_id}.png")
            report.found[item_id] = name
        except Exception:
            report.missing.append(item_id)

    (out_dir / MANIFEST).write_text(json.dumps({
        "game_dir": str(game_dir),
        "build": _build_marker(game_dir),
        "sprite_count": report.sprite_count,
        "found": report.found,
        "missing": report.missing,
    }, indent=1), encoding="utf-8")
    return report


def read_manifest(out_dir: Path | None = None) -> dict | None:
    out_dir = out_dir or CACHE_DIR
    try:
        return json.loads((out_dir / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def needs_extraction(game_dir: Path | None, out_dir: Path | None = None) -> bool:
    manifest = read_manifest(out_dir)
    if manifest is None:
        return True
    return game_dir is not None and manifest.get("build") != _build_marker(game_dir)


def icon_paths(ids: Iterable[str], out_dir: Path | None = None) -> dict[str, Path]:
    out_dir = out_dir or CACHE_DIR
    return {i: out_dir / f"{i}.png" for i in ids if (out_dir / f"{i}.png").exists()}
