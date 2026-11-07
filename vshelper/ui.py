"""Tkinter window: tick items manually, or let the helper read them from the game."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import json
import time

from . import gamedata, icons
from . import settings as user_settings
from .data import CACHE_ROOT, CACHED_DB_PATH, Database, DatabaseError, Item, parse_database
from .evolutions import ItemPlan, Suggestion, held_in_order, plans_for_held, suggest
from .memory.game import GameMap, GameReader, ReadResult
from .memory.winapi import process_exe_path

POLL_SECONDS = 1.0
GAME_SEARCH_SECONDS = 10.0


class IconThread(threading.Thread):
    """Extracts item pictures from the game files once, waiting until the game folder is known."""

    def __init__(self, db: Database, game_map: GameMap | None, messages: "queue.Queue[tuple[str, str]]"):
        super().__init__(daemon=True)
        self.db = db
        self.map = game_map
        self.messages = messages
        self.stopped = threading.Event()

    def run(self) -> None:
        exe_name = self.map.process_name if self.map else "VampireSurvivors.exe"
        aliases = self.map.enum_aliases if self.map else {}
        announced = False
        while not self.stopped.is_set():
            exe = process_exe_path(exe_name)
            game_dir = icons.find_game_dir(Path(exe) if exe else None)
            if game_dir is not None:
                if not icons.needs_extraction(game_dir):
                    return
                try:
                    report = icons.extract_icons(
                        game_dir, self.db, aliases,
                        progress=lambda m: self.messages.put(("status", m)))
                except icons.IconError as exc:
                    self.messages.put(("status", f"No item pictures: {exc}"))
                    return
                except Exception as exc:  # unexpected game file format; pictures are optional
                    self.messages.put(("status", f"No item pictures: unexpected error {exc!r}"))
                    return
                self.messages.put(("done", f"Item pictures: {len(report.found)} of {len(self.db.items)} found."))
                return
            if not icons.read_manifest() and not announced:
                self.messages.put(("status", "Item pictures: start the game once so the helper can find it."))
                announced = True
            self.stopped.wait(GAME_SEARCH_SECONDS)


class ReaderThread(threading.Thread):
    """Polls the game in the background so memory searches never freeze the window."""

    def __init__(self, reader: GameReader, results: "queue.Queue[ReadResult]"):
        super().__init__(daemon=True)
        self.reader = reader
        self.results = results
        self.enabled = threading.Event()
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.is_set():
            if self.enabled.is_set():
                try:
                    self.results.put(self.reader.poll())
                except Exception as exc:  # keep the thread alive; report the problem in the status bar
                    self.results.put(ReadResult("error", f"Unexpected error while reading the game: {exc!r}"))
            self.stopped.wait(POLL_SECONDS)
        self.reader.close()


WIKI_REFRESH_DAYS = 7


class WikiThread(threading.Thread):
    """Downloads fresh evolution data from the wiki about once a week (used from the next start)."""

    def __init__(self, db: Database, messages: "queue.Queue[tuple[str, str]]"):
        super().__init__(daemon=True)
        self.db = db
        self.messages = messages

    def run(self) -> None:
        try:
            age_days = (time.time() - CACHED_DB_PATH.stat().st_mtime) / 86400
        except OSError:
            age_days = None
        if age_days is not None and age_days < WIKI_REFRESH_DAYS:
            return
        from .wiki import WikiError, download_database
        try:
            raw, _skipped = download_database()
            fresh = parse_database(raw, source="wiki download")
        except (WikiError, DatabaseError) as exc:
            self.messages.put(("wiki", f"Wiki update skipped: {exc}"))
            return
        CACHED_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHED_DB_PATH.write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
        old = {(e.result, e.requires) for e in self.db.evolutions}
        new = {(e.result, e.requires) for e in fresh.evolutions}
        if old != new:
            self.messages.put(("wiki", f"New wiki data downloaded ({len(new - old)} changed recipes). "
                                       "Restart the helper to use it."))


class App:
    def __init__(self, root: tk.Tk, db: Database, game_map: GameMap | None, map_error: str | None = None,
                 notice: str | None = None):
        self.root = root
        self.db = db
        self.vars: dict[str, tk.BooleanVar] = {}
        self.checkbuttons: dict[str, ttk.Checkbutton] = {}
        self.results: "queue.Queue[ReadResult]" = queue.Queue()
        self.detected: ReadResult | None = None  # latest auto-detect result (owned items and levels)
        self.icon_messages: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.icons: dict[str, tk.PhotoImage] = {}
        self.small_icons: dict[str, tk.PhotoImage] = {}
        self.settings, settings_warning = user_settings.load()
        self.expansion_vars: dict[str, tk.BooleanVar] = {}
        notice = notice or settings_warning

        root.title("Vampire Survivors Helper")
        root.geometry("1000x620")
        root.minsize(640, 400)

        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=game_map is not None)
        auto = ttk.Checkbutton(top, text="Auto-detect from game", variable=self.auto_var, command=self._toggle_auto)
        auto.pack(side="left")
        ttk.Button(top, text="Clear", command=self._clear).pack(side="left", padx=6)
        ttk.Label(top, text="Filter:").pack(side="left", padx=(12, 2))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(top, textvariable=self.filter_var, width=24).pack(side="left")

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6)
        # Only items that take part in a recipe are listed; the rest can't evolve anything.
        in_recipes = {i for e in db.evolutions for i in (e.result, *e.requires)}
        left = ttk.Notebook(body)
        body.add(left, weight=1)
        item_list = self._item_list(left, [
            ("Weapons", [i for i in db.weapons() if not i.evolved and i.id in in_recipes]),
            ("Passive Items", [i for i in db.passives() if i.id in in_recipes]),
            ("Evolved Weapons", [i for i in db.weapons() if i.evolved and i.id in in_recipes]),
        ])
        left.add(item_list, text="Items")
        left.add(self._settings_tab(left), text="Settings")

        results = ttk.Frame(body)
        self.output = tk.Text(results, wrap="word", state="disabled", font=("Segoe UI", 10), spacing1=2, spacing3=2)
        results_scroll = ttk.Scrollbar(results, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=results_scroll.set)
        results_scroll.pack(side="right", fill="y")
        self.output.pack(side="left", fill="both", expand=True)
        self.output.tag_configure("header", font=("Segoe UI", 11, "bold"), spacing1=10)
        self.output.tag_configure("have", foreground="#1b7f2a")
        self.output.tag_configure("missing", foreground="#c0392b", font=("Segoe UI", 10, "bold"))
        self.output.tag_configure("result", font=("Segoe UI", 10, "bold"))
        self.output.tag_configure("detail", foreground="#666666", lmargin1=70, lmargin2=70)
        self.output.tag_configure("ready", foreground="#ffffff", background="#1b7f2a", font=("Segoe UI", 9, "bold"))
        self.output.tag_configure("levelup", foreground="#ffffff", background="#d35400", font=("Segoe UI", 9, "bold"))
        self.output.tag_configure("level", foreground="#d35400", font=("Segoe UI", 9))
        self.output.tag_configure("maxed", foreground="#1b7f2a", font=("Segoe UI", 9, "bold"))
        body.add(results, weight=2)

        bar = ttk.Frame(root, relief="sunken")
        bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.status, anchor="w", padding=4).pack(side="left", fill="x", expand=True)
        self.icon_status = tk.StringVar(value=notice or "")
        ttk.Label(bar, textvariable=self.icon_status, anchor="e", padding=4).pack(side="right")

        self.checks: dict[str, gamedata.Check] = {}
        self.game_reader: GameReader | None = None
        self._load_icons()
        self._load_game_data()
        self.icon_thread = IconThread(db, game_map, self.icon_messages)
        self.icon_thread.start()
        WikiThread(db, self.icon_messages).start()

        self.reader_thread: ReaderThread | None = None
        if game_map is not None:
            self.game_reader = GameReader(db, game_map)
            self.reader_thread = ReaderThread(self.game_reader, self.results)
            self._load_game_data()  # teach the reader the game's own item names, if known
            self.reader_thread.start()
        else:
            self.auto_var.set(False)
            auto.state(["disabled"])
            self.status.set(f"Auto-detect unavailable: {map_error}")
        self._toggle_auto()
        self._apply_filter()
        self._refresh()
        root.after(200, self._drain_results)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _item_list(self, parent: tk.Widget, sections: list[tuple[str, list[Item]]]) -> ttk.Frame:
        """One scrollable list with a heading per section, in the order given."""
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(-ev.delta // 120, "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        row = 0
        for title, items in sections:
            ttk.Label(inner, text=title, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, sticky="w", padx=4, pady=(10 if row else 2, 2))
            row += 1
            for item in sorted(items, key=lambda i: i.name.lower()):
                var = tk.BooleanVar()
                label = item.name if item.dlc in ("Base game", "") else f"{item.name}  ({item.dlc})"
                cb = ttk.Checkbutton(inner, text=label, variable=var, command=self._refresh)
                cb.grid(row=row, column=0, sticky="w", padx=14, pady=1)
                row += 1
                self.vars[item.id] = var
                self.checkbuttons[item.id] = cb
        return outer

    def _settings_tab(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=8)
        group = ttk.LabelFrame(frame, text="Expansions", padding=8)
        group.pack(fill="x", anchor="n")
        ttk.Label(group, text="Untick an expansion to hide its items and evolutions.",
                  wraplength=280).pack(anchor="w", pady=(0, 6))
        for name in self.db.expansions():
            var = tk.BooleanVar(value=name not in self.settings.hidden_expansions)
            ttk.Checkbutton(group, text=name, variable=var, command=self._expansions_changed).pack(anchor="w")
            self.expansion_vars[name] = var
        buttons = ttk.Frame(group)
        buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(buttons, text="All on", command=lambda: self._set_all_expansions(True)).pack(side="left")
        ttk.Button(buttons, text="All off", command=lambda: self._set_all_expansions(False)).pack(side="left", padx=6)
        return frame

    def hidden_expansions(self) -> set[str]:
        return set(self.settings.hidden_expansions)

    def _set_all_expansions(self, on: bool) -> None:
        for var in self.expansion_vars.values():
            var.set(on)
        self._expansions_changed()

    def _expansions_changed(self) -> None:
        self.settings.hidden_expansions = [n for n, v in self.expansion_vars.items() if not v.get()]
        error = user_settings.save(self.settings)
        if error:
            self.icon_status.set(error)
        self._apply_filter()
        self._refresh()

    def _apply_filter(self) -> None:
        text = self.filter_var.get().lower()
        hidden = self.hidden_expansions()
        for item_id, cb in self.checkbuttons.items():
            item = self.db.items[item_id]
            visible = text in item.name.lower() and item.dlc not in hidden
            if visible:
                cb.grid()  # grid() restores the original row, so the order is kept
            else:
                cb.grid_remove()

    def owned(self) -> set[str]:
        if self.auto_var.get() and self.detected is not None:
            return set(self.detected.owned)  # includes items that aren't in any recipe
        return {i for i, v in self.vars.items() if v.get()}

    def level_of(self, item_id: str) -> tuple[int, int] | None:
        if self.auto_var.get() and self.detected is not None:
            return self.detected.level_of(item_id)
        return None

    def _needs_leveling(self, s: Suggestion) -> list[tuple[str, int, int]]:
        """Parts that must be max level but (according to the game) aren't yet."""
        out = []
        for item in s.evolution.max_level:
            lv = self.level_of(item)
            if lv and lv[0] < lv[1]:
                out.append((item, lv[0], lv[1]))
        return out

    def _load_icons(self) -> None:
        """Load cached pictures (if any) into the item list and results."""
        for item_id, path in icons.icon_paths(self.db.items).items():
            try:
                img = tk.PhotoImage(file=str(path))
            except tk.TclError:
                continue  # unreadable cache file; the item just shows without a picture
            self.icons[item_id] = img
            self.small_icons[item_id] = img.subsample(2)
        for item_id, cb in self.checkbuttons.items():
            if item_id in self.small_icons:
                cb.configure(image=self.small_icons[item_id], compound="left")

    def _load_game_data(self) -> None:
        """Use evolution data read from the game files: check recipes and learn internal item names."""
        data = gamedata.load(CACHE_ROOT)
        if data is None:
            return
        self.checks = gamedata.compare(self.db, data)
        if self.game_reader is not None:
            self.game_reader.matcher.add_aliases(gamedata.internal_to_item(self.db, data))

    def _insert_item(self, item_id: str, tag: str, show_level: bool = False) -> None:
        img = self.icons.get(item_id)
        if img is not None:
            self.output.image_create("end", image=img, padx=2, align="center")
        self.output.insert("end", self.db.name(item_id), tag)
        lv = self.level_of(item_id) if show_level else None
        if lv:
            self.output.insert("end", f" Lv {lv[0]}/{lv[1]}", "maxed" if lv[0] >= lv[1] else "level")

    def _details(self, s: Suggestion, skip_missing: bool = False) -> list[str]:
        evo = s.evolution
        details = []
        if s.missing and not skip_missing:
            details.append("need: " + ", ".join(self.db.name(m) for m in s.missing))
        leveling = self._needs_leveling(s)
        if leveling:
            details.append("level up first: " + ", ".join(f"{self.db.name(i)} {lv}/{mx}" for i, lv, mx in leveling))
        elif evo.max_level:
            details.append("max level: " + ", ".join(self.db.name(m) for m in evo.max_level))
        if evo.notes:
            details.append(evo.notes)
        if not evo.verified:
            details.append("unverified data - double-check in game")
        check = self.checks.get(evo.result)
        if check and check.status == "match":
            details.append("\u2713 matches game files")
        elif check:
            details.append("\u26a0 game files say: " + " + ".join(self.db.name(r) for r in check.game_requires))
        return details

    def _insert_suggestion(self, s: Suggestion) -> None:
        """One recipe line: weapon + item = evolution."""
        evo = s.evolution
        out = self.output
        out.insert("end", "  ")
        for i, req in enumerate(evo.requires):
            if i:
                out.insert("end", "   +   ")
            self._insert_item(req, "missing" if req in s.missing else "have")
        out.insert("end", "   =   ")
        self._insert_item(evo.result, "result")
        out.insert("end", "\n")
        details = self._details(s)
        if details:
            out.insert("end", "  |  ".join(details) + "\n", "detail")

    def _insert_plan(self, plan: ItemPlan, owned: set[str]) -> None:
        """A held item followed by each evolution it can make and what that still needs."""
        out = self.output
        out.insert("end", "  ")
        self._insert_item(plan.item, "result")
        out.insert("end", "\n")
        if not plan.options:
            text = "already evolved" if self.db.items[plan.item].evolved else "no evolution"
            out.insert("end", text + "\n", "detail")
            return
        for s in plan.options:
            out.insert("end", "        \u2192  ")
            self._insert_item(s.evolution.result, "result")
            others = [r for r in s.evolution.requires if r != plan.item]
            if others:
                out.insert("end", "    needs  ")
                for j, r in enumerate(others):
                    if j:
                        out.insert("end", ",  ")
                    have = r in owned
                    self._insert_item(r, "have" if have else "missing")
                    out.insert("end", " \u2713" if have else " \u2717", "have" if have else "missing")
            if not s.missing:
                if self._needs_leveling(s):
                    out.insert("end", "    LEVEL UP", "levelup")
                else:
                    out.insert("end", "    READY", "ready")
            out.insert("end", "\n")
            details = self._details(s, skip_missing=True)
            if details:
                out.insert("end", "  |  ".join(details) + "\n", "detail")

    def _refresh(self) -> None:
        owned = self.owned()
        hidden = self.hidden_expansions()
        out = self.output
        out.configure(state="normal")
        out.delete("1.0", "end")
        if not owned:
            out.insert("end", "Waiting for your items. Start a run with Auto-detect on, "
                              "or tick the items you're holding in the Items list.")
            out.configure(state="disabled")
            return

        out.insert("end", "YOU'RE HOLDING\n", "header")
        held = held_in_order(self.db, owned)
        for kind in ("weapon", "passive"):
            group = [i for i in held if self.db.items[i].kind == kind]
            if group:
                out.insert("end", "  ")
                for i, item in enumerate(group):
                    if i:
                        out.insert("end", "    ")
                    self._insert_item(item, "result", show_level=True)
                out.insert("end", "\n")

        ready = suggest(self.db, owned, hidden).ready
        if ready:
            out.insert("end", "READY TO EVOLVE - max the weapon, then open a chest\n", "header")
            for s in ready:
                self._insert_suggestion(s)

        out.insert("end", "HOW TO EVOLVE YOUR ITEMS\n", "header")
        for plan in plans_for_held(self.db, owned, hidden):
            self._insert_plan(plan, owned)
        out.configure(state="disabled")

    def _clear(self) -> None:
        for v in self.vars.values():
            v.set(False)
        self._refresh()

    def _toggle_auto(self) -> None:
        auto = self.auto_var.get() and self.reader_thread is not None
        for cb in self.checkbuttons.values():
            cb.state(["disabled"] if auto else ["!disabled"])
        if self.reader_thread is None:
            return
        if auto:
            self.reader_thread.enabled.set()
            self.status.set("Looking for Vampire Survivors...")
        else:
            self.reader_thread.enabled.clear()
            self.status.set("Manual mode: tick the items you have.")

    def _drain_results(self) -> None:
        while True:
            try:
                kind, message = self.icon_messages.get_nowait()
            except queue.Empty:
                break
            self.icon_status.set(message)
            if kind == "done":
                self._load_icons()
                self._load_game_data()
                self._refresh()
        latest = None
        while True:
            try:
                latest = self.results.get_nowait()
            except queue.Empty:
                break
        if latest is not None and self.auto_var.get():
            self.status.set(latest.message)
            if latest.state == "ok":
                changed = self.detected is None or (latest.owned, latest.levels) != (
                    self.detected.owned, self.detected.levels)
                self.detected = latest
                for item_id, var in self.vars.items():
                    var.set(item_id in latest.owned)
                if changed:
                    self._refresh()
        self.root.after(250, self._drain_results)

    def _close(self) -> None:
        if self.reader_thread:
            self.reader_thread.stopped.set()
        self.icon_thread.stopped.set()
        self.root.destroy()


def run(db: Database, game_map: GameMap | None, map_error: str | None = None, notice: str | None = None) -> None:
    root = tk.Tk()
    App(root, db, game_map, map_error, notice)
    root.mainloop()
