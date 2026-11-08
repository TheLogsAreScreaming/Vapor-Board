"""Plain-language wording for the desktop. Pure functions, no Tkinter, so they test anywhere."""
from datetime import datetime, timezone
from .tcp import ConnectionState

TROUBLESHOOT = ("Check that the radio is powered on, joined to the same Wi-Fi network as this Mac, "
                "and has its network (TCP) API turned on. The usual port is 4403.")


def friendly_time(stamp, now=None):
    """'Today 4:05 PM', 'Yesterday 9:12 AM', 'Nov 3, 2:40 PM' or 'Nov 3, 2025' from SQLite UTC text.

    SQLite CURRENT_TIMESTAMP is UTC; the operator reads local time. Unparseable text is returned as is.
    """
    try:
        moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return str(stamp)
    now = (now or datetime.now(timezone.utc)).astimezone(moment.tzinfo)
    clock = moment.strftime("%I:%M %p").lstrip("0")
    days = (now.date() - moment.date()).days
    if days == 0:
        return f"Today {clock}"
    if days == 1:
        return f"Yesterday {clock}"
    if moment.year == now.year:
        return f"{moment.strftime('%b')} {moment.day}, {clock}"
    return f"{moment.strftime('%b')} {moment.day}, {moment.year}"


def radio_presentation(state):
    """(pill kind, short label, one-line explanation) for a RadioDisplayState."""
    if state.tcp == ConnectionState.CONNECTING:
        return "warning", "Connecting…", "Opening a connection to the radio."
    if state.tcp == ConnectionState.CONNECTED and state.protocol_verified:
        noun = "packet" if state.decoded == 1 else "packets"
        return "success", "Receiving", f"Listening to the mesh. {state.decoded} {noun} received so far."
    if state.tcp == ConnectionState.CONNECTED:
        return "info", "Connected", "Connected. Waiting for the radio to send its first packet."
    if state.tcp == ConnectionState.ERROR:
        detail = state.detail.rstrip(".") if state.detail else "The connection failed"
        return "danger", "Connection problem", f"{detail}. {TROUBLESHOOT}"
    return "neutral", "Not connected", "Enter your radio's address and choose Connect. Nothing is sent to the radio."


def parse_local_time(text, end_of_day=False):
    """UTC 'YYYY-MM-DD HH:MM:SS' for local text like '2026-11-20', '2026-11-20 9:30' or '2026-11-20 9:30 PM'.

    Blank text gives None. A date alone means the start of that day, or (end_of_day) the end of it.
    """
    text = " ".join(str(text or "").split()).upper()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I %p", "%Y-%m-%d"):
        try:
            moment = datetime.strptime(text, pattern)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"“{text.lower()}” isn't a date like 2026-11-20 or 2026-11-20 9:30 PM")
    if pattern == "%Y-%m-%d" and end_of_day:
        moment = moment.replace(hour=23, minute=59, second=59)
    return moment.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def local_time_text(stamp):
    """'2026-11-20 9:30 PM' local form of a UTC stamp, for editing; '' for None."""
    if not stamp:
        return ""
    moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    return moment.strftime("%Y-%m-%d ") + moment.strftime("%I:%M %p").lstrip("0")


def schedule_state(entry, now=None):
    """'scheduled', 'expired' or 'live' for a post with optional publish_at / expires_at (UTC)."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if entry.get("publish_at") and entry["publish_at"] > now:
        return "scheduled"
    if entry.get("expires_at") and entry["expires_at"] <= now:
        return "expired"
    return "live"


def first_line(body, limit):
    line = body.splitlines()[0] if body else ""
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


def plural(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
