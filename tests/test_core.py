import struct
import json
import tempfile
import unittest
from pathlib import Path

from vshelper.data import DatabaseError, load_database, parse_database
from vshelper.evolutions import suggest
from vshelper.memory.game import GameReader, ItemMatcher, load_game_map
from vshelper.memory.il2cpp import Il2Cpp, normalize_name
from vshelper.memory.winapi import ProcessNotFound

from tests.fake_il2cpp import HEAP, FakeGame


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

    def test_plans_start_from_held_items_weapons_first(self):
        from vshelper.evolutions import plans_for_held
        plans = plans_for_held(self.db, {"bracer", "knife", "whip", "hollow_heart"})
        self.assertEqual([p.item for p in plans][:2], ["knife", "whip"])  # weapons before passives
        knife = plans[0]
        self.assertEqual(knife.options[0].evolution.result, "thousand_edge")
        self.assertEqual(knife.options[0].missing, ())

    def test_plan_text(self):
        from vshelper.evolutions import format_plan
        text = format_plan(self.db, {"knife"})
        self.assertIn("YOU'RE HOLDING: Knife", text)
        self.assertIn("Thousand Edge: needs Bracer (need)", text)
        self.assertEqual(format_plan(self.db, set()), "No items held.")


class MatcherTests(unittest.TestCase):
    def test_aliases_ids_and_names(self):
        gmap = load_game_map()
        m = ItemMatcher(load_database(), gmap.enum_aliases, {"#7": "garlic"})
        self.assertEqual(m.match("MAGIC_MISSILE"), "magic_wand")
        self.assertEqual(m.match("Magic Wand"), "magic_wand")
        self.assertEqual(m.match("king_bible"), "king_bible")
        self.assertEqual(m.match("#7"), "garlic")
        self.assertIsNone(m.match("NOT_A_THING"))

    def test_near_identical_spelling_only_when_asked(self):
        m = ItemMatcher(load_database(), {}, {})
        self.assertIsNone(m.match("Sinistro Custos"))
        self.assertEqual(m.match("Sinistro Custos", fuzzy=True), "sinestro_custos")
        self.assertIsNone(m.match("Completely Different", fuzzy=True))
        self.assertIsNone(m.match("#1467", fuzzy=True))

    def test_normalize_name(self):
        self.assertEqual(normalize_name("<Player>k__BackingField"), "player")
        self.assertEqual(normalize_name("_weaponsManager"), "weaponsmanager")


class Il2CppTests(unittest.TestCase):
    def test_find_class_and_fields(self):
        g = FakeGame()
        il2 = Il2Cpp(g.m)
        klass = il2.find_class("GameManager")
        self.assertEqual(klass, g.gm_obj_cls)
        self.assertEqual(il2.find_field(klass, "MainCharacters").name, "_mainCharacters")
        self.assertEqual(il2.find_class("GM", "VampireSurvivors.Framework"), g.root_cls)
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
        g.set_list(g.weapon_list, [1, 2])   # WHIP, MAGIC_MISSILE
        g.set_list(g.passive_list, [4])     # MAXHEALTH -> Hollow Heart
        result = _reader(g).poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"whip", "magic_wand", "hollow_heart"})

    def test_discovers_lists_when_names_differ(self):
        g = FakeGame(root_name="GameManager2", root_field="Instance", player_field="somethingElse",
                     weapons_field="renamedList")
        g.set_list(g.weapon_list, [1])
        g.set_list(g.passive_list, [3])
        reader = _reader(g, roots=[{"class": "GameManager2", "static_field": ["Instance"]}])
        result = reader.poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"whip", "spinach"})

    def test_reads_names_and_levels_like_the_real_game(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Wine Glass", 5, 8), ("Whip", 8, 8)])
        g.set_named(g.passive_list, [("Hollow Heart", 2, 5)])
        result = _reader(g).poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"wine_glass", "whip", "hollow_heart"})
        self.assertEqual(result.level_of("wine_glass"), (5, 8))
        self.assertEqual(result.level_of("whip"), (8, 8))

    def test_coop_players_are_read(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Whip", 8, 8)])
        weapons, passives = g.add_player("TP_Rinaldo_Character")
        g.set_named(weapons, [("Knife", 3, 8), ("Prototype A", 1, 8)])
        g.set_named(passives, [("Bracer", 2, 5)])
        result = _reader(g).poll()
        self.assertEqual(result.owned, {"whip"})  # player 1 as before
        self.assertEqual([p.index for p in result.players], [0, 1])
        friend = result.players[1]
        self.assertEqual(friend.owned, {"knife", "prototype_a", "bracer"})
        self.assertEqual(friend.level_of("knife"), (3, 8))
        self.assertEqual(friend.label, "Player 2 (Rinaldo)")
        self.assertIn("2 players", result.message)

    def test_solo_game_has_one_player(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Whip", 8, 8)])
        self.assertEqual(len(_reader(g).poll().players), 1)

    def test_game_spelling_differs_from_the_wiki(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Dextro Custos", 6, 6), ("Sinistro Custos", 6, 6)], enum_value=1438)
        result = _reader(g).poll()
        self.assertEqual(result.owned, {"dextro_custos", "sinestro_custos"})
        self.assertEqual(result.unrecognized, ())

    def test_held_items_give_their_picture_names(self):
        g = FakeGame()
        e_arr = struct.unpack_from("<Q", g.m.heap, g.weapon_list + 0x10 - HEAP)[0]
        g.set_named(g.weapon_list, [("Sinistro Custos", 6, 6)])
        el = struct.unpack_from("<Q", g.m.heap, e_arr + 0x20 - HEAP)[0]
        data = g.make_data("Sinistro Custos", "-05-TP_CUSTOS2.png", "TP_CUSTOS4")
        g.m.w64(el + 0x18, data)
        seen = []
        reader = _reader(g)
        reader.on_catalog = seen.append
        reader.poll()
        reader.poll()
        held = [c for c in seen if "Sinistro Custos" in c]
        self.assertEqual(len(held), 1)  # sent once, not every poll
        self.assertEqual(held[0]["Sinistro Custos"]["frame"], "-05-TP_CUSTOS2.png")

    def test_reads_the_item_catalogue_once(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Keremet Bubbles", 2, 8)])
        g.set_catalog([(1433, "Keremet Bubbles", "-05-TP_ACID1.png", "TP_ACID2"),
                       (1434, "Keremet Morbus", "-05-TP_ACID2.png", "")])
        seen = []
        reader = _reader(g)
        reader.on_catalog = seen.append
        self.assertEqual(reader.poll().owned, {"keremet_bubbles"})
        reader.poll()
        self.assertEqual(len(seen), 1)  # only once per game session
        self.assertEqual(seen[0]["Keremet Bubbles"], {"frame": "-05-TP_ACID1.png", "evo_into": "TP_ACID2"})
        self.assertIn("Keremet Morbus", seen[0])

    def test_discovery_steps_into_the_players_list(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [1])
        gmap_paths = {"weapons": [["Nope"]], "passives": [["Nope"]]}
        result = _reader(g, inventories=gmap_paths).poll()
        self.assertEqual(result.state, "ok", result.message)
        self.assertEqual(result.owned, {"whip"})

    def test_updates_when_inventory_changes(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [1])
        reader = _reader(g)
        self.assertEqual(reader.poll().owned, {"whip"})
        g.set_list(g.weapon_list, [1, 2])
        self.assertEqual(reader.poll().owned, {"whip", "magic_wand"})

    def test_waiting_when_no_run(self):
        g = FakeGame()
        g.set_objects(g.players, [])  # no player yet
        self.assertEqual(_reader(g).poll().state, "waiting")

    def test_unreadable_item_is_mentioned(self):
        g = FakeGame()
        g.set_named(g.weapon_list, [("Whip", 1, 8)])
        e = g.obj(g.equip_cls, 0x28)  # an equipment object with no name and no type
        g.m.w32(e + 0x10, -5)
        arr = struct.unpack_from("<Q", g.m.heap, g.weapon_list + 0x10 - HEAP)[0]
        g.m.w64(arr + 0x20 + 8, e)
        g.m.w32(g.weapon_list + 0x18, 2)
        result = _reader(g, type_field=["nothing_here"]).poll()
        self.assertEqual(result.owned, {"whip"})
        self.assertIn("1 item(s) couldn't be identified", result.message)

    def test_unrecognized_item_reported(self):
        g = FakeGame(enum_names=("VOID", "WHIP", "MYSTERY"))
        g.set_list(g.weapon_list, [1, 2])
        result = _reader(g).poll()
        self.assertEqual(result.owned, {"whip"})
        self.assertEqual(result.unrecognized, ("#2",))  # raw number: enum order isn't trusted

    def test_list_bigger_than_an_inventory_is_ignored(self):
        g = FakeGame()
        g.set_list(g.weapon_list, [1] * 13)  # 13 whips: a pool or ground items, not what you hold
        result = _reader(g, inventories={"weapons": [["Nope"]]}).poll()  # found by the automatic search
        self.assertEqual(result.owned, frozenset())

    def test_configured_path_is_trusted_at_any_size(self):
        g = FakeGame()
        g.set_named(g.passive_list, [("Spinach", 5, 5)] * 17)
        result = _reader(g).poll()
        self.assertIn("spinach", result.owned)

    def test_inventory_scoring(self):
        from vshelper.memory.game import score_inventory_path
        held = score_inventory_path(("_player", "_weaponsManager", "_activeEquipment"), 3, 3)
        ground = score_inventory_path(("_pickupManager", "_activePickups"), 3, 3)
        self.assertGreater(held, ground)
        self.assertLessEqual(ground, 0)
        self.assertEqual(score_inventory_path(("_player", "_weapons"), 30, 30), 0)

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


class DiagnoseTests(unittest.TestCase):
    def test_report_runs_end_to_end(self):
        from vshelper import diagnose
        g = FakeGame()
        g.set_list(g.weapon_list, [1, 2])
        g.set_list(g.passive_list, [4])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.txt"
            self.assertEqual(diagnose.run(out, open_memory=lambda _name: g.m), 0)
            text = out.read_text(encoding="utf-8")
        self.assertIn("state: ok", text)
        self.assertIn("All lists with recognisable items", text)
        self.assertIn("Class layouts", text)
        self.assertNotIn("this section failed", text)
        self.assertIn("YOU'RE HOLDING", text)


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
