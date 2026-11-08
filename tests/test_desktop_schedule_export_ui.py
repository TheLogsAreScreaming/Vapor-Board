"""Post scheduling, CSV export and demo mode in the real Tk window; skipped without a display."""
from desktop_harness import DesktopHarness, walk
from vapor_board.bbs import BulletinBoard
from vapor_board.ui_format import local_time_text


class DesktopScheduleExportUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        self.board_id = BulletinBoard(self.database).create_board("General")

    def entry(self, root, name):
        return next(w for w in walk(root) if w.winfo_name() == name)

    def test_publish_a_post_with_a_schedule_and_edit_it(self):
        def scenario(root):
            editor = self.texts(root, "Boards")[1]
            self.entry(root, "publish_at").insert(0, "2030-01-01 9:00 AM")
            self.entry(root, "expires_at").insert(0, "2030-01-31")
            editor.insert("1.0", "New year sale notice")
            self.buttons(root, "Boards")["Publish post"].invoke()
            self.assertEqual(self.toast(root), "Post published: Added to General.")
            self.assertEqual(self.entry(root, "publish_at").get(), "")
            view = self.texts(root, "Boards")[0].get("1.0", "end-1c")
            self.assertIn("Shows from", view)
            post_list = self.lists(root, "Boards")[1]
            self.assertEqual(self.rows(post_list), ("◷  Operator — New year sale notice",))
            self.pick(root, post_list, 0)
            self.buttons(root, "Boards")["Edit"].invoke()
            self.assertEqual(self.entry(root, "publish_at").get(), "2030-01-01 9:00 AM")
            self.entry(root, "publish_at").delete(0, "end")
            self.entry(root, "expires_at").delete(0, "end")
            self.entry(root, "expires_at").insert(0, "soon")
            self.buttons(root, "Boards")["Save changes"].invoke()
            self.assertTrue(self.toast(root).startswith("Post not updated: “soon” isn't a date"))
            self.entry(root, "expires_at").delete(0, "end")
            self.buttons(root, "Boards")["Save changes"].invoke()
            self.assertEqual(self.rows(post_list), ("Operator — New year sale notice",))
            self.assert_page_fits(root, "Boards")

        self.run_desktop(scenario)
        post = BulletinBoard(self.database).list_posts(self.board_id)[0]
        self.assertEqual((post["publish_at"], post["expires_at"]), (None, None))

    def test_bad_dates_keep_the_draft(self):
        def scenario(root):
            editor = self.texts(root, "Boards")[1]
            self.entry(root, "expires_at").insert(0, "2030-13-45")
            editor.insert("1.0", "Draft")
            self.buttons(root, "Boards")["Publish post"].invoke()
            self.assertTrue(self.toast(root).startswith("Post not published: "))
            self.assertEqual(editor.get("1.0", "end-1c"), "Draft")

        self.run_desktop(scenario)
        self.assertEqual(BulletinBoard(self.database).list_posts(self.board_id), [])

    def test_export_from_the_file_menu(self):
        BulletinBoard(self.database).post(self.board_id, "Operator", "Hello")

        def scenario(root):
            menu = root.nametowidget(".menubar.file")
            menu.invoke(menu.index("Export as Spreadsheets (CSV)"))
            self.assertTrue(self.toast(root).startswith("Spreadsheets exported: 1 post, 0 messages and 0 customers saved to ~/Documents/Vapor Board Exports/"))

        self.run_desktop(scenario)
        exports = list((self.home / "Documents" / "Vapor Board Exports").iterdir())
        self.assertEqual(len(exports), 1)
        self.assertTrue((exports[0] / "posts.csv").is_file())
        self.assertEqual(self.staff.activity()[0]["action"], "exported spreadsheets")

    def test_demo_mode_uses_sample_data_and_keeps_the_radio_off(self):
        self.argv = ["--demo"]
        self.sign_in_as = None

        def scenario(root):
            self.assertIsNone(self.gate(root))
            self.assertEqual(root.title(), "Vapor Board demo — sample data, radio off")
            self.assertIn("Demo Owner  ·  Owner / admin", self.labels(root))
            buttons = self.buttons(root, "Overview")
            self.assertFalse(self.enabled(buttons["Connect"]))
            self.assertIn("Demo mode: radio connections are switched off.", self.labels(self.page(root, "Overview")))
            self.nav(root, "Boards").invoke()
            root.update()
            self.assertEqual(self.rows(self.lists(root, "Boards")[0]), ("Store hours", "New arrivals", "Staff notes"))

        self.run_desktop(scenario, page="Overview")
        # The real shop folder is untouched.
        self.assertEqual([b["name"] for b in BulletinBoard(self.database).list_boards()], ["General"])
        self.assertTrue((self.home / ".vapor-board-demo" / "bbs.sqlite").exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
