"""Entry point:  python -m vshelper                        (open the helper window)
              python -m vshelper diagnose               (write a detection report)
              python -m vshelper update-data            (download the latest data from the wiki)
              python -m vshelper update-data --bundled  (developers: refresh the bundled copy)"""

from __future__ import annotations

import json
import sys

from .data import CACHED_DB_PATH, DEFAULT_DB_PATH, DatabaseError, load_best_database, parse_database
from .memory.game import GameMapError, load_game_map


def _report_startup_error(message: str) -> None:
    """Print the error, and also show it in a popup (pythonw has no console to print to)."""
    print(f"Error: {message}")
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Vampire Survivors Helper", message)
        root.destroy()
    except Exception:  # no tkinter or no display: the printed message is all we can do
        pass


def update_data(bundled: bool) -> int:
    from .wiki import WikiError, download_database
    target = DEFAULT_DB_PATH if bundled else CACHED_DB_PATH
    print("Downloading evolution data from vampire.survivors.wiki ...")
    try:
        raw, skipped = download_database()
        db = parse_database(raw, source="wiki download")
    except (WikiError, DatabaseError) as exc:
        print(f"Error: {exc}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(db.evolutions)} recipes and {len(db.items)} items to {target}")
    if skipped:
        print("Not imported (conditions that aren't items):")
        for row in skipped:
            print(f"  {row}")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["update-data"]:
        return update_data(bundled="--bundled" in argv)
    if argv[:1] == ["diagnose"]:
        from . import diagnose
        try:
            return diagnose.run()
        except (DatabaseError, GameMapError) as exc:
            print(f"Error: {exc}")
            return 1

    try:
        db, db_warning = load_best_database()
    except DatabaseError as exc:
        _report_startup_error(str(exc))
        return 1
    game_map, map_error = None, None
    try:
        game_map = load_game_map()
    except GameMapError as exc:
        map_error = str(exc)

    from . import updater
    if updater.FROZEN:
        updater.cleanup_old_exe()  # the previous exe left behind by a self-update

    from . import ui  # imported late so 'diagnose' works without tkinter
    ui.run(db, game_map, map_error, notice=db_warning)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
