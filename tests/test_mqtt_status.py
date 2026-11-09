import socket
import unittest
from vapor_board import mqtt_status
from vapor_board.config import ShopConfig
from vapor_board.mqtt_status import MqttMonitor, PacketReader, connect_packet, subscribe_packet


class FakeSocket:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def settimeout(self, _value):
        pass

    def sendall(self, data):
        self.sent.append(bytes(data))

    def recv(self, _size):
        if not self.replies:
            return b""
        reply = self.replies.pop(0)
        if reply is None:
            raise socket.timeout()
        return reply

    def close(self):
        pass


CONNACK_OK = b"\x20\x02\x00\x00"
SUBACK_OK = b"\x90\x03\x00\x01\x00"
PUBLISH = b"\x30\x06\x00\x01tsec"


class PacketTests(unittest.TestCase):
    def test_connect_has_no_credentials_or_will(self):
        packet = connect_packet("vb")
        self.assertEqual(packet, b"\x10\x0e\x00\x04MQTT\x04\x02\x00\x3c\x00\x02vb")

    def test_subscribe_is_qos_zero(self):
        self.assertEqual(subscribe_packet(1, "msh/#"), b"\x82\x0a\x00\x01\x00\x05msh/#\x00")

    def test_reader_handles_split_and_joined_packets(self):
        reader = PacketReader()
        self.assertEqual(reader.feed(b"\x20"), [])
        self.assertEqual(reader.feed(b"\x02\x00\x00\xd0\x00"), [(2, b"\x00\x00"), (13, b"")])

    def test_module_cannot_publish(self):
        self.assertFalse(hasattr(mqtt_status, "publish_packet"))
        self.assertNotIn("0x30", open(mqtt_status.__file__).read())


class MonitorTests(unittest.TestCase):
    def run_session(self, replies, topic="msh/#"):
        fake = FakeSocket(replies)
        monitor = MqttMonitor("broker.local", topic=topic, socket_factory=lambda _a, _t: fake)
        with self.assertRaises(mqtt_status.MqttError):
            monitor._session()
        return monitor, fake

    def test_counts_messages_and_sends_only_connect_and_subscribe(self):
        monitor, fake = self.run_session([CONNACK_OK, SUBACK_OK, None, PUBLISH, PUBLISH])
        self.assertEqual(monitor.status().messages, 2)
        self.assertEqual([packet[0] >> 4 for packet in fake.sent], [1, 8])

    def test_refused_connection_says_why(self):
        fake = FakeSocket([b"\x20\x02\x00\x05"])
        monitor = MqttMonitor("b", socket_factory=lambda _a, _t: fake)
        with self.assertRaisesRegex(mqtt_status.MqttError, "anonymous"):
            monitor._session()

    def test_refused_subscription_is_an_error(self):
        fake = FakeSocket([CONNACK_OK, b"\x90\x03\x00\x01\x80"])
        monitor = MqttMonitor("b", socket_factory=lambda _a, _t: fake)
        with self.assertRaisesRegex(mqtt_status.MqttError, "subscription"):
            monitor._session()


class ConfigTests(unittest.TestCase):
    def test_off_by_default(self):
        config = ShopConfig()
        self.assertFalse(config.mqtt_enabled)
        self.assertEqual((config.mqtt_host, config.radio_type), ("", "meshtastic"))

    def test_bad_values_are_refused(self):
        for bad in ({"mqtt_port": 0}, {"mqtt_topic": ""}, {"mqtt_host": "a b"}, {"radio_type": "lora"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ShopConfig(**bad)


if __name__ == "__main__":
    unittest.main()
