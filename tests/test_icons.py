import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from vshelper import icons
from vshelper.data import load_database
from vshelper.memory.game import load_game_map

try:
    from PIL import Image
except ImportError:  # Pillow arrives with UnityPy; extraction tests need it
    Image = None


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.lookup = icons.build_lookup(load_database(), load_game_map().enum_aliases)

    def test_matches_names_ids_affixes_and_internal_names(self):
        self.assertEqual(icons.match_sprite("Whip", self.lookup), "whip")
        self.assertEqual(icons.match_sprite("HollowHeart_Icon", self.lookup), "hollow_heart")
        self.assertEqual(icons.match_sprite("MAGIC_MISSILE", self.lookup), "magic_wand")
        self.assertIsNone(icons.match_sprite("Background", self.lookup))

    def test_frame_names_from_game_json(self):
        text = json.dumps({"WHIP": [{"name": "Whip", "frameName": "WhipIcon.png"}],
                           "OTHER": [{"name": "Nothing", "frameName": "x.png"}]})
        self.assertEqual(icons.frame_names_from_json(text, self.lookup), {"whip": "WhipIcon.png"})
        self.assertEqual(icons.frame_names_from_json("not json", self.lookup), {})

    def test_steam_library_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "steamapps").mkdir()
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders" { "0" { "path" "C:\\\\Steam" } "1" { "path" "F:\\\\SteamLibrary" } }')
            libs = icons.steam_libraries(root)
            self.assertIn(Path("F:\\SteamLibrary"), libs)


class _FakeObj:
    def __init__(self, type_name, name, payload):
        self.type = types.SimpleNamespace(name=type_name)
        self._name = name
        self._payload = payload

    def peek_name(self):
        return self._name

    def read(self):
        if self.type.name == "Sprite":
            return types.SimpleNamespace(image=self._payload)
        return types.SimpleNamespace(m_Script=self._payload)


@unittest.skipIf(Image is None, "Pillow not installed")
class ExtractTests(unittest.TestCase):
    def test_extracts_matching_sprites(self):
        red = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        objs = [
            _FakeObj("Sprite", "Whip", red),
            _FakeObj("Sprite", "SomeFrame", red),
            _FakeObj("Sprite", "Background", red),
            _FakeObj("TextAsset", "weaponData", json.dumps({"GARLIC": [{"name": "Garlic", "frameName": "SomeFrame.png"}]})),
        ]
        fake = types.ModuleType("UnityPy")
        fake.load = lambda _path: types.SimpleNamespace(objects=objs)
        sys.modules["UnityPy"] = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                game = Path(d) / "game"
                (game / "VampireSurvivors_Data").mkdir(parents=True)
                out = Path(d) / "icons"
                report = icons.extract_icons(game, load_database(), {}, out_dir=out)
                self.assertEqual(report.found, {"whip": "Whip", "garlic": "SomeFrame"})
                with Image.open(out / "whip.png") as img:
                    self.assertEqual(img.size, (icons.ICON_SIZE, icons.ICON_SIZE))
                self.assertFalse(icons.needs_extraction(game, out))
                self.assertIn("knife", icons.read_manifest(out)["missing"])
        finally:
            del sys.modules["UnityPy"]

    def test_missing_unity_data_folder(self):
        sys.modules["UnityPy"] = types.ModuleType("UnityPy")
        try:
            with tempfile.TemporaryDirectory() as d, self.assertRaises(icons.IconError):
                icons.extract_icons(Path(d), load_database(), {}, out_dir=Path(d) / "o")
        finally:
            del sys.modules["UnityPy"]


if __name__ == "__main__":
    unittest.main()
