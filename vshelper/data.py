"""Loading and validating the evolution database (vshelper/data/evolutions.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "evolutions.json"


class DatabaseError(Exception):
    """Raised when the evolution database is missing or malformed."""


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    kind: str  # "weapon" or "passive"
    dlc: str = "Base game"
    evolved: bool = False


@dataclass(frozen=True)
class Evolution:
    result: str
    requires: tuple[str, ...]
    max_level: tuple[str, ...] = ()
    verified: bool = True
    notes: str = ""


@dataclass
class Database:
    items: dict[str, Item] = field(default_factory=dict)
    evolutions: list[Evolution] = field(default_factory=list)

    def weapons(self) -> list[Item]:
        return [i for i in self.items.values() if i.kind == "weapon"]

    def passives(self) -> list[Item]:
        return [i for i in self.items.values() if i.kind == "passive"]

    def name(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.name if item else item_id


def load_database(path: Path | str = DEFAULT_DB_PATH) -> Database:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DatabaseError(f"Evolution database not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DatabaseError(f"Evolution database {path} is not valid JSON: {exc}") from exc
    return parse_database(raw, source=str(path))


def parse_database(raw: dict, source: str = "<data>") -> Database:
    db = Database()
    errors: list[str] = []

    for kind, key in (("weapon", "weapons"), ("passive", "passives")):
        for entry in raw.get(key, []):
            try:
                item = Item(
                    id=entry["id"],
                    name=entry["name"],
                    kind=kind,
                    dlc=entry.get("dlc", "Base game"),
                    evolved=bool(entry.get("evolved", False)),
                )
            except KeyError as exc:
                errors.append(f"{key} entry {entry!r} is missing {exc}")
                continue
            if item.id in db.items:
                errors.append(f"duplicate item id '{item.id}'")
            db.items[item.id] = item

    for entry in raw.get("evolutions", []):
        try:
            evo = Evolution(
                result=entry["result"],
                requires=tuple(entry["requires"]),
                max_level=tuple(entry.get("max_level", ())),
                verified=bool(entry.get("verified", True)),
                notes=entry.get("notes", ""),
            )
        except KeyError as exc:
            errors.append(f"evolution entry {entry!r} is missing {exc}")
            continue
        for ref in (evo.result, *evo.requires, *evo.max_level):
            if ref not in db.items:
                errors.append(f"evolution '{evo.result}' references unknown item '{ref}'")
        for ref in evo.max_level:
            if ref not in evo.requires:
                errors.append(f"evolution '{evo.result}': max_level item '{ref}' is not in requires")
        db.evolutions.append(evo)

    if errors:
        raise DatabaseError(f"Problems in {source}:\n  " + "\n  ".join(errors))
    return db
