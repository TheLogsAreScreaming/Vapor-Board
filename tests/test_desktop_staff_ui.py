"""Sign-in screen, lock, and the Staff page in the real Tk window; skipped without a display."""
from unittest import mock
from desktop_harness import DesktopHarness, walk, OWNER, OWNER_PASSWORD
from vapor_board import desktop
from vapor_board.accounts import StaffDirectory


class DesktopStaffUiTests(DesktopHarness):
    def entry(self, root, name):
        return next(w for w in walk(root) if w.winfo_name() == name)

    def type_into(self, root, name, text):
        entry = self.entry(root, name)
        entry.delete(0, "end")
        entry.insert(0, text)

    def gate_button(self, root, text):
        return next(w for w in walk(self.gate(root)) if w.winfo_class() == "TButton" and w.cget("text") == text)

    def test_first_launch_creates_the_owner_account(self):
        self.staff_path.unlink()
        self.sign_in_as = None

        def scenario(root):
            self.assertIsNotNone(self.gate(root))
            self.assertIn("Set up Vapor Board", self.labels(self.gate(root)))
            for name, value in (("name", "Dana"), ("username", "dana"), ("password", "longpassword"), ("confirm", "different")):
                self.gate_entry(root, name).insert(0, value)
            self.gate_button(root, "Create owner account").invoke()
            self.assertIn("The passwords don't match.", self.labels(self.gate(root)))
            confirm = self.gate_entry(root, "confirm")
            confirm.delete(0, "end")
            confirm.insert(0, "longpassword")
            self.gate_button(root, "Create owner account").invoke()
            root.update()
            self.assertIsNone(self.gate(root))
            self.assertEqual(self.toast(root), "Owner account created: Add your staff on the Staff page.")
            self.assertIn("Dana  ·  Owner / admin", self.labels(root))

        self.run_desktop(scenario)
        self.assertTrue(StaffDirectory(self.staff_path).get("dana").is_admin)

    def test_wrong_password_is_refused(self):
        self.sign_in_as = None

        def scenario(root):
            self.assertIn("Sign in to Vapor Board", self.labels(self.gate(root)))
            self.gate_entry(root, "username").insert(0, OWNER)
            self.gate_entry(root, "password").insert(0, "not it")
            self.gate_button(root, "Sign in").invoke()
            self.assertIn("That username and password don't match an active account.", self.labels(self.gate(root)))
            self.assertEqual(self.gate_entry(root, "password").get(), "")
            self.sign_in(root, OWNER, OWNER_PASSWORD)
            self.assertIsNone(self.gate(root))

        self.run_desktop(scenario)

    def test_lock_returns_to_sign_in_and_logs_it(self):
        def scenario(root):
            self.assertIn("Operator  ·  Owner / admin", self.labels(root))
            self.buttons(root)["Lock"].invoke()
            root.update()
            self.assertIsNotNone(self.gate(root))
            self.sign_in(root, OWNER, OWNER_PASSWORD)
            self.assertIsNone(self.gate(root))

        self.run_desktop(scenario)
        actions = [entry["action"] for entry in StaffDirectory(self.staff_path).activity()]
        self.assertEqual(actions[:3], ["signed in", "signed out", "signed in"])

    def test_owner_adds_staff_who_then_cannot_manage_accounts(self):
        def scenario(root):
            buttons = self.buttons(root, "Staff")
            team = self.lists(root, "Staff")[0]
            self.assertEqual(self.rows(team), ("Operator (you)  ·  owner  ·  Owner / admin",))
            for name, value in (("add_name", "Jess"), ("add_username", "jess"), ("add_password", "password1")):
                self.type_into(root, name, value)
            buttons["Add staff member"].invoke()
            self.assertEqual(self.toast(root), "Staff member added: Jess can now sign in as “jess”.")
            self.assertEqual(self.rows(team), ("Operator (you)  ·  owner  ·  Owner / admin", "Jess  ·  jess  ·  Staff"))
            self.assertEqual(team.selection(), ("1",))
            self.assertTrue(self.enabled(buttons["Disable"]))
            self.assert_page_fits(root, "Staff")

            self.buttons(root)["Lock"].invoke()
            root.update()
            self.sign_in(root, "jess", "password1")
            self.nav(root, "Staff").invoke()
            root.update()
            buttons = self.buttons(root, "Staff")
            self.assertFalse(self.enabled(buttons["Add staff member"]))
            self.pick(root, team, 0)
            self.assertFalse(self.enabled(buttons["Disable"]))
            self.assertFalse(self.enabled(buttons["Set password"]))
            self.pick(root, team, 1)
            self.assertTrue(self.enabled(buttons["Set password"]))
            self.type_into(root, "new_password", "brand new pass")
            buttons["Set password"].invoke()
            self.assertEqual(self.toast(root), "Password changed: Jess signs in with the new password from now on.")

        self.run_desktop(scenario, page="Staff")
        self.assertIsNotNone(StaffDirectory(self.staff_path).authenticate("jess", "brand new pass"))

    def test_disable_and_activity_log(self):
        owner = self.staff.authenticate(OWNER, OWNER_PASSWORD)
        self.staff.create("jess", "Jess", "password1", actor=owner, iterations=1000)

        def scenario(root):
            team = self.lists(root, "Staff")[0]
            self.pick(root, team, 1)
            self.buttons(root, "Staff")["Disable"].invoke()
            self.assertEqual(self.toast(root), "Account disabled: Jess can no longer sign in.")
            self.assertEqual(self.rows(team)[1], "Jess  ·  jess  ·  Staff  ·  Disabled")
            self.buttons(root, "Staff")["Activity log"].invoke()
            root.update()
            self.assertIn("owner  ·  account disabled  ·  jess", self.rows(team)[0])
            self.assertFalse(self.buttons(root, "Staff")["Set password"].winfo_ismapped())
            self.assert_page_fits(root, "Staff")

        self.run_desktop(scenario, page="Staff")

    def test_board_actions_are_recorded_under_the_signed_in_name(self):
        def scenario(root):
            entry = next(w for w in walk(self.page(root, "Boards")) if w.winfo_class() == "TEntry")
            entry.insert(0, "Closures")
            self.buttons(root, "Boards")["Add board"].invoke()

        self.run_desktop(scenario)
        latest = StaffDirectory(self.staff_path).activity()[0]
        self.assertEqual((latest["actor"], latest["action"], latest["detail"]), (OWNER, "board created", "Closures"))

    def test_auto_lock_after_idle_minutes(self):
        self.write_shop({"auto_lock_minutes": 1})

        def scenario(root):
            pending = root.tk.call("after", "info")
            self.assertTrue(pending)
            # Pretend a long idle spell has passed, then run the waiting timers (the lock check among them).
            with mock.patch.object(desktop.time, "monotonic", return_value=10 ** 9):
                for job in pending:
                    try:
                        root.tk.eval(root.tk.call("after", "info", job)[0])
                    except Exception:
                        pass  # a timer that only makes sense later (e.g. a fading notice)
            root.update()
            self.assertIsNotNone(self.gate(root))

        self.run_desktop(scenario)
        self.assertEqual(StaffDirectory(self.staff_path).activity()[0]["action"], "locked after inactivity")


if __name__ == "__main__":
    import unittest
    unittest.main()
