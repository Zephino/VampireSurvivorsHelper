"""Tkinter window: tick items manually, or let the helper read them from the game."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import icons
from .data import Database, Item
from .evolutions import Suggestion, suggest
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


class App:
    def __init__(self, root: tk.Tk, db: Database, game_map: GameMap | None, map_error: str | None = None):
        self.root = root
        self.db = db
        self.vars: dict[str, tk.BooleanVar] = {}
        self.checkbuttons: dict[str, ttk.Checkbutton] = {}
        self.results: "queue.Queue[ReadResult]" = queue.Queue()
        self.icon_messages: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.icons: dict[str, tk.PhotoImage] = {}
        self.small_icons: dict[str, tk.PhotoImage] = {}

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
        item_list = self._item_list(body, [
            ("Weapons", [i for i in db.weapons() if not i.evolved]),
            ("Passive Items", db.passives()),
            ("Evolved Weapons", [i for i in db.weapons() if i.evolved]),
        ])
        body.add(item_list, weight=1)

        self.output = tk.Text(body, wrap="word", state="disabled", font=("Segoe UI", 10), spacing1=2, spacing3=2)
        self.output.tag_configure("header", font=("Segoe UI", 11, "bold"), spacing1=10)
        self.output.tag_configure("have", foreground="#1b7f2a")
        self.output.tag_configure("missing", foreground="#c0392b", font=("Segoe UI", 10, "bold"))
        self.output.tag_configure("result", font=("Segoe UI", 10, "bold"))
        self.output.tag_configure("detail", foreground="#666666", lmargin1=40, lmargin2=40)
        body.add(self.output, weight=2)

        bar = ttk.Frame(root, relief="sunken")
        bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.status, anchor="w", padding=4).pack(side="left", fill="x", expand=True)
        self.icon_status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.icon_status, anchor="e", padding=4).pack(side="right")

        self._load_icons()
        self.icon_thread = IconThread(db, game_map, self.icon_messages)
        self.icon_thread.start()

        self.reader_thread: ReaderThread | None = None
        if game_map is not None:
            self.reader_thread = ReaderThread(GameReader(db, game_map), self.results)
            self.reader_thread.start()
        else:
            self.auto_var.set(False)
            auto.state(["disabled"])
            self.status.set(f"Auto-detect unavailable: {map_error}")
        self._toggle_auto()
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
                label = item.name if item.dlc == "Base game" else f"{item.name}  ({item.dlc})"
                cb = ttk.Checkbutton(inner, text=label, variable=var, command=self._refresh)
                cb.grid(row=row, column=0, sticky="w", padx=14, pady=1)
                row += 1
                self.vars[item.id] = var
                self.checkbuttons[item.id] = cb
        return outer

    def _apply_filter(self) -> None:
        text = self.filter_var.get().lower()
        for item_id, cb in self.checkbuttons.items():
            visible = text in self.db.items[item_id].name.lower()
            if visible:
                cb.grid()  # grid() restores the original row, so the order is kept
            else:
                cb.grid_remove()

    def owned(self) -> set[str]:
        return {i for i, v in self.vars.items() if v.get()}

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

    def _insert_item(self, item_id: str, tag: str) -> None:
        img = self.icons.get(item_id)
        if img is not None:
            self.output.image_create("end", image=img, padx=2, align="center")
        self.output.insert("end", self.db.name(item_id), tag)

    def _insert_suggestion(self, s: Suggestion) -> None:
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
        details = []
        if s.missing:
            details.append("need: " + ", ".join(self.db.name(m) for m in s.missing))
        if evo.max_level:
            details.append("max level: " + ", ".join(self.db.name(m) for m in evo.max_level))
        if evo.notes:
            details.append(evo.notes)
        if not evo.verified:
            details.append("unverified data - double-check in game")
        if details:
            out.insert("end", "  |  ".join(details) + "\n", "detail")

    def _refresh(self) -> None:
        suggestions = suggest(self.db, self.owned())
        out = self.output
        out.configure(state="normal")
        out.delete("1.0", "end")
        sections = (
            ("READY - open a chest after 10:00", suggestions.ready),
            ("ONE ITEM AWAY", suggestions.one_away),
            ("OTHER EVOLUTIONS FOR YOUR ITEMS", suggestions.further),
        )
        if not any(group for _, group in sections):
            out.insert("end", "Select the weapons and passive items you have to see possible evolutions.")
        for title, group in sections:
            if group:
                out.insert("end", title + "\n", "header")
                for s in group:
                    self._insert_suggestion(s)
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
                changed = False
                for item_id, var in self.vars.items():
                    want = item_id in latest.owned
                    if var.get() != want:
                        var.set(want)
                        changed = True
                if changed:
                    self._refresh()
        self.root.after(250, self._drain_results)

    def _close(self) -> None:
        if self.reader_thread:
            self.reader_thread.stopped.set()
        self.icon_thread.stopped.set()
        self.root.destroy()


def run(db: Database, game_map: GameMap | None, map_error: str | None = None) -> None:
    root = tk.Tk()
    App(root, db, game_map, map_error)
    root.mainloop()
