"""Checks for and installs updates from GitHub using git (the helper is installed with git clone).

All functions raise UpdateError with a message that can be shown to the user.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRANCH = "main"
REPO_URL = "https://github.com/Zephino/VampireSurvivorsHelper"
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


def check(root: Path = PROJECT_ROOT) -> UpdateInfo:
    """Fetch from GitHub and report whether a newer version exists (changes nothing locally)."""
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
    """Command (and folder) that starts a new copy of the helper with the same Python."""
    return [sys.executable, "-m", "vshelper"], root
