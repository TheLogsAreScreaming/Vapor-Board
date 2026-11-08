"""Receive-only radio worker with cancellation-safe startup and event delivery."""
import time
from queue import Queue, Empty
from threading import Event, Lock, Thread
from .radio_session import RadioSession
from .tcp import ConnectionState

class RadioWorker:
    HEARTBEAT_SECONDS = 300  # the radio closes idle API sessions after about 15 minutes

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or RadioSession
        self.events = Queue()
        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._session = None
        self._generation = 0

    def start(self, settings=None):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._generation += 1
            generation = self._generation
            self._stop = Event()
            stop = self._stop
            self._thread = Thread(target=self._run, args=(settings, generation, stop), daemon=True)
            self._thread.start()
            return True

    def _emit(self, generation, kind, data=None):
        with self._lock:
            if generation == self._generation:
                self.events.put((kind, data))

    def _run(self, settings, generation, stop):
        session = None
        try:
            if stop.is_set():
                return
            session = self.session_factory(settings=settings)
            with self._lock:
                if stop.is_set() or generation != self._generation:
                    return
                self._session = session
            self._emit(generation, "connecting")
            if stop.is_set():
                return
            if not session.connect():
                if not stop.is_set():
                    self._emit(generation, "error", "Couldn't connect to the radio")
                return
            if stop.is_set():
                return
            self._emit(generation, "tcp_open")
            beat = time.monotonic()
            while not stop.is_set():
                if time.monotonic() - beat >= self.HEARTBEAT_SECONDS and hasattr(session, "keep_alive"):
                    beat = time.monotonic()
                    try:
                        session.keep_alive()
                    except (OSError, ConnectionError) as exc:
                        if not stop.is_set():
                            self._emit(generation, "error", str(exc))
                        break
                try:
                    variants = session.receive()
                except Exception as exc:
                    if not stop.is_set():
                        self._emit(generation, "error", str(exc))
                    break
                if stop.is_set():
                    break
                for item in variants:
                    if stop.is_set():
                        break
                    self._emit(generation, "protobuf", item)
                if session.state != ConnectionState.CONNECTED:
                    break
        except Exception as exc:
            if not stop.is_set():
                self._emit(generation, "error", str(exc))
        finally:
            if session is not None:
                session.disconnect()
            with self._lock:
                if self._session is session:
                    self._session = None
            if not stop.is_set():
                self._emit(generation, "disconnected")

    def stop(self):
        with self._lock:
            self._generation += 1
            self._stop.set()
            session = self._session
            while True:
                try:
                    self.events.get_nowait()
                except Empty:
                    break
        if session is not None:
            session.disconnect()

    def send_text(self, destination, text, channel=0):
        """Send a direct text on the current connection. False when not connected or not allowed."""
        with self._lock:
            session = self._session
        if session is None or not hasattr(session, "send_text"):
            return False
        try:
            session.send_text(destination, text, channel)
        except (PermissionError, ValueError, OSError, ConnectionError):
            return False
        return True

    def poll(self):
        try:
            return self.events.get_nowait()
        except Empty:
            return None
