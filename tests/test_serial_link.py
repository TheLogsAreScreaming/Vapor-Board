"""USB link over a pseudo-terminal, so no radio is needed."""
import os
import pty
import socket
import unittest
from unittest import mock
from vapor_board import meshwire, serial_link
from vapor_board.radio_session import RadioSession
from vapor_board.serial_link import MeshtasticSerialClient, SerialPort, SerialSettings
from vapor_board.tcp import ConnectionState


class SerialTests(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        self.path = os.ttyname(slave)
        self.addCleanup(os.close, slave)
        self.addCleanup(os.close, self.master)

    def test_settings_accept_only_device_paths(self):
        for bad in ("", "radio.local", "/etc/passwd", 5):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    SerialSettings(path=bad)
        self.assertEqual(SerialSettings(path="/dev/cu.usbserial-1").host, "/dev/cu.usbserial-1")

    def test_port_reads_writes_and_reports_quiet(self):
        port = SerialPort(self.path, 0.05)
        self.addCleanup(port.close)
        with self.assertRaises(socket.timeout):
            port.recv(16)
        os.write(self.master, b"\x94\xc3")
        self.assertEqual(port.recv(16), b"\x94\xc3")
        port.sendall(b"hello")
        self.assertEqual(os.read(self.master, 16), b"hello")

    def test_closed_port_raises_oserror(self):
        port = SerialPort(self.path, 0.05)
        port.close()
        port.close()
        with self.assertRaises(OSError):
            port.recv(1)

    def session(self, transmit=False):
        settings = SerialSettings(path="/dev/cu.fake", transmissions_enabled=transmit)
        with mock.patch("vapor_board.tcp.socket.create_connection", side_effect=AssertionError("network used")):
            port = SerialPort(self.path, 0.05)
            self.addCleanup(port.close)
            return RadioSession(client=MeshtasticSerialClient(settings, lambda address, timeout: port))

    def test_session_asks_for_config_and_stays_up_when_quiet(self):
        session = self.session()
        self.assertTrue(session.connect())
        self.assertEqual(os.read(self.master, 64)[:2], b"\x94\xc3")
        self.assertEqual(session.receive(), [])
        self.assertEqual(session.state, ConnectionState.CONNECTED)

    def test_transmit_stays_gated_over_usb(self):
        session = self.session(transmit=False)
        session.connect()
        with self.assertRaises(PermissionError):
            session.send_text(0x1234, "hi")
        with self.assertRaises(PermissionError):
            session.reader.client.send_control(meshwire.text_message(0x1234, "hi", 7))

    def test_session_picks_usb_from_settings(self):
        session = RadioSession(SerialSettings(path="/dev/cu.fake"))
        self.assertIsInstance(session.reader.client, MeshtasticSerialClient)

    def test_ports_exclude_bluetooth(self):
        with mock.patch.object(serial_link.glob, "glob", side_effect=lambda p: ["/dev/cu.usbserial-1"] if "usbserial" in p and "wch" not in p else []):
            self.assertEqual(serial_link.list_ports(), ["/dev/cu.usbserial-1"])


if __name__ == "__main__":
    unittest.main()
