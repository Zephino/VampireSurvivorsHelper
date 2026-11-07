import tkinter as tk
import unittest
from tkinter import ttk

from vshelper.widgets import FlowFrame


def make_root():
    try:
        root = tk.Tk()
    except tk.TclError:  # no display (e.g. a headless server)
        return None
    root.withdraw()
    return root


class FlowFrameTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        if self.root is None:
            self.skipTest("no display available")

    def tearDown(self):
        self.root.destroy()

    def test_buttons_are_placed_and_wrap_when_narrow(self):
        # Widths are passed in directly: a hidden test window doesn't report its size on Windows.
        flow = FlowFrame(self.root, padding=4)
        flow.pack(fill="x")
        buttons = [flow.add(ttk.Button(flow, text=f"Button number {i}")) for i in range(3)]
        self.root.update_idletasks()

        def rows():
            return {int(b.place_info()["y"]) for b in buttons}

        flow.relayout(2000)
        self.assertEqual(len(rows()), 1)  # wide: one row
        flow.relayout(150)
        self.assertEqual(len(rows()), 3)  # narrow: one per row
        self.assertGreater(flow._height, buttons[0].winfo_reqheight() * 2)

    def test_hidden_widgets_are_skipped(self):
        flow = FlowFrame(self.root)
        flow.pack(fill="x")
        a = flow.add(ttk.Label(flow, text="a"))
        b = flow.add(ttk.Label(flow, text="b"))
        self.root.update()
        flow.set_visible(a, False)
        self.assertEqual(a.place_info(), {})
        self.assertNotEqual(b.place_info(), {})


if __name__ == "__main__":
    unittest.main()
