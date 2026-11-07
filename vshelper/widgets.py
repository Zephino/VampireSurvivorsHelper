"""Small layout helpers so the window stays readable when it (or the side panel) is narrow."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class FlowFrame(ttk.Frame):
    """A row of widgets that wraps onto the next line when it runs out of width
    (like words in a paragraph). Create children with this frame as parent, then add() them."""

    def __init__(self, parent: tk.Widget, gap_x: int = 6, gap_y: int = 4, padding=0, **kwargs) -> None:
        super().__init__(parent, padding=padding, **kwargs)
        self._items: list[tuple[tk.Widget, int]] = []  # (widget, extra space before it)
        self._hidden: set[tk.Widget] = set()
        self._gap_x, self._gap_y = gap_x, gap_y
        # Remember padding and height ourselves: reading them back with cget() returns
        # different types depending on the Tk version (Tk 9 returns objects, not numbers).
        pad = padding if isinstance(padding, (tuple, list)) else (padding,)
        self._pad_x = int(pad[0]) if pad else 0
        self._pad_y = int(pad[1]) if len(pad) > 1 else self._pad_x
        self._height = -1
        self._last_width = -1
        self._pending = False
        self.bind("<Configure>", self._on_configure)

    def contains(self, widget: tk.Widget) -> bool:
        return any(w is widget for w, _ in self._items)

    def add(self, widget: tk.Widget, space_before: int = 0) -> tk.Widget:
        self._items.append((widget, space_before))
        # a child that changes size (e.g. a status label with new text) needs a new layout
        widget.bind("<Configure>", lambda e: self._schedule(), add="+")
        self._schedule()
        return widget

    def set_visible(self, widget: tk.Widget, visible: bool) -> None:
        if visible:
            self._hidden.discard(widget)
        else:
            self._hidden.add(widget)
            widget.place_forget()
        self.relayout()

    def _schedule(self) -> None:
        if not self._pending:
            self._pending = True
            self.after_idle(self.relayout)

    def _on_configure(self, event: tk.Event) -> None:
        if event.width != self._last_width:
            self.relayout()

    def relayout(self) -> None:
        self._pending = False
        width = self.winfo_width()
        self._last_width = width
        if width <= 1:  # not drawn yet: lay out as one row using the requested sizes
            width = 10_000
        pad_x, pad_y = self._pad_x, self._pad_y
        # first work out the rows, then place each widget centred vertically in its row
        rows: list[list[tuple[tk.Widget, int, int, int]]] = [[]]
        x = pad_x
        for widget, space in self._items:
            if widget in self._hidden:
                continue
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if rows[-1] and x + space + w > width - pad_x:  # doesn't fit: start a new row
                rows.append([])
                x, space = pad_x, 0
            rows[-1].append((widget, x + space, w, h))
            x += space + w + self._gap_x
        y = pad_y
        for row in rows:
            row_height = max((h for *_, h in row), default=0)
            for widget, wx, _w, h in row:
                widget.place(x=wx, y=y + (row_height - h) // 2)
            y += row_height + self._gap_y
        height = max(y - self._gap_y + pad_y, 1)
        if height != self._height:
            self._height = height
            self.configure(height=height)


def wrap_with_width(container: tk.Widget, labels: list[ttk.Label], margin: int = 40) -> None:
    """Keep each label's wraplength matched to the container's width."""
    def update(event: tk.Event) -> None:
        for label in labels:
            label.configure(wraplength=max(event.width - margin, 80))
    container.bind("<Configure>", update, add="+")
