import sys
import unittest
from unittest import mock

from vshelper import game_launcher


class GameLauncherTests(unittest.TestCase):
    def test_not_running(self):
        self.assertFalse(game_launcher.is_running("DefinitelyNotRunning12345.exe"))

    def test_launch_uses_steam_link(self):
        if sys.platform == "win32":
            with mock.patch("os.startfile", create=True) as start:
                self.assertIsNone(game_launcher.launch())
            start.assert_called_once_with("steam://rungameid/1794680")
        else:
            with mock.patch("webbrowser.open", return_value=True) as open_:
                self.assertIsNone(game_launcher.launch())
            open_.assert_called_once_with("steam://rungameid/1794680")

    def test_launch_failure_is_explained(self):
        target = "os.startfile" if sys.platform == "win32" else "webbrowser.open"
        with mock.patch(target, side_effect=OSError("no handler"), create=True):
            self.assertIn("Is Steam installed", game_launcher.launch())


if __name__ == "__main__":
    unittest.main()
