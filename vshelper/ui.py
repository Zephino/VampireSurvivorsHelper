"""Tkinter window: tick items manually, or let the helper read them from the game."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from .data import Database, Item
from .evolutions import format_suggestions, suggest
from .memory.game import GameMap, GameReader, ReadResult

POLL_SECONDS = 1.0


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

        root.title("Vampire Survivors Helper")
        root.geometry("900x600")
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
        tabs = ttk.Notebook(body)
        body.add(tabs, weight=1)
        self.frames = {}
        for title, items in (
            ("Weapons", [i for i in db.weapons() if not i.evolved]),
            ("Passives", db.passives()),
            ("Evolved", [i for i in db.weapons() if i.evolved]),
        ):
            self.frames[title] = self._item_list(tabs, title, items)

        self.output = tk.Text(body, wrap="word", state="disabled", font=("Consolas", 10))
        body.add(self.output, weight=2)

        self.status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.status, anchor="w", padding=4, relief="sunken").pack(fill="x", side="bottom")

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

    def _item_list(self, tabs: ttk.Notebook, title: str, items: list[Item]) -> ttk.Frame:
        outer = ttk.Frame(tabs)
        tabs.add(outer, text=title)
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
        for item in sorted(items, key=lambda i: i.name.lower()):
            var = tk.BooleanVar()
            label = item.name if item.dlc == "Base game" else f"{item.name}  ({item.dlc})"
            cb = ttk.Checkbutton(inner, text=label, variable=var, command=self._refresh)
            cb.pack(anchor="w", padx=4, pady=1)
            self.vars[item.id] = var
            self.checkbuttons[item.id] = cb
        return inner

    def _apply_filter(self) -> None:
        text = self.filter_var.get().lower()
        for item_id, cb in self.checkbuttons.items():
            visible = text in self.db.items[item_id].name.lower()
            if visible and not cb.winfo_ismapped():
                cb.pack(anchor="w", padx=4, pady=1)
            elif not visible:
                cb.pack_forget()

    def owned(self) -> set[str]:
        return {i for i, v in self.vars.items() if v.get()}

    def _refresh(self) -> None:
        text = format_suggestions(self.db, suggest(self.db, self.owned()))
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

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
        self.root.destroy()


def run(db: Database, game_map: GameMap | None, map_error: str | None = None) -> None:
    root = tk.Tk()
    App(root, db, game_map, map_error)
    root.mainloop()
