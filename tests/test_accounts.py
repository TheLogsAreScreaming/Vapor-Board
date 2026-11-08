import sqlite3
import tempfile
import unittest
from pathlib import Path
from vapor_board.accounts import ADMIN, STAFF, AccountError, StaffDirectory, MAX_FAILURES


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class StaffDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "staff.sqlite"
        self.clock = Clock()
        self.staff = StaffDirectory(self.path, clock=self.clock)

    def owner(self):
        return self.staff.create("Owner", "Sam Owner", "correct horse", role=STAFF, iterations=1000)

    def test_first_account_is_always_the_owner_admin(self):
        self.assertFalse(self.staff.exists())
        owner = self.owner()
        self.assertTrue(self.staff.exists())
        self.assertEqual((owner.username, owner.role, owner.active), ("owner", ADMIN, True))
        self.assertEqual(self.staff.activity()[0]["action"], "owner account created")

    def test_passwords_are_stored_hashed_never_in_plain_text(self):
        self.owner()
        raw = self.path.read_bytes()
        self.assertNotIn(b"correct horse", raw)
        with sqlite3.connect(self.path) as db:
            stored, salt = db.execute("SELECT password_hash, salt FROM staff").fetchone()
        self.assertEqual(len(stored), 64)
        self.assertEqual(len(bytes.fromhex(salt)), 16)

    def test_sign_in_checks_the_password_and_ignores_username_case(self):
        self.owner()
        self.assertEqual(self.staff.authenticate("OWNER", "correct horse").username, "owner")
        self.assertIsNone(self.staff.authenticate("owner", "wrong password"))
        self.assertIsNone(self.staff.authenticate("nobody", "correct horse"))
        actions = [entry["action"] for entry in self.staff.activity()]
        self.assertEqual(actions[:3], ["sign-in failed", "sign-in failed", "signed in"])
        self.assertTrue(self.staff.get("owner").last_sign_in)

    def test_repeated_failures_pause_sign_in(self):
        self.owner()
        for _ in range(MAX_FAILURES):
            self.assertIsNone(self.staff.authenticate("owner", "nope nope"))
        with self.assertRaisesRegex(AccountError, "Too many wrong passwords"):
            self.staff.authenticate("owner", "correct horse")
        self.clock.now += 61
        self.assertIsNotNone(self.staff.authenticate("owner", "correct horse"))

    def test_only_admins_add_accounts(self):
        owner = self.owner()
        with self.assertRaises(AccountError):
            self.staff.create("jess", "Jess", "password1", iterations=1000)
        jess = self.staff.create("jess", "Jess", "password1", actor=owner, iterations=1000)
        self.assertEqual(jess.role, STAFF)
        with self.assertRaisesRegex(AccountError, "owner or admin"):
            self.staff.create("kim", "Kim", "password1", actor=jess, iterations=1000)
        with self.assertRaisesRegex(AccountError, "already taken"):
            self.staff.create("JESS", "Jess 2", "password1", actor=owner, iterations=1000)

    def test_input_rules(self):
        owner = self.owner()
        for username, name, password, message in (("a", "A", "password1", "Usernames"), ("has space", "A", "password1", "Usernames"),
                                                   ("ok", "", "password1", "name"), ("ok", "A", "short", "at least 8")):
            with self.subTest(username=username, password=password), self.assertRaisesRegex(AccountError, message):
                self.staff.create(username, name, password, actor=owner, iterations=1000)

    def test_disabled_accounts_cannot_sign_in_and_the_last_admin_stays(self):
        owner = self.owner()
        self.staff.create("jess", "Jess", "password1", actor=owner, iterations=1000)
        self.assertFalse(self.staff.set_active("jess", False, owner).active)
        self.assertIsNone(self.staff.authenticate("jess", "password1"))
        self.assertEqual(self.staff.activity()[0]["detail"], "account disabled")
        with self.assertRaisesRegex(AccountError, "signed in with"):
            self.staff.set_active("owner", False, owner)
        second = self.staff.create("kim", "Kim", "password1", role=ADMIN, actor=owner, iterations=1000)
        self.staff.set_active("owner", False, second)
        with self.assertRaisesRegex(AccountError, "signed in with"):
            self.staff.set_active("kim", False, second)
        self.staff.set_active("jess", True, second)
        self.assertIsNotNone(self.staff.authenticate("jess", "password1"))

    def test_last_active_admin_cannot_be_disabled_by_another_admin(self):
        owner = self.owner()
        kim = self.staff.create("kim", "Kim", "password1", role=ADMIN, actor=owner, iterations=1000)
        self.staff.set_active("kim", False, owner)
        # Re-enable kim, then kim disables owner: allowed (kim remains). Disabling kim now would leave none.
        self.staff.set_active("kim", True, owner)
        self.staff.set_active("owner", False, kim)
        self.assertEqual([a.username for a in self.staff.accounts() if a.active and a.role == ADMIN], ["kim"])

    def test_password_changes(self):
        owner = self.owner()
        jess = self.staff.create("jess", "Jess", "password1", actor=owner, iterations=1000)
        self.staff.set_password("jess", "new password", jess, iterations=1000)
        self.assertIsNotNone(self.staff.authenticate("jess", "new password"))
        with self.assertRaisesRegex(AccountError, "your own"):
            self.staff.set_password("owner", "hijacked!", jess)
        self.staff.set_password("jess", "reset by owner", owner, iterations=1000)
        self.assertIsNotNone(self.staff.authenticate("jess", "reset by owner"))
        self.assertIsNone(self.staff.authenticate("jess", "new password"))

    def test_activity_log_is_newest_first_and_bounded(self):
        self.owner()
        for number in range(5):
            self.staff.log("owner", "post published", f"Board {number}")
        log = self.staff.activity(limit=3)
        self.assertEqual([entry["detail"] for entry in log], ["Board 4", "Board 3", "Board 2"])
        self.staff.log("x" * 100, "y" * 100, "z" * 500)
        entry = self.staff.activity(1)[0]
        self.assertEqual((len(entry["actor"]), len(entry["action"]), len(entry["detail"])), (40, 60, 200))


if __name__ == "__main__":
    unittest.main()
