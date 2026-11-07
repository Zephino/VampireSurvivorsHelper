"""Works out which evolutions are possible from the items the player owns."""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import Database, Evolution


@dataclass(frozen=True)
class Suggestion:
    evolution: Evolution
    owned: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass
class Suggestions:
    ready: list[Suggestion] = field(default_factory=list)      # everything owned
    one_away: list[Suggestion] = field(default_factory=list)   # missing exactly one item
    further: list[Suggestion] = field(default_factory=list)    # missing two or more


def suggest(db: Database, owned: set[str], hidden_dlc: set[str] | frozenset[str] = frozenset()) -> Suggestions:
    """Return evolutions that involve at least one owned item, grouped by how close they are.

    Evolutions whose result is already owned, or that belong to a hidden expansion, are skipped.
    """
    out = Suggestions()
    for evo in db.evolutions:
        if evo.result in owned or evo.dlc in hidden_dlc:
            continue
        have = tuple(r for r in evo.requires if r in owned)
        if not have:
            continue
        missing = tuple(r for r in evo.requires if r not in owned)
        s = Suggestion(evo, have, missing)
        if not missing:
            out.ready.append(s)
        elif len(missing) == 1:
            out.one_away.append(s)
        else:
            out.further.append(s)
    return out


@dataclass(frozen=True)
class ItemPlan:
    """An item the player holds and the evolutions it takes part in."""
    item: str
    options: tuple[Suggestion, ...]


def held_in_order(db: Database, owned: set[str]) -> list[str]:
    """Held items: weapons first, then passive items, each alphabetical."""
    return sorted((i for i in owned if i in db.items),
                  key=lambda i: (db.items[i].kind != "weapon", db.name(i).lower()))


def plans_for_held(db: Database, owned: set[str], hidden_dlc: set[str] | frozenset[str] = frozenset()) -> list[ItemPlan]:
    """For each held item (weapons first), the evolutions it can be part of and what is still missing."""
    plans = []
    for item in held_in_order(db, owned):
        options = []
        for evo in db.evolutions:
            if item not in evo.requires or evo.result in owned or evo.dlc in hidden_dlc:
                continue
            have = tuple(r for r in evo.requires if r in owned)
            missing = tuple(r for r in evo.requires if r not in owned)
            options.append(Suggestion(evo, have, missing))
        options.sort(key=lambda s: (len(s.missing), db.name(s.evolution.result).lower()))
        plans.append(ItemPlan(item, tuple(options)))
    return plans


def format_plan(db: Database, owned: set[str], hidden_dlc: set[str] | frozenset[str] = frozenset()) -> str:
    """Plain-text version of the window's results (used by the diagnose report)."""
    if not owned:
        return "No items held."
    lines = ["YOU'RE HOLDING: " + ", ".join(db.name(i) for i in held_in_order(db, owned)), ""]
    ready = suggest(db, owned, hidden_dlc).ready
    if ready:
        lines.append("READY TO EVOLVE - open a chest")
        lines += [f"  {' + '.join(db.name(r) for r in s.evolution.requires)} = {db.name(s.evolution.result)}"
                  for s in ready]
        lines.append("")
    lines.append("HOW TO EVOLVE YOUR ITEMS")
    for plan in plans_for_held(db, owned, hidden_dlc):
        lines.append(f"  {db.name(plan.item)}")
        if not plan.options:
            lines.append("      no evolution")
        for s in plan.options:
            others = [r for r in s.evolution.requires if r != plan.item]
            needs = ", ".join(f"{db.name(r)} {'(have)' if r in owned else '(need)'}" for r in others)
            lines.append(f"      -> {db.name(s.evolution.result)}" + (f": needs {needs}" if needs else "")
                         + ("  READY" if not s.missing else ""))
    return "\n".join(lines)
