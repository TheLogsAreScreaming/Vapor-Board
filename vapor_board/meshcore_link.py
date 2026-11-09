"""Listen-only link to a MeshCore companion radio over USB or its network port.

It sends three local requests to the radio (start, device query, next waiting message), none of
which go on the air. There is no code here to send a message or an advert. Text is dropped as
soon as a frame is recognised, so MeshCore traffic never reaches boards, messages or replies.
"""
from dataclasses import dataclass
from .serial_link import SerialPort
from .tcp import ConnectionState, MeshtasticTcpClient, TcpSettings

TO_RADIO, FROM_RADIO = 0x3C, 0x3E  # '<' and '>'
MAX_FRAME = 300
CMD_APP_START, CMD_SYNC_NEXT, CMD_DEVICE_QUERY = 1, 10, 22
RESP_SELF_INFO, RESP_DIRECT, RESP_CHANNEL, RESP_NO_MORE, RESP_DEVICE_INFO, RESP_DIRECT_V3, RESP_CHANNEL_V3 = 5, 7, 8, 10, 13, 16, 17
PUSH_MESSAGES_WAITING = 0x83
PROTOCOL_VERSION = 3
_ALLOWED = {CMD_APP_START, CMD_SYNC_NEXT, CMD_DEVICE_QUERY}


@dataclass(frozen=True)
class MeshCoreSettings:
    """A /dev/ path for USB, otherwise a host name or address and port."""
    address: str
    port: int = 5000
    timeout: float = 1.0

    def __post_init__(self):
        TcpSettings(host=self.address, port=self.port, timeout=self.timeout)  # same validation as other links


def frame(payload):
    """A request to the radio. Only the listen-only requests can be framed."""
    if not payload or payload[0] not in _ALLOWED:
        raise PermissionError("Vapor Board only listens on MeshCore")
    return bytes([TO_RADIO]) + len(payload).to_bytes(2, "little") + bytes(payload)


def app_start():
    return frame(bytes([CMD_APP_START, PROTOCOL_VERSION]) + b"\x00" * 6 + b"Vapor Board")


def device_query():
    return frame(bytes([CMD_DEVICE_QUERY, PROTOCOL_VERSION]))


def sync_next():
    return frame(bytes([CMD_SYNC_NEXT]))


class FrameDecoder:
    """Splits the radio's byte stream into payloads, skipping anything between frames."""
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data):
        self._buffer += data
        payloads = []
        while True:
            start = self._buffer.find(FROM_RADIO)
            if start < 0:
                self._buffer.clear()
                return payloads
            del self._buffer[:start]
            if len(self._buffer) < 3:
                return payloads
            size = int.from_bytes(self._buffer[1:3], "little")
            if not 0 < size <= MAX_FRAME:
                del self._buffer[0]  # not really a frame start
                continue
            if len(self._buffer) < 3 + size:
                return payloads
            payloads.append(bytes(self._buffer[3:3 + size]))
            del self._buffer[:3 + size]


def describe(payload):
    """A small dict for the status display. Message text and senders are left out on purpose."""
    code = payload[0]
    if code in (RESP_DIRECT, RESP_DIRECT_V3):
        return {"variant": "meshcore_message", "kind": "direct"}
    if code in (RESP_CHANNEL, RESP_CHANNEL_V3):
        return {"variant": "meshcore_message", "kind": "channel"}
    return {"variant": "meshcore_other", "code": code}


class MeshCoreSession:
    """Same shape as RadioSession for the worker, without send_text."""
    def __init__(self, settings, socket_factory=None):
        usb = settings.address.startswith("/dev/")
        factory = socket_factory or ((lambda address, timeout: SerialPort(address[0], timeout)) if usb else None)
        self.client = MeshtasticTcpClient(TcpSettings(host=settings.address, port=settings.port, timeout=settings.timeout), factory)
        self.decoder = FrameDecoder()
        self.protocol_verified = False
        self.last_error = None
        self.frames_seen = 0

    @property
    def state(self):
        return self.client.state

    def connect(self):
        self.protocol_verified = False
        self.frames_seen = 0
        self.decoder = FrameDecoder()
        if not self.client.connect():
            self.last_error = self.client.last_error
            return False
        self.client._write(app_start())
        self.client._write(device_query())
        return True

    def keep_alive(self):
        self.client._write(sync_next())

    def receive(self):
        if self.state != ConnectionState.CONNECTED:
            self.protocol_verified = False
            raise ConnectionError("connection closed")
        chunk = self.client.receive(4096)
        if not chunk:
            return []
        results = []
        for payload in self.decoder.feed(chunk):
            self.frames_seen += 1
            self.protocol_verified = True
            if payload[0] in (RESP_SELF_INFO, PUSH_MESSAGES_WAITING, RESP_DIRECT, RESP_CHANNEL, RESP_DIRECT_V3, RESP_CHANNEL_V3):
                self.client._write(sync_next())  # collect the next waiting message from the radio
            results.append(describe(payload))
        return results

    def disconnect(self):
        self.protocol_verified = False
        self.client.disconnect()

    def send(self, *_args, **_kwargs):
        raise PermissionError("Vapor Board only listens on MeshCore")


def make_session(settings=None):
    """The session for these settings: MeshCore, or the default Meshtastic one."""
    from .radio_session import RadioSession
    return MeshCoreSession(settings) if isinstance(settings, MeshCoreSettings) else RadioSession(settings=settings)
