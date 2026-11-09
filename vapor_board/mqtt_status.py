"""Optional, receive-only MQTT status: counts messages seen on a broker on the shop's network.

Off by default. This module can only connect, subscribe and ping; it has no way to publish.
Message contents are discarded without being read, and nothing reaches the radio or the boards.
No username or password: shop settings never hold credentials, so the broker must allow anonymous reads.
"""
import secrets
import socket
import time
from dataclasses import dataclass
from threading import Event, Lock, Thread

CONNACK, PUBLISH, SUBACK, PINGRESP = 2, 3, 9, 13
PINGREQ = b"\xc0\x00"
DISCONNECT = b"\xe0\x00"
KEEP_ALIVE, PING_EVERY, RETRY_SECONDS, MAX_PACKET = 60, 30, 30, 1 << 20


class MqttError(ConnectionError):
    """The broker refused us or sent something that isn't MQTT."""


def _text(value):
    data = value.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def _packet(first_byte, body):
    size, length = len(body), bytearray()
    while True:
        byte, size = size & 0x7F, size >> 7
        length.append(byte | (0x80 if size else 0))
        if not size:
            return bytes([first_byte]) + bytes(length) + body


def connect_packet(client_id, keep_alive=KEEP_ALIVE):
    """MQTT 3.1.1 CONNECT with a clean session, no will and no credentials."""
    return _packet(0x10, _text("MQTT") + b"\x04\x02" + keep_alive.to_bytes(2, "big") + _text(client_id))


def subscribe_packet(packet_id, topic):
    return _packet(0x82, packet_id.to_bytes(2, "big") + _text(topic) + b"\x00")


class PacketReader:
    """Splits a byte stream into (packet type, body)."""
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data):
        self._buffer += data
        packets = []
        while len(self._buffer) >= 2:
            size, shift, index = 0, 0, 1
            while True:
                if index >= len(self._buffer):
                    return packets  # the length isn't all here yet
                byte = self._buffer[index]
                size |= (byte & 0x7F) << shift
                index, shift = index + 1, shift + 7
                if not byte & 0x80:
                    break
                if shift > 21:
                    raise MqttError("not an MQTT broker")
            if size > MAX_PACKET:
                raise MqttError("the broker sent a message that is too large")
            if len(self._buffer) < index + size:
                return packets
            packets.append((self._buffer[0] >> 4, bytes(self._buffer[index:index + size])))
            del self._buffer[:index + size]
        return packets


@dataclass(frozen=True)
class MqttStatus:
    state: str = "off"  # off | connecting | connected | problem
    messages: int = 0
    detail: str = ""

    @property
    def summary(self):
        if self.state == "connected":
            return f"connected, {self.messages} seen"
        return {"connecting": "connecting", "problem": "no connection", "off": "off"}[self.state]


class MqttMonitor:
    def __init__(self, host, port=1883, topic="msh/#", socket_factory=socket.create_connection, timeout=5.0):
        self.host, self.port, self.topic = host, port, topic
        self.socket_factory, self.timeout = socket_factory, timeout
        self._stop = Event()
        self._lock = Lock()
        self._status = MqttStatus()
        self._socket = None
        self._thread = None

    def status(self):
        with self._lock:
            return self._status

    def _set(self, state, detail="", add=0):
        with self._lock:
            self._status = MqttStatus(state, self._status.messages + add, detail)

    def start(self):
        if self._thread is None:
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except (OSError, MqttError, ValueError) as exc:
                if not self._stop.is_set():
                    self._set("problem", str(exc))
            finally:
                sock, self._socket = self._socket, None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._stop.wait(RETRY_SECONDS)

    def _session(self):
        self._set("connecting")
        sock = self._socket = self.socket_factory((self.host, self.port), self.timeout)
        sock.settimeout(self.timeout)
        sock.sendall(connect_packet(f"vapor-board-{secrets.token_hex(4)}"))
        reader, last_ping = PacketReader(), time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - last_ping >= PING_EVERY:
                sock.sendall(PINGREQ)
                last_ping = time.monotonic()
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise MqttError("the broker closed the connection")
            for kind, body in reader.feed(data):
                self._handle(sock, kind, body)
        try:
            sock.sendall(DISCONNECT)
        except OSError:
            pass

    def _handle(self, sock, kind, body):
        if kind == CONNACK:
            if len(body) != 2 or body[1] != 0:
                raise MqttError("the broker refused the connection; it must allow anonymous reads")
            sock.sendall(subscribe_packet(1, self.topic))
        elif kind == SUBACK:
            if body[-1:] == b"\x80" or len(body) < 3:
                raise MqttError("the broker refused the subscription")
            self._set("connected")
        elif kind == PUBLISH:
            self._set("connected", add=1)  # counted; the contents are never looked at
