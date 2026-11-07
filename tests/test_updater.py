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


class OnlineCheckTests(unittest.TestCase):
    """The exe's check reads a VERSION file over HTTP; a file:// URL stands in for GitHub."""

    def check(self, remote_version: str, current: str) -> updater.UpdateInfo:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "VERSION"
            f.write_text(remote_version + "\n")
            return updater.check_online(current, f.as_uri())

    def test_newer_and_same(self):
        self.assertTrue(self.check("00.14.00", "00.13.01").available)
        self.assertFalse(self.check("00.13.01", "00.13.01").available)
        self.assertTrue(self.check("00.00.34", "00.20.01").available)  # renumbered release is still offered
        self.assertFalse(self.check("00.13.1", "00.13.01").available)   # compares numbers, not text

    def test_bad_response(self):
        with self.assertRaises(updater.UpdateError):
            self.check("<html>not found</html>", "00.13.01")

    def test_unreachable(self):
        with self.assertRaises(updater.UpdateError):
            updater.check_online("00.13.01", "file:///does/not/exist/VERSION")


if __name__ == "__main__":
    unittest.main()
