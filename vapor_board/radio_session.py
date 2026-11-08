"""Radio session over the Meshtastic TCP API with honest connection and protocol state.

On connect it sends want_config (a local API request, nothing goes on the air) so the radio
starts streaming. Mesh transmissions go only through send_text(), which refuses unless the
shop turned transmit on, and only to a single node.
"""
import secrets
from .frame_reader import FramedTcpReader
from .tcp import MeshtasticTcpClient, ConnectionState
from .serial_link import MeshtasticSerialClient, SerialSettings
from .meshwire import decode_from_radio, want_config, heartbeat, text_message


class RadioSession:
    def __init__(self, settings=None, client=None, parser=None):
        if client is None:
            client = MeshtasticSerialClient(settings) if isinstance(settings, SerialSettings) else MeshtasticTcpClient(settings)
        self.reader = FramedTcpReader(client)
        self.parser = parser if parser is not None else decode_from_radio
        self.protocol_verified = False
        self.last_error = None
        self.frames_seen = 0

    @property
    def state(self):
        return self.reader.client.state

    @property
    def can_transmit(self):
        settings = getattr(self.reader.client, "settings", None)
        return bool(settings and settings.transmissions_enabled and hasattr(self.reader.client, "transmit"))

    def connect(self):
        self.protocol_verified = False
        self.frames_seen = 0
        self.last_error = None
        if not self.reader.connect():
            return False
        self._control(want_config(secrets.randbelow(0xFFFFFFFE) + 1))
        return True

    def _control(self, frame):
        send = getattr(self.reader.client, "send_control", None)
        if send is not None:
            send(frame)

    def keep_alive(self):
        self._control(heartbeat())

    def receive(self):
        if self.state != ConnectionState.CONNECTED:
            self.protocol_verified = False
            raise ConnectionError("TCP disconnected")
        try:
            frames = self.reader.read_frames()
            results = []
            for frame in frames:
                message = self.parser(frame)
                results.append(message if isinstance(message, dict) else _describe(message))
                self.frames_seen += 1
                self.protocol_verified = True
            if self.state != ConnectionState.CONNECTED:
                self.protocol_verified = False
            return results
        except Exception as exc:
            self.protocol_verified = False
            self.last_error = str(exc)
            raise

    def disconnect(self):
        self.protocol_verified = False
        self.reader.disconnect()

    def send(self, *_args, **_kwargs):
        raise PermissionError("outbound radio transmission disabled")

    def send_text(self, destination, text, channel=0):
        """Send one direct text message on the mesh. Refused unless transmit is turned on."""
        if not self.can_transmit:
            raise PermissionError("radio transmit is turned off")
        self.reader.client.transmit(text_message(destination, text, secrets.randbelow(0xFFFFFFFE) + 1, channel=channel))


def _describe(message):
    """Variant name for a parsed protobuf object (custom parsers in tests)."""
    variant = message.WhichOneof("payload_variant")
    return {"variant": variant or "unknown"}
