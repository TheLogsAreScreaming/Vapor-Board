import socket
import unittest
from vapor_board import meshcore_link as mc
from vapor_board.meshcore_link import FrameDecoder, MeshCoreSession, MeshCoreSettings, make_session
from vapor_board.radio_session import RadioSession
from vapor_board.tcp import TcpSettings


def from_radio(payload):
    return b">" + len(payload).to_bytes(2, "little") + payload


class FakeSocket:
    def __init__(self):
        self.incoming, self.sent = [], []

    def recv(self, _size):
        if not self.incoming:
            raise socket.timeout()
        return self.incoming.pop(0)

    def sendall(self, data):
        self.sent.append(bytes(data))

    def shutdown(self, _how):
        pass

    def close(self):
        pass


class FramingTests(unittest.TestCase):
    def test_requests_match_the_companion_format(self):
        self.assertEqual(mc.sync_next(), b"<\x01\x00\x0a")
        self.assertEqual(mc.device_query(), b"<\x02\x00\x16\x03")
        self.assertEqual(mc.app_start()[:11], b"<\x13\x00\x01\x03" + b"\x00" * 6)

    def test_only_listen_requests_can_be_framed(self):
        for code in (2, 3, 7, 0):  # send message, send channel message, advert, nothing
            with self.subTest(code=code), self.assertRaises(PermissionError):
                mc.frame(bytes([code]) + b"hello")

    def test_decoder_handles_noise_and_split_frames(self):
        decoder = FrameDecoder()
        whole = from_radio(b"\x0a") + from_radio(b"\x83")
        self.assertEqual(decoder.feed(b"boot log" + whole[:4]), [b"\x0a"])
        self.assertEqual(decoder.feed(whole[4:]), [b"\x83"])

    def test_oversize_length_is_not_a_frame(self):
        self.assertEqual(FrameDecoder().feed(b">\xff\xff" + from_radio(b"\x0a")), [b"\x0a"])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSocket()
        self.session = MeshCoreSession(MeshCoreSettings("10.0.0.9"), socket_factory=lambda _a, _t: self.fake)
        self.assertTrue(self.session.connect())

    def test_connect_sends_only_local_requests(self):
        self.assertEqual([frame[3] for frame in self.fake.sent], [mc.CMD_APP_START, mc.CMD_DEVICE_QUERY])

    def test_waiting_messages_are_collected_and_their_text_is_dropped(self):
        self.fake.sent.clear()
        text = b"\x07" + b"\x01" * 6 + b"\x00\x00" + b"\x00" * 4 + b"private words"
        self.fake.incoming = [from_radio(b"\x83"), from_radio(text)]
        first = self.session.receive()
        self.assertEqual(first, [{"variant": "meshcore_other", "code": 0x83}])
        second = self.session.receive()
        self.assertEqual(second, [{"variant": "meshcore_message", "kind": "direct"}])
        self.assertNotIn("private", repr(second))
        self.assertEqual(self.fake.sent, [mc.sync_next(), mc.sync_next()])
        self.assertTrue(self.session.protocol_verified)

    def test_channel_messages_and_v3_are_recognised(self):
        self.fake.incoming = [from_radio(b"\x08\x00"), from_radio(b"\x11\x00"), from_radio(b"\x10\x00")]
        kinds = [self.session.receive()[0]["kind"] for _ in range(3)]
        self.assertEqual(kinds, ["channel", "channel", "direct"])

    def test_quiet_radio_is_fine(self):
        self.assertEqual(self.session.receive(), [])

    def test_there_is_no_way_to_send_text(self):
        self.assertFalse(hasattr(self.session, "send_text"))
        with self.assertRaises(PermissionError):
            self.session.send("hello")


class FactoryTests(unittest.TestCase):
    def test_picks_the_session_by_settings(self):
        self.assertIsInstance(make_session(MeshCoreSettings("10.0.0.9")), MeshCoreSession)
        self.assertIsInstance(make_session(TcpSettings()), RadioSession)
        self.assertIsInstance(make_session(None), RadioSession)

    def test_bad_settings_are_refused(self):
        with self.assertRaises(ValueError):
            MeshCoreSettings("10.0.0.9", port=0)


if __name__ == "__main__":
    unittest.main()
