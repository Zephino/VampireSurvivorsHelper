import json
import tempfile
import unittest
from pathlib import Path

from vshelper.data import DatabaseError, load_database, parse_database
from vshelper.evolutions import format_suggestions, suggest
from vshelper.memory.game import GameReader, ItemMatcher, load_game_map
from vshelper.memory.il2cpp import Il2Cpp, normalize_name
from vshelper.memory.winapi import ProcessNotFound

from tests.fake_il2cpp import FakeGame


class DatabaseTests(unittest.TestCase):
    def test_bundled_database_is_valid(self):
        db = load_database()
        self.assertGreater(len(db.evolutions), 20)
        self.assertIn("whip", db.items)

    def test_unknown_reference_is_reported(self):
        raw = {"weapons": [{"id": "a", "name": "A"}], "evolutions": [{"result": "b", "requires": ["a"]}]}
        with self.assertRaises(DatabaseError) as ctx:
            parse_database(raw)
        self.assertIn("unknown item 'b'", str(ctx.exception))

    def test_missing_file_is_reported(self):
        with self.assertRaises(DatabaseError):
            load_database("does-not-exist.json")


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.db = load_database()

    def test_ready_and_one_away(self):
        s = suggest(self.db, {"whip", "hollow_heart", "magic_wand"})
        self.assertEqual([x.evolution.result for x in s.ready], ["bloody_tear"])
        self.assertIn("holy_wand", [x.evolution.result for x in s.one_away])

    def test_owned_result_is_skipped(self):
        s = suggest(self.db, {"whip", "hollow_heart", "bloody_tear"})
        self.assertNotIn("bloody_tear", [x.evolution.result for x in s.ready])
        self.assertIn("fuwalafuwaloo", [x.evolution.result for x in s.one_away])

    def test_format_mentions_missing_item(self):
        text = format_suggestions(self.db, suggest(self.db, {"knife"}))
        self.assertIn("Thousand Edge", text)
        self.assertIn("need: Bracer", text)

    def test_empty(self):
        self.assertIn("Select", format_suggestions(self.db, suggest(self.db, set())))


class MatcherTests(unittest.TestCase):
    def test_aliases_ids_and_names(self):
        gmap = load_game_map()
        m = ItemMatcher(load_database(), gmap.enum_aliases, {"#7": "garlic"})
        self.assertEqual(m.match("MAGIC_MISSILE"), "magic_wand")
        self.assertEqual(m.match("Magic Wand"), "magic_wand")
        self.assertEqual(m.match("king_bible"), "king_bible")
        self.assertEqual(m.match("#7"), "garlic")
        self.assertIsNone(m.match("NOT_A_THING"))

    def test_normalize_name(self):
        self.assertEqual(normalize_name("<Player>k__BackingField"), "player")
        self.assertEqual(normalize_name("_weaponsManager"), "weaponsmanager")


class Il2CppTests(unittest.TestCase):
    def test_find_class_and_fields(self):
        g = FakeGame()
        il2 = Il2Cpp(g.m)
        klass = il2.find_class("GameManager")
        self.assertEqual(klass, g.gm_obj_cls)
        self.assertEqual(il2.find_field(klass, "player").name, "_player")
        self.assertEqual(il2.read_static_ptr(il2.find_class("GM"), "Core"), g.gm)
        self.assertEqual(il2.enum_names(g.enum_cls), g.enum_names)

    def test_list_elements(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [0, 1])
        self.assertEqual(len(Il2Cpp(g.m).collection_elements(g.weapon_list)), 2)


def _reader(game: FakeGame, **map_overrides):
    gmap = load_game_map()
    for k, v in map_overrides.items():
        setattr(gmap, k, v)
    return GameReader(load_database(), gmap, open_memory=lambda _name: game.m)


class GameReaderTests(unittest.TestCase):
    def test_reads_inventory_through_configured_path(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [0, 1])   # WHIP, MAGIC_MISSILE
        g.set_list(g.passive_list, [3])     # MAXHEALTH -> Hollow Heart
        result = _reader(g).poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"whip", "magic_wand", "hollow_heart"})

    def test_discovers_lists_when_names_differ(self):
        g = FakeGame(root_name="GameManager2", root_field="Instance", player_field="somethingElse",
                     weapons_field="renamedList")
        g.set_list(g.weapon_list, [0])
        g.set_list(g.passive_list, [2])
        reader = _reader(g, roots=[{"class": "GameManager2", "static_field": ["Instance"]}])
        result = reader.poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"whip", "spinach"})

    def test_updates_when_inventory_changes(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [0])
        reader = _reader(g)
        self.assertEqual(reader.poll().owned, {"whip"})
        g.set_list(g.weapon_list, [0, 1])
        self.assertEqual(reader.poll().owned, {"whip", "magic_wand"})

    def test_waiting_when_no_run(self):
        g = FakeGame()
        g.m.w64(g.gm + 0x10, 0)  # no player
        self.assertEqual(_reader(g).poll().state, "waiting")

    def test_unrecognized_item_reported(self):
        g = FakeGame(enum_names=("WHIP", "MYSTERY"))
        g.set_list(g.weapon_list, [0, 1])
        result = _reader(g).poll()
        self.assertEqual(result.owned, {"whip"})
        self.assertEqual(result.unrecognized, ("MYSTERY",))

    def test_game_not_running(self):
        def missing(_name):
            raise ProcessNotFound("VampireSurvivors.exe is not running.")
        reader = GameReader(load_database(), load_game_map(), open_memory=missing)
        self.assertEqual(reader.poll().state, "not_running")

    def test_main_class_missing_is_an_error(self):
        g = FakeGame(root_name="Other")
        result = _reader(g, roots=[{"class": "Nope", "static_field": ["X"]}]).poll()
        self.assertEqual(result.state, "error")
        self.assertIn("diagnose", result.message)


class GameMapTests(unittest.TestCase):
    def test_invalid_map_is_reported(self):
        from vshelper.memory.game import GameMapError
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.json"
            p.write_text(json.dumps({"process_name": "x"}))
            with self.assertRaises(GameMapError):
                load_game_map(p)


if __name__ == "__main__":
    unittest.main()
