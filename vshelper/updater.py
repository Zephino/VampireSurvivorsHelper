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

from .paths import FROZEN, RESOURCE_ROOT

PROJECT_ROOT = RESOURCE_ROOT
BRANCH = "main"
REPO_URL = "https://github.com/Zephino/VampireSurvivorsHelper"
DOWNLOAD_URL = REPO_URL + "/releases/latest"
RAW_VERSION_URL = "https://raw.githubusercontent.com/Zephino/VampireSurvivorsHelper/main/VERSION"
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


def check_online(current: str, url: str = RAW_VERSION_URL) -> UpdateInfo:
    """For the standalone exe: read the latest version number from GitHub."""
    req = urllib.request.Request(url, headers={"User-Agent": "VampireSurvivorsHelper"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            latest = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Couldn't check for updates (GitHub said {exc.code}). If the project is private, "
                          "ask whoever gave you the app for the newest version.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({exc}).") from exc
    if not version_key(latest):
        raise UpdateError(f"GitHub returned an unexpected version: {latest[:40]!r}")
    # Any different version counts as an update: the numbering was reset once (to 00.00.34),
    # so a newer release can have a lower number than an older exe.
    different = version_key(latest) != version_key(current)
    changes = [f"Download version {latest} from the GitHub page"] if different else []
    return UpdateInfo(current, latest, 1 if different else 0, changes)


def check(root: Path = PROJECT_ROOT) -> UpdateInfo:
    """Report whether a newer version exists (changes nothing locally)."""
    if FROZEN:
        return check_online(local_version(root))
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
    if FROZEN:
        raise UpdateError(f"The standalone app can't replace itself. Download the new version from {DOWNLOAD_URL}")
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
