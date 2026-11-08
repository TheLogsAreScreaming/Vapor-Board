"""Navigation, Overview, radio controls, Settings and layout of the real Tk window."""
from unittest import mock
from desktop_harness import DesktopHarness, walk
from vapor_board import desktop, ui_theme
from vapor_board.bbs import BulletinBoard

PAGES = ("Overview", "Boards", "Messages", "Customers", "Staff", "Settings")


class DesktopShellUiTests(DesktopHarness):
    def seed(self):
        bbs = BulletinBoard(self.database)
        board = bbs.create_board("Store hours")
        bbs.post(board, "Operator", "Open 10–8 today")
        bbs.send_mail("sam", "Operator", "Hello")
        return board

    # ---- layout -------------------------------------------------------------------------
    def test_every_page_fits_the_default_window(self):
        self.seed()
        for page in PAGES:
            with self.subTest(page=page):
                self.run_desktop(lambda root, page=page: self.assert_page_fits(root, page), page=page)

    def test_every_page_fits_the_smallest_window(self):
        self.seed()
        for page in PAGES:
            with self.subTest(page=page):
                self.run_desktop(lambda root, page=page: self.assert_page_fits(root, page), page=page, size="900x600")

    def test_every_page_fits_with_large_text(self):
        self.seed()
        self.write_shop({"text_size": "large"})
        for page in PAGES:
            with self.subTest(page=page):
                self.run_desktop(lambda root, page=page: self.assert_page_fits(root, page), page=page)

    def assert_sidebar_fits(self, root):
        root.update()
        radio = next(w for w in walk(root) if w.winfo_class() == "TLabel" and w.cget("text") == "RADIO").master
        search = next(w for w in walk(root) if w.winfo_name() == "search")
        for widget in [search] + [self.nav(root, name) for name in PAGES]:
            with self.subTest(widget=str(widget)):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), radio.winfo_rooty())

    def test_sidebar_fits_the_smallest_window_and_large_text(self):
        self.run_desktop(self.assert_sidebar_fits, page="Overview", size="900x600")
        self.write_shop({"text_size": "large"})
        self.run_desktop(self.assert_sidebar_fits, page="Overview")

    def test_navigation_marks_the_current_page(self):
        def scenario(root):
            for page in PAGES:
                self.nav(root, page).invoke()
                root.update()
                active = [name for name in PAGES if self.nav(root, name).cget("style") == "NavActive.TButton"]
                self.assertEqual(active, [page])

        self.run_desktop(scenario, page="Overview")

    def test_appearance_setting_picks_the_palette(self):
        for appearance, palette in (("light", ui_theme.LIGHT), ("dark", ui_theme.DARK)):
            with self.subTest(appearance=appearance):
                self.write_shop({"appearance": appearance})
                self.run_desktop(lambda root, palette=palette: self.assertEqual(root.cget("bg").upper(), palette.background), page="Overview")

    # ---- overview -----------------------------------------------------------------------
    def test_first_run_shows_a_getting_started_checklist(self):
        def scenario(root):
            page = self.page(root, "Overview")
            self.assertIn("Getting started", self.card_titles(root, page))
            text = self.labels(page)
            for step in ("Create a board", "Write your first post", "Send a private message", "Connect a radio (optional)"):
                self.assertIn(step, text)
            self.assert_page_fits(root, "Overview")
            self.buttons(root, "Overview")["Go to Boards  →"].invoke()
            root.update()
            self.assertEqual(self.nav(root, "Boards").cget("style"), "NavActive.TButton")

        self.run_desktop(scenario, page="Overview")

    def test_recent_posts_open_the_post_on_its_board(self):
        board = self.seed()
        other = BulletinBoard(self.database).create_board("Announcements")
        BulletinBoard(self.database).post(other, "Jess", "New stock")

        def scenario(root):
            page = self.page(root, "Overview")
            self.assertIn("Recent posts", self.card_titles(root, page))
            recent = self.lists(root, "Overview")[0]
            self.assertEqual(self.rows(recent), ("Announcements  ·  Jess — New stock", "Store hours  ·  Operator — Open 10–8 today"))
            self.pick(root, recent, 1)
            self.assertEqual(self.nav(root, "Boards").cget("style"), "NavActive.TButton")
            boards, posts = self.lists(root, "Boards")
            self.assertEqual(boards.selection(), ("0",))
            self.assertEqual(posts.selection(), ("0",))
            self.assertTrue(self.enabled(self.buttons(root, "Boards")["Edit"]))

        self.run_desktop(scenario, page="Overview")

    def test_stat_tiles_count_and_link(self):
        self.seed()

        def scenario(root):
            page = self.page(root, "Overview")
            text = self.labels(page)
            self.assertIn("Waiting in the Operator inbox", text)
            self.buttons(root, "Overview")["Open Messages  →"].invoke()
            root.update()
            self.assertEqual(self.nav(root, "Messages").cget("style"), "NavActive.TButton")

        self.run_desktop(scenario, page="Overview")

    # ---- radio --------------------------------------------------------------------------
    def radio_parts(self, root):
        page = self.page(root, "Overview")
        host, port = [w for w in walk(page) if w.winfo_class() == "TEntry"]
        return host, port, self.buttons(root, "Overview")

    @staticmethod
    def pill_texts(root):
        return [w.cget("text") for w in walk(root) if w.winfo_class() == "Label" and str(w.cget("text")).startswith("●  ")]

    def test_invalid_port_is_flagged_beside_the_field(self):
        worker = mock.Mock()
        worker.poll.return_value = None

        def scenario(root):
            host, port, buttons = self.radio_parts(root)
            self.assertFalse(self.enabled(buttons["Disconnect"]))
            port.delete(0, "end")
            port.insert(0, "abc")
            buttons["Connect"].invoke()
            root.update()
            self.assertTrue(port.instate(["invalid"]))
            self.assertTrue(any(t.startswith("Check the connection settings") for t in self.labels(self.page(root, "Overview"))))
            worker.start.assert_not_called()

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(scenario, page="Overview")

    def test_connect_and_disconnect_follow_the_radio_state(self):
        worker = mock.Mock()
        worker.start.return_value = True
        worker.poll.return_value = None

        def scenario(root):
            host, port, buttons = self.radio_parts(root)
            self.assertIn("●  Not connected", self.pill_texts(root))
            buttons["Connect"].invoke()
            root.update()
            worker.start.assert_called_once()
            self.assertEqual(worker.start.call_args[0][0].port, 4403)
            self.assertFalse(self.enabled(buttons["Connect"]))
            self.assertTrue(self.enabled(buttons["Disconnect"]))
            self.assertTrue(host.instate(["disabled"]))
            self.assertIn("●  Connecting…", self.pill_texts(root))
            buttons["Disconnect"].invoke()
            worker.stop.assert_called()
            self.assertTrue(self.enabled(buttons["Connect"]))
            self.assertEqual(self.toast(root), "Radio disconnected")
            self.assertIn("●  Not connected", self.pill_texts(root))

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(scenario, page="Overview")

    # ---- settings -----------------------------------------------------------------------
    def test_unreadable_settings_file_opens_with_defaults_and_explains(self):
        self.write_shop("{not json")

        def scenario(root):
            self.assertTrue(self.toast(root).startswith("Settings file couldn't be read"))
            page = self.page(root, "Settings")
            self.assertIn("Settings file couldn't be read", self.card_titles(root, page))
            self.assertIn("Vapor Board", self.labels(page))
            self.assert_page_fits(root, "Settings")

        self.run_desktop(scenario, page="Settings")

    def test_settings_show_safety_defaults(self):
        def scenario(root):
            text = self.labels(self.page(root, "Settings"))
            self.assertEqual(text[text.index("Radio transmit") + 1], "Off")
            self.assertIn("21+", text)
            self.assertIn("Required", text)

        self.run_desktop(scenario, page="Settings")


if __name__ == "__main__":
    import unittest
    unittest.main()
