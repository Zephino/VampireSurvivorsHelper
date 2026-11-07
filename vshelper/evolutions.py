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


def format_suggestions(db: Database, suggestions: Suggestions) -> str:
    """Plain-text report (used by the diagnose report; the window draws its own with pictures)."""
    lines: list[str] = []

    def describe(s: Suggestion) -> str:
        evo = s.evolution
        recipe = " + ".join(db.name(r) for r in evo.requires)
        text = f"  {recipe}  =  {db.name(evo.result)}"
        if s.missing:
            text += f"\n      need: {', '.join(db.name(m) for m in s.missing)}"
        if evo.max_level:
            text += f"\n      max level: {', '.join(db.name(m) for m in evo.max_level)}"
        if evo.notes:
            text += f"\n      note: {evo.notes}"
        if not evo.verified:
            text += "\n      (unverified data - double-check in game)"
        return text

    sections = (
        ("READY - open a chest after 10:00", suggestions.ready),
        ("ONE ITEM AWAY", suggestions.one_away),
        ("OTHER EVOLUTIONS FOR YOUR ITEMS", suggestions.further),
    )
    for title, group in sections:
        if group:
            lines.append(title)
            lines.extend(describe(s) for s in group)
            lines.append("")

    if not lines:
        return "Select the weapons and passive items you have to see possible evolutions."
    return "\n".join(lines).rstrip()
