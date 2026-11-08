"""Recovery code and restoring staff accounts in the real Tk window."""
import unittest
from unittest import mock
from desktop_harness import DesktopHarness, walk, OWNER, OWNER_PASSWORD
from vapor_board import backup, desktop
from vapor_board.accounts import StaffDirectory


class RecoveryUiTests(DesktopHarness):
    @staticmethod
    def screen(root):
        frame = next(w for w in walk(root) if w.winfo_name() == "recovery")
        return frame if frame.winfo_manager() else None

    @staticmethod
    def shown_code(root):
        return next(w for w in walk(root) if w.winfo_name() == "recovery_code").get()

    def click(self, scope, text):
        next(w for w in walk(scope) if w.winfo_class() == "TButton" and w.cget("text") == text).invoke()

    def test_first_launch_shows_a_code_and_stores_it_only_once_saved(self):
        self.staff_path.unlink()
        self.sign_in_as = None

        def scenario(root):
            for name, value in (("name", "Dana"), ("username", "dana"), ("password", "longpassword"), ("confirm", "longpassword")):
                self.gate_entry(root, name).insert(0, value)
            self.click(self.gate(root), "Create owner account")
            root.update()
            self.assertIsNotNone(self.screen(root))
            self.assertEqual(len(self.shown_code(root)), 24)
            self.assertFalse(StaffDirectory(self.staff_path).has_recovery_code())
            self.click(self.screen(root), "I've saved it")
            self.assertIsNone(self.screen(root))
            self.assertTrue(StaffDirectory(self.staff_path).has_recovery_code())

        self.run_desktop(scenario, page="Overview")

    def test_forgot_password_resets_it_and_issues_a_new_code(self):
        self.sign_in_as = None
        code = self.staff.new_recovery_code()
        self.staff.save_recovery_code(code, self.staff.get(OWNER), iterations=1000)

        def scenario(root):
            self.click(self.gate(root), "Forgot password?")
            root.update()
            for name, value in (("username", OWNER), ("code", code), ("password", "brand new pass"), ("confirm", "brand new pass")):
                self.gate_entry(root, name).insert(0, value)
            self.click(self.gate(root), "Reset and sign in")
            root.update()
            self.assertIsNone(self.gate(root))
            self.assertIsNotNone(self.screen(root))
            self.assertNotEqual(self.shown_code(root), code)

        self.run_desktop(scenario, page="Overview")
        self.assertIsNotNone(self.staff.authenticate(OWNER, "brand new pass"))

    def test_wrong_code_stays_on_the_form(self):
        self.sign_in_as = None

        def scenario(root):
            self.click(self.gate(root), "Forgot password?")
            root.update()
            for name, value in (("username", OWNER), ("code", "AAAA"), ("password", "brand new pass"), ("confirm", "brand new pass")):
                self.gate_entry(root, name).insert(0, value)
            self.click(self.gate(root), "Reset and sign in")
            self.assertIn("That username and recovery code don't match an active owner or admin.", self.labels(self.gate(root)))

        self.run_desktop(scenario, page="Overview")
        self.assertIsNotNone(self.staff.authenticate(OWNER, OWNER_PASSWORD))

    def test_replacing_can_be_cancelled_and_locking_hides_the_code(self):
        def scenario(root):
            self.buttons(root, "Staff")["New recovery code…"].invoke()
            root.update()
            self.click(self.screen(root), "Keep current code")
            self.assertIsNone(self.screen(root))
            self.buttons(root, "Staff")["New recovery code…"].invoke()
            root.update()
            self.assertIsNotNone(self.screen(root))
            next(w for w in walk(root) if w.winfo_class() == "TButton" and w.cget("text") == "Lock").invoke()
            root.update()
            self.assertIsNone(self.screen(root))
            self.assertIsNotNone(self.gate(root))

        self.run_desktop(scenario, page="Staff")

    def restore(self, answers):
        from vapor_board.bbs import BulletinBoard
        BulletinBoard(self.database).create_board("General")
        folder = self.database.parent / "backups"
        saved = backup.create_backup(self.database, folder, staff_database=self.staff_path)
        self.staff.create("clerk", "Pat", "correct horse", actor=self.staff.get(OWNER), iterations=1000)

        def scenario(root):
            with mock.patch.object(desktop.filedialog, "askopenfilename", return_value=str(saved.path)), \
                    mock.patch.object(desktop.messagebox, "askyesno", side_effect=answers) as ask:
                self.buttons(root, "Settings")["Restore…"].invoke()
            root.update()
            self.assertEqual(ask.call_args.kwargs["default"], "no")
            self.assertEqual(ask.call_count, 2)
            self.outcome = self.gate(root) is not None

        self.run_desktop(scenario, page="Settings")

    def test_restoring_staff_accounts_signs_everyone_out(self):
        self.restore([True, True])
        self.assertTrue(self.outcome)
        self.assertIsNone(self.staff.get("clerk"))

    def test_saying_no_keeps_todays_accounts(self):
        self.restore([True, False])
        self.assertFalse(self.outcome)
        self.assertIsNotNone(self.staff.get("clerk"))


if __name__ == "__main__":
    unittest.main()
