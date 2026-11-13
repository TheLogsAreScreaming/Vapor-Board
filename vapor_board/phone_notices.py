"""Read-only customer notices for paired phones, over the shop's own Wi-Fi. Off unless turned on.

What a phone can get: the boards marked Visible and the posts inside their Show from / Until
window — the same view as the kiosk — and nothing else. There is one route, GET /v1/notices.
No posting, no messages, no customer list, no staff-only boards, no post authors.

Pairing: staff pair a phone to an approved customer (Customers page). That makes a random
32-byte key, shown once as a QR code / vaporboard://pair link. Every request is signed with the
key (HMAC-SHA256 over method, path, time and a one-time nonce) and every answer is signed back,
so nobody else on the Wi-Fi can read through the feed or feed the phone fake notices. The key is
never sent over the network after pairing. Notices themselves travel unencrypted on the shop's
Wi-Fi; they are the same text the kiosk shows on the counter.

Each request re-checks that the customer is still approved and the phone still paired, so
Remove access or Remove phone cuts the phone off on its next refresh.

Protocol: docs/PHONE_NOTICES.md. Test vectors shared with the Android app:
tests/data/phone_notices_vectors.json.
"""
import hashlib
import hmac
import json
import secrets
import socket
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from .bbs import STAMP, BulletinBoard
from .customers import CustomerBook, CustomerError

PROTOCOL = "VBN1"
ROUTE = "/v1/notices"
DEFAULT_PORT = 8765
CLOCK_SKEW = 300            # seconds a phone's clock may be off before it must resync
NONCE_MEMORY = 2 * CLOCK_SKEW
PER_PHONE_PER_MINUTE = 20
MAX_POSTS_PER_BOARD = 50
MAX_PHONES_PER_CUSTOMER = 3
_HEX = set("0123456789abcdef")


class PhoneError(ValueError):
    """A pairing change was refused; the message is shown to staff."""


# ---- signing (shared with the Android app; see the test vectors) -------------------------
def request_message(method, path, timestamp, nonce):
    return f"{PROTOCOL}\n{method}\n{path}\n{timestamp}\n{nonce}".encode("utf-8")


def response_message(nonce, status, body):
    return f"{PROTOCOL}\nRESP\n{nonce}\n{status}\n{hashlib.sha256(body).hexdigest()}".encode("utf-8")


def sign(key, message):
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def pairing_link(host, port, device_id, key, shop_name):
    """The vaporboard://pair link a phone scans. The key is base64url without padding."""
    import base64
    encoded = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
    return (f"vaporboard://pair?v=1&host={quote(host, safe='')}&port={int(port)}&device={device_id}"
            f"&key={encoded}&shop={quote(shop_name, safe='')}")


def iso(stamp):
    """'2026-11-20 09:00:00' (UTC) -> '2026-11-20T09:00:00Z'; None stays None."""
    return None if stamp in (None, "") else stamp.replace(" ", "T") + "Z"


# ---- paired phones -----------------------------------------------------------------------
class PhoneBook:
    """Phones paired to customers, stored with the boards in bbs.sqlite (table phone_devices)."""

    def __init__(self, database_path):
        self.path = Path(database_path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS phone_devices (
            id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL, secret TEXT NOT NULL,
            paired_by TEXT NOT NULL, paired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT)""")
        return db

    def pair(self, customer_id, actor):
        """Pair a new phone to an approved customer. Returns (device id, key bytes)."""
        if actor is None or not getattr(actor, "active", False) or not getattr(actor, "username", ""):
            raise PhoneError("Sign in as staff first")
        customer = CustomerBook(self.path).get(customer_id)
        if customer is None:
            raise PhoneError("Customer not found")
        if not customer.approved:
            raise PhoneError("Approve the customer (in-person ID check) before pairing a phone")
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM phone_devices WHERE customer_id = ?", (customer.id,)).fetchone()[0]
            if count >= MAX_PHONES_PER_CUSTOMER:
                raise PhoneError(f"{customer.name} already has {MAX_PHONES_PER_CUSTOMER} phones. Remove one first.")
            device_id, key = secrets.token_hex(6), secrets.token_bytes(32)
            db.execute("INSERT INTO phone_devices (id, customer_id, secret, paired_by) VALUES (?, ?, ?, ?)",
                       (device_id, customer.id, key.hex(), actor.username))
        return device_id, key

    def phones(self, customer_id):
        if not self.path.exists():
            return []
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, paired_by, paired_at, last_seen_at FROM phone_devices WHERE customer_id = ? ORDER BY paired_at, id",
                (customer_id,))]

    def remove(self, device_id, actor):
        if actor is None or not getattr(actor, "active", False):
            raise PhoneError("Sign in as staff first")
        with self._connect() as db:
            if db.execute("DELETE FROM phone_devices WHERE id = ?", (str(device_id),)).rowcount != 1:
                raise PhoneError("Phone not found")

    def remove_for_customer(self, customer_id):
        """Forget every phone of a customer (used when the customer record is deleted)."""
        if not self.path.exists():
            return
        with self._connect() as db:
            db.execute("DELETE FROM phone_devices WHERE customer_id = ?", (customer_id,))

    def lookup(self, device_id):
        """(key bytes, customer or None) for a paired phone, or None when unknown."""
        if not isinstance(device_id, str) or len(device_id) != 12 or not set(device_id) <= _HEX or not self.path.exists():
            return None
        with self._connect() as db:
            row = db.execute("SELECT customer_id, secret FROM phone_devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            return None
        return bytes.fromhex(row["secret"]), CustomerBook(self.path).get(row["customer_id"])

    def touch(self, device_id):
        with self._connect() as db:
            db.execute("UPDATE phone_devices SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?", (device_id,))


# ---- the feed ----------------------------------------------------------------------------
def snapshot(database, shop_name, now=None):
    """Everything a customer may read right now: visible boards and their current posts."""
    now_stamp = (now or datetime.now(timezone.utc)).strftime(STAMP)
    bbs = BulletinBoard(database)
    boards = []
    if Path(database).exists():
        for board in bbs.customer_boards():  # staff-only boards never get here
            posts = bbs.customer_posts(board["id"], now=now_stamp, limit=MAX_POSTS_PER_BOARD)
            boards.append({"id": board["id"], "name": board["name"], "posts": [
                {"id": p["id"], "body": p["body"], "posted_at": iso(p["created_at"]), "pinned": p["pinned_at"] is not None,
                 "shows_from": iso(p["publish_at"]), "until": iso(p["expires_at"])} for p in posts]})
    return {"protocol": PROTOCOL, "shop": shop_name, "server_time": iso(now_stamp), "boards": boards}


class NoticesFeed:
    """Answers one request at a time. Pure logic, so it is tested without sockets."""

    def __init__(self, database, shop_name, clock=time.time):
        self.database = Path(database)
        self.shop_name = shop_name
        self.clock = clock
        self._nonces = {}               # (device, nonce) -> time seen
        self._hits = {}                 # device -> deque of request times
        self._lock = threading.Lock()

    @staticmethod
    def _json(status, payload, key=None, nonce=""):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
        if key is not None:
            headers["X-VB-Signature"] = sign(key, response_message(nonce, status, body))
        return status, headers, body

    def _error(self, status, code, message, key=None, nonce="", **extra):
        return self._json(status, {"error": code, "message": message, **extra}, key, nonce)

    def handle(self, method, path, headers):
        """(status, headers, body bytes) for one request. Header names are matched case-insensitively."""
        headers = {str(k).lower(): str(v) for k, v in headers.items()}
        if path != ROUTE:
            return self._error(404, "not_found", "Not found")
        if method != "GET":
            return self._error(405, "method_not_allowed", "Only GET")
        device, stamp = headers.get("x-vb-device", ""), headers.get("x-vb-time", "")
        nonce, signature = headers.get("x-vb-nonce", ""), headers.get("x-vb-signature", "").lower()
        if not (len(nonce) == 32 and set(nonce) <= _HEX and stamp.isdigit() and len(signature) == 64):
            return self._error(400, "bad_request", "Missing or malformed signature headers")
        found = PhoneBook(self.database).lookup(device)
        if found is None:
            return self._error(401, "unknown_phone", "This phone is not paired with the shop")
        key, customer = found
        if not hmac.compare_digest(sign(key, request_message(method, path, stamp, nonce)), signature):
            return self._error(401, "bad_signature", "Signature does not match")
        now = self.clock()
        if abs(now - int(stamp)) > CLOCK_SKEW:
            return self._error(401, "clock", "Phone clock is off", key, nonce,
                               server_time=datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        with self._lock:
            for seen_key in [k for k, t in self._nonces.items() if now - t > NONCE_MEMORY]:
                del self._nonces[seen_key]
            if (device, nonce) in self._nonces:
                return self._error(401, "replay", "Request already used", key, nonce)
            self._nonces[(device, nonce)] = now
            hits = self._hits.setdefault(device, deque())
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= PER_PHONE_PER_MINUTE:
                return self._error(429, "rate_limited", "Too many refreshes; wait a minute", key, nonce)
            hits.append(now)
        if customer is None or not customer.approved:
            return self._error(403, "access_removed", "Access removed by the shop", key, nonce)
        PhoneBook(self.database).touch(device)
        return self._json(200, snapshot(self.database, self.shop_name,
                                        datetime.fromtimestamp(now, timezone.utc)), key, nonce)


# ---- the local network listener ---------------------------------------------------------
def local_address():
    """This Mac's address on the local network (no packet is sent), or '' when offline."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


class NoticesServer:
    """GET-only HTTP listener on the shop network, in a background thread."""

    def __init__(self, feed, port=DEFAULT_PORT, host="0.0.0.0", on_request=None):
        self.feed, self.port, self.host, self.on_request = feed, port, host, on_request
        self._server = None
        self._thread = None

    def start(self):
        feed, on_request = self.feed, self.on_request

        class Handler(BaseHTTPRequestHandler):
            server_version = "VaporBoard"
            sys_version = ""

            def _answer(self):
                status, headers, body = feed.handle(self.command, self.path, dict(self.headers.items()))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if on_request:
                    on_request(self.client_address[0], status)

            do_GET = _answer
            do_POST = do_PUT = do_DELETE = do_PATCH = _answer

            def log_message(self, *_args):  # nothing on stdout; the desktop keeps its own log
                pass

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="phone-notices", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def running(self):
        return self._server is not None
