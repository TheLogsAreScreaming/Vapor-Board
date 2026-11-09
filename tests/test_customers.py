import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook, CustomerError, normalise_node

STAFF = SimpleNamespace(username="jess", active=True)


class CustomerBookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "bbs.sqlite"
        self.book = CustomerBook(self.path)

    def test_new_customers_wait_for_approval(self):
        sam = self.book.add("  Sam   Lee ", "555-0100", "!A1B2C3D4", actor=STAFF)
        self.assertEqual((sam.name, sam.contact, sam.node_id, sam.status, sam.approved), ("Sam Lee", "555-0100", "!a1b2c3d4", "pending", False))
        self.assertEqual(self.book.pending_count(), 1)

    def test_approval_needs_staff_and_an_in_person_id_check(self):
        sam = self.book.add("Sam", actor=STAFF)
        with self.assertRaisesRegex(CustomerError, "ID in person"):
            self.book.approve(sam.id, STAFF, id_checked_21_plus=False)
        with self.assertRaisesRegex(CustomerError, "Sign in"):
            self.book.approve(sam.id, None, id_checked_21_plus=True)
        with self.assertRaisesRegex(CustomerError, "Sign in"):
            self.book.approve(sam.id, SimpleNamespace(username="old", active=False), id_checked_21_plus=True)
        done = self.book.approve(sam.id, STAFF, id_checked_21_plus=True)
        self.assertTrue(done.approved)
        self.assertEqual(done.verified_by, "jess")
        self.assertTrue(done.verified_at)
        self.assertEqual(self.book.pending_count(), 0)

    def test_revoke_and_remove(self):
        sam = self.book.add("Sam", node_id="a1b2c3d4", actor=STAFF)
        self.book.approve(sam.id, STAFF, True)
        self.assertFalse(self.book.revoke(sam.id, STAFF).approved)
        self.assertEqual(self.book.by_node("!A1B2C3D4").name, "Sam")
        self.book.remove(sam.id, STAFF)
        self.assertIsNone(self.book.get(sam.id))
        self.assertIsNone(self.book.by_node("!a1b2c3d4"))
        with self.assertRaises(CustomerError):
            self.book.remove(sam.id, STAFF)

    def test_list_order_pending_first(self):
        for name in ("Zed", "Amy", "Bo"):
            self.book.add(name, actor=STAFF)
        self.book.approve(self.book.customers()[0].id, STAFF, True)  # Amy
        self.assertEqual([c.name for c in self.book.customers()], ["Bo", "Zed", "Amy"])

    def test_input_rules(self):
        self.assertEqual(normalise_node(""), "")
        for bad in ("!xyz", "!a1b2c3d", "a1b2c3d4e", "!a1b2 c3d4"):
            with self.subTest(node=bad), self.assertRaises(CustomerError):
                normalise_node(bad)
        with self.assertRaisesRegex(CustomerError, "name"):
            self.book.add("   ", actor=STAFF)
        self.book.add("Sam", node_id="!a1b2c3d4", actor=STAFF)
        with self.assertRaisesRegex(CustomerError, "already belongs"):
            self.book.add("Other", node_id="!A1B2C3D4", actor=STAFF)

    def test_customers_live_in_the_board_database_and_survive_backups(self):
        from vapor_board import backup
        BulletinBoard(self.path).create_board("General")
        self.book.add("Sam", actor=STAFF)
        made = backup.create_backup(self.path, Path(self.directory.name) / "backups")
        self.assertEqual([c.name for c in CustomerBook(made.path).customers()], ["Sam"])


class BoardVisibilityTests(unittest.TestCase):
    def test_boards_are_visible_until_marked_staff_only(self):
        with tempfile.TemporaryDirectory() as folder:
            bbs = BulletinBoard(Path(folder) / "bbs.sqlite")
            hours, staff = bbs.create_board("Hours"), bbs.create_board("Staff notes")
            self.assertEqual(bbs.board_visibility(), {hours: True, staff: True})
            bbs.set_customer_visible(staff, False)
            self.assertEqual([b["name"] for b in bbs.customer_boards()], ["Hours"])
            self.assertEqual(bbs.list_boards(), [{"id": hours, "name": "Hours"}, {"id": staff, "name": "Staff notes"}])
            with self.assertRaises(ValueError):
                bbs.set_customer_visible(99, True)



class ForgetCustomerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "bbs.sqlite"
        self.bbs = BulletinBoard(self.db)
        self.book = CustomerBook(self.db)
        self.staff = SimpleNamespace(username="jess", active=True)

    def test_deleting_removes_their_messages_only(self):
        sam = self.book.add("Sam", actor=self.staff)
        self.bbs.send_mail("Sam", "Shop", "hello")
        self.bbs.send_mail("Shop", "Sam", "hi")
        self.bbs.send_mail("Pat", "Shop", "keep me")
        self.assertTrue(self.book.remove(sam.id, self.staff, ["Shop"]))
        self.assertEqual([m["body"] for m in self.bbs.inbox("Shop")], ["keep me"])
        self.assertEqual(self.bbs.inbox("Sam"), [])

    def test_shared_or_staff_names_keep_their_messages(self):
        first = self.book.add("Sam", actor=self.staff)
        second = self.book.add("sam", actor=self.staff)
        staff_named = self.book.add("Jess", actor=self.staff)
        self.bbs.send_mail("Sam", "Shop", "hello")
        self.bbs.send_mail("Jess", "Shop", "staff note")
        self.assertFalse(self.book.remove(first.id, self.staff, ["Shop"]))
        self.assertFalse(self.book.remove(staff_named.id, self.staff, ["Shop", "jess"]))
        self.assertEqual(len(self.bbs.inbox("Shop")), 2)
        self.assertTrue(self.book.remove(second.id, self.staff, ["Shop"]))  # now the only Sam


if __name__ == "__main__":
    unittest.main()
