"""Local search over posts and the operator's own messages (no window needed)."""
import tempfile
import unittest
from pathlib import Path
from vapor_board.bbs import BulletinBoard


class SearchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bbs = BulletinBoard(Path(directory.name) / "bbs.sqlite")
        hours = self.bbs.create_board("Hours")
        news = self.bbs.create_board("News")
        self.bbs.post(hours, "Operator", "Closed Monday for the holiday")
        self.bbs.post(news, "Jess", "New coils in stock")
        self.bbs.send_mail("Sam", "Operator", "Are you open on the holiday?")
        self.bbs.send_mail("Operator", "Riley", "Your order is in")
        self.bbs.send_mail("alice", "carol", "holiday party at carol's")  # not the operator's mail

    def kinds(self, query):
        return [(r["kind"], r["body"]) for r in self.bbs.search("Operator", query)]

    def test_finds_posts_and_own_messages_newest_first(self):
        self.assertEqual(self.kinds("HOLIDAY"), [("message", "Are you open on the holiday?"),
                                                ("post", "Closed Monday for the holiday")])
        post = self.bbs.search("Operator", "holiday")[1]
        self.assertEqual((post["board_name"], post["author"]), ("Hours", "Operator"))

    def test_other_mailboxes_are_never_searched(self):
        self.assertEqual(self.kinds("party"), [])
        self.assertEqual(self.kinds("carol"), [])

    def test_matches_authors_and_correspondents(self):
        self.assertEqual(self.kinds("jess"), [("post", "New coils in stock")])
        self.assertEqual(self.kinds("riley"), [("message", "Your order is in")])
        self.assertEqual(self.kinds("sam"), [("message", "Are you open on the holiday?")])

    def test_wildcards_are_plain_text(self):
        self.assertEqual(self.kinds("%"), [])
        self.assertEqual(self.kinds("_"), [])
        board = self.bbs.list_boards()[0]["id"]
        self.bbs.post(board, "Operator", "50% off_today")
        self.assertEqual(self.kinds("50%"), [("post", "50% off_today")])
        self.assertEqual(self.kinds("f_t"), [("post", "50% off_today")])

    def test_query_and_limit_are_validated(self):
        for bad in ("", "   ", "x" * 101):
            with self.assertRaises(ValueError):
                self.bbs.search("Operator", bad)
        with self.assertRaises(ValueError):
            self.bbs.search("Operator", "holiday", limit=0)
        self.assertEqual(len(self.bbs.search("Operator", "o", limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
