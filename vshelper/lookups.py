"""Remembers per-item wiki lookups (cache/wiki_lookups.json) and adds what they find to the data.

Used when you hold (or plan) an item the helper has no recipe for: its wiki page is read once and
the answer is kept for RECHECK_DAYS, so the wiki isn't asked again every run.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .data import Database, Evolution, Item
from .wiki import ItemLookup, slug

LOOKUP_FILE = "wiki_lookups.json"
RECHECK_DAYS = 7
NOTE = "Found on the item's wiki page - check it for any special conditions."


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class LookupCache:
    def __init__(self, folder: Path):
        self.path = folder / LOOKUP_FILE
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries: dict[str, dict] = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.entries = {}

    def get(self, name: str) -> dict | None:
        return self.entries.get(_key(name))

    def is_fresh(self, name: str, now: float | None = None) -> bool:
        entry = self.get(name)
        now = time.time() if now is None else now
        return bool(entry) and now - entry.get("checked", 0) < RECHECK_DAYS * 86400

    def put(self, name: str, lookup: ItemLookup | None, now: float | None = None) -> dict:
        entry = {"checked": time.time() if now is None else now, "found": lookup is not None}
        if lookup is not None:
            entry.update(name=lookup.name, kind=lookup.kind, url=lookup.url, recipes=lookup.recipes)
        self.entries[_key(name)] = entry
        if lookup is not None:
            self.entries[_key(lookup.name)] = entry  # the page may be a redirect from another name
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # not saved: it's only a cache, the lookup simply happens again next time
        return entry


def apply_to_db(db: Database, entry: dict) -> int:
    """Add the items and recipes from a lookup entry. Returns how many recipes were new."""
    if not entry.get("found"):
        return 0
    by_canon = {_key(i.name): i.id for i in db.items.values()}

    def ensure(name: str, kind: str, evolved: bool = False) -> str:
        existing = by_canon.get(_key(name))
        if existing:
            return existing
        item_id = slug(name)
        db.items[item_id] = Item(id=item_id, name=name, kind=kind, dlc="", evolved=evolved)
        by_canon[_key(name)] = item_id
        return item_id

    page_item = entry.get("name", "")
    if page_item:
        ensure(page_item, entry.get("kind", "weapon"))
    known = {(e.result, frozenset(e.requires)) for e in db.evolutions}
    added = 0
    for recipe in entry.get("recipes", []):
        kind = recipe.get("kind", "evolution")
        result = ensure(recipe["result"], "weapon", evolved=True)
        requires = []
        for i, name in enumerate(recipe.get("requires", [])):
            # the first part is the page's own item; other evolution parts are usually passives
            requires.append(ensure(name, "weapon" if i == 0 or kind == "union" else "passive"))
        if result in requires or (result, frozenset(requires)) in known:
            continue
        db.evolutions.append(Evolution(result=result, requires=tuple(requires), max_level=(requires[0],),
                                       notes=NOTE, kind=kind, dlc=""))
        known.add((result, frozenset(requires)))
        added += 1
    return added
