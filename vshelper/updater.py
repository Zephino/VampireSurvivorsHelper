"""Checks for and installs updates from GitHub.

From source (installed with git clone): updates with git. As the standalone .exe: compares the
version with GitHub and points to the download page (an exe can't replace itself while running).
All functions raise UpdateError with a message that can be shown to the user.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .paths import FOLDER_BUILD, FROZEN, RESOURCE_ROOT

PROJECT_ROOT = RESOURCE_ROOT
BRANCH = "main"
REPO_URL = "https://github.com/Zephino/VampireSurvivorsHelper"
DOWNLOAD_URL = REPO_URL + "/releases/latest"
GIT_TIMEOUT = 90
CREATE_NO_WINDOW = 0x08000000  # don't flash a console window on Windows


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    current: str
    latest: str | None
    behind: int                                     # commits on GitHub that this copy doesn't have
    changes: list[str] = field(default_factory=list)  # their titles, newest first
    download_url: str = ""                          # the exe in the GitHub release (standalone exe only)

    @property
    def available(self) -> bool:
        return self.behind > 0


def local_version(root: Path = PROJECT_ROOT) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip() or "?"
    except OSError:
        return "?"


def _run(args: list[str], root: Path, timeout: int = GIT_TIMEOUT) -> str:
    kwargs = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        done = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout, **kwargs)
    except FileNotFoundError as exc:
        raise UpdateError(f"'{args[0]}' was not found. Install Git for Windows (git-scm.com) to update "
                          f"from here, or download the latest version from {REPO_URL}") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"'{' '.join(args[:2])}' took too long. Check your internet connection.") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise UpdateError(f"'{' '.join(args[:2])}' failed: {detail[-1] if detail else 'unknown error'}")
    return done.stdout.strip()


def _git(*args: str, root: Path = PROJECT_ROOT) -> str:
    return _run(["git", *args], root)


def is_git_checkout(root: Path = PROJECT_ROOT) -> bool:
    return (root / ".git").exists()


def _require_git_checkout(root: Path) -> None:
    if not is_git_checkout(root):
        raise UpdateError("This copy wasn't downloaded with git, so it can't update itself. "
                          f"Download the latest version from {REPO_URL} (Code > Download ZIP).")


def version_key(version: str) -> tuple[int, ...]:
    """'00.13.01' -> (0, 13, 1) so versions compare correctly."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


RELEASES_API = "https://api.github.com/repos/Zephino/VampireSurvivorsHelper/releases/latest"
EXE_NAME = "VampireSurvivorsHelper.exe"
MAX_EXE_BYTES = 300 * 1024 * 1024


def _get_json(url: str) -> dict:
    import json
    req = urllib.request.Request(url, headers={"User-Agent": "VampireSurvivorsHelper",
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Couldn't check for updates (GitHub said {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({exc}).") from exc


def check_release(current: str, fetch=_get_json, url: str = RELEASES_API) -> UpdateInfo:
    """For the standalone exe: the newest GitHub release that has an exe attached."""
    release = fetch(url)
    latest = str(release.get("tag_name", "")).lstrip("vV")
    asset = next((a for a in release.get("assets", []) if a.get("name") == EXE_NAME), None)
    if not version_key(latest) or asset is None:
        raise UpdateError("The latest GitHub release has no exe to download yet.")
    different = version_key(latest) != version_key(current)  # numbering was reset once: any change
    notes = [line[2:].strip() for line in str(release.get("body", "")).splitlines() if line.startswith("- ")]
    return UpdateInfo(current, latest, 1 if different else 0, notes[:8] if different else [],
                      asset.get("browser_download_url", ""))


def _download_file(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "VampireSurvivorsHelper"})
    size = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as out:
            while chunk := resp.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_EXE_BYTES:
                    raise UpdateError("The download is unexpectedly large; update cancelled.")
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Downloading the update failed ({exc}).") from exc


def apply_release(info: UpdateInfo, exe: Path, download=_download_file) -> str:
    """Replace the running exe with the release's exe.

    Windows won't overwrite a running program but does allow renaming it, so: download to
    '<name>.new', rename the running exe to '<name>.old.exe', move the new one into place. The
    old file is deleted the next time the helper starts (cleanup_old_exe).
    """
    if not info.available or not info.download_url:
        return f"Already up to date ({info.current})."
    new = exe.with_name(exe.stem + ".new")
    old = exe.with_name(exe.stem + ".old.exe")
    try:
        download(info.download_url, new)
        with open(new, "rb") as f:
            if f.read(2) != b"MZ" or new.stat().st_size < 1024 * 1024:
                raise UpdateError("The downloaded file isn't a valid program; update cancelled.")
        if old.exists():
            old.unlink()
        exe.rename(old)
    except OSError as exc:
        new.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't install the update in {exe.parent} ({exc}). If the helper is in a "
                          f"protected folder, move it (e.g. to Documents) or download it from {DOWNLOAD_URL}") from exc
    except UpdateError:
        new.unlink(missing_ok=True)
        raise
    try:
        new.rename(exe)
    except OSError as exc:
        old.rename(exe)  # put the old version back so the helper still starts
        new.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't put the new version in place ({exc}).") from exc
    return f"Updated to {info.latest}. Restart the helper to use it."


def cleanup_old_exe(exe: Path | None = None) -> None:
    """Delete the previous exe left behind by an update (it can't delete itself while running)."""
    exe = exe or Path(sys.executable)
    for leftover in (exe.with_name(exe.stem + ".old.exe"), exe.with_name(exe.stem + ".new")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass  # still running (just restarted): try again next start


def check(root: Path = PROJECT_ROOT) -> UpdateInfo:
    """Report whether a newer version exists (changes nothing locally)."""
    if FROZEN:
        return check_release(local_version(root))
    _require_git_checkout(root)
    _git("fetch", "--quiet", "origin", BRANCH, root=root)
    remote = f"origin/{BRANCH}"
    behind = int(_git("rev-list", "--count", f"HEAD..{remote}", root=root) or 0)
    try:
        latest = _git("show", f"{remote}:VERSION", root=root).strip()
    except UpdateError:
        latest = None
    changes = _git("log", "--format=%s", f"HEAD..{remote}", root=root).splitlines() if behind else []
    return UpdateInfo(local_version(root), latest, behind, changes)


def apply(root: Path = PROJECT_ROOT) -> str:
    """Download and install the latest version. Returns a short summary."""
    if FOLDER_BUILD:
        raise UpdateError(f"This is the folder version: download the new VampireSurvivorsHelper-folder.zip from "
                          f"{DOWNLOAD_URL} and replace the folder with it.")
    if FROZEN:
        return apply_release(check(root), Path(sys.executable))
    _require_git_checkout(root)
    before = _git("rev-parse", "HEAD", root=root)
    try:
        _git("pull", "--ff-only", "origin", BRANCH, root=root)
    except UpdateError as exc:
        raise UpdateError(f"{exc}. If you changed any of the helper's files yourself, undo those "
                          "changes (or download a fresh copy) and try again.") from exc
    after = _git("rev-parse", "HEAD", root=root)
    if before == after:
        return f"Already up to date ({local_version(root)})."
    changed = _git("diff", "--name-only", before, after, root=root).splitlines()
    summary = f"Updated to {local_version(root)}."
    if "requirements.txt" in changed:
        _run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "-r", "requirements.txt"], root,
             timeout=600)
        summary += " New packages were installed."
    return summary + " Restart the helper to use it."


def restart_command(root: Path = PROJECT_ROOT) -> tuple[list[str], Path]:
    """Command (and folder) that starts a new copy of the helper."""
    if FROZEN:
        return [sys.executable], Path(sys.executable).parent
    return [sys.executable, "-m", "vshelper"], root
