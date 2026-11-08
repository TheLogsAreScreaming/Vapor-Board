"""Optional check for a newer Vapor Board release. Off unless the shop turns it on or asks.

Uses macOS's own curl, so it needs no bundled certificates. It sends no shop data: only a
plain request for the public release list.
"""
import json
import re
import subprocess
from . import __version__

URL = "https://api.github.com/repos/TheLogsAreScreaming/Vapor-Board-Releases/releases?per_page=20"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-?rc\.?(\d+))?$", re.IGNORECASE)


def parse_version(text):
    """A sortable tuple for '1.0.0rc2' or 'v1.0.0-rc.2'; a final release sorts after its candidates. None if unreadable."""
    match = _VERSION.match(str(text or "").strip())
    if not match:
        return None
    major, minor, patch, candidate = match.groups()
    return (int(major), int(minor), int(patch), 1 if candidate is None else 0, int(candidate or 0))


def _fetch():
    done = subprocess.run(["/usr/bin/curl", "-fsSL", "--max-time", "10", "-H", "Accept: application/vnd.github+json", URL],
                          capture_output=True, timeout=15, check=False)
    if done.returncode:
        raise OSError("the release list couldn't be reached")
    return done.stdout


def check(current=__version__, fetch=_fetch):
    """The newest published tag if it is newer than current, else None. Raises OSError or ValueError on failure."""
    try:
        releases = json.loads(fetch())
    except subprocess.SubprocessError as exc:
        raise OSError("the release list couldn't be reached") from exc
    if not isinstance(releases, list):
        raise ValueError("unexpected reply")
    mine = parse_version(current)
    tags = [(parse_version(r.get("tag_name")), r["tag_name"]) for r in releases
            if isinstance(r, dict) and not r.get("draft") and parse_version(r.get("tag_name"))]
    newest = max(tags, default=None)
    return newest[1] if newest and mine and newest[0] > mine else None
