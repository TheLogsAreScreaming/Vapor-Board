"""Staff alerts for new customer messages. Local only: a Mac notification, never the radio.

The banner names no customer and shows no message text, because a shop Mac's screen may
be in view of customers.
"""
import subprocess
import sys
import time

COOLDOWN_SECONDS = 30.0
_SCRIPT = ("-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run")


class AlertGate:
    """Lets one sound and banner through per cooldown, so a burst of messages is one alert."""
    def __init__(self, cooldown=COOLDOWN_SECONDS, clock=time.monotonic):
        self.cooldown, self.clock = cooldown, clock
        self._last = None

    def ready(self):
        now = self.clock()
        if self._last is not None and now - self._last < self.cooldown:
            return False
        self._last = now
        return True


def banner_command(title, message):
    """osascript arguments; title and message are passed as data, never as script text."""
    return ["osascript", *_SCRIPT, title, message]


def show_banner(title, message):
    """Show a macOS notification without waiting for it. Failure is ignored: the in-app notice still shows."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(banner_command(title, message), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
