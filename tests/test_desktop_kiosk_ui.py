"""Customer kiosk in the real Tk window; skipped without a display."""
import tkinter as tk
from desktop_harness import DesktopHarness, walk, OWNER, OWNER_PASSWORD
from vapor_board.bbs import BulletinBoard


class DesktopKioskUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        self.write_shop({"kiosk_fullscreen": False})

    @staticmethod
    def kiosk(root):
        frame = next(w for w in walk(root) if w.winfo_name() == "kiosk")
        return frame if frame.winfo_manager() else None

    def kiosk_parts(self, root):
        frame = self.kiosk(root)
        tree = next(w for w in walk(frame) if w.winfo_class() == "Treeview")
        text = next(w for w in walk(frame) if w.winfo_class() == "Text")
        return tree, text

    def test_kiosk_shows_only_visible_boards_and_needs_staff_to_leave(self):
        bbs = BulletinBoard(self.database)
        hours = bbs.create_board("Store hours")
        notes = bbs.create_board("Staff notes")
        news = bbs.create_board("News")
        bbs.post(hours, "Operator", "Open 10–8 today")
        first = bbs.post(hours, "Operator", "Closed Monday")
        bbs.pin_post(first, True)
        bbs.post(notes, "Operator", "Cash count at 6")
        bbs.set_customer_visible(notes, False)

        def scenario(root):
            self.buttons(root, "Overview")["Start kiosk"].invoke()
            root.update()
            self.assertIsNotNone(self.kiosk(root))
            tree, text = self.kiosk_parts(root)
            self.assertEqual(self.rows(tree), ("Store hours", "News"))
            shown = text.get("1.0", "end-1c")
            self.assertTrue(shown.startswith("◆  Pinned\nClosed Monday\nPosted "))
            self.assertIn("Open 10–8 today", shown)
            self.assertNotIn("Cash count", shown)
            self.pick(root, tree, 1)
            self.assertEqual(text.get("1.0", "end-1c"), "Nothing posted here yet.")
            # Staff are signed out: shortcuts and the window behind are locked away.
            self.assertNotIn("Operator  ·  Owner / admin", self.labels(root))
            self.buttons(root)["Staff sign-in"].invoke()
            root.update()
            self.assertIsNotNone(self.gate(root))
            next(w for w in walk(self.gate(root)) if w.winfo_class() == "TButton" and w.cget("text") == "Back to kiosk").invoke()
            root.update()
            self.assertIsNone(self.gate(root))
            self.assertIsNotNone(self.kiosk(root))
            self.buttons(root)["Staff sign-in"].invoke()
            root.update()
            self.sign_in(root, OWNER, OWNER_PASSWORD)
            self.assertIsNone(self.kiosk(root))
            self.assertIn("Operator  ·  Owner / admin", self.labels(root))

        self.run_desktop(scenario, page="Overview")
        actions = [entry["action"] for entry in self.staff.activity()]
        self.assertEqual(actions[:3], ["kiosk stopped", "signed in", "kiosk started"])

    def start(self, root):
        self.buttons(root, "Overview")["Start kiosk"].invoke()
        root.update()

    def test_kiosk_shows_tagline_and_a_scaled_logo(self):
        BulletinBoard(self.database).create_board("Hours")
        self.write_shop({"kiosk_fullscreen": False, "kiosk_logo": "logo.png", "kiosk_tagline": "Open late on Fridays"})

        def scenario(root):
            image = tk.PhotoImage(master=root, width=600, height=300)
            image.write(str(self.database.parent / "logo.png"), format="png")
            root.update()

        self.run_desktop(scenario, page="Overview")

        def branded(root):
            self.start(root)
            self.assertIn("Open late on Fridays", self.labels(self.kiosk(root)))
            logo = next(w for w in walk(self.kiosk(root)) if w.winfo_name() == "kiosk_logo")
            self.assertLessEqual(logo.winfo_reqheight(), 100)

        self.run_desktop(branded, page="Overview")

    def test_kiosk_shows_hours_and_contact(self):
        BulletinBoard(self.database).create_board("Hours")
        self.write_shop({"kiosk_fullscreen": False, "shop_hours": "10-8 daily", "shop_contact": "555-0100"})

        def scenario(root):
            self.start(root)
            self.assertIn("10-8 daily   ·   555-0100", self.labels(self.kiosk(root)))

        self.run_desktop(scenario, page="Overview")

    def test_missing_logo_falls_back_to_the_monogram(self):
        BulletinBoard(self.database).create_board("Hours")
        self.write_shop({"kiosk_fullscreen": False, "kiosk_logo": "nope.png"})

        def scenario(root):
            self.start(root)
            self.assertFalse([w for w in walk(self.kiosk(root)) if w.winfo_name() == "kiosk_logo"])

        self.run_desktop(scenario, page="Overview")

    def test_kiosk_needs_a_visible_board(self):
        board = BulletinBoard(self.database).create_board("Staff notes")
        BulletinBoard(self.database).set_customer_visible(board, False)

        def scenario(root):
            self.buttons(root, "Overview")["Start kiosk"].invoke()
            root.update()
            self.assertIsNone(self.kiosk(root))
            self.assertTrue(self.toast(root).startswith("Nothing for customers to read"))

        self.run_desktop(scenario, page="Overview")

    def test_kiosk_rotates_boards_when_idle(self):
        self.write_shop({"kiosk_fullscreen": False, "kiosk_rotate_seconds": 5})
        bbs = BulletinBoard(self.database)
        bbs.create_board("Store hours")
        bbs.create_board("News")
        from unittest import mock
        from vapor_board import desktop

        def scenario(root):
            self.buttons(root, "Overview")["Start kiosk"].invoke()
            root.update()
            tree, _text = self.kiosk_parts(root)
            self.assertEqual(tree.selection(), ("0",))
            with mock.patch.object(desktop.time, "monotonic", return_value=10 ** 9):
                for job in root.tk.call("after", "info"):
                    try:
                        root.tk.eval(root.tk.call("after", "info", job)[0])
                    except Exception:
                        pass
            root.update()
            self.assertEqual(tree.selection(), ("1",))

        self.run_desktop(scenario, page="Overview")


if __name__ == "__main__":
    import unittest
    unittest.main()
