"""Customers page in the real Tk window; skipped without a display."""
from unittest import mock
from desktop_harness import DesktopHarness, walk
from vapor_board import desktop
from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook


class DesktopCustomersUiTests(DesktopHarness):
    def type_into(self, root, name, text):
        entry = next(w for w in walk(root) if w.winfo_name() == name)
        entry.delete(0, "end")
        entry.insert(0, text)

    def test_add_then_approve_after_confirming_the_id_check(self):
        def scenario(root):
            customers = self.lists(root, "Customers")[0]
            self.assertEqual(self.placeholder(customers), "No customers yet — add one on the right")
            self.type_into(root, "customer_name", "Sam Lee")
            self.type_into(root, "customer_node", "!A1B2C3D4")
            self.buttons(root, "Customers")["Add customer"].invoke()
            self.assertEqual(self.toast(root), "Customer added: Sam Lee is waiting for approval.")
            self.assertEqual(self.rows(customers), ("Sam Lee  ·  Waiting for approval  ·  !a1b2c3d4",))
            buttons = self.buttons(root, "Customers")
            self.assertTrue(self.enabled(buttons["Approve…"]))
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=False) as ask:
                buttons["Approve…"].invoke()
            self.assertEqual(ask.call_args.kwargs["default"], "no")
            self.assertIn("21 or older", ask.call_args.args[1])
            self.assertFalse(CustomerBook(self.database).customers()[0].approved)
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=True):
                buttons["Approve…"].invoke()
            self.assertEqual(self.toast(root), "Customer approved: Sam Lee can now read the visible boards.")
            self.assertEqual(self.rows(customers), ("Sam Lee  ·  Approved  ·  !a1b2c3d4",))
            self.assertFalse(self.enabled(buttons["Approve…"]))
            self.assertTrue(any("ID checked by owner" in text for text in self.labels(self.page(root, "Customers"))))
            self.assert_page_fits(root, "Customers")

        self.run_desktop(scenario, page="Customers")
        customer = CustomerBook(self.database).customers()[0]
        self.assertEqual((customer.approved, customer.verified_by), (True, "owner"))
        actions = [e["action"] for e in self.staff.activity()]
        self.assertEqual(actions[:2], ["customer approved", "customer added"])

    def test_bad_node_id_is_explained(self):
        def scenario(root):
            self.type_into(root, "customer_name", "Sam")
            self.type_into(root, "customer_node", "12345")
            self.buttons(root, "Customers")["Add customer"].invoke()
            self.assertTrue(self.toast(root).startswith("Customer not added: Radio node IDs look like"))

        self.run_desktop(scenario, page="Customers")
        self.assertEqual(CustomerBook(self.database).customers(), [])

    def test_remove_access_and_delete(self):
        owner = self.staff.get("owner")
        book = CustomerBook(self.database)
        sam = book.add("Sam", actor=owner)
        book.approve(sam.id, owner, True)

        def scenario(root):
            customers = self.lists(root, "Customers")[0]
            self.pick(root, customers, 0)
            self.buttons(root, "Customers")["Remove access"].invoke()
            self.assertEqual(self.rows(customers), ("Sam  ·  Access removed",))
            self.pick(root, customers, 0)
            with mock.patch.object(desktop.messagebox, "askyesno", return_value=True):
                self.buttons(root, "Customers")["Delete"].invoke()
            self.assertEqual(self.rows(customers), ())

        self.run_desktop(scenario, page="Customers")
        self.assertEqual(CustomerBook(self.database).customers(), [])

    def test_mark_a_board_staff_only(self):
        bbs = BulletinBoard(self.database)
        bbs.create_board("Hours")
        notes = bbs.create_board("Staff notes")

        def scenario(root):
            self.buttons(root, "Customers")["Visible boards"].invoke()
            root.update()
            boards = self.lists(root, "Customers")[0]
            self.assertEqual(self.rows(boards), ("Visible  ·  Hours", "Visible  ·  Staff notes"))
            self.pick(root, boards, 1)
            self.buttons(root, "Customers")["Hide from customers"].invoke()
            self.assertEqual(self.rows(boards), ("Visible  ·  Hours", "Staff only  ·  Staff notes"))
            self.assertEqual(self.buttons(root, "Customers")["Show to customers"].winfo_ismapped(), True)
            self.assert_page_fits(root, "Customers")

        self.run_desktop(scenario, page="Customers")
        self.assertEqual(BulletinBoard(self.database).board_visibility()[notes], False)


    def test_staff_answer_and_decline_questions(self):
        from types import SimpleNamespace
        from unittest import mock
        from vapor_board import desktop
        from vapor_board.bbs import BulletinBoard
        from vapor_board.customers import CustomerBook

        database = self.home / ".vapor-board" / "bbs.sqlite"
        bbs = BulletinBoard(database)
        board = bbs.create_board("Store hours")
        staff = SimpleNamespace(username="owner", active=True)
        book = CustomerBook(database)
        customer = book.add("Sam", actor=staff)
        book.add_question(customer, board, "Open Sunday?")
        book.add_question(customer, board, "Any deals?")

        def scenario(root):
            self.buttons(root, "Customers")["Questions"].invoke()
            root.update()
            questions = self.lists(root, "Customers")[0]
            self.assertEqual(len(questions.get_children()), 2)
            self.assert_page_fits(root, "Customers")
            questions.selection_set("0")
            root.update()
            with mock.patch.object(desktop.simpledialog, "askstring", return_value="Noon to 5"):
                self.buttons(root, "Customers")["Answer…"].invoke()
            root.update()
            questions.selection_set("0")
            root.update()
            self.buttons(root, "Customers")["Decline"].invoke()
            root.update()
            self.assertEqual(self.placeholder(questions), "No questions waiting")

        self.run_desktop(scenario, page="Customers")
        self.assertEqual(book.questions(), [])
        bodies = [p["body"] for p in BulletinBoard(database).list_posts(board)]
        self.assertIn("Q: Open Sunday?\nA: Noon to 5", bodies)
        self.assertFalse(any("Any deals" in body for body in bodies))


if __name__ == "__main__":
    import unittest
    unittest.main()
