"""Entry point:  python -m vshelper            (open the helper window)
              python -m vshelper diagnose   (write a memory-detection report)"""

from __future__ import annotations

import sys

from .data import DatabaseError, load_database
from .memory.game import GameMapError, load_game_map


def main(argv: list[str]) -> int:
    if argv[:1] == ["diagnose"]:
        from . import diagnose
        try:
            return diagnose.run()
        except (DatabaseError, GameMapError) as exc:
            print(f"Error: {exc}")
            return 1

    try:
        db = load_database()
    except DatabaseError as exc:
        print(f"Error: {exc}")
        return 1
    game_map, map_error = None, None
    try:
        game_map = load_game_map()
    except GameMapError as exc:
        map_error = str(exc)

    from . import ui  # imported late so 'diagnose' works without tkinter
    ui.run(db, game_map, map_error)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
