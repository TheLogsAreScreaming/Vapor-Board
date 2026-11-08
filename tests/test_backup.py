"""Backup snapshots, verification and all-or-nothing restore (no window needed)."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from vapor_board import backup
from vapor_board.accounts import StaffDirectory
from vapor_board.bbs import BulletinBoard

NOON = datetime(2026, 11, 7, 12, 0, 0)
LATER = datetime(2026, 11, 7, 13, 0, 0)


class BackupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "bbs.sqlite"
        self.folder = self.root / "backups"
        self.bbs = BulletinBoard(self.database)
        board = self.bbs.create_board("General")
        self.bbs.post(board, "Operator", "Hello")
        self.bbs.send_mail("Sam", "Operator", "Hi")

    def test_backup_is_a_verified_copy_with_counts(self):
        info = backup.create_backup(self.database, self.folder, now=NOON)
        self.assertEqual(info.path.name, "bbs-20261107-120000.sqlite")
        self.assertEqual((info.boards, info.posts, info.messages), (1, 1, 1))
        self.assertEqual(info.created, NOON)
        self.assertEqual(info.summary, "1 board, 1 post, 1 message")
        self.assertEqual(BulletinBoard(info.path).list_boards(), [{"id": 1, "name": "General"}])
        self.assertEqual(list(self.folder.glob("*.partial")), [])

    def test_two_backups_in_one_second_do_not_overwrite(self):
        first = backup.create_backup(self.database, self.folder, now=NOON)
        second = backup.create_backup(self.database, self.folder, now=NOON)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(len(backup.list_backups(self.folder)), 2)

    def test_no_database_means_no_backup(self):
        with self.assertRaisesRegex(backup.BackupError, "no database"):
            backup.create_backup(self.root / "missing.sqlite", self.folder)
        self.assertFalse(self.folder.exists())

    def test_list_is_newest_first_and_skips_junk(self):
        backup.create_backup(self.database, self.folder, now=NOON)
        backup.create_backup(self.database, self.folder, now=NOON.replace(hour=13))
        (self.folder / "bbs-20261107-140000.sqlite").write_text("not a database")
        self.assertEqual([b.created.hour for b in backup.list_backups(self.folder)], [13, 12])
        self.assertEqual(backup.list_backups(self.root / "nowhere"), [])

    def test_inspect_rejects_files_that_are_not_backups(self):
        junk = self.root / "notes.sqlite"
        junk.write_text("hello")
        with self.assertRaisesRegex(backup.BackupError, "readable database"):
            backup.inspect(junk)
        other = self.root / "other.sqlite"
        import sqlite3
        with sqlite3.connect(other) as db:
            db.execute("CREATE TABLE things (id INTEGER)")
        with self.assertRaisesRegex(backup.BackupError, "isn't a Vapor Board backup"):
            backup.inspect(other)
        with self.assertRaisesRegex(backup.BackupError, "doesn't exist"):
            backup.inspect(self.root / "gone.sqlite")

    def test_restore_brings_back_old_data_and_keeps_a_safety_copy(self):
        saved = backup.create_backup(self.database, self.folder, now=NOON)
        self.bbs.create_board("Added later")
        self.bbs.delete_post(1)
        safety = backup.restore_backup(saved.path, self.database, self.folder, now=NOON.replace(hour=15))
        self.assertEqual([b["name"] for b in self.bbs.list_boards()], ["General"])
        self.assertEqual(len(self.bbs.list_posts(1)), 1)
        self.assertEqual(safety.label, "before restore")
        self.assertEqual(safety.path.name, "bbs-20261107-150000-before-restore.sqlite")
        self.assertEqual(safety.boards, 2)
        # The safety copy undoes the restore.
        backup.restore_backup(safety.path, self.database, self.folder)
        self.assertEqual([b["name"] for b in self.bbs.list_boards()], ["General", "Added later"])

    def test_failed_restore_changes_nothing(self):
        junk = self.root / "bbs-20261107-120000.sqlite"
        junk.write_text("garbage")
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(junk, self.database, self.folder)
        self.assertEqual([b["name"] for b in self.bbs.list_boards()], ["General"])
        self.assertFalse(self.folder.exists())  # refused before any safety copy was needed
        self.assertFalse((self.root / "bbs.sqlite.restoring").exists())

    def test_restoring_the_live_database_onto_itself_is_refused(self):
        with self.assertRaisesRegex(backup.BackupError, "live database"):
            backup.restore_backup(self.database, self.database, self.folder)

    def test_restore_onto_a_fresh_install_needs_no_safety_copy(self):
        saved = backup.create_backup(self.database, self.folder, now=NOON)
        fresh = self.root / "new" / "bbs.sqlite"
        self.assertIsNone(backup.restore_backup(saved.path, fresh, self.folder))
        self.assertEqual(BulletinBoard(fresh).list_boards(), [{"id": 1, "name": "General"}])


class StaffBackupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database, self.folder, self.staff_path = self.root / "bbs.sqlite", self.root / "backups", self.root / "staff.sqlite"
        BulletinBoard(self.database).create_board("General")
        self.staff = StaffDirectory(self.staff_path)
        self.owner = self.staff.create("owner", "Sam", "correct horse", iterations=1000)

    def backup(self, now=NOON):
        return backup.create_backup(self.database, self.folder, now=now, staff_database=self.staff_path)

    def test_backup_saves_staff_privately_and_keeps_the_board_listing_clean(self):
        info = self.backup()
        sidecar = backup.staff_file(info.path)
        self.assertEqual(sidecar.name, "bbs-20261107-120000.staff")
        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
        found = backup.staff_in_backup(info.path)
        self.assertEqual((found.accounts, found.admins), (1, 1))
        self.assertEqual([b.path for b in backup.list_backups(self.folder)], [info.path])

    def test_backup_without_staff_has_nothing_to_restore(self):
        info = backup.create_backup(self.database, self.folder, now=NOON)
        self.assertIsNone(backup.staff_in_backup(info.path))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(info.path, self.database, self.folder, staff_database=self.staff_path, restore_staff=True)

    def test_a_board_restore_leaves_accounts_alone(self):
        info = self.backup()
        self.staff.create("clerk", "Pat", "correct horse", actor=self.owner, iterations=1000)
        backup.restore_backup(info.path, self.database, self.folder, now=LATER, staff_database=self.staff_path)
        self.assertIsNotNone(self.staff.get("clerk"))

    def test_restoring_staff_brings_accounts_back_and_keeps_a_safety_copy(self):
        info = self.backup()
        self.staff.create("clerk", "Pat", "correct horse", actor=self.owner, iterations=1000)
        safety = backup.restore_backup(info.path, self.database, self.folder, now=LATER, staff_database=self.staff_path, restore_staff=True)
        self.assertIsNone(self.staff.get("clerk"))
        self.assertIsNotNone(self.staff.authenticate("owner", "correct horse"))
        self.assertEqual(backup.staff_in_backup(safety.path).accounts, 2)

    def test_a_backup_nobody_could_sign_in_to_is_refused(self):
        info = self.backup()
        with sqlite3.connect(backup.staff_file(info.path)) as db:
            db.execute("UPDATE staff SET active = 0")
        self.assertIsNone(backup.staff_in_backup(info.path))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(info.path, self.database, self.folder, now=LATER, staff_database=self.staff_path, restore_staff=True)
        self.assertIsNotNone(self.staff.authenticate("owner", "correct horse"))

    def test_a_damaged_staff_file_changes_nothing(self):
        info = self.backup()
        backup.staff_file(info.path).write_bytes(b"not a database, not even close" * 100)
        self.assertIsNone(backup.staff_in_backup(info.path))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(info.path, self.database, self.folder, now=LATER, staff_database=self.staff_path, restore_staff=True)
        self.assertEqual(self.staff.get("owner").username, "owner")


if __name__ == "__main__":
    unittest.main()
