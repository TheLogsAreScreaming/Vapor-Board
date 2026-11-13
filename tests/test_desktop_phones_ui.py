"""Pairing a customer's phone from the Customers page, in the real Tk window; skipped without a display."""
import tkinter as tk
from unittest import mock
from desktop_harness import DesktopHarness, walk
from vapor_board import desktop, phone_notices
from vapor_board.customers import CustomerBook


class FakeServer:
    started = []

    def __init__(self, feed, port, **_kwargs):
        self.feed, self.port = feed, port

    def start(self):
        FakeServer.started.append(self.port)
        return self

    def stop(self):
        pass


class DesktopPhonesUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        owner = self.staff.get("owner")
        book = CustomerBook(self.database)
        self.sam = book.add("Sam", actor=owner)
        book.approve(self.sam.id, owner, True)
        self.pending = book.add("Pat", actor=owner)
        FakeServer.started = []

    def dialog(self, root):
        return next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))

    def dialog_buttons(self, dialog):
        return {w.cget("text"): w for w in walk(dialog) if w.winfo_class() == "TButton"}

    def test_pair_and_remove_a_phone(self):
        self.write_shop({"phone_notices_enabled": True, "phone_notices_address": "192.168.1.20"})

        def scenario(root):
            customers = self.lists(root, "Customers")[0]
            self.assertEqual(self.rows(customers)[0], "Pat  ·  Waiting for approval")
            self.pick(root, customers, 0)
            phones = self.buttons(root, "Customers")["Phones…"]
            self.assertFalse(self.enabled(phones), "pending customers can't pair a phone")
            self.pick(root, customers, 1)
            self.assertTrue(self.enabled(phones))
            phones.invoke()
            dialog = self.dialog(root)
            self.assertEqual(dialog.title(), "Phones for Sam")
            buttons = self.dialog_buttons(dialog)
            buttons["Pair a new phone"].invoke()
            root.update()
            canvases = [w for w in walk(dialog) if isinstance(w, tk.Canvas)]
            self.assertEqual(len(canvases), 1)
            self.assertGreater(len(canvases[0].find_all()), 100)
            self.assertTrue(any("192.168.1.20" in text for text in self.labels(dialog)))
            self.assertEqual(len(phone_notices.PhoneBook(self.database).phones(self.sam.id)), 1)
            tree = next(w for w in walk(dialog) if w.winfo_class() == "Treeview")
            self.pick(root, tree, 0)
            buttons["Remove phone"].invoke()
            self.assertEqual(self.toast(root), "Phone removed: It can no longer read the notices.")
            self.assertEqual(phone_notices.PhoneBook(self.database).phones(self.sam.id), [])
            buttons["Close"].invoke()

        with mock.patch.object(phone_notices, "NoticesServer", FakeServer):
            self.run_desktop(scenario, page="Customers")
        self.assertEqual(FakeServer.started, [8765])
        actions = [e["action"] for e in self.staff.activity()]
        self.assertEqual(actions[:2], ["phone removed", "phone paired"])

    def test_off_by_default(self):
        def scenario(root):
            customers = self.lists(root, "Customers")[0]
            self.pick(root, customers, 1)
            self.buttons(root, "Customers")["Phones…"].invoke()
            dialog = self.dialog(root)
            self.assertFalse(self.enabled(self.dialog_buttons(dialog)["Pair a new phone"]))
            self.assertTrue(any("Phone notices are off" in text for text in self.labels(dialog)))

        with mock.patch.object(phone_notices, "NoticesServer", FakeServer):
            self.run_desktop(scenario, page="Customers")
        self.assertEqual(FakeServer.started, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
