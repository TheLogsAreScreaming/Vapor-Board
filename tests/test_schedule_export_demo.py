import csv
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from vapor_board import demo
from vapor_board.accounts import StaffDirectory
from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook
from vapor_board.export import export_csv, safe_cell
from vapor_board.local_operator import inspect_database
from vapor_board.ui_format import parse_local_time, local_time_text, schedule_state


class Folder(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.path = self.folder / "bbs.sqlite"


class ScheduleTests(Folder):
    def test_customers_see_only_published_unexpired_posts(self):
        bbs = BulletinBoard(self.path)
        board = bbs.create_board("Hours")
        bbs.post(board, "Op", "always")
        bbs.post(board, "Op", "later", publish_at="2030-01-01 00:00:00")
        bbs.post(board, "Op", "gone", expires_at="2020-01-01 00:00:00")
        window = bbs.post(board, "Op", "window", publish_at="2026-01-01 00:00:00", expires_at="2026-02-01 00:00:00")
        bodies = lambda now: [p["body"] for p in bbs.customer_posts(board, now=now)]
        self.assertEqual(bodies("2026-01-15 12:00:00"), ["window", "always"])
        self.assertEqual(bodies("2026-03-01 00:00:00"), ["always"])
        self.assertEqual(len(bbs.list_posts(board)), 4)  # staff see everything
        bbs.set_schedule(window, None, None)
        self.assertIn("window", bodies("2026-03-01 00:00:00"))

    def test_schedule_validation(self):
        bbs = BulletinBoard(self.path)
        board = bbs.create_board("Hours")
        with self.assertRaisesRegex(ValueError, "after the start"):
            bbs.post(board, "Op", "x", publish_at="2026-02-01 00:00:00", expires_at="2026-01-01 00:00:00")
        with self.assertRaisesRegex(ValueError, "UTC time"):
            bbs.post(board, "Op", "x", publish_at="tomorrow")
        with self.assertRaises(ValueError):
            bbs.set_schedule(99, None, None)

    def test_old_databases_gain_the_columns_and_the_reader_copes_without_them(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE boards (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
            db.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, board_id INTEGER, author TEXT, body TEXT, created_at TEXT)")
            db.execute("INSERT INTO boards (name) VALUES ('Old')")
            db.execute("INSERT INTO posts (board_id, author, body, created_at) VALUES (1, 'Op', 'hi', '2025-01-01 00:00:00')")
        old = inspect_database(self.path, 1)["posts"][0]
        self.assertEqual((old["publish_at"], old["expires_at"], old["pinned_at"]), (None, None, None))
        self.assertEqual([p["body"] for p in BulletinBoard(self.path).customer_posts(1)], ["hi"])

    def test_local_time_parsing(self):
        stamp = parse_local_time("2026-11-20 9:30 pm")
        local = datetime(2026, 11, 20, 21, 30).astimezone().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(stamp, local)
        self.assertEqual(parse_local_time("2026-11-20 21:30"), local)
        self.assertEqual(local_time_text(stamp), "2026-11-20 9:30 PM")
        self.assertIsNone(parse_local_time("  "))
        end = parse_local_time("2026-11-20", end_of_day=True)
        self.assertEqual(local_time_text(end), "2026-11-20 11:59 PM")
        with self.assertRaisesRegex(ValueError, "isn't a date"):
            parse_local_time("next tuesday")

    def test_schedule_state(self):
        now = "2026-06-01 00:00:00"
        self.assertEqual(schedule_state({"publish_at": "2026-07-01 00:00:00"}, now), "scheduled")
        self.assertEqual(schedule_state({"expires_at": "2026-05-01 00:00:00"}, now), "expired")
        self.assertEqual(schedule_state({"publish_at": None, "expires_at": None}, now), "live")


class ExportTests(Folder):
    def test_export_writes_four_spreadsheets_with_safe_cells(self):
        bbs = BulletinBoard(self.path)
        board = bbs.create_board("Hours")
        bbs.post(board, "Op", "=HYPERLINK(\"http://x\")")
        bbs.send_mail("sam", "Op", "+1 555")
        CustomerBook(self.path).add("@Sam", actor=SimpleNamespace(username="op", active=True))
        staff = StaffDirectory(self.folder / "staff.sqlite")
        staff.create("op", "Op", "password1", iterations=1000)
        made, counts = export_csv(self.path, staff.path, self.folder / "out", now=datetime(2026, 11, 7, 9, 0, 0))
        self.assertEqual(made.name, "vapor-board-export-20261107-090000")
        self.assertEqual(counts, {"posts.csv": 1, "messages.csv": 1, "customers.csv": 1, "activity.csv": 1})
        with open(made / "posts.csv", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][0], "board")
        self.assertEqual(rows[1][-1], "'=HYPERLINK(\"http://x\")")
        self.assertEqual(safe_cell("-2"), "'-2")
        self.assertEqual(safe_cell(None), "")
        self.assertEqual(safe_cell(5), "5")

    def test_export_without_any_data(self):
        made, counts = export_csv(self.folder / "missing.sqlite", self.folder / "none.sqlite", self.folder / "out")
        self.assertEqual(set(counts.values()), {0})
        self.assertTrue((made / "activity.csv").exists())


class DemoTests(Folder):
    def test_demo_seeds_its_own_folder_and_resets_each_time(self):
        folder, account = demo.prepare(self.folder)
        self.assertEqual(folder, self.folder / ".vapor-board-demo")
        self.assertEqual(account.username, "demo")
        bbs = BulletinBoard(folder / "bbs.sqlite")
        self.assertEqual([b["name"] for b in bbs.customer_boards()], ["Store hours", "New arrivals"])
        bbs.create_board("Scratch")
        demo.prepare(self.folder)
        self.assertNotIn("Scratch", [b["name"] for b in BulletinBoard(folder / "bbs.sqlite").list_boards()])
        self.assertFalse((self.folder / ".vapor-board").exists())
        self.assertFalse(demo.CONFIG.transmissions_enabled)


if __name__ == "__main__":
    unittest.main()
