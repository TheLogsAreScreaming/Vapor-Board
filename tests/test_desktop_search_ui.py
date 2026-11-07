"""The sidebar search box and Search page of the real Tk window."""
from desktop_harness import DesktopHarness, walk
from vapor_board.bbs import BulletinBoard


class DesktopSearchUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        bbs = BulletinBoard(self.database)
        self.hours = bbs.create_board("Hours")
        news = bbs.create_board("News")
        self.post_id = bbs.post(self.hours, "Operator", "Closed Monday for the holiday")
        bbs.post(news, "Jess", "New coils in stock")
        bbs.send_mail("Sam", "Operator", "Are you open on the holiday?")
        bbs.send_mail("alice", "carol", "holiday party")  # someone else's mail

    @staticmethod
    def search_entry(root):
        return next(w for w in walk(root) if w.winfo_name() == "search")

    def search(self, root, text):
        entry = self.search_entry(root)
        entry.delete(0, "end")
        entry.insert(0, text)
        entry.submit()  # the entry's Return binding
        root.update()

    def test_search_lists_posts_and_own_messages(self):
        def scenario(root):
            self.search(root, "holiday")
            self.assertEqual(self.labels(self.page(root, "Search"))[1], "2 results for “holiday”  ·  1 post, 1 message")
            results = self.lists(root, "Search")[0]
            self.assertEqual(self.rows(results), ("✉  Sam — Are you open on the holid…",
                                                  "▤  Hours  ·  Operator — Closed Monday for the hol…"))
            open_button = self.buttons(root, "Search")["Open"]
            self.assertFalse(self.enabled(open_button))
            self.pick(root, results, 1)
            preview = self.texts(root, "Search")[0]
            self.assertEqual(preview.get("1.0", "end-1c"), "Closed Monday for the holiday")
            self.assertEqual(preview.get(*preview.tag_ranges("match")[:2]), "holiday")
            self.assertIn("Post in Hours", self.card_titles(root, self.page(root, "Search")))
            self.assertTrue(self.enabled(open_button))
            self.assert_page_fits(root, "Search")

        self.run_desktop(scenario, page="Overview")

    def test_open_a_post_result_shows_it_on_its_board(self):
        def scenario(root):
            self.search(root, "monday")
            results = self.lists(root, "Search")[0]
            self.pick(root, results, 0)
            self.buttons(root, "Search")["Open"].invoke()
            root.update()
            self.assertEqual(self.nav(root, "Boards").cget("style"), "NavActive.TButton")
            boards, posts = self.lists(root, "Boards")
            self.assertEqual(boards.selection(), ("0",))
            self.assertEqual(posts.selection(), ("0",))

        self.run_desktop(scenario, page="Overview")

    def test_open_a_message_result_shows_the_conversation(self):
        def scenario(root):
            self.search(root, "open on")
            results = self.lists(root, "Search")[0]
            self.pick(root, results, 0)
            self.buttons(root, "Search")["Open"].invoke()
            root.update()
            self.assertEqual(self.nav(root, "Messages").cget("style"), "NavActive.TButton")
            self.assertIn("Conversation with Sam", self.card_titles(root, self.page(root, "Messages")))

        self.run_desktop(scenario, page="Overview")

    def test_search_page_fits_the_smallest_window(self):
        def scenario(root):
            self.search(root, "holiday")
            self.pick(root, self.lists(root, "Search")[0], 0)
            self.assert_page_fits(root, "Search")

        self.run_desktop(scenario, page="Overview", size="900x600")

    def test_no_matches_and_private_mail_stay_hidden(self):
        def scenario(root):
            self.search(root, "party")
            results = self.lists(root, "Search")[0]
            self.assertEqual(self.rows(results), ())
            self.assertEqual(self.placeholder(results), "No matches")
            self.assertIn("No matches", self.card_titles(root, self.page(root, "Search")))

        self.run_desktop(scenario, page="Overview")


if __name__ == "__main__":
    import unittest
    unittest.main()
