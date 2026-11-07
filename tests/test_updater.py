import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vshelper import updater


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class UpdaterTests(unittest.TestCase):
    """Uses a local 'GitHub' (a bare repository) and a clone of it, like the user's install."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        self.author = self.tmp / "author"
        git(self.tmp, "clone", "--quiet", str(self.remote), str(self.author))
        for repo in (self.author,):
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "Test")
        self.commit("00.01.00", "First version")
        self.user = self.tmp / "user"
        git(self.tmp, "clone", "--quiet", str(self.remote), str(self.user))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, version: str, message: str, extra: dict | None = None) -> None:
        (self.author / "VERSION").write_text(version + "\n")
        for name, text in (extra or {}).items():
            (self.author / name).write_text(text)
        git(self.author, "add", "-A")
        git(self.author, "commit", "--quiet", "-m", message)
        git(self.author, "push", "--quiet", "origin", "HEAD:main")

    def test_up_to_date(self):
        info = updater.check(self.user)
        self.assertFalse(info.available)
        self.assertEqual((info.current, info.latest), ("00.01.00", "00.01.00"))

    def test_finds_and_applies_update(self):
        self.commit("00.02.00", "Add dark theme")
        self.commit("00.03.00", "Add cards")
        info = updater.check(self.user)
        self.assertTrue(info.available)
        self.assertEqual(info.behind, 2)
        self.assertEqual(info.latest, "00.03.00")
        self.assertEqual(info.changes, ["Add cards", "Add dark theme"])
        self.assertEqual(updater.local_version(self.user), "00.01.00")  # checking changes nothing
        summary = updater.apply(self.user)
        self.assertIn("Updated to 00.03.00", summary)
        self.assertEqual(updater.local_version(self.user), "00.03.00")
        self.assertIn("Already up to date", updater.apply(self.user))

    def test_local_edits_give_a_clear_error(self):
        self.commit("00.02.00", "Change")
        (self.user / "VERSION").write_text("edited by hand\n")
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply(self.user)
        self.assertIn("changed any of the helper's files", str(ctx.exception))

    def test_not_a_git_copy(self):
        plain = self.tmp / "zip-download"
        plain.mkdir()
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.check(plain)
        self.assertIn("Download ZIP", str(ctx.exception))


class ExeUpdateTests(unittest.TestCase):
    """The standalone exe updates itself from the latest GitHub release."""

    RELEASE = {"tag_name": "v00.00.35", "body": "## Version 00.00.35\n### Changes\n- Self-updating exe\n- More",
               "assets": [{"name": "VampireSurvivorsHelper.exe", "browser_download_url": "https://x/new.exe"}]}

    def test_check_release(self):
        info = updater.check_release("00.00.34", fetch=lambda url: self.RELEASE)
        self.assertTrue(info.available)
        self.assertEqual((info.latest, info.download_url), ("00.00.35", "https://x/new.exe"))
        self.assertEqual(info.changes, ["Self-updating exe", "More"])
        self.assertFalse(updater.check_release("00.00.35", fetch=lambda url: self.RELEASE).available)
        self.assertTrue(updater.check_release("00.20.01", fetch=lambda url: self.RELEASE).available)  # renumbered

    def test_release_without_exe(self):
        with self.assertRaises(updater.UpdateError):
            updater.check_release("00.00.34", fetch=lambda url: {"tag_name": "v00.00.35", "assets": []})

    def _install(self, payload: bytes):
        d = Path(tempfile.mkdtemp())
        exe = d / "VampireSurvivorsHelper.exe"
        exe.write_bytes(b"MZ old version" + b"\0" * 2_000_000)
        info = updater.check_release("00.00.34", fetch=lambda url: self.RELEASE)

        def download(url, target):
            target.write_bytes(payload)
        return d, exe, info, download

    def test_swaps_in_the_new_exe_and_cleans_up_later(self):
        d, exe, info, download = self._install(b"MZ new version" + b"\0" * 2_000_000)
        self.assertIn("Updated to 00.00.35", updater.apply_release(info, exe, download=download))
        self.assertTrue(exe.read_bytes().startswith(b"MZ new"))
        old = d / "VampireSurvivorsHelper.old.exe"
        self.assertTrue(old.exists())                 # the running exe was renamed, not overwritten
        updater.cleanup_old_exe(exe)                  # next start
        self.assertFalse(old.exists())
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["VampireSurvivorsHelper.exe"])

    def test_bad_download_leaves_the_old_exe(self):
        d, exe, info, download = self._install(b"<html>not a program</html>")
        with self.assertRaises(updater.UpdateError):
            updater.apply_release(info, exe, download=download)
        self.assertTrue(exe.read_bytes().startswith(b"MZ old"))
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["VampireSurvivorsHelper.exe"])


if __name__ == "__main__":
    unittest.main()
