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


def build_database(recipes: list[Recipe], weapon_titles: list[str], passive_titles: list[str]) -> dict:
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


def download_database() -> tuple[dict, list[str]]:
    """Fetch everything from the wiki. Returns (database dict, skipped rows)."""
    recipes, skipped = parse_evolution_page(fetch_wikitext(EVOLUTION_PAGE))
    if len(recipes) < 20:
        raise WikiError(f"Only {len(recipes)} recipes found on the wiki's Evolution page; "
                        "the page layout may have changed.")
    return build_database(recipes, fetch_category("Weapons"), fetch_category("Passive items")), skipped
