import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from vapor_board import meshwire
from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook
from vapor_board.frame_reader import FramedTcpReader
from vapor_board.radio_replies import RadioReplies
from vapor_board.radio_session import RadioSession
from vapor_board.tcp import ConnectionState, MeshtasticTcpClient, TcpSettings

ME, SAM, STRANGER = 0xDEADBEEF, 0xA1B2C3D4, 0x01020304
STAFF = SimpleNamespace(username="jess", active=True)


def dm(text, sender=SAM, to=ME, packet_id=1, **extra):
    return {"variant": "packet", "from": sender, "to": to, "channel": 0, "id": packet_id, "portnum": 1, "text": text,
            "via_mqtt": False, **extra}


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class RadioRepliesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "bbs.sqlite"
        self.bbs = BulletinBoard(self.db)
        self.hours = self.bbs.create_board("Store hours")
        self.notes = self.bbs.create_board("Staff notes")
        self.bbs.set_customer_visible(self.notes, False)
        self.bbs.post(self.hours, "Op", "Open 10-8 today")
        self.bbs.post(self.hours, "Op", "Hidden until 2099", publish_at="2099-01-01 00:00:00")
        book = CustomerBook(self.db)
        self.sam = book.add("Sam", node_id=meshwire.node_id(SAM), actor=STAFF)
        book.approve(self.sam.id, STAFF, True)
        book.add("Pending Pat", node_id="!0a0b0c0d", actor=STAFF)
        self.clock = Clock()
        self.router = RadioReplies(self.db, "Corner Shop", "Corner Shop", clock=self.clock, per_customer=50, per_shop=50)
        self.router.handle({"variant": "my_info", "node_num": ME})
        self.ids = iter(range(100, 10_000))

    def test_more_pages_through_older_posts(self):
        for number in range(1, 8):
            self.bbs.post(self.hours, "Op", f"note {number}")
        first = self.ask("read 1").replies[0]
        self.assertEqual(first, "Store hours (send more for older): note 7 | note 6 | note 5")
        self.assertEqual(self.ask("more").replies[0], "Store hours (send more for older): note 4 | note 3 | note 2")
        self.assertEqual(self.ask("more").replies[0], "Store hours: note 1 | Open 10-8 today")
        self.assertEqual(self.ask("more").replies[0], "Send read and a board number first.")

    def test_questions_wait_for_staff_and_post_without_the_name(self):
        reply = self.ask("ask 1 Open Sunday?").replies[0]
        self.assertIn("Staff will review", reply)
        self.assertEqual(self.ask("read 1").replies[0], "Store hours: Open 10-8 today")
        book = CustomerBook(self.db)
        question = book.questions()[0]
        self.assertEqual((question.customer_name, question.body), ("Sam", "Open Sunday?"))
        book.answer_question(question.id, "Noon to 5", "Corner Shop", STAFF)
        self.assertEqual(book.questions(), [])
        text = self.ask("read 1").replies[0]
        self.assertIn("Q: Open Sunday? A: Noon to 5", text)
        self.assertNotIn("Sam", text)

    def test_questions_are_limited_and_declining_posts_nothing(self):
        for number in range(3):
            self.assertIn("Staff will review", self.ask(f"ask 1 question {number}").replies[0])
        self.assertIn("waiting already", self.ask("ask 1 one more").replies[0])
        self.assertEqual(self.ask("ask 9 nope").note, "ask: incomplete")
        self.assertEqual(self.ask("ask 1").note, "ask: incomplete")
        book = CustomerBook(self.db)
        book.decline_question(book.questions()[0].id, STAFF)
        self.assertEqual(len(book.questions()), 2)
        self.assertEqual(self.ask("read 1").replies[0], "Store hours: Open 10-8 today")

    def test_answering_needs_staff(self):
        self.ask("ask 1 hello?")
        book = CustomerBook(self.db)
        with self.assertRaises(Exception):
            book.answer_question(book.questions()[0].id, "hi", "Shop", None)

    def test_follow_shows_only_newer_posts_and_only_once(self):
        self.assertIn("aren't following", self.ask("new").replies[0])
        self.assertIn("Following Store hours", self.ask("follow 1").replies[0])
        self.assertEqual(self.ask("new").replies[0], "No new posts.")
        for number in range(1, 5):
            self.bbs.post(self.hours, "Op", f"note {number}")
        self.assertEqual(self.ask("new").replies[0], "Store hours: note 1 | Store hours: note 2 | Store hours: note 3 (send new for more)")
        self.assertEqual(self.ask("new").replies[0], "Store hours: note 4")
        self.assertEqual(self.ask("new").replies[0], "No new posts.")
        self.ask("unfollow 1")
        self.bbs.post(self.hours, "Op", "later")
        self.assertIn("aren't following", self.ask("new").replies[0])

    def test_new_skips_boards_hidden_since_following(self):
        self.ask("follow 1")
        self.bbs.post(self.hours, "Op", "secret now")
        self.bbs.set_customer_visible(self.hours, False)
        self.assertIn("aren't following", self.ask("new").replies[0])

    def test_scheduled_post_counts_as_new_when_it_appears(self):
        self.ask("follow 1")
        hidden = self.bbs.customer_posts(self.hours)
        self.assertEqual(len(hidden), 1)  # the 2099 post isn't marked seen
        self.assertNotIn(2, CustomerBook(self.db).seen_posts(self.sam.id))

    def test_deleting_a_customer_clears_their_questions_and_follows(self):
        self.ask("ask 1 hello?")
        self.ask("follow 1")
        book = CustomerBook(self.db)
        book.remove(self.sam.id, STAFF)
        self.assertEqual(book.questions(), [])
        self.assertEqual(book.followed_boards(self.sam.id), set())
        self.assertEqual(book.seen_posts(self.sam.id), set())

    def test_info_sends_only_what_is_set(self):
        self.assertEqual(self.ask("info").replies[0], "Corner Shop. No shop details set.")
        self.router.hours, self.router.contact = "10-8 daily", ""
        self.assertEqual(self.ask("info").replies[0], "Corner Shop. Hours: 10-8 daily")

    def test_more_stops_when_the_board_is_hidden(self):
        for number in range(1, 6):
            self.bbs.post(self.hours, "Op", f"note {number}")
        self.ask("read 1")
        self.bbs.set_customer_visible(self.hours, False)
        self.assertEqual(self.ask("more").replies[0], "Send read and a board number first.")

    def ask(self, text, **extra):
        return self.router.handle(dm(text, packet_id=next(self.ids), **extra))

    def test_commands(self):
        self.assertIn("Commands:", self.ask("help").replies[0])
        self.assertEqual(self.ask("/BOARDS").replies, ["1 Store hours. Send: read N"])
        self.assertEqual(self.ask("read 1").replies, ["Store hours: Open 10-8 today"])
        self.assertTrue(self.ask("read 7").replies[0].startswith("Send read and a board number from 1 to 1"))
        self.assertEqual(self.ask("dance").note, "unknown command")

    def test_msg_and_inbox_round_trip(self):
        outcome = self.ask("msg Do you have size 10?")
        self.assertTrue(outcome.replies[0].startswith("Sent to Corner Shop."))
        self.assertEqual(self.bbs.inbox("Corner Shop")[0]["sender"], "Sam")
        self.assertEqual(self.ask("inbox").replies, ["No new messages."])
        self.bbs.send_mail("Corner Shop", "Sam", "Yes, in stock!")
        self.assertEqual(self.ask("inbox").replies, ["Corner Shop: Yes, in stock!"])
        self.assertEqual(self.ask("inbox").replies, ["No new messages."])

    def test_only_direct_messages_from_approved_customers_get_replies(self):
        cases = {
            "broadcast": dm("help", to=meshwire.BROADCAST, packet_id=1),
            "someone else's DM": dm("help", to=0x55555555, packet_id=2),
            "unregistered node": dm("help", sender=STRANGER, packet_id=3),
            "pending customer": dm("help", sender=0x0A0B0C0D, packet_id=4),
            "via MQTT": dm("help", packet_id=5, via_mqtt=True),
            "not text": dm("help", packet_id=6, portnum=67),
            "our own echo": dm("help", sender=ME, packet_id=7),
        }
        for name, event in cases.items():
            with self.subTest(name):
                self.assertEqual(self.router.handle(event).replies, [])
        self.assertEqual(self.router.handle(cases["unregistered node"] | {"id": 30}).note, "no reply to unregistered radio !01020304")

    def test_nothing_is_answered_before_the_radio_says_who_it_is(self):
        fresh = RadioReplies(self.db, "Corner Shop", "Corner Shop")
        self.assertEqual(fresh.handle(dm("help")).replies, [])

    def test_duplicates_answered_once(self):
        self.assertTrue(self.router.handle(dm("help", packet_id=42)).replies)
        self.assertEqual(self.router.handle(dm("help", packet_id=42)).replies, [])

    def test_rate_limits(self):
        self.router = RadioReplies(self.db, "Corner Shop", "Corner Shop", clock=self.clock)
        self.router.handle({"variant": "my_info", "node_num": ME})
        for _ in range(3):
            self.assertTrue(self.ask("help").replies)
        limited = self.ask("help")
        self.assertEqual((limited.replies, limited.note), ([], "rate limit: no reply to Sam"))
        self.clock.now += 61
        self.assertTrue(self.ask("help").replies)

    def test_staff_only_and_scheduled_posts_stay_hidden(self):
        reply = " ".join(self.ask("read 1").replies + self.ask("boards").replies)
        self.assertNotIn("Hidden until", reply)
        self.assertNotIn("Staff notes", reply)

    def test_long_replies_are_split(self):
        self.bbs.post(self.hours, "Op", "word " * 150)
        replies = self.ask("read 1").replies
        self.assertEqual(len(replies), 3)
        self.assertTrue(all(len(r.encode()) <= meshwire.MAX_TEXT_BYTES for r in replies))
        self.assertTrue(replies[-1].endswith("…"))


class FakeSocket:
    def __init__(self, chunks=()):
        self.chunks, self.sent = list(chunks), []

    def recv(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def sendall(self, data):
        self.sent.append(bytes(data))

    def shutdown(self, how):
        pass

    def close(self):
        pass


class LinkTests(unittest.TestCase):
    def client(self, sock, transmit=False):
        return MeshtasticTcpClient(TcpSettings(transmissions_enabled=transmit), socket_factory=lambda addr, timeout: sock)

    def test_connect_asks_for_config_but_never_transmits_by_default(self):
        sock = FakeSocket()
        session = RadioSession(client=self.client(sock))
        self.assertTrue(session.connect())
        self.assertEqual(len(sock.sent), 1)
        self.assertEqual(meshwire.fields(sock.sent[0][4:])[0][0], 3)  # want_config_id
        self.assertFalse(session.can_transmit)
        with self.assertRaises(PermissionError):
            session.send_text(SAM, "hi")
        with self.assertRaises(PermissionError):
            session.reader.client.transmit(meshwire.text_message(SAM, "hi", 1))
        with self.assertRaises(PermissionError):
            session.reader.client.send_control(meshwire.text_message(SAM, "hi", 1))
        with self.assertRaises(PermissionError):
            session.reader.client.send(b"x")
        session.keep_alive()
        self.assertEqual(meshwire.fields(sock.sent[-1][4:])[0][0], 7)  # heartbeat

    def test_transmit_on_sends_only_direct_text(self):
        sock = FakeSocket()
        session = RadioSession(client=self.client(sock, transmit=True))
        session.connect()
        session.send_text(SAM, "Store hours: Open 10-8")
        packet = meshwire.fields(meshwire.fields(sock.sent[-1][4:])[0][2])
        self.assertEqual(dict((n, v) for n, _w, v in packet)[2], SAM)
        with self.assertRaises(ValueError):
            session.send_text(meshwire.BROADCAST, "everyone")

    def test_a_quiet_radio_keeps_the_connection(self):
        frame = meshwire.frame(b"\x1a\x06\x08" + meshwire._varint(ME))  # FromRadio{my_info{my_node_num}}
        sock = FakeSocket([socket.timeout(), frame[:3], socket.timeout(), frame[3:]])
        session = RadioSession(client=self.client(sock))
        session.connect()
        self.assertEqual(session.receive(), [])
        self.assertEqual(session.receive(), [])
        self.assertEqual(session.receive(), [])
        self.assertEqual(session.state, ConnectionState.CONNECTED)
        self.assertEqual(session.receive(), [{"variant": "my_info", "node_num": ME}])
        self.assertTrue(session.protocol_verified)


class OfficialProtobufTests(unittest.TestCase):
    """Cross-check the hand-written codec with the official bindings, when installed."""
    def setUp(self):
        try:
            from meshtastic.protobuf import mesh_pb2, portnums_pb2
        except ImportError:
            self.skipTest("meshtastic package not installed")
        self.mesh, self.ports = mesh_pb2, portnums_pb2

    def test_round_trip(self):
        message = self.mesh.ToRadio()
        message.ParseFromString(meshwire.text_message(SAM, "héllo", 77, channel=2)[4:])
        packet = message.packet
        self.assertEqual((packet.to, packet.channel, packet.decoded.portnum, packet.decoded.payload.decode(), packet.id, packet.want_ack),
                         (SAM, 2, self.ports.TEXT_MESSAGE_APP, "héllo", 77, True))
        message.ParseFromString(meshwire.want_config(5)[4:])
        self.assertEqual(message.want_config_id, 5)
        incoming = self.mesh.FromRadio(id=9)
        incoming.packet.CopyFrom(self.mesh.MeshPacket(**{"from": SAM}, to=ME, channel=1, id=99))
        incoming.packet.decoded.portnum = self.ports.TEXT_MESSAGE_APP
        incoming.packet.decoded.payload = b"read 1"
        decoded = meshwire.decode_from_radio(incoming.SerializeToString())
        self.assertEqual((decoded["from"], decoded["to"], decoded["channel"], decoded["id"], decoded["text"]), (SAM, ME, 1, 99, "read 1"))


class WireTests(unittest.TestCase):
    def test_malformed_bytes_are_rejected(self):
        for bad in (b"\x12\x10ab", b"\x80", b"\x0f"):
            with self.subTest(bad=bad), self.assertRaises(meshwire.WireError):
                meshwire.decode_from_radio(bad)

    def test_text_limits(self):
        with self.assertRaises(ValueError):
            meshwire.text_message(SAM, "x" * 201, 1)
        with self.assertRaises(ValueError):
            meshwire.text_message(0, "x", 1)


if __name__ == "__main__":
    unittest.main()
