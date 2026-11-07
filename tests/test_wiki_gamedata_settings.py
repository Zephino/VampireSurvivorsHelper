import json
import tempfile
import unittest
from pathlib import Path

from vshelper import gamedata, settings
from vshelper.data import load_database, parse_database
from vshelper.evolutions import suggest
from vshelper.memory.game import load_game_map
from vshelper.wiki import build_database, parse_evolution_page, slug

PAGE = """
==Mechanics==
ignored
==List of Evolutions, Unions, Gifts and Morphs==
===Base game===
====Evolutions====
{| class="wikitable"
! style="text-align:center" |Base weapon
!
! style="text-align:center" |Passive item
!
! style="text-align:center" |Evolution
|-
|{{Sprite|Whip|small|1|1}}
|'''+'''
|{{Sprite|Hollow Heart|small|1|1}}
|'''='''
|{{Sprite|Bloody Tear|small|1|1}}
|-
|{{Sprite|Clock Lancet|small|1|1}}
|'''+'''
|Max level:<br />{{Sprite|Silver Ring|small|1|1}}<br />{{Sprite|Gold Ring|small|1|1}}
|'''='''
|{{Sprite|Infinite Corridor|small|1|1}}
|}
====Unions====
{| class="wikitable"
!Base Weapons
!
!Union
|-
|{{Sprite|Peachone|small|1|1}}<br />{{Sprite|Ebony Wings|small|1|1}}
|{{NA|colspan=2}}
|'''='''
|{{Sprite|Vandalier|small|1|1}}
|}
====Morphs====
{| class="wikitable"
|-
|{{Sprite|Bone|small|1|1}}
|'''+'''
|Reach level 80
|'''='''
|{{Sprite|Anima of Mortaccio|small|1|1}}
|}
===Emerald Diorama===
====Evolutions====
{| class="wikitable"
|-
|{{Sprite|Fleuret|small|1|1|dlc=ed}}
|{{NA|colspan=2}}
|'''+'''
|[[Crystalline Carve]]
|'''='''
|{{Sprite|Dress Sword|small|1|1|dlc=ed}}
|-
|{{Sprite|Spirit Rings|small|1|1|dlc=ed}}
|'''+'''
|5 passives
|'''='''
|{{Sprite|Rings of Calamity|small|1|1|dlc=ed}}
|}
"""


class WikiParserTests(unittest.TestCase):
    def setUp(self):
        self.recipes, self.skipped = parse_evolution_page(PAGE)

    def test_rows(self):
        by_result = {r.results[0]: r for r in self.recipes}
        self.assertEqual(set(by_result), {"Bloody Tear", "Infinite Corridor", "Vandalier", "Dress Sword"})
        self.assertEqual(by_result["Bloody Tear"].catalysts, ["Hollow Heart"])
        self.assertEqual(by_result["Infinite Corridor"].max_level, ["Silver Ring", "Gold Ring"])
        self.assertEqual(by_result["Vandalier"].kind, "union")
        self.assertEqual(by_result["Vandalier"].weapons, ["Peachone", "Ebony Wings"])
        self.assertEqual(by_result["Dress Sword"].notes, ["Also needs: Crystalline Carve"])
        self.assertEqual(by_result["Dress Sword"].dlc, "Emerald Diorama")

    def test_morphs_ignored_and_unreadable_conditions_reported(self):
        self.assertFalse(any("Anima" in r.results[0] for r in self.recipes))
        self.assertEqual(len(self.skipped), 1)
        self.assertIn("5 passives", self.skipped[0])

    def test_built_database_is_valid(self):
        raw = build_database(self.recipes, ["Whip", "Bone"], ["Armor (item)", "Gifts", "Passive items"])
        db = parse_database(raw)
        self.assertEqual(db.items["hollow_heart"].kind, "passive")
        self.assertTrue(db.items["bloody_tear"].evolved)
        self.assertIn("armor", db.items)
        self.assertNotIn("gifts", db.items)
        self.assertEqual(db.expansions(), ["Emerald Diorama"])

    def test_slug(self):
        self.assertEqual(slug("Tirajisú"), "tirajisu")
        self.assertEqual(slug("Skull O'Maniac"), "skull_omaniac")


class BundledDataTests(unittest.TestCase):
    def test_every_alias_points_at_a_real_item(self):
        db = load_database()
        bad = {k: v for k, v in load_game_map().enum_aliases.items() if v not in db.items}
        self.assertEqual(bad, {})

    def test_hidden_expansion_removes_its_recipes(self):
        db = load_database()
        owned = {"silver_wind", "pummarola"}  # Festive Winds, Legacy of the Moonspell
        self.assertIn("festive_winds", [s.evolution.result for s in suggest(db, owned).ready])
        hidden = suggest(db, owned, {"Legacy of the Moonspell"})
        self.assertNotIn("festive_winds", [s.evolution.result for s in hidden.ready])


class GameDataTests(unittest.TestCase):
    GAME_JSON = json.dumps({
        "WHIP": [{"name": "Whip", "evoInto": "VAMPIRICA", "evoSynergy": ["MAXHEALTH"]}, {"level": 2}],
        "VAMPIRICA": [{"name": "Bloody Tear"}],
        "MAXHEALTH": [{"name": "Hollow Heart"}],
        "KNIFE": [{"name": "Knife", "evoInto": "THOUSAND", "evoSynergy": ["MAXHEALTH"]}],
        "THOUSAND": [{"name": "Thousand Edge"}],
    })

    def test_parse_and_compare(self):
        db = load_database()
        data = gamedata.parse_game_json(self.GAME_JSON)
        self.assertEqual(data.recipes["WHIP"], {"into": "VAMPIRICA", "synergy": ["MAXHEALTH"]})
        checks = gamedata.compare(db, data)
        self.assertEqual(checks["bloody_tear"].status, "match")
        self.assertEqual(checks["thousand_edge"].status, "mismatch")  # wiki says Bracer
        self.assertEqual(set(checks["thousand_edge"].game_requires), {"knife", "hollow_heart"})
        self.assertNotIn("holy_wand", checks)  # not covered by this game data

    def test_internal_names_map_to_items(self):
        mapping = gamedata.internal_to_item(load_database(), gamedata.parse_game_json(self.GAME_JSON))
        self.assertEqual(mapping["MAXHEALTH"], "hollow_heart")

    def test_unknown_internal_names_are_worked_out_from_recipes(self):
        text = json.dumps({
            "C1_SHRINK_GUARDI": [{"level": 1}],  # the game gives no display name
            "C1_CLEARDEBRIS": [{"name": "Clear Debris", "evoInto": "C1_ASTEROIDS", "evoSynergy": ["C1_SHRINK_GUARDI"]}],
            "C1_ASTEROIDS": [{"name": "Clear Asteroids"}],
        })
        db = load_database()
        data = gamedata.parse_game_json(text)
        self.assertEqual(gamedata.internal_to_item(db, data)["C1_SHRINK_GUARDI"], "mini_guardian")
        self.assertEqual(gamedata.compare(db, data)["clear_asteroids"].status, "match")

    def test_two_unknown_names_in_one_recipe(self):
        text = json.dumps({
            "C1_REPORT1": [{"level": 1, "evoInto": "C1_MEETING", "evoSynergy": ["C1_SHRINK_CREWMA"]}],
            "C1_SHRINK_CREWMA": [{"level": 1}],
            "C1_MEETING": [{"name": "Emergency Meeting"}],
        })
        db = load_database()
        mapping = gamedata.internal_to_item(db, gamedata.parse_game_json(text))
        self.assertEqual(mapping["C1_REPORT1"], "report")
        self.assertEqual(mapping["C1_SHRINK_CREWMA"], "mini_crewmate")

    def test_non_game_text_is_ignored(self):
        self.assertEqual(gamedata.parse_game_json("hello").recipes, {})
        self.assertEqual(gamedata.parse_game_json("[1, 2]").names, {})

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            gamedata.save(gamedata.parse_game_json(self.GAME_JSON), Path(d))
            self.assertIn("WHIP", gamedata.load(Path(d)).recipes)
            self.assertIsNone(gamedata.load(Path(d) / "missing"))


class SettingsTests(unittest.TestCase):
    def test_defaults_roundtrip_and_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            s, warning = settings.load(path)
            self.assertEqual((s.hidden_expansions, warning), ([], None))
            self.assertTrue(s.dark_theme)  # dark theme is on by default
            s.hidden_expansions = ["Emerald Diorama"]
            s.dark_theme = False
            self.assertIsNone(settings.save(s, path))
            self.assertEqual(settings.load(path)[0].hidden_expansions, ["Emerald Diorama"])
            self.assertFalse(settings.load(path)[0].dark_theme)
            path.write_text("{broken")
            s, warning = settings.load(path)
            self.assertEqual(s.hidden_expansions, [])
            self.assertIn("using defaults", warning)


if __name__ == "__main__":
    unittest.main()
