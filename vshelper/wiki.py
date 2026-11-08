"""Imports evolution recipes and item names from the Vampire Survivors wiki (vampire.survivors.wiki).

Wiki content is CC BY-SA; the generated data file records its source and date.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

API = "https://vampire.survivors.wiki/api.php"
USER_AGENT = "VampireSurvivorsHelper/1.0 (https://github.com/Zephino/VampireSurvivorsHelper)"
TIMEOUT = 30
EVOLUTION_PAGE = "Evolution"
SKIP_SECTIONS = ("morph",)  # character morphs are not item evolutions
NON_ITEMS = ("treasure chest",)  # pictures used in tables that are not inventory items
DLC_SECTION_BASE = "Base game"
# Infobox dlc codes -> expansion names (as the Evolution page's section titles call them)
DLC_CODES = {"lm": "Legacy of the Moonspell", "tf": "Tides of the Foscari", "em": "Emergency Meeting",
             "og": "Operation Guns", "oc": "Ode to Castlevania", "ed": "Emerald Diorama",
             "ac": "Ante Chamber", "bm": "Legacy of the Bloodmoon", "lb": "Legacy of the Bloodmoon"}


class WikiError(Exception):
    """The wiki could not be reached or its pages could not be understood."""


def slug(name: str) -> str:
    """'Tirajisú' -> 'tirajisu', "Skull O'Maniac" -> 'skull_omaniac'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


# ---- fetching -------------------------------------------------------------
def _api(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WikiError(f"Could not reach the wiki ({exc}).") from exc
    except ValueError as exc:
        raise WikiError(f"The wiki returned something that is not JSON: {exc}") from exc
    if "error" in data:
        raise WikiError(f"Wiki API error: {data['error'].get('info', data['error'])}")
    return data


def fetch_wikitext(page: str) -> str:
    try:
        return _api({"action": "parse", "page": page, "prop": "wikitext"})["parse"]["wikitext"]
    except KeyError as exc:
        raise WikiError(f"Unexpected wiki response for page '{page}'.") from exc


def fetch_category(category: str) -> list[str]:
    titles: list[str] = []
    params = {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
              "cmlimit": "500", "cmtype": "page"}
    for _ in range(20):  # 20 pages of 500 is far more than the wiki has
        data = _api(params)
        titles += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        if "continue" not in data:
            return titles
        params.update(data["continue"])
    return titles


# ---- parsing --------------------------------------------------------------
SPRITE = re.compile(r"\{\{\s*Sprite\s*\|([^|}]+)([^}]*)\}\}", re.IGNORECASE)
HEADING = re.compile(r"^(={2,4})\s*(.*?)\s*\1\s*$")


@dataclass
class Recipe:
    kind: str                      # evolution | union | gift
    dlc: str
    weapons: list[str]             # base weapon names (always need max level)
    catalysts: list[str]           # other required items
    max_level: list[str]           # catalysts that must also be max level
    results: list[str]
    notes: list[str] = field(default_factory=list)


def _cells(row: str) -> list[str]:
    """Split a wikitable row into cell texts (handles multi-line cells and 'a || b')."""
    cells: list[str] = []
    for line in row.split("\n"):
        if line.startswith(("|", "!")):
            for part in re.split(r"\|\||!!", line[1:]):
                # drop cell attributes such as 'colspan="3" |'
                if "|" in part and "{{" not in part.split("|", 1)[0] and "[[" not in part.split("|", 1)[0]:
                    part = part.split("|", 1)[1]
                cells.append(part.strip())
        elif cells:
            cells[-1] += "\n" + line
    return cells


def _sprites(cell: str) -> list[str]:
    names = []
    for m in SPRITE.finditer(cell):
        name = m.group(1).strip()
        if not name.lower().startswith(NON_ITEMS):
            names.append(name)
    return names


def _clean(text: str) -> str:
    text = SPRITE.sub("", text)
    text = re.sub(r"\{\{[^}]*\}\}|<[^>]+>|'''?", " ", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    return " ".join(text.split())


def parse_evolution_page(wikitext: str) -> tuple[list[Recipe], list[str]]:
    """Return (recipes, skipped-row descriptions) from the Evolution page wikitext."""
    recipes: list[Recipe] = []
    skipped: list[str] = []
    dlc = DLC_SECTION_BASE
    kind = "evolution"
    in_list = False
    table: list[str] | None = None

    for line in wikitext.split("\n"):
        h = HEADING.match(line)
        if h:
            level, title = len(h.group(1)), _clean(h.group(2))
            if level == 2:
                in_list = title.lower().startswith("list of")
            elif level == 3 and in_list:
                dlc = title
            elif level == 4:
                t = title.lower()
                kind = "union" if t.startswith("union") else "gift" if t.startswith("gift") else \
                    "morph" if t.startswith("morph") else "evolution"
            continue
        if not in_list:
            continue
        if line.startswith("{|"):
            table = []
            continue
        if table is None:
            continue
        if line.startswith("|}"):
            if not kind.startswith(SKIP_SECTIONS):
                # leading newline so a table without a header row still splits on its first "|-"
                for row in ("\n" + "\n".join(table)).split("\n|-")[1:]:
                    recipe = _parse_row(row, kind, dlc)
                    if isinstance(recipe, Recipe):
                        recipes.append(recipe)
                    elif recipe:
                        skipped.append(recipe)
            table = None
            continue
        table.append(line)
    return recipes, skipped


def _parse_row(row: str, kind: str, dlc: str) -> Recipe | str | None:
    cells = [c for c in _cells(row) if c]
    eq = next((i for i, c in enumerate(cells) if _clean(c) == "="), None)
    if eq is None or eq == 0:
        return None  # header or decoration row
    inputs, outputs = cells[:eq], cells[eq + 1:]
    results = [s for c in outputs for s in _sprites(c)]
    weapons = _sprites(inputs[0])
    catalysts, max_level, notes = [], [], []
    for cell in inputs[1:]:
        text = _clean(cell)
        if text in ("+", ""):
            if not _sprites(cell):
                continue
        names = _sprites(cell)
        leftover = text.replace("+", "").replace("Max level:", "").strip()
        if leftover and not names:
            if re.fullmatch(r"\s*\[\[[^\]]+\]\]\s*", cell):  # a linked non-item condition, e.g. a Glimmer
                notes.append(f"Also needs: {leftover}")
                continue
            return f"{dlc} {kind}: {' + '.join(weapons)} -> {', '.join(results)} (condition: {leftover})"
        catalysts += names
        if "max level" in text.lower():
            max_level += names
    if not weapons or not results:
        return f"{dlc} {kind}: could not read row {_clean(row)[:80]!r}"
    return Recipe(kind, dlc, weapons, catalysts, max_level, results, notes)


# ---- building the database ------------------------------------------------
def _item_title(title: str) -> str:
    return re.sub(r"\s*\((item|weapon)\)\s*$", "", title)


def build_database(recipes: list[Recipe], weapon_titles: list[str], passive_titles: list[str],
                   game_ids: dict[str, str] | None = None) -> dict:
    """Produce data in the format of vshelper/data/evolutions.json."""
    weapons: dict[str, dict] = {}
    passives: dict[str, dict] = {}
    evolved: set[str] = set()

    def add(table: dict, name: str, dlc: str | None) -> str:
        item_id = slug(name)
        entry = table.setdefault(item_id, {"id": item_id, "name": name})
        if dlc and "dlc" not in entry:
            entry["dlc"] = dlc
        return item_id

    weapon_names = {_item_title(t) for t in weapon_titles}
    for r in recipes:
        for w in r.weapons:
            add(weapons, w, r.dlc)
        for res in r.results:
            add(weapons, res, r.dlc)
            evolved.add(slug(res))
    for r in recipes:
        for c in r.catalysts:
            if slug(c) not in weapons and c not in weapon_names:
                add(passives, c, r.dlc)
            else:
                add(weapons, c, r.dlc)
    for t in passive_titles:
        name = _item_title(t)
        if name.lower() not in ("passive items", "evolution", "gifts") and slug(name) not in weapons:
            add(passives, name, None)
    for t in weapon_titles:
        name = _item_title(t)
        if name.lower() != "weapons" and slug(name) not in passives:
            add(weapons, name, None)
    for item_id in evolved:
        weapons[item_id]["evolved"] = True
    by_slug = {slug(n): code for n, code in (game_ids or {}).items()}
    for table in (weapons, passives):
        for item_id, entry in table.items():
            if item_id in by_slug:
                entry["game_id"] = by_slug[item_id]  # lets the helper recognise the game's codes

    evolutions = []
    seen = set()
    for r in recipes:
        requires = [slug(n) for n in r.weapons + r.catalysts]
        max_level = [slug(n) for n in r.weapons + r.max_level]
        for res in r.results:
            key = (slug(res), tuple(sorted(requires)))
            if key in seen:
                continue
            seen.add(key)
            entry = {"result": slug(res), "requires": list(dict.fromkeys(requires)),
                     "max_level": list(dict.fromkeys(max_level)), "kind": r.kind, "dlc": r.dlc}
            notes = list(r.notes)
            if r.kind == "union":
                notes.append("Union: the weapons merge into one slot.")
            elif r.kind == "gift":
                notes.append("Gift: you keep the base weapon and get this as an extra.")
            if notes:
                entry["notes"] = " ".join(notes)
            evolutions.append(entry)

    return {
        "_comment": f"Generated from {API.rsplit('/', 1)[0]} (CC BY-SA) on {date.today().isoformat()} "
                    "by 'python -m vshelper update-data'. Edit by re-running that command.",
        "source": "vampire.survivors.wiki",
        "generated": date.today().isoformat(),
        "weapons": sorted(weapons.values(), key=lambda i: i["name"].lower()),
        "passives": sorted(passives.values(), key=lambda i: i["name"].lower()),
        "evolutions": evolutions,
    }


def fetch_pages(titles: list[str]) -> dict[str, str]:
    """{title: wikitext} for many pages, 50 per request."""
    pages: dict[str, str] = {}
    for start in range(0, len(titles), 50):
        data = _api({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                     "titles": "|".join(titles[start:start + 50])})
        for page in data.get("query", {}).get("pages", []):
            revs = page.get("revisions") or []
            if revs:
                pages[page["title"]] = revs[0].get("slots", {}).get("main", {}).get("content", "")
    return pages


def read_item_pages(titles: list[str]) -> list[ItemLookup]:
    """Every item page's infobox."""
    out = []
    for title, text in fetch_pages(titles).items():
        lookup = parse_item_page(title, text)
        if lookup is not None:
            out.append(lookup)
    return out


def recipes_from_item_pages(lookups: list[ItemLookup], passive_names: set[str]) -> list[Recipe]:
    """Recipes from the weapon pages' infoboxes (evolution / union fields). Some recipes are only
    listed there, not on the Evolution page."""
    out: list[Recipe] = []
    for lookup in lookups:
        if lookup.kind != "weapon":
            continue
        for r in lookup.recipes:
            requires = [n for n in r["requires"] if n]
            if not requires or not r["result"] or r["result"] in passive_names:
                continue  # e.g. a page naming a passive as its "evolution": not a real recipe
            kind, notes = r["kind"], ["From the item's wiki page."]
            if any(n.lower().startswith("chaos ") for n in requires[1:]):
                kind = "morph"  # character morphs: a Chaos relic plus the character at level 80
                notes = ["Morph: needs the character at level 80 with this relic - see the wiki."]
            weapons = requires if kind == "union" else requires[:1]
            catalysts = [] if kind == "union" else requires[1:]
            out.append(Recipe(kind, lookup.dlc, weapons, catalysts, [], [r["result"]], notes))
    return out


def download_database(item_pages: bool = True) -> tuple[dict, list[str]]:
    """Fetch everything from the wiki. Returns (database dict, skipped rows).

    item_pages: also read every weapon page for recipes missing from the Evolution page.
    """
    recipes, skipped = parse_evolution_page(fetch_wikitext(EVOLUTION_PAGE))
    if len(recipes) < 20:
        raise WikiError(f"Only {len(recipes)} recipes found on the wiki's Evolution page; "
                        "the page layout may have changed.")
    weapon_titles = fetch_category("Weapons")
    passive_titles = fetch_category("Passive items")
    if item_pages:
        known_results = {slug(res) for r in recipes for res in r.results}
        # results the Evolution page skipped for non-item conditions ("6 passives", ...) stay out:
        # the item pages leave those conditions out and they would look ready too early
        known_results |= {slug(m.group(1)) for row in skipped for m in [re.search(r"-> (.+?) \(condition", row)] if m}
        passive_names = {_item_title(t) for t in passive_titles}
        pages = read_item_pages([t for t in weapon_titles + passive_titles
                                 if t.lower() not in ("weapons", "passive items")])
        game_ids = {p.name: p.game_id for p in pages if p.game_id}
        added = 0
        for r in recipes_from_item_pages(pages, passive_names):
            result = slug(r.results[0])
            if result in known_results:
                continue  # the Evolution page already has this one (with more detail)
            known_results.add(result)
            recipes.append(r)
            added += 1
        skipped.append(f"(added {added} recipes found only on item pages)")
    else:
        game_ids = {}
    return build_database(recipes, weapon_titles, passive_titles, game_ids), skipped


# ---- looking up a single item ---------------------------------------------
PAGE_URL = "https://vampire.survivors.wiki/w/"
INFOBOX = re.compile(r"\{\{\s*Infobox ([^\n|]+)(.*?)\n\}\}", re.S | re.IGNORECASE)


@dataclass
class ItemLookup:
    name: str                       # the page title (canonical item name)
    kind: str                       # "weapon" or "passive" (from the infobox type)
    recipes: list[dict]             # {"result", "requires", "kind"} in database-entry style, by name
    url: str
    dlc: str = DLC_SECTION_BASE     # from the infobox's dlc code
    game_id: str = ""               # the game's internal code (infobox 'id'), e.g. BMN011_FIRE2_BALL


def _infobox_fields(text: str) -> dict[str, str]:
    """Infobox 'key = value' pairs. Fields are split on '|' outside [[links]] and {{templates}},
    so several fields on one line ('|evolution = X|evolution-item = Y') are read correctly."""
    parts, depth, current = [], 0, []
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in ("[[", "{{"):
            depth += 1
            current.append(pair)
            i += 2
            continue
        if pair in ("]]", "}}") and depth:
            depth -= 1
            current.append(pair)
            i += 2
            continue
        if text[i] == "|" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(text[i])
        i += 1
    parts.append("".join(current))
    fields: dict[str, str] = {}
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = value.strip()
    return fields


def _plain(value: str) -> str:
    """'[[Armor (item)|Armor]]' / 'Armor (item)' / '{{slink|Armor}}' -> 'Armor'."""
    value = re.sub(r"\{\{\s*slink\s*\|([^|}]+)[^}]*\}\}", r"\1", value, flags=re.I)
    value = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^}]*\}\}|<[^>]+>", "", value)
    return _item_title(value.strip())


def parse_item_page(title: str, wikitext: str) -> ItemLookup | None:
    """Read an item page's infobox: its evolution / union and what they need."""
    m = INFOBOX.search(wikitext)
    if not m:
        return None
    box_type = m.group(1).strip().lower()
    if not ("weapon" in box_type or "passive" in box_type):
        return None  # e.g. a redirect to an arcana or character page: not an item
    fields = _infobox_fields(m.group(2))
    name = _item_title(fields.get("name") or title)
    kind = "passive" if "passive" in box_type else "weapon"
    recipes = []
    for result_key, item_prefix, recipe_kind in (("evolution", "evolution-item", "evolution"),
                                                 ("union", "union-item", "union")):
        result = _plain(fields.get(result_key, ""))
        if not result:
            continue
        needs = [_plain(fields[k]) for k in sorted(fields) if k == item_prefix or
                 re.fullmatch(re.escape(item_prefix) + r"\d+", k)]
        recipes.append({"result": result, "requires": [name, *[n for n in needs if n]], "kind": recipe_kind})
    if fields.get("type", "").strip().lower() == "union":  # the union's own page lists its parts
        parts = [_plain(fields[k]) for k in sorted(fields) if re.fullmatch(r"requires\d+", k)]
        if parts:
            recipes.append({"result": name, "requires": [p for p in parts if p], "kind": "union"})
    dlc = DLC_CODES.get(fields.get("dlc", "").strip().lower(), DLC_SECTION_BASE)
    game_id = _plain(fields.get("id", "")).strip()
    return ItemLookup(name, kind, recipes, PAGE_URL + urllib.parse.quote(title.replace(" ", "_")), dlc, game_id)


def lookup_item(name: str) -> ItemLookup | None:
    """Fetch and read the wiki page for one item. None if there is no such page."""
    try:
        data = _api({"action": "parse", "page": name, "prop": "wikitext", "redirects": "1"})
    except WikiError as exc:
        if "doesn't exist" in str(exc) or "missingtitle" in str(exc):
            return None
        raise
    parse = data.get("parse", {})
    return parse_item_page(parse.get("title", name), parse.get("wikitext", ""))


# ---- item pictures ---------------------------------------------------------
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def sprite_urls(names: list[str]) -> dict[str, str | None]:
    """{item name: URL of its 'Sprite-<name>.png' on the wiki, or None if there is none}."""
    result: dict[str, str | None] = {}
    for start in range(0, len(names), 50):  # the API takes up to 50 titles per request
        batch = names[start:start + 50]
        titles = {f"File:Sprite-{n}.png": n for n in batch}
        data = _api({"action": "query", "titles": "|".join(titles), "prop": "imageinfo", "iiprop": "url"})
        query = data.get("query", {})
        renamed = {r["to"]: r["from"] for r in query.get("normalized", [])}
        for page in query.get("pages", []):
            title = renamed.get(page.get("title"), page.get("title"))
            name = titles.get(title)
            if name is None:
                continue
            info = page.get("imageinfo") or [{}]
            result[name] = None if page.get("missing") else info[0].get("url")
        for n in batch:
            result.setdefault(n, None)
    return result


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WikiError(f"Could not download {url} ({exc}).") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise WikiError(f"{url} is unexpectedly large.")
    return data
