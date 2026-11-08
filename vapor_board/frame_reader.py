"""Read-only adapter from TCP bytes to framed Meshtastic protobuf payloads."""
from .meshtastic_frames import FrameDecoder
from .tcp import ConnectionState


class FramedTcpReader:
    def __init__(self, client, decoder=None):
        self.client = client
        self.decoder = decoder if decoder is not None else FrameDecoder()
        self.frames_received = 0

    def connect(self):
        self.decoder.reset()
        self.frames_received = 0
        return self.client.connect()

    def read_frames(self, size=4096):
        if self.client.state != ConnectionState.CONNECTED:
            raise ConnectionError("TCP is not connected")
        try:
            chunk = self.client.receive(size)
        except ConnectionError:
            self.decoder.reset()
            raise
        if chunk is None:  # quiet radio: keep any partial frame for the next read
            return []
        if not chunk:
            self.decoder.reset()
            return []
        frames = self.decoder.feed(chunk)
        self.frames_received += len(frames)
        return frames

    def disconnect(self):
        self.decoder.reset()
        self.client.disconnect()

    def send(self, *_args, **_kwargs):
        raise PermissionError("frame reader is receive-only")
