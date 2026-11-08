import tempfile
import unittest
from pathlib import Path

from vshelper import lookups
from vshelper.data import load_database
from vshelper.evolutions import plans_for_held
from vshelper.wiki import parse_item_page

KEREMET = """{{DLC Content|oc}}
{{Infobox Weapon
|dlc = oc
|type =Normal
|evolution =Keremet Morbus
|evolution-item =Armor (item)
|max-level =8
}}
'''Keremet Bubbles''' is a weapon."""

CLOCK = """{{Infobox Weapon
|type = Normal
|evolution = [[Infinite Corridor]]
|evolution-item = Silver Ring
|evolution-item2 = {{slink|Gold Ring}}
}}"""

UNION_PAGE = """{{Infobox Weapon
|name = Shimmering Sands
|type = Union
|requires1 = Kyra-Stones
|requires2 = Descent Into Misery
}}"""

NEW_ITEM = """{{Infobox Weapon
|type = Normal
|evolution = Brand New Evolution
|evolution-item = Spinach
}}"""


class ParseItemPageTests(unittest.TestCase):
    def test_evolution_with_one_and_two_items(self):
        k = parse_item_page("Keremet Bubbles", KEREMET)
        self.assertEqual(k.recipes, [{"result": "Keremet Morbus", "requires": ["Keremet Bubbles", "Armor"],
                                      "kind": "evolution"}])
        c = parse_item_page("Clock Lancet", CLOCK)
        self.assertEqual(c.recipes[0]["requires"], ["Clock Lancet", "Silver Ring", "Gold Ring"])
        self.assertEqual(c.recipes[0]["result"], "Infinite Corridor")

    def test_union_page_and_passive(self):
        u = parse_item_page("Shimmering Sands", UNION_PAGE)
        self.assertEqual(u.recipes, [{"result": "Shimmering Sands", "requires": ["Kyra-Stones", "Descent Into Misery"],
                                      "kind": "union"}])
        p = parse_item_page("Spinach", "{{Infobox Passive item\n|stage-item = x\n}}")
        self.assertEqual((p.kind, p.recipes), ("passive", []))
        self.assertIsNone(parse_item_page("Nothing", "no infobox here"))
        arcana = "{{Infobox Arcana\n|name = Gemini (I)\n}}"  # a redirect can land on a non-item page
        self.assertIsNone(parse_item_page("Speculo Keremet Bubbles", arcana))


class InfoboxLayoutTests(unittest.TestCase):
    def test_several_fields_on_one_line(self):
        text = "{{Infobox Weapon\n|dlc=oc\n|evolution = Nitesco|evolution-item=Empty Tome|id =TP_ENERGY1\n|rarity=50\n}}"
        lookup = parse_item_page("Globus", text)
        self.assertEqual(lookup.recipes, [{"result": "Nitesco", "requires": ["Globus", "Empty Tome"],
                                           "kind": "evolution"}])
        self.assertEqual(lookup.dlc, "Ode to Castlevania")

    def test_links_with_pipes_stay_whole(self):
        text = "{{Infobox Weapon\n|evolution = [[Armor (item)|Armor]] thing|evolution-item = {{slink|Gold Ring|txt=Gold}}\n}}"
        lookup = parse_item_page("X", text)
        self.assertEqual(lookup.recipes[0]["requires"], ["X", "Gold Ring"])


class LookupCacheTests(unittest.TestCase):
    def test_new_item_and_recipe_are_added_and_remembered(self):
        db = load_database()
        with tempfile.TemporaryDirectory() as d:
            cache = lookups.LookupCache(Path(d))
            self.assertFalse(cache.is_fresh("Mystery Gun"))
            entry = cache.put("Mystery Gun", parse_item_page("Mystery Gun", NEW_ITEM))
            self.assertTrue(lookups.LookupCache(Path(d)).is_fresh("mystery gun"))  # saved, case-insensitive
            self.assertEqual(lookups.apply_to_db(db, entry), 1)
            self.assertEqual(lookups.apply_to_db(db, entry), 0)  # not added twice
        self.assertIn("mystery_gun", db.items)
        plan = plans_for_held(db, {"mystery_gun"})[0]
        self.assertEqual(plan.options[0].evolution.result, "brand_new_evolution")
        self.assertEqual(plan.options[0].missing, ("spinach",))
        self.assertNotIn("", db.expansions())

    def test_known_recipe_is_not_duplicated(self):
        db = load_database()
        before = len(db.evolutions)
        entry = {"found": True, **parse_item_page("Keremet Bubbles", KEREMET).__dict__}
        self.assertEqual(lookups.apply_to_db(db, entry), 0)
        self.assertEqual(len(db.evolutions), before)

    def test_not_found_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            cache = lookups.LookupCache(Path(d))
            entry = cache.put("Nope", None, now=1000.0)
            self.assertFalse(entry["found"])
            self.assertTrue(cache.is_fresh("Nope", now=1000.0 + 3600))
            self.assertFalse(cache.is_fresh("Nope", now=1000.0 + 8 * 86400))  # asked again after a week


if __name__ == "__main__":
    unittest.main()
