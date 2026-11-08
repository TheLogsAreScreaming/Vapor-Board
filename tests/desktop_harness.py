"""Shared harness: opens the real Tk desktop invisibly against a temporary home."""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock
from vapor_board import desktop
from vapor_board.accounts import StaffDirectory

OWNER, OWNER_PASSWORD = "owner", "correct horse"


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class DesktopHarness(unittest.TestCase):
    """Base for window tests; skipped where no display is available (Linux CI)."""
    def setUp(self):
        try:
            tk.Tk().destroy()
        except tk.TclError as exc:
            self.skipTest(f"no display: {exc}")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        (self.home / ".vapor-board").mkdir()
        self.database = self.home / ".vapor-board" / "bbs.sqlite"
        self.staff_path = self.home / ".vapor-board" / "staff.sqlite"
        # Signed in as the owner by default; display name "Operator" matches the default mailbox.
        self.staff = StaffDirectory(self.staff_path)
        self.staff.create(OWNER, "Operator", OWNER_PASSWORD, iterations=1000)
        self.sign_in_as = (OWNER, OWNER_PASSWORD)
        self.argv = []  # command-line arguments for desktop.main (e.g. ["--demo"])

    def write_shop(self, settings):
        (self.home / ".vapor-board" / "shop.json").write_text(
            settings if isinstance(settings, str) else json.dumps(settings), encoding="utf-8")

    def run_desktop(self, scenario, page="Boards", size=None):
        def mainloop(root, *_args):
            try:
                root.attributes("-alpha", 0.0)  # invisible: nothing flashes on the operator's screen
                root.geometry(f"{size}+4000+4000" if size else "+4000+4000")
                if self.sign_in_as:
                    self.sign_in(root, *self.sign_in_as)
                self.nav(root, page).invoke()  # open the page from the sidebar, as the operator would
                root.update()  # map it so selection bindings fire
                scenario(root)
            finally:
                for pending in root.tk.call("after", "info"):
                    root.after_cancel(pending)
                root.destroy()
        # Keep the window off-screen and fail on any dialog a scenario did not mock.
        unexpected = mock.Mock(side_effect=AssertionError("unexpected dialog"))
        with mock.patch.object(Path, "home", return_value=self.home), \
                mock.patch.object(tk.Tk, "mainloop", mainloop), \
                mock.patch.multiple(desktop.messagebox, showwarning=unexpected, showerror=unexpected,
                                    showinfo=unexpected, askyesno=unexpected), \
                mock.patch.object(desktop.filedialog, "askopenfilename", unexpected):
            desktop.main(self.argv)

    # ---- signing in ----------------------------------------------------------------------
    @staticmethod
    def gate(root):
        """The sign-in screen, or None once someone has signed in."""
        frame = next(w for w in walk(root) if w.winfo_name() == "gate")
        return frame if frame.winfo_manager() else None

    @staticmethod
    def gate_entry(root, name):
        return next(w for w in walk(root) if w.winfo_name() == f"gate_{name}")

    def sign_in(self, root, username, password):
        gate = self.gate(root)
        self.assertIsNotNone(gate, "sign-in screen not showing")
        for name, value in (("username", username), ("password", password)):
            entry = self.gate_entry(root, name)
            entry.delete(0, "end")
            entry.insert(0, value)
        next(w for w in walk(gate) if w.winfo_class() == "TButton" and w.cget("text") == "Sign in").invoke()
        root.update()

    # ---- finding things -----------------------------------------------------------------
    @staticmethod
    def nav(root, name):
        """Sidebar button for a page."""
        return next(w for w in walk(root) if w.winfo_class() == "TButton" and getattr(w, "page_name", None) == name)

    @staticmethod
    def page(root, name):
        """The page frame for a sidebar entry."""
        return next(w for w in walk(root) if w.winfo_class() == "TFrame" and getattr(w, "page_name", None) == name)

    def buttons(self, root, page=None):
        scope = self.page(root, page) if page else root
        return {w.cget("text"): w for w in walk(scope) if w.winfo_class() == "TButton"}

    def lists(self, root, page):
        """ListView trees on a page, top to bottom, left to right as built."""
        return [w for w in walk(self.page(root, page)) if w.winfo_class() == "Treeview"]

    def texts(self, root, page):
        return [w for w in walk(self.page(root, page)) if isinstance(w, tk.Text)]

    @staticmethod
    def rows(tree):
        return tuple(tree.item(i, "text")[2:] for i in tree.get_children() if i != "placeholder")

    @staticmethod
    def placeholder(tree):
        return tree.item("placeholder", "text")[2:] if tree.exists("placeholder") else None

    @staticmethod
    def pick(root, tree, index):
        """Select a row as a click would: through the widget's own selection event."""
        tree.selection_set(str(index))
        tree.focus(str(index))
        root.update()

    @staticmethod
    def labels(widget):
        return [w.cget("text") for w in walk(widget) if w.winfo_class() in ("TLabel", "Label") and w.cget("text")]

    @staticmethod
    def card_titles(root, page_frame):
        return [root.getvar(str(w.cget("textvariable"))) if str(w.cget("textvariable")) else w.cget("text")
                for w in walk(page_frame) if w.winfo_class() == "TLabel" and w.cget("style") == "Card.Headline.TLabel"]

    @staticmethod
    def toast(root):
        """(kind-visible?, 'Title: message') for the floating notice."""
        frame = next(w for w in walk(root) if w.winfo_name() == "toast")
        if not frame.winfo_manager():
            return None
        title = next(w for w in walk(frame) if w.winfo_name() == "toast_title").cget("text")
        message = next(w for w in walk(frame) if w.winfo_name() == "toast_message").cget("text")
        return ": ".join(part for part in (title, message) if part)

    @staticmethod
    def enabled(button):
        return not button.instate(["disabled"])

    @staticmethod
    def _collapsed(widget, page):
        while widget is not page:
            if widget.winfo_manager() == "":
                return True
            widget = widget.master
        return False

    def assert_page_fits(self, root, name):
        root.update()
        page = self.page(root, name)
        bottom = page.winfo_rooty() + page.winfo_height()
        right = page.winfo_rootx() + page.winfo_width()
        for widget in walk(page):
            if widget is page or widget.winfo_class() in ("TFrame", "TScrollbar"):
                continue
            if self._collapsed(widget, page):  # deliberately hidden (e.g. collapsed details)
                continue
            with self.subTest(page=name, widget=str(widget)):
                self.assertTrue(widget.winfo_ismapped(), "hidden by lack of space")
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right)
                # ...and not cut off by its own container either.
                parent = widget.master
                while parent is not page:
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), parent.winfo_rootx() + parent.winfo_width() + 1, f"clipped by {parent}")
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), parent.winfo_rooty() + parent.winfo_height() + 1, f"clipped by {parent}")
                    parent = parent.master
