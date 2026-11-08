"""Tkinter window: tick items manually, or let the helper read them from the game."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import json
import time

import subprocess
import sys
import webbrowser

from . import game_launcher, gamedata, icons, lookups, updater
from . import settings as user_settings
from .data import CACHE_ROOT, CACHED_DB_PATH, Database, DatabaseError, Item, parse_database
from .evolutions import ItemPlan, Suggestion, held_in_order, plans_for_held, suggest
from .memory.game import GameMap, GameReader, ReadResult
from .memory.winapi import process_exe_path
from .widgets import FlowFrame

POLL_SECONDS = 1.0
GAME_SEARCH_SECONDS = 10.0
REEXTRACT_SECONDS = 600.0  # re-reading the game files is heavy: at most every 10 minutes


class IconThread(threading.Thread):
    """Extracts item pictures from the game files, waiting until the game folder is known.

    Keeps watching afterwards: when the game's item catalogue is read from memory during a run
    (it names the picture of every item, DLC included), pictures are extracted again.
    """

    def __init__(self, db: Database, game_map: GameMap | None, messages: "queue.Queue[tuple[str, str]]",
                 wiki_pictures=lambda: True):
        super().__init__(daemon=True)
        self.db = db
        self.map = game_map
        self.wiki_pictures = wiki_pictures  # read the setting each time (it can change while running)
        self.messages = messages
        self.stopped = threading.Event()
        self.wake = threading.Event()  # set when the catalogue was saved, to check right away

    def run(self) -> None:
        exe_name = self.map.process_name if self.map else "VampireSurvivors.exe"
        aliases = self.map.enum_aliases if self.map else {}
        announced = False
        last_extract = None
        while not self.stopped.is_set():
            exe = process_exe_path(exe_name)
            game_dir = icons.find_game_dir(Path(exe) if exe else None)
            recently = last_extract is not None and time.monotonic() - last_extract < REEXTRACT_SECONDS
            if game_dir is not None and not recently and icons.needs_extraction(game_dir):
                last_extract = time.monotonic()
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
            if self.wiki_pictures() and (game_dir is None or not icons.needs_extraction(game_dir)):
                self._fetch_from_wiki()
            if game_dir is None and not icons.read_manifest() and not icons.icon_paths(self.db.items) \
                    and not announced:
                self.messages.put(("status", "Item pictures: start the game once so the helper can find it."))
                announced = True
            self.wake.wait(GAME_SEARCH_SECONDS)
            self.wake.clear()

    def _fetch_from_wiki(self) -> None:
        """Download pictures the game files didn't give us (only asks about each item once a week)."""
        from .wiki import WikiError
        todo = icons.items_to_fetch_from_wiki(self.db)
        if not todo:
            return
        try:
            saved = icons.download_wiki_icons(self.db, todo, progress=lambda m: self.messages.put(("status", m)))
        except (WikiError, icons.IconError) as exc:
            self.messages.put(("status", f"Couldn't get pictures from the wiki: {exc}"))
            self.wiki_pictures = lambda: False  # don't retry every few seconds this session
            return
        have = len(icons.icon_paths(self.db.items))
        self.messages.put(("done", f"Item pictures: {have} of {len(self.db.items)} ({saved} new from the wiki)."))


class LookupThread(threading.Thread):
    """Looks items up on the wiki one at a time, off the UI thread."""

    def __init__(self, messages: "queue.Queue[tuple[str, object]]"):
        super().__init__(daemon=True)
        self.messages = messages
        self.todo: "queue.Queue[str]" = queue.Queue()

    def run(self) -> None:
        from .wiki import WikiError, lookup_item
        while True:
            name = self.todo.get()
            try:
                self.messages.put(("wiki-lookup", (name, lookup_item(name), None)))
            except WikiError as exc:
                self.messages.put(("wiki-lookup", (name, None, str(exc))))


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

# Colours for the two themes. Light keeps the native Windows look; dark uses ttk's "clam" theme,
# which (unlike the native one) lets every colour be changed.
PALETTES = {
    "light": {"bg": None, "panel": None, "fg": "#000000", "text_bg": "#ffffff", "muted": "#666666",
              "have": "#1b7f2a", "missing": "#c0392b", "level": "#d35400", "select": "#cce4f7",
              "border": "#a0a0a0", "card": "#f4f4f4", "planned": "#1e6fd9"},
    "dark": {"bg": "#1e1f22", "panel": "#2b2d31", "fg": "#e3e5e8", "text_bg": "#232428", "muted": "#9a9da3",
             "have": "#5fd068", "missing": "#ff6b6b", "level": "#ffa94d", "select": "#3d4250",
             "border": "#3f4147", "card": "#2b2d31", "planned": "#5aa9ff"},
}


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
        self.detected: ReadResult | None = None
        self.planned: set[str] = set()  # items ticked while auto-detect is on ("what if I had this")
        self.canvases: list[tk.Canvas] = []  # scrollable areas, coloured by the theme
        self.texts: list[tk.Text] = []  # result panes, coloured by the theme
        self.cards: dict[tk.Text, list[tk.Frame]] = {}  # item cards embedded in each pane  # latest auto-detect result (owned items and levels)
        self.icon_messages: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.icons: dict[str, tk.PhotoImage] = {}
        self.small_icons: dict[str, tk.PhotoImage] = {}
        self.settings, settings_warning = user_settings.load()
        self.expansion_vars: dict[str, tk.BooleanVar] = {}
        notice = notice or settings_warning

        root.title(f"Vampire Survivors Helper v{updater.local_version()}")
        self.native_theme = ttk.Style(root).theme_use()
        root.geometry("1000x620")
        root.minsize(480, 320)

        self.auto_var = tk.BooleanVar(value=game_map is not None and self.settings.auto_detect)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())

        # One row of tabs across the whole window.
        # Co-op: choose whose items Overview and How to evolve show (hidden when playing alone).
        self.player_var = tk.IntVar(value=0)
        # Bar above the tabs: co-op player switch (left) and the game launch button (right).
        # Co-op player switch: its own row above the tabs, shown only when there are 2+ players.
        self.top_bar = ttk.Frame(root, padding=(6, 4, 6, 0))
        self.player_bar = FlowFrame(self.top_bar)
        self.player_bar.pack(side="left", fill="x", expand=True)
        self._player_labels: tuple[str, ...] = ()
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        # The launch button sits in the tab row, on the right (placed over the notebook's empty
        # tab-row space instead of taking a row of its own).
        self.launch_button = ttk.Button(root, text="\u25b6 Launch Vampire Survivors", command=self._launch_game,
                                        style="TabRow.TButton")
        self.launch_button.place(in_=self.tabs, relx=1.0, x=0, y=0, anchor="ne")
        self.launch_button.lift()
        self.results_tabs = self.tabs  # Overview / How to evolve / All evolutions live here too
        # Overview: the item list on the left (hidden automatically while auto-detect is on),
        # your items and what's ready on the right.
        self.overview_paned = ttk.PanedWindow(self.tabs, orient="horizontal")
        overview_frame = self.overview_paned
        self.items_frame = ttk.Frame(self.overview_paned)
        overview_results, self.overview_text = self._text_pane(self.overview_paned)
        howto_frame, self.howto_text = self._text_pane(self.tabs)
        self.howto_frame = howto_frame
        guide_frame = ttk.Frame(self.tabs)
        search_bar = FlowFrame(guide_frame, padding=(4, 4))
        search_bar.pack(fill="x")
        search_bar.add(ttk.Label(search_bar, text="Search:"))
        self.guide_search = tk.StringVar()
        self.guide_search.trace_add("write", lambda *_: self._schedule_guide_refresh())
        search_bar.add(ttk.Entry(search_bar, textvariable=self.guide_search, width=30))
        search_bar.add(ttk.Label(search_bar, text="weapon, item, evolution or character name"))
        guide_body, self.guide_text = self._text_pane(guide_frame)
        guide_body.pack(fill="both", expand=True)
        self._guide_job: str | None = None

        # The item list (Clear + Filter on top). Only items that take part in a recipe are
        # listed; the rest can't evolve anything.
        in_recipes = {i for e in db.evolutions for i in (e.result, *e.requires)}
        list_bar = FlowFrame(self.items_frame, padding=(4, 4))
        list_bar.pack(fill="x")
        list_bar.add(ttk.Button(list_bar, text="Clear", command=self._clear))
        list_bar.add(ttk.Label(list_bar, text="Search:"), 8)
        list_bar.add(ttk.Entry(list_bar, textvariable=self.filter_var, width=24))
        list_bar.add(ttk.Label(list_bar, text="item or expansion name", style="Hint.TLabel"))
        item_list = self._item_list(self.items_frame, [
            ("Weapons", [i for i in db.weapons() if not i.evolved and i.id in in_recipes]),
            ("Passive Items", [i for i in db.passives() if i.id in in_recipes]),
            ("Evolved Weapons", [i for i in db.weapons() if i.evolved and i.id in in_recipes]),
        ])
        item_list.pack(fill="both", expand=True)
        self.overview_paned.add(self.items_frame, weight=1)
        self.overview_paned.add(overview_results, weight=2)
        self.settings_frame = self._settings_tab(self.tabs)

        self.tabs.add(overview_frame, text="Overview")
        self.tabs.add(howto_frame, text="How to evolve")
        self.tabs.add(guide_frame, text="All evolutions")
        self.tabs.add(self.settings_frame, text="Settings")
        body = self.tabs

        bar = FlowFrame(root, gap_x=16, gap_y=0, relief="sunken", padding=(4, 2))
        bar.pack(fill="x", side="bottom", before=body)  # packed first so it is never squeezed out
        self.status = tk.StringVar(value="")
        self.icon_status = tk.StringVar(value=notice or "")
        status_labels = [bar.add(ttk.Label(bar, textvariable=self.status, justify="left")),
                         bar.add(ttk.Label(bar, textvariable=self.icon_status, justify="left"))]

        def wrap_status(event: tk.Event) -> None:  # long messages wrap instead of being cut off
            for label in status_labels:
                label.configure(wraplength=max(event.width - 16, 100))
        bar.bind("<Configure>", wrap_status, add="+")

        self.checks: dict[str, gamedata.Check] = {}
        self.game_reader: GameReader | None = None
        self._load_icons()
        self._load_game_data()
        self.icon_thread = IconThread(db, game_map, self.icon_messages,
                                      wiki_pictures=lambda: self.settings.wiki_pictures)
        self.icon_thread.start()
        WikiThread(db, self.icon_messages).start()
        # Items without a known recipe are looked up on their wiki page (answers are cached).
        self.lookups = lookups.LookupCache(CACHE_ROOT)
        for entry in list(self.lookups.entries.values()):
            lookups.apply_to_db(db, entry)
        self._lookup_pending: set[str] = set()
        self._lookup_failed: set[str] = set()  # couldn't reach the wiki this session
        self.lookup_thread = LookupThread(self.icon_messages)
        self.lookup_thread.start()
        if self.settings.check_updates_on_start:
            self._check_updates(quiet=True)
        self._game_process = game_map.process_name if game_map else "VampireSurvivors.exe"
        if self.settings.launch_game_on_start and not game_launcher.is_running(self._game_process):
            self._launch_game()  # greys the button out while Steam starts the game
        else:
            self._update_launch_button()
        root.after(5000, self._watch_game)

        self.reader_thread: ReaderThread | None = None
        if game_map is not None:
            self.game_reader = GameReader(db, game_map, on_catalog=self._catalog_read)
            self.reader_thread = ReaderThread(self.game_reader, self.results)
            self._load_game_data()  # teach the reader the game's own item names, if known
            self.reader_thread.start()
        else:
            self.auto_var.set(False)
            self.auto_check.state(["disabled"])
            self.status.set(f"Auto-detect unavailable: {map_error}")
        self.apply_theme()
        self._toggle_auto(save=False)
        self._apply_filter()
        self._refresh()
        root.after(200, self._drain_results)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _scrollable(self, parent: tk.Widget, stretch: bool = False,
                    on_width=None) -> tuple[ttk.Frame, ttk.Frame]:
        """(outer, inner): put widgets in inner; outer scrolls them vertically with bar and mouse wheel.
        stretch=True makes inner as wide as the visible area; on_width(width) is called on resize."""
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0)
        self.canvases.append(canvas)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        def on_resize(event: tk.Event) -> None:
            if stretch:
                canvas.itemconfigure(window, width=event.width)
            if on_width:
                on_width(event.width)
        canvas.bind("<Configure>", on_resize)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(-ev.delta // 120, "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return outer, inner

    def _item_list(self, parent: tk.Widget, sections: list[tuple[str, list[Item]]]) -> ttk.Frame:
        """One scrollable list with a heading per section, in the order given."""
        outer, inner = self._scrollable(parent, stretch=True, on_width=self._list_width_changed)
        row = 0
        for title, items in sections:
            ttk.Label(inner, text=title, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, sticky="w", padx=4, pady=(10 if row else 2, 2))
            row += 1
            for item in sorted(items, key=lambda i: i.name.lower()):
                var = tk.BooleanVar()
                label = item.name if item.dlc in ("Base game", "") else f"{item.name}  ({item.dlc})"
                cb = ttk.Checkbutton(inner, text=label, variable=var, style="List.TCheckbutton",
                                     command=lambda i=item.id: self._item_clicked(i))
                cb.grid(row=row, column=0, sticky="w", padx=14, pady=1)
                row += 1
                self.vars[item.id] = var
                self.checkbuttons[item.id] = cb
        return outer

    def _settings_tab(self, parent: tk.Widget) -> ttk.Frame:
        outer, frame = self._scrollable(parent, stretch=True, on_width=self._settings_width_changed)
        frame.configure(padding=8)
        game = ttk.LabelFrame(frame, text="Game", padding=8)
        game.pack(fill="x", anchor="n", pady=(0, 8))
        self.launch_on_start_var = tk.BooleanVar(value=self.settings.launch_game_on_start)
        ttk.Checkbutton(game, text="Start Vampire Survivors when the helper opens", variable=self.launch_on_start_var,
                        command=self._launch_on_start_changed, style="Setting.TCheckbutton").pack(anchor="w")
        ttk.Button(game, text="\u25b6 Launch Vampire Survivors now", command=self._launch_game).pack(anchor="w", pady=(6, 0))

        detection = ttk.LabelFrame(frame, text="Detection", padding=8)
        detection.pack(fill="x", anchor="n", pady=(0, 8))
        self.auto_check = ttk.Checkbutton(detection, text="Auto-detect items from the game", variable=self.auto_var,
                                          command=self._toggle_auto, style="Setting.TCheckbutton")
        self.auto_check.pack(anchor="w")
        self.wiki_lookup_var = tk.BooleanVar(value=self.settings.wiki_lookup)
        ttk.Checkbutton(detection, text="Look up items without a known recipe on the wiki", variable=self.wiki_lookup_var,
                        command=self._wiki_lookup_changed, style="Setting.TCheckbutton").pack(anchor="w")
        self.wiki_pictures_var = tk.BooleanVar(value=self.settings.wiki_pictures)
        ttk.Checkbutton(detection, text="Download missing item pictures from the wiki", variable=self.wiki_pictures_var,
                        command=self._wiki_pictures_changed, style="Setting.TCheckbutton").pack(anchor="w")
        self.hide_items_var = tk.BooleanVar(value=self.settings.hide_items_when_auto)
        ttk.Checkbutton(detection, text="Hide the item list while auto-detect is on", variable=self.hide_items_var,
                        command=self._hide_items_changed, style="Setting.TCheckbutton").pack(anchor="w")
        ttk.Label(detection, text="Item list (Overview tab): with auto-detect on, tick items you don't have "
                             "to plan ahead - they show as planned (blue) with what else you'd need. "
                             "With auto-detect off, tick what you're holding.",
                  wraplength=280, style="Wrap.TLabel").pack(anchor="w", pady=(4, 0))

        appearance = ttk.LabelFrame(frame, text="Appearance", padding=8)
        appearance.pack(fill="x", anchor="n", pady=(0, 8))
        self.dark_var = tk.BooleanVar(value=self.settings.dark_theme)
        ttk.Checkbutton(appearance, text="Dark theme", variable=self.dark_var, style="Setting.TCheckbutton",
                        command=self._theme_changed).pack(anchor="w")

        updates = ttk.LabelFrame(frame, text="Updates", padding=8)
        updates.pack(fill="x", anchor="n", pady=(0, 8))
        self.version_label = ttk.Label(updates, text=f"Installed version: {updater.local_version()}",
                                       wraplength=280, style="Wrap.TLabel")
        self.version_label.pack(anchor="w")
        self.update_on_start_var = tk.BooleanVar(value=self.settings.check_updates_on_start)
        ttk.Checkbutton(updates, text="Check for updates when the helper starts", variable=self.update_on_start_var,
                        style="Setting.TCheckbutton",
                        command=self._update_on_start_changed).pack(anchor="w", pady=(4, 0))
        buttons = FlowFrame(updates)
        buttons.pack(fill="x", pady=(6, 0))
        self.check_button = buttons.add(ttk.Button(buttons, text="Check for updates", command=self._check_updates))
        self.update_button = ttk.Button(buttons, text="Update now", command=self._apply_update, state="disabled")
        buttons.add(self.update_button)
        self.restart_button = ttk.Button(buttons, text="Restart helper", command=self._restart)
        self.update_buttons = buttons
        self.update_status = tk.StringVar(value="")
        ttk.Label(updates, textvariable=self.update_status, wraplength=280, justify="left", style="Wrap.TLabel").pack(anchor="w", pady=(6, 0))
        self.web_button = ttk.Button(updates, text="Open GitHub page", command=lambda: webbrowser.open(updater.REPO_URL))

        main = ttk.LabelFrame(frame, text="Main screen", padding=8)
        main.pack(fill="x", anchor="n", pady=(0, 8))
        ttk.Label(main, text="Choose what the results pane shows.", wraplength=280, style="Wrap.TLabel").pack(anchor="w", pady=(0, 6))
        self.show_vars: dict[str, tk.BooleanVar] = {}
        for key, label in user_settings.MAIN_SCREEN_OPTIONS:
            var = tk.BooleanVar(value=getattr(self.settings, key))
            ttk.Checkbutton(main, text=label, variable=var, command=self._main_screen_changed,
                            style="Setting.TCheckbutton").pack(anchor="w")
            self.show_vars[key] = var
        group = ttk.LabelFrame(frame, text="Expansions", padding=8)
        group.pack(fill="x", anchor="n")
        ttk.Label(group, text="Untick an expansion to hide its items and evolutions.",
                  wraplength=280, style="Wrap.TLabel").pack(anchor="w", pady=(0, 6))
        for name in self.db.expansions():
            var = tk.BooleanVar(value=name not in self.settings.hidden_expansions)
            ttk.Checkbutton(group, text=name, variable=var, command=self._expansions_changed,
                            style="Setting.TCheckbutton").pack(anchor="w")
            self.expansion_vars[name] = var
        buttons = FlowFrame(group)
        buttons.pack(fill="x", pady=(6, 0))
        buttons.add(ttk.Button(buttons, text="All on", command=lambda: self._set_all_expansions(True)))
        buttons.add(ttk.Button(buttons, text="All off", command=lambda: self._set_all_expansions(False)))

        trouble = ttk.LabelFrame(frame, text="Troubleshooting", padding=8)
        trouble.pack(fill="x", anchor="n", pady=(8, 0))
        ttk.Label(trouble, text="If your items aren't detected: start a run in the game, pause it, then create a "
                                "report and send the file it saves on your Desktop.", wraplength=280, justify="left", style="Wrap.TLabel").pack(anchor="w")
        self.report_button = ttk.Button(trouble, text="Create diagnose report", command=self._create_report)
        self.report_button.pack(anchor="w", pady=(6, 0))
        self.report_status = tk.StringVar(value="")
        ttk.Label(trouble, textvariable=self.report_status, wraplength=280, justify="left", style="Wrap.TLabel").pack(anchor="w", pady=(6, 0))
        return outer

    # ---- keep text readable when panels are narrow ----
    def _list_width_changed(self, width: int) -> None:
        self._list_wrap = max(width - 60, 80)  # room for the checkbox and picture
        ttk.Style(self.root).configure("List.TCheckbutton", wraplength=self._list_wrap)

    def _settings_width_changed(self, width: int) -> None:
        self._settings_wrap = max(width - 60, 80)
        style = ttk.Style(self.root)
        style.configure("Setting.TCheckbutton", wraplength=self._settings_wrap)
        for label in self._wrap_labels():
            label.configure(wraplength=self._settings_wrap)

    def _wrap_labels(self) -> list[tk.Widget]:
        """Settings labels that should wrap to the panel width (marked with style Wrap.TLabel)."""
        found, stack = [], [self.settings_frame]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if isinstance(w, ttk.Label) and str(w.cget("style")) == "Wrap.TLabel":
                found.append(w)
        return found

    def _reapply_wrapping(self) -> None:
        """Theme changes reset style options, so restore the current wrap widths."""
        style = ttk.Style(self.root)
        style.configure("List.TCheckbutton", wraplength=getattr(self, "_list_wrap", 260))
        style.configure("Setting.TCheckbutton", wraplength=getattr(self, "_settings_wrap", 260))

    # ---- wiki lookups for items without a known recipe ----
    @staticmethod
    def _wiki_url(name: str) -> str:
        from .wiki import PAGE_URL
        return PAGE_URL + name.replace(" ", "_")

    def _insert_link(self, out: tk.Text, text: str, url: str) -> None:
        tag = f"link{len(out.tag_names())}"
        pal = PALETTES["dark" if self.settings.dark_theme else "light"]
        out.tag_configure(tag, foreground=pal["planned"], underline=True)
        out.tag_bind(tag, "<Button-1>", lambda e: webbrowser.open(url))
        out.tag_bind(tag, "<Enter>", lambda e: out.configure(cursor="hand2"))
        out.tag_bind(tag, "<Leave>", lambda e: out.configure(cursor=""))
        out.insert("end", text, tag)

    def _queue_lookups(self, owned: set[str], hidden: set[str]) -> None:
        """Ask the wiki about held/planned items that have no recipe, and unrecognised items."""
        if not self.settings.wiki_lookup:
            return
        names = [self.db.name(p.item) for p in plans_for_held(self.db, owned, hidden) if not p.options]
        if self.auto_on() and self.detected is not None:
            names += [n for n in self.detected.unrecognized if not n.startswith("#")]
        for name in names:
            if name in self._lookup_pending or name in self._lookup_failed or self.lookups.is_fresh(name):
                continue
            self._lookup_pending.add(name)
            self.lookup_thread.todo.put(name)

    def _lookup_finished(self, name: str, lookup, error: str | None) -> None:
        self._lookup_pending.discard(name)
        if error:
            self._lookup_failed.add(name)
            self.icon_status.set(f"Couldn't look up {name} on the wiki: {error}")
        else:
            entry = self.lookups.put(name, lookup)
            added = lookups.apply_to_db(self.db, entry)
            if self.game_reader is not None:
                self.game_reader.matcher.refresh()  # items new to the helper can now be recognised
            if added:
                self.icon_status.set(f"Found {added} recipe(s) for {name} on the wiki.")
                self.icon_thread.wake.set()  # new items may need pictures
        self._refresh()

    def _wiki_pictures_changed(self) -> None:
        self.settings.wiki_pictures = self.wiki_pictures_var.get()
        self._save_settings()
        if self.settings.wiki_pictures:
            self.icon_thread.wake.set()

    def _wiki_lookup_changed(self) -> None:
        self.settings.wiki_lookup = self.wiki_lookup_var.get()
        self._save_settings()
        self._refresh()

    # ---- item list visibility (left side of Overview) ----
    def _hide_items_changed(self) -> None:
        self.settings.hide_items_when_auto = self.hide_items_var.get()
        self._save_settings()
        self._update_items_tab()

    def _update_items_tab(self) -> None:
        """Hide the item list on Overview while auto-detect reads the game (if that setting is on)."""
        hide = self.auto_var.get() and self.reader_thread is not None and self.settings.hide_items_when_auto
        shown = str(self.items_frame) in self.overview_paned.panes()
        if hide and shown:
            self.overview_paned.forget(self.items_frame)
        elif not hide and not shown:
            self.overview_paned.insert(0, self.items_frame, weight=1)

    def _save_settings(self) -> None:
        error = user_settings.save(self.settings)
        if error:
            self.icon_status.set(error)

    # ---- diagnose report ----
    def _create_report(self) -> None:
        from . import diagnose
        self.report_button.state(["disabled"])
        self.report_status.set("Collecting information - this can take a minute or two...")

        def work() -> None:
            try:
                path = diagnose.report_path()
                diagnose.run(path)
                self.icon_messages.put(("report-done", str(path)))
            except Exception as exc:  # show any failure instead of losing it in a background thread
                self.icon_messages.put(("report-error", f"The report couldn't be created: {exc!r}"))
        threading.Thread(target=work, daemon=True).start()

    def _report_message(self, kind: str, message: str) -> None:
        self.report_button.state(["!disabled"])
        if kind == "report-error":
            self.report_status.set(message)
            return
        self.report_status.set(f"Report saved on your Desktop: {message}")

    # ---- launching the game ----
    def _launch_game(self) -> None:
        error = game_launcher.launch()
        if error:
            self.icon_status.set(error)
        else:
            self.status.set("Starting Vampire Survivors through Steam...")
            self.launch_button.state(["disabled"])
            self.root.after(15000, self._update_launch_button)  # re-enable if it didn't start

    def _watch_game(self) -> None:
        """Without auto-detect nothing reports on the game, so check now and then for the button."""
        if not self.auto_on():
            self._update_launch_button()
        self.root.after(5000, self._watch_game)

    def _launch_on_start_changed(self) -> None:
        self.settings.launch_game_on_start = self.launch_on_start_var.get()
        self._save_settings()

    def _update_launch_button(self, running: bool | None = None) -> None:
        """Grey the button out while the game is running (known from auto-detect, else checked)."""
        if running is None:
            running = game_launcher.is_running(self._game_process)
        self.launch_button.configure(text="Game running" if running else "\u25b6 Launch Vampire Survivors")
        self.launch_button.state(["disabled"] if running else ["!disabled"])

    # ---- updates ----
    def _update_on_start_changed(self) -> None:
        self.settings.check_updates_on_start = self.update_on_start_var.get()
        error = user_settings.save(self.settings)
        if error:
            self.icon_status.set(error)

    def _in_background(self, kind: str, work) -> None:
        """Run git work off the UI thread; the result arrives in _drain_results."""
        def run() -> None:
            try:
                self.icon_messages.put((kind, work()))
            except updater.UpdateError as exc:
                self.icon_messages.put(("update-error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def _check_updates(self, quiet: bool = False) -> None:
        self.check_button.state(["disabled"])
        self.update_status.set("Checking GitHub for updates...")
        self._quiet_check = quiet
        self._in_background("update-check", updater.check)

    def _apply_update(self) -> None:
        self.update_button.state(["disabled"])
        self.check_button.state(["disabled"])
        self.update_status.set("Downloading and installing the update...")
        self._in_background("update-done", updater.apply)

    def _update_message(self, kind: str, message) -> None:
        self.check_button.state(["!disabled"])
        if kind == "update-error":
            self.update_status.set(message)
            if updater.FROZEN or not updater.is_git_checkout():
                self.web_button.configure(text="Open download page", command=lambda: webbrowser.open(
                    updater.DOWNLOAD_URL if updater.FROZEN else updater.REPO_URL))
                self.web_button.pack(anchor="w", pady=(6, 0))
            if not getattr(self, "_quiet_check", False):
                self.icon_status.set("Update failed - see Settings > Updates.")
            return
        if kind == "update-check":
            info: updater.UpdateInfo = message
            if info.available:
                latest = info.latest or "a newer version"
                changes = "\n".join(f"\u2022 {c}" for c in info.changes[:8])
                more = f"\n... and {len(info.changes) - 8} more" if len(info.changes) > 8 else ""
                self.update_status.set(f"Update available: {info.current} \u2192 {latest}\n{changes}{more}")
                self.update_button.state(["!disabled"])
                self.icon_status.set(f"Update available ({latest}) - Settings > Updates.")
            else:
                self.update_status.set(f"You have the latest version ({info.current}).")
                self.update_button.state(["disabled"])
            return
        # update-done
        self.update_status.set(message)
        self.version_label.configure(text=f"Installed version: {updater.local_version()}")
        if "Restart" in message:
            if not self.update_buttons.contains(self.restart_button):
                self.update_buttons.add(self.restart_button)
            self.icon_status.set("Update installed - restart the helper to use it.")

    def _restart(self) -> None:
        command, folder = updater.restart_command()
        try:
            subprocess.Popen(command, cwd=folder)
        except OSError as exc:
            self.update_status.set(f"Couldn't restart automatically ({exc}). Close and reopen the helper.")
            return
        self._close()

    def _main_screen_changed(self) -> None:
        for key, var in self.show_vars.items():
            setattr(self.settings, key, var.get())
        error = user_settings.save(self.settings)
        if error:
            self.icon_status.set(error)
        self._apply_list_pictures()
        self._refresh()

    def _theme_changed(self) -> None:
        self.settings.dark_theme = self.dark_var.get()
        error = user_settings.save(self.settings)
        if error:
            self.icon_status.set(error)
        self.apply_theme()
        self._refresh()  # item cards are drawn with the theme's colours

    def apply_theme(self) -> None:
        """Colour every widget for the light or dark theme (instant, no restart needed)."""
        dark = self.settings.dark_theme
        pal = PALETTES["dark" if dark else "light"]
        style = ttk.Style(self.root)
        if dark:
            style.theme_use("clam")
            bg, panel, fg = pal["bg"], pal["panel"], pal["fg"]
            style.configure(".", background=bg, foreground=fg, fieldbackground=panel, bordercolor=pal["border"],
                            darkcolor=bg, lightcolor=panel, troughcolor=bg, selectbackground=pal["select"],
                            selectforeground=fg, insertcolor=fg, focuscolor=pal["select"])
            style.configure("TNotebook", background=bg, bordercolor=pal["border"])
            style.configure("TNotebook.Tab", background=panel, foreground=pal["muted"], padding=(10, 4))
            style.map("TNotebook.Tab", background=[("selected", bg)], foreground=[("selected", fg)])
            style.configure("TButton", background=panel, foreground=fg, padding=(10, 3))
            style.map("TButton", background=[("active", pal["select"]), ("pressed", pal["select"])])
            style.configure("TCheckbutton", background=bg, foreground=fg, indicatorbackground=panel,
                            indicatorforeground=fg)
            style.map("TCheckbutton", background=[("active", bg)],
                      indicatorbackground=[("selected", pal["have"]), ("disabled", bg)],
                      foreground=[("disabled", pal["muted"])])
            style.configure("TEntry", fieldbackground=panel, foreground=fg, insertcolor=fg)
            style.configure("TLabelframe", background=bg, bordercolor=pal["border"])
            style.configure("TLabelframe.Label", background=bg, foreground=fg)
            style.configure("TScrollbar", background=panel, troughcolor=bg, arrowcolor=fg, bordercolor=bg)
            style.map("TScrollbar", background=[("active", pal["select"])])
            style.configure("TPanedwindow", background=bg)
            self.root.configure(background=bg)
        else:
            style.theme_use(self.native_theme)
            self.root.configure(background=style.lookup("TFrame", "background") or "SystemButtonFace")
        self._reapply_wrapping()
        style.configure("TabRow.TButton", padding=(10, 1))  # as tall as a tab
        canvas_bg = pal["bg"] or style.lookup("TFrame", "background") or "SystemButtonFace"
        for canvas in self.canvases:
            canvas.configure(background=canvas_bg)
        for text in self.texts:
            text.configure(background=pal["text_bg"], foreground=pal["fg"], insertbackground=pal["fg"],
                           selectbackground=pal["select"])
            text.tag_configure("have", foreground=pal["have"])
            text.tag_configure("missing", foreground=pal["missing"])
            text.tag_configure("detail", foreground=pal["muted"])
            text.tag_configure("carddetail", foreground=pal["muted"])
            text.tag_configure("characters", foreground=pal["planned"])
            text.tag_configure("level", foreground=pal["level"])
            text.tag_configure("maxed", foreground=pal["have"])
            text.tag_configure("subheader", foreground=pal["muted"])

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
            visible = (text in item.name.lower() or text in item.dlc.lower()) and item.dlc not in hidden
            if visible:
                cb.grid()  # grid() restores the original row, so the order is kept
            else:
                cb.grid_remove()

    def auto_on(self) -> bool:
        return self.auto_var.get() and self.reader_thread is not None

    def selected_player(self):
        """The co-op player picked in the player bar (None = player 1 / single player)."""
        index = self.player_var.get()
        if index and self.auto_on() and self.detected is not None and index < len(self.detected.players):
            return self.detected.players[index]
        return None

    def owned(self) -> set[str]:
        """Items to plan with: detected items (if auto-detect is on) plus anything ticked."""
        friend = self.selected_player()
        if friend is not None:
            return set(friend.owned)  # another player's items (planning applies to player 1)
        if self.auto_on():
            detected = set(self.detected.owned) if self.detected is not None else set()
            return detected | self.planned  # detected includes items that aren't in any recipe
        return {i for i, v in self.vars.items() if v.get()}

    def is_planned(self, item_id: str) -> bool:
        """Ticked by hand while auto-detect is on, i.e. not actually held."""
        return self.auto_on() and self.selected_player() is None and item_id in self.planned

    def _item_clicked(self, item_id: str) -> None:
        if self.auto_on():
            detected = self.detected.owned if self.detected is not None else frozenset()
            if item_id in detected:
                self.vars[item_id].set(True)  # really held: stays ticked
                return
            if self.vars[item_id].get():
                self.planned.add(item_id)
            else:
                self.planned.discard(item_id)
        self._refresh()

    def level_of(self, item_id: str) -> tuple[int, int] | None:
        if not self.settings.show_levels:
            return None  # also hides LEVEL UP and "level up first"
        friend = self.selected_player()
        if friend is not None:
            return friend.level_of(item_id)
        if self.auto_var.get() and self.detected is not None:
            return self.detected.level_of(item_id)
        return None

    def _update_player_bar(self) -> None:
        """Show Player 1 | Player 2 ... when more than one player is in the game."""
        players = self.detected.players if self.auto_on() and self.detected is not None else ()
        labels = tuple(p.label + (" - you" if p.index == 0 else "") for p in players)
        if labels == self._player_labels:
            return
        self._player_labels = labels
        for child in self.player_bar.winfo_children():
            child.destroy()
        self.player_bar._items.clear()
        if len(labels) < 2:
            self.player_var.set(0)
            self.top_bar.pack_forget()
            return
        if self.player_var.get() >= len(labels):
            self.player_var.set(0)
        self.player_bar.add(ttk.Label(self.player_bar, text="Show items of:"))
        for i, label in enumerate(labels):
            self.player_bar.add(ttk.Radiobutton(self.player_bar, text=label, value=i, variable=self.player_var,
                                                style="Toolbutton", command=self._refresh))
        self.top_bar.pack(fill="x", before=self.tabs)

    def holder_title(self) -> str:
        friend = self.selected_player()
        return f"{friend.label.upper()} IS HOLDING" if friend else "YOU'RE HOLDING"

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
        self._apply_list_pictures()

    def _apply_list_pictures(self) -> None:
        for item_id, cb in self.checkbuttons.items():
            if self.settings.show_pictures and item_id in self.small_icons:
                cb.configure(image=self.small_icons[item_id], compound="left")
            else:
                cb.configure(image="", compound="none")

    def _catalog_read(self, catalog: dict) -> None:
        """Runs on the reader thread: save the game's item catalogue, then let the picture
        thread fetch any pictures it makes findable."""
        before = len(gamedata.load_catalog(CACHE_ROOT))
        if gamedata.save_catalog(catalog, CACHE_ROOT) > before:
            self.icon_thread.wake.set()

    def _load_game_data(self) -> None:
        """Use evolution data read from the game files: check recipes and learn internal item names."""
        data = gamedata.load(CACHE_ROOT)
        if data is None:
            return
        self.checks = gamedata.compare(self.db, data)
        if self.game_reader is not None:
            self.game_reader.matcher.add_aliases(gamedata.internal_to_item(self.db, data))

    def _insert_item(self, out: tk.Text, item_id: str, tag: str, show_level: bool = False) -> None:
        img = self.icons.get(item_id) if self.settings.show_pictures else None
        if img is not None:
            out.image_create("end", image=img, padx=2, align="center")
        out.insert("end", self.db.name(item_id), tag)
        lv = self.level_of(item_id) if show_level else None
        if lv:
            out.insert("end", f" Lv {lv[0]}/{lv[1]}", "maxed" if lv[0] >= lv[1] else "level")

    def _details(self, s: Suggestion, skip_missing: bool = False) -> list[str]:
        evo = s.evolution
        details = []
        show = self.settings.show_details
        if s.missing and not skip_missing and show:
            details.append("need: " + ", ".join(self.db.name(m) for m in s.missing))
        leveling = self._needs_leveling(s)
        if leveling:
            details.append("level up first: " + ", ".join(f"{self.db.name(i)} {lv}/{mx}" for i, lv, mx in leveling))
        elif evo.max_level and show:
            details.append("max level: " + ", ".join(self.db.name(m) for m in evo.max_level))
        if evo.notes and show:
            details.append(evo.notes)
        if not evo.verified and show:
            details.append("unverified data - double-check in game")
        check = self.checks.get(evo.result) if self.settings.show_game_check else None
        if check and check.status == "match":
            details.append("\u2713 matches game files")
        elif check:
            details.append("\u26a0 game files say: " + " + ".join(self.db.name(r) for r in check.game_requires))
        return details

    def _insert_suggestion(self, out: tk.Text, s: Suggestion, plain_missing: bool = False,
                           characters: bool = False) -> None:
        """One recipe line: weapon + item = evolution. plain_missing: don't colour unowned parts red.
        characters: add who starts with the recipe's weapons."""
        evo = s.evolution
        out.insert("end", "  ")
        for i, req in enumerate(evo.requires):
            if i:
                out.insert("end", "   +   ")
            missing_tag = "plain" if plain_missing else "missing"
            self._insert_item(out, req, missing_tag if req in s.missing else "have")
        out.insert("end", "   =   ")
        self._insert_item(out, evo.result, "result")
        out.insert("end", "\n")
        details = self._details(s, skip_missing=plain_missing)
        if details:
            out.insert("end", "  |  ".join(details) + "\n", "detail")
        if characters:
            starters = self._starters(evo)
            if starters:
                out.insert("end", "Starting weapon of \u2014 " + "  |  ".join(starters) + "\n", "characters")

    def _starters(self, evo) -> list[str]:
        """'Keremet Bubbles: Rinaldo Gandolfi' for each part some character starts with."""
        out = []
        for req in evo.requires:
            chars = self.db.items[req].characters if req in self.db.items else ()
            if chars:
                out.append(f"{self.db.name(req)}: {', '.join(chars)}")
        return out

    def _insert_plan(self, out: tk.Text, plan: ItemPlan, owned: set[str]) -> None:
        """A held item card, then for each evolution: result card, the parts it needs, and its status."""
        self._card(out, plan.item, "held")
        out.insert("end", "\n")
        if not plan.options:
            name = self.db.name(plan.item)
            entry = self.lookups.get(name)
            if name in self._lookup_pending:
                out.insert("end", "No recipe known - searching the wiki...\n", "carddetail")
            elif entry is not None:
                text = "already evolved" if self.db.items[plan.item].evolved else "No evolution found on the wiki"
                out.insert("end", text + "  ", "carddetail")
                self._insert_link(out, "Open wiki page", entry.get("url") or self._wiki_url(name))
                out.insert("end", "\n")
            else:
                text = "already evolved" if self.db.items[plan.item].evolved else "no evolution"
                out.insert("end", text + "\n", "carddetail")
            return
        for s in plan.options:
            out.insert("end", "      \u2192  ", "result")
            self._card(out, s.evolution.result, "result")
            others = [r for r in s.evolution.requires if r != plan.item]
            if others:
                out.insert("end", "  needs  ", "result")
                for r in others:
                    self._card(out, r, "have" if r in owned else "missing",
                               needs_max=r in s.evolution.max_level)
            if not s.missing:
                if any(self.is_planned(r) for r in s.evolution.requires):
                    pal = PALETTES["dark" if self.settings.dark_theme else "light"]
                    self._badge(out, "PLANNED", pal["planned"])
                elif self._needs_leveling(s):
                    self._badge(out, "LEVEL UP", "#d35400")
                else:
                    self._badge(out, "READY", "#1b7f2a")
            out.insert("end", "\n")
            details = self._details(s, skip_missing=True)
            if details:
                out.insert("end", "  |  ".join(details) + "\n", "carddetail")

    def _text_pane(self, parent: tk.Widget) -> tuple[ttk.Frame, tk.Text]:
        """A read-only, scrollable rich-text pane for results."""
        frame = ttk.Frame(parent)
        text = tk.Text(frame, wrap="word", state="disabled", font=("Segoe UI", 10), spacing1=2, spacing3=2,
                       borderwidth=0, highlightthickness=0, padx=4, pady=4)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("header", font=("Segoe UI", 11, "bold"), spacing1=10)
        text.tag_configure("subheader", font=("Segoe UI", 10, "bold"), spacing1=8)
        text.tag_configure("missing", font=("Segoe UI", 10, "bold"))
        text.tag_configure("result", font=("Segoe UI", 10, "bold"))
        text.tag_configure("detail", lmargin1=70, lmargin2=70)
        text.tag_configure("carddetail", lmargin1=40, lmargin2=40, spacing3=8)
        text.tag_configure("characters", lmargin1=70, lmargin2=70, font=("Segoe UI", 9, "italic"))
        text.tag_configure("ready", foreground="#ffffff", background="#1b7f2a", font=("Segoe UI", 9, "bold"))
        text.tag_configure("levelup", foreground="#ffffff", background="#d35400", font=("Segoe UI", 9, "bold"))
        text.tag_configure("level", font=("Segoe UI", 9))
        text.tag_configure("maxed", font=("Segoe UI", 9, "bold"))
        self.texts.append(text)
        return frame, text

    def _begin(self, out: tk.Text) -> tk.Text:
        out.configure(state="normal")
        out.delete("1.0", "end")
        for card in self.cards.pop(out, []):  # embedded cards aren't destroyed by delete()
            card.destroy()
        return out

    # ---- item cards: picture top-left, level top-right, name along the bottom ----
    CARD_WIDTH = 132
    CARD_HEIGHT = 76

    def _card(self, out: tk.Text, item_id: str, state: str = "plain", needs_max: bool = False) -> None:
        """Insert an item card. state: held (shows level), have (owned: level or check mark),
        missing (red border, 'need'), result (an evolution) or plain. Items ticked as planned
        while auto-detect is on get a blue border and 'planned'. needs_max: this recipe needs the
        item at max level - if it isn't yet, the card gets an orange border."""
        pal = PALETTES["dark" if self.settings.dark_theme else "light"]
        if state in ("held", "have") and self.is_planned(item_id):
            state = "planned"
        lv = self.level_of(item_id) if state in ("held", "have") else None
        border = {"held": pal["border"], "have": pal["have"], "missing": pal["missing"],
                  "planned": pal["planned"]}.get(state, pal["border"])
        if state == "have" and needs_max and lv and lv[0] < lv[1]:
            border = pal["level"]  # have it, but it still needs levelling for this recipe
        card = tk.Frame(out, width=self.CARD_WIDTH, height=self.CARD_HEIGHT, background=pal["card"],
                        highlightthickness=2, highlightbackground=border, highlightcolor=border)
        card.grid_propagate(False)
        card.columnconfigure(1, weight=1)
        card.rowconfigure(1, weight=1)
        img = self.icons.get(item_id) if self.settings.show_pictures else None
        icon = tk.Label(card, image=img, background=pal["card"]) if img else \
            tk.Frame(card, width=32, height=32, background=pal["card"])
        icon.grid(row=0, column=0, sticky="nw", padx=(4, 0), pady=(4, 0))

        level_text, level_color = "", pal["muted"]
        if lv:
            level_text = f"Lv {lv[0]}/{lv[1]}"
            level_color = pal["have"] if lv[0] >= lv[1] else pal["level"]
            if state == "have" and not needs_max:
                level_color = pal["muted"]  # this recipe doesn't need it maxed: level is just info
        elif state == "have":
            level_text, level_color = "\u2713 have", pal["have"]
        elif state == "missing":
            level_text, level_color = "\u2717 need", pal["missing"]
        elif state == "planned":
            level_text, level_color = "\u2605 planned", pal["planned"]
        tk.Label(card, text=level_text, background=pal["card"], foreground=level_color,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="ne", padx=(0, 6), pady=(4, 0))

        name_color = pal["missing"] if state == "missing" else pal["fg"]
        tk.Label(card, text=self.db.name(item_id), background=pal["card"], foreground=name_color,
                 font=("Segoe UI", 9, "bold"), wraplength=self.CARD_WIDTH - 12, justify="left",
                 anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 4))

        def scroll(event: tk.Event) -> str:  # keep the mouse wheel working over cards
            out.yview_scroll(-event.delta // 120, "units")
            return "break"
        for widget in (card, *card.winfo_children()):
            widget.bind("<MouseWheel>", scroll)
        out.window_create("end", window=card, padx=3, pady=3, align="center")
        self.cards.setdefault(out, []).append(card)

    def _badge(self, out: tk.Text, text: str, color: str) -> None:
        """A small coloured status label (READY / LEVEL UP) next to the cards."""
        badge = tk.Label(out, text=text, background=color, foreground="#ffffff",
                         font=("Segoe UI", 9, "bold"), padx=8, pady=2)
        out.window_create("end", window=badge, padx=8, align="center")
        self.cards.setdefault(out, []).append(badge)

    def _card_recipe(self, out: tk.Text, s: Suggestion) -> None:
        """card + card = card, then the details line."""
        evo = s.evolution
        for i, req in enumerate(evo.requires):
            if i:
                out.insert("end", "  +  ", "result")
            self._card(out, req, "missing" if req in s.missing else "have", needs_max=req in evo.max_level)
        out.insert("end", "  =  ", "result")
        self._card(out, evo.result, "result")
        out.insert("end", "\n")
        details = self._details(s, skip_missing=True)
        if details:
            out.insert("end", "  |  ".join(details) + "\n", "carddetail")

    def _refresh(self) -> None:
        owned = self.owned()
        hidden = self.hidden_expansions()
        self._queue_lookups(owned, hidden)
        self._render_overview(owned, hidden)
        self._render_howto(owned, hidden)
        self._render_guide()
        # Settings > Main screen > "How to evolve your items" shows or hides that tab
        if self.settings.show_how_to:
            self.results_tabs.add(self.howto_frame)  # re-adding a hidden tab restores it in place
        else:
            self.results_tabs.hide(self.howto_frame)

    WAITING = ("Waiting for your items. Start a run with auto-detect on (Settings > Detection), "
               "or turn it off and tick the items you're holding in the list on the left.")

    def _render_overview(self, owned: set[str], hidden: set[str]) -> None:
        out = self._begin(self.overview_text)
        opts = self.settings
        if not owned:
            out.insert("end", self.WAITING)
        else:
            if opts.show_holding:
                out.insert("end", self.holder_title() + "\n", "header")
                held = held_in_order(self.db, owned)
                for kind, title in (("weapon", "Weapons"), ("passive", "Passive items")):
                    group = [i for i in held if self.db.items[i].kind == kind]
                    if group:
                        out.insert("end", title + "\n", "subheader")
                        for item in group:
                            self._card(out, item, "held")
                        out.insert("end", "\n")
            all_ready = suggest(self.db, owned, hidden).ready if opts.show_ready else []
            planned = [s for s in all_ready if any(self.is_planned(r) for r in s.evolution.requires)]
            ready = [s for s in all_ready if s not in planned and not self._needs_leveling(s)]
            leveling = [s for s in all_ready if s not in planned and self._needs_leveling(s)]
            if ready:
                levels_known = self.auto_on() and self.settings.show_levels
                hint = "open a chest" if levels_known else "max the weapon, then open a chest"
                out.insert("end", f"READY TO EVOLVE - {hint}\n", "header")
                for s in ready:
                    self._card_recipe(out, s)
            if leveling:
                out.insert("end", "ALL PARTS - LEVEL UP FIRST\n", "header")
                for s in leveling:
                    self._card_recipe(out, s)
            if planned:
                out.insert("end", "WITH YOUR PLANNED ITEMS\n", "header")
                for s in planned:
                    self._card_recipe(out, s)
            if not all_ready and opts.show_ready:
                out.insert("end", "READY TO EVOLVE\n", "header")
                out.insert("end", "Nothing yet - see the How to evolve tab for what to pick up.\n", "detail")
            if opts.show_evolve_into:
                self._render_evolve_into(out, owned, hidden)
            if not (opts.show_holding or opts.show_ready or opts.show_evolve_into):
                out.insert("end", "Overview is switched off in Settings > Main screen.")
        out.configure(state="disabled")

    def _render_evolve_into(self, out: tk.Text, owned: set[str], hidden: set[str]) -> None:
        """One compact line per evolution of each held weapon that still needs parts
        (recipes with every part are already under Ready to evolve)."""
        rows, shown = [], set()
        for plan in plans_for_held(self.db, owned, hidden):
            if self.db.items[plan.item].kind != "weapon":
                continue
            for s in plan.options:
                key = (s.evolution.result, s.evolution.requires)
                if s.missing and key not in shown:  # a union of two held weapons is listed once
                    shown.add(key)
                    rows.append((plan.item, s))
        if not rows:
            return
        whose = "THEIR" if self.selected_player() else "YOUR"
        out.insert("end", f"WHAT {whose} ITEMS EVOLVE INTO\n", "header")
        for item, s in rows:
            out.insert("end", "  ")
            self._insert_item(out, item, "result")
            out.insert("end", "  \u2192  ")
            self._insert_item(out, s.evolution.result, "result")
            others = [r for r in s.evolution.requires if r != item]
            if others:
                out.insert("end", "    needs  ")
                for j, r in enumerate(others):
                    if j:
                        out.insert("end", ",  ")
                    have = r in owned
                    tag = "have" if have else "missing"
                    self._insert_item(out, r, tag)
                    out.insert("end", " \u2713" if have else " \u2717", tag)
            if s.evolution.kind == "union":
                out.insert("end", "   (union)", "detail")
            out.insert("end", "\n")

    def _render_howto(self, owned: set[str], hidden: set[str]) -> None:
        out = self._begin(self.howto_text)
        if not owned:
            out.insert("end", self.WAITING)
        else:
            friend = self.selected_player()
            title = f"HOW {friend.label.upper()} CAN EVOLVE" if friend else "HOW TO EVOLVE YOUR ITEMS"
            out.insert("end", title + "\n", "header")
            for plan in plans_for_held(self.db, owned, hidden):
                if plan.options or self.settings.show_no_evolution:
                    self._insert_plan(out, plan, owned)
        out.configure(state="disabled")

    def _guide_matches(self, evo, query: str) -> bool:
        """The search box matches item names and the names of characters who start with them."""
        for item_id in (evo.result, *evo.requires):
            item = self.db.items.get(item_id)
            if item and (query in item.name.lower() or any(query in c.lower() for c in item.characters)):
                return True
        return False

    def _schedule_guide_refresh(self) -> None:
        """Re-draw the guide shortly after typing stops (it has 150+ recipes with pictures)."""
        if self._guide_job:
            self.root.after_cancel(self._guide_job)
        self._guide_job = self.root.after(250, self._render_guide)

    def _render_guide(self) -> None:
        """Every recipe, grouped by expansion; held items green; filtered by the search box."""
        self._guide_job = None
        out = self._begin(self.guide_text)
        owned = self.owned()
        hidden = self.hidden_expansions()
        query = self.guide_search.get().strip().lower()
        shown = 0
        for dlc in ["Base game", *self.db.expansions(), ""]:  # "" = recipes found by wiki lookups
            if dlc in hidden:
                continue
            evos = [e for e in self.db.evolutions if e.dlc == dlc and (not query or self._guide_matches(e, query))]
            if not evos:
                continue
            out.insert("end", (dlc or "Found on the wiki").upper() + "\n", "header")
            for kind, title in (("evolution", "Evolutions"), ("union", "Unions"), ("gift", "Gifts"),
                                ("morph", "Morphs (character level 80 + relic)")):
                group = [e for e in evos if e.kind == kind]
                if not group:
                    continue
                out.insert("end", title + "\n", "subheader")
                for evo in group:
                    have = tuple(r for r in evo.requires if r in owned)
                    missing = tuple(r for r in evo.requires if r not in owned)
                    self._insert_suggestion(out, Suggestion(evo, have, missing), plain_missing=True,
                                            characters=True)
                    shown += 1
        if not shown:
            out.insert("end", "No evolutions match your search." if query else "All expansions are hidden in Settings.")
        out.configure(state="disabled")

    def _clear(self) -> None:
        """Manual mode: untick everything. Auto-detect: remove only the planned items."""
        if self.auto_on():
            for item_id in self.planned:
                self.vars[item_id].set(False)
            self.planned.clear()
        else:
            for v in self.vars.values():
                v.set(False)
        self._refresh()

    def _toggle_auto(self, save: bool = True) -> None:
        if save and self.reader_thread is not None:
            self.settings.auto_detect = self.auto_var.get()
            self._save_settings()
        self._update_player_bar()
        if self.auto_on():  # anything ticked by hand that isn't detected becomes "planned"
            detected = self.detected.owned if self.detected is not None else frozenset()
            self.planned = {i for i, v in self.vars.items() if v.get()} - detected
        self._update_items_tab()
        self._refresh()
        auto = self.auto_on()
        if self.reader_thread is None:
            return
        if auto:
            self.reader_thread.enabled.set()
            self.status.set("Looking for Vampire Survivors... (tick items in the list to plan ahead)")
        else:
            self.reader_thread.enabled.clear()
            self.status.set("Manual mode: tick the items you have.")

    def _drain_results(self) -> None:
        while True:
            try:
                kind, message = self.icon_messages.get_nowait()
            except queue.Empty:
                break
            if kind.startswith("update"):
                self._update_message(kind, message)
                continue
            if kind.startswith("report"):
                self._report_message(kind, message)
                continue
            if kind == "wiki-lookup":
                self._lookup_finished(*message)
                continue
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
        if latest is not None:
            self._update_launch_button(running=latest.state != "not_running")
        if latest is not None and self.auto_var.get():
            self.status.set(latest.message)
            if latest.state == "ok":
                changed = self.detected is None or (latest.owned, latest.levels, latest.players) != (
                    self.detected.owned, self.detected.levels, self.detected.players)
                self.detected = latest
                self._update_player_bar()
                self.planned -= latest.owned  # picked up in the game: now really held
                for item_id, var in self.vars.items():
                    var.set(item_id in latest.owned or item_id in self.planned)
                if changed:
                    self._refresh()
        self.root.after(250, self._drain_results)

    def _close(self) -> None:
        if self.reader_thread:
            self.reader_thread.stopped.set()
        self.icon_thread.stopped.set()
        self.icon_thread.wake.set()
        self.root.destroy()


def run(db: Database, game_map: GameMap | None, map_error: str | None = None, notice: str | None = None) -> None:
    root = tk.Tk()
    App(root, db, game_map, map_error, notice)
    root.mainloop()
