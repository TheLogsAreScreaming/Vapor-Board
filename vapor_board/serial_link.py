"""USB serial link to a Meshtastic radio, using only the standard library.

The radio's USB API uses the same framing as its network API, so this is a socket-shaped
port handed to MeshtasticTcpClient: the same transmit gate applies. Nothing here goes on
the air except what that client's transmit() allows.
"""
import glob
import os
import select
import socket
import termios
import time
from dataclasses import dataclass
from .tcp import MeshtasticTcpClient

BAUD = 115200
WAKE = b"\xc3" * 32  # tells a sleeping or console-mode radio that an API client is here
_PATTERNS = ("/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.SLAB*", "/dev/cu.wchusbserial*")


def list_ports():
    """USB serial devices that could be a radio, without Bluetooth and debug ports."""
    return sorted({path for pattern in _PATTERNS for path in glob.glob(pattern)})


@dataclass(frozen=True)
class SerialSettings:
    path: str
    timeout: float = 1.0
    transmissions_enabled: bool = False

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path.startswith(("/dev/cu.", "/dev/tty.")) or len(self.path) > 200:
            raise ValueError("a USB radio address looks like /dev/cu.usbserial-0001")
        if type(self.transmissions_enabled) is not bool:
            raise ValueError("transmissions_enabled must be a boolean")

    # MeshtasticTcpClient hands these to the factory as an address.
    @property
    def host(self):
        return self.path

    @property
    def port(self):
        return BAUD


class SerialPort:
    """The parts of a socket that MeshtasticTcpClient uses."""
    def __init__(self, path, timeout):
        self.timeout = timeout
        self._fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            mode = termios.tcgetattr(self._fd)
            mode[0] = mode[1] = mode[3] = 0  # raw: no echo or line handling
            mode[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            mode[4] = mode[5] = termios.B115200
            termios.tcsetattr(self._fd, termios.TCSANOW, mode)
            termios.tcflush(self._fd, termios.TCIOFLUSH)
        except (termios.error, OSError) as exc:
            os.close(self._fd)
            self._fd = None
            raise OSError(f"couldn't set up {path}: {exc}") from exc

    def _descriptor(self):
        if self._fd is None:
            raise OSError("port is closed")
        return self._fd

    def recv(self, size):
        ready, _w, _x = select.select([self._descriptor()], [], [], self.timeout)
        if not ready:
            raise socket.timeout()
        return os.read(self._descriptor(), size)

    def sendall(self, data):
        view = memoryview(bytes(data))
        while view:
            _r, ready, _x = select.select([], [self._descriptor()], [], self.timeout)
            if not ready:
                raise OSError("the radio stopped accepting data")
            view = view[os.write(self._descriptor(), view):]

    def shutdown(self, _how):
        pass

    def close(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


def open_port(address, timeout):
    port = SerialPort(address[0], timeout)
    try:
        port.sendall(WAKE)
        time.sleep(0.1)  # the radio needs a moment before its first API request
    except OSError:
        port.close()
        raise
    return port


class MeshtasticSerialClient(MeshtasticTcpClient):
    def __init__(self, settings, socket_factory=None):
        super().__init__(settings, socket_factory or open_port)
