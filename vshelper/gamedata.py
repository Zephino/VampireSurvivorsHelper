"""Evolution data read from the game's own files, used to double-check the wiki data.

Weapon data in Vampire Survivors is JSON keyed by internal id, e.g.
  {"WHIP": [{"name": "Whip", "evoInto": "VAMPIRICA", "evoSynergy": ["MAXHEALTH"], ...}, ...]}
The exact layout is not guaranteed, so parsing is tolerant: anything it can't read is ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .data import Database

GAME_DATA_FILE = "game_data.json"


def _canon(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class GameData:
    names: dict[str, str] = field(default_factory=dict)         # internal id -> display name
    recipes: dict[str, dict] = field(default_factory=dict)      # internal id -> {"into": id, "synergy": [ids]}

    def merge(self, other: "GameData") -> None:
        for k, v in other.names.items():
            self.names.setdefault(k, v)
        for k, v in other.recipes.items():
            self.recipes.setdefault(k, v)

    def to_json(self) -> dict:
        return {"names": self.names, "recipes": self.recipes}

    @classmethod
    def from_json(cls, raw: dict) -> "GameData":
        return cls(dict(raw.get("names", {})), dict(raw.get("recipes", {})))


def parse_game_json(text: str) -> GameData:
    """Extract names and evolution recipes from one game data file (empty if not that kind of file)."""
    out = GameData()
    if "evoInto" not in text and '"name"' not in text:
        return out
    try:
        data = json.loads(text)
    except ValueError:
        return out
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        levels = value if isinstance(value, list) else [value]
        for level in levels:
            if not isinstance(level, dict):
                continue
            name = level.get("name")
            if isinstance(name, str) and name.strip() and key not in out.names:
                out.names[key] = name.strip()
            into = level.get("evoInto")
            if isinstance(into, str) and into and key not in out.recipes:
                synergy = level.get("evoSynergy") or []
                if isinstance(synergy, str):
                    synergy = [synergy]
                out.recipes[key] = {"into": into, "synergy": [s for s in synergy if isinstance(s, str)]}
    return out


def save(game_data: GameData, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / GAME_DATA_FILE).write_text(json.dumps(game_data.to_json(), indent=1, ensure_ascii=False),
                                          encoding="utf-8")


def load(out_dir: Path) -> GameData | None:
    try:
        return GameData.from_json(json.loads((out_dir / GAME_DATA_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError):
        return None


def internal_to_item(db: Database, game_data: GameData) -> dict[str, str]:
    """Internal game id -> database item id.

    First by display name; then by elimination: if a game recipe and a wiki recipe for the same
    evolution differ by exactly one unknown internal id, that id must be the remaining item
    (e.g. C1_SHRINK_GUARDI -> Mini Guardian, REVIVAL -> Tirajisú).
    """
    by_name = {_canon(i.name): i.id for i in db.items.values()}
    mapping = {k: by_name[_canon(n)] for k, n in game_data.names.items() if _canon(n) in by_name}
    by_result: dict[str, list] = {}
    for evo in db.evolutions:
        by_result.setdefault(evo.result, []).append(evo)

    changed = True
    while changed:
        changed = False
        for base, recipe in game_data.recipes.items():
            parts = list(dict.fromkeys([base, *recipe["synergy"]]))
            into = recipe["into"]
            unknown = [p for p in parts if p not in mapping]
            known = {mapping[p] for p in parts if p in mapping}
            if into in mapping and len(unknown) == 1:
                for evo in by_result.get(mapping[into], []):
                    leftover = [r for r in evo.requires if r not in known]
                    if len(evo.requires) == len(parts) and len(leftover) == 1 and leftover[0] not in mapping.values():
                        mapping[unknown[0]] = leftover[0]
                        changed = True
                        break
            elif into not in mapping and not unknown:
                matches = [e.result for e in db.evolutions if set(e.requires) == known]
                if len(matches) == 1 and matches[0] not in mapping.values():
                    mapping[into] = matches[0]
                    changed = True
    return mapping


@dataclass(frozen=True)
class Check:
    status: str                     # match | mismatch
    game_requires: tuple[str, ...]  # item ids (or raw internal ids when unknown)


def compare(db: Database, game_data: GameData) -> dict[str, Check]:
    """Compare each database evolution with the game's recipe for the same result.

    Returns {result item id: Check}. Evolutions the game data doesn't cover are left out.
    """
    to_item = internal_to_item(db, game_data)
    game_recipes: dict[str, list[tuple[str, ...]]] = {}
    for base, recipe in game_data.recipes.items():
        result = to_item.get(recipe["into"])
        if not result:
            continue
        parts = tuple(sorted({to_item.get(x, x) for x in [base, *recipe["synergy"]]}))
        game_recipes.setdefault(result, []).append(parts)

    checks: dict[str, Check] = {}
    for evo in db.evolutions:
        options = game_recipes.get(evo.result)
        if not options:
            continue
        mine = tuple(sorted(set(evo.requires)))
        if mine in options:
            checks[evo.result] = Check("match", mine)
        elif evo.result not in checks:
            checks[evo.result] = Check("mismatch", options[0])
    return checks
