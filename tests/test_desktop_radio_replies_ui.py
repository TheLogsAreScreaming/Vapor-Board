"""Radio replies wired through the real Tk window with a fake radio; skipped without a display."""
import time
from types import SimpleNamespace
from unittest import mock
from desktop_harness import DesktopHarness
from vapor_board import desktop
from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook

ME, SAM = 0xDEADBEEF, 0xA1B2C3D4


class DesktopRadioRepliesUiTests(DesktopHarness):
    def setUp(self):
        super().setUp()
        BulletinBoard(self.database).create_board("Store hours")
        book = CustomerBook(self.database)
        staff = SimpleNamespace(username="owner", active=True)
        sam = book.add("Sam", node_id="!a1b2c3d4", actor=staff)
        book.approve(sam.id, staff, True)

    def worker(self, events):
        worker = mock.Mock()
        worker.start.return_value = True
        worker.send_text.return_value = True
        worker.poll.side_effect = list(events) + [None] * 1000
        return worker

    @staticmethod
    def drain(root):
        for _ in range(3):
            time.sleep(0.12)
            root.update()

    def events(self):
        return [("protobuf", {"variant": "my_info", "node_num": ME}),
                ("protobuf", {"variant": "packet", "from": SAM, "to": ME, "channel": 0, "id": 7, "portnum": 1,
                              "text": "boards", "via_mqtt": False})]

    def test_replies_when_transmit_is_on(self):
        self.write_shop({"transmissions_enabled": True})
        worker = self.worker(self.events())

        def scenario(root):
            self.drain(root)
            worker.send_text.assert_called_once_with(SAM, "1 Store hours. Send: read N", 0)
            self.assertIn("Replies to approved customers", self.labels(root))

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(scenario, page="Overview")
        latest = self.staff.activity()[0]
        self.assertEqual((latest["actor"], latest["detail"]), ("radio", "listed boards (1 of 1 replies sent)"))

    def message_events(self):
        return self.events()[:1] + [("protobuf", {"variant": "packet", "from": SAM, "to": ME, "channel": 0, "id": n, "portnum": 1,
                                                  "text": "msg Open late?", "via_mqtt": False}) for n in (8, 9)]

    def test_customer_message_alerts_staff_once_without_naming_them_in_the_banner(self):
        self.write_shop({"transmissions_enabled": True, "shop_name": "Corner"})
        worker = self.worker(self.message_events())

        def scenario(root):
            self.drain(root)
            self.assertEqual(self.toast(root), "New customer message: From Sam. Open Messages to reply.")

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(scenario, page="Overview")
        self.banner.assert_called_once_with("Corner", "New customer message")

    def test_alerts_can_be_turned_off(self):
        self.write_shop({"transmissions_enabled": True, "message_alerts": False})
        worker = self.worker(self.message_events())

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(lambda root: self.drain(root), page="Overview")
        self.banner.assert_not_called()

    def test_silent_when_transmit_is_off(self):
        worker = self.worker(self.events())

        def scenario(root):
            self.drain(root)
            worker.send_text.assert_not_called()
            self.assertIn("Listen-only · transmit off", self.labels(root))

        with mock.patch.object(desktop, "RadioWorker", return_value=worker):
            self.run_desktop(scenario, page="Overview")


if __name__ == "__main__":
    import unittest
    unittest.main()
