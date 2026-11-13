import json
import secrets
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from vapor_board.bbs import BulletinBoard
from vapor_board.customers import CustomerBook
from vapor_board.phone_notices import (CLOCK_SKEW, PER_PHONE_PER_MINUTE, ROUTE, NoticesFeed, NoticesServer, PhoneBook,
                                       PhoneError, pairing_link, request_message, response_message, sign, snapshot)

STAFF = SimpleNamespace(username="jess", active=True)
NOW = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc).timestamp()
VECTORS = json.loads((Path(__file__).parent / "data" / "phone_notices_vectors.json").read_text("utf-8"))


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def signed_headers(device, key, now=NOW, nonce=None, method="GET", path=ROUTE):
    nonce = nonce or secrets.token_hex(16)
    stamp = str(int(now))
    return nonce, {"X-VB-Device": device, "X-VB-Time": stamp, "X-VB-Nonce": nonce,
                   "X-VB-Signature": sign(key, request_message(method, path, stamp, nonce))}


class VectorTests(unittest.TestCase):
    """The same numbers are checked by the Android app's unit tests."""

    def test_request_and_response_signatures(self):
        key = bytes.fromhex(VECTORS["key_hex"])
        request = VECTORS["request"]
        message = request_message(request["method"], request["path"], request["time"], request["nonce"])
        self.assertEqual(message.decode(), request["message"])
        self.assertEqual(sign(key, message), request["signature"])
        response = VECTORS["response"]
        message = response_message(response["nonce"], response["status"], response["body"].encode("utf-8"))
        self.assertEqual(message.decode(), response["message"])
        self.assertEqual(sign(key, message), response["signature"])

    def test_pairing_link(self):
        pairing = VECTORS["pairing"]
        self.assertEqual(pairing_link(pairing["host"], pairing["port"], pairing["device"],
                                      bytes.fromhex(VECTORS["key_hex"]), pairing["shop"]), pairing["link"])


class FeedTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "bbs.sqlite"
        self.bbs = BulletinBoard(self.db)
        self.deals = self.bbs.create_board("Deals")
        self.staff_board = self.bbs.create_board("Staff notes")
        self.bbs.set_customer_visible(self.staff_board, False)
        self.bbs.post(self.deals, "jess", "Open late Friday")
        self.bbs.post(self.deals, "jess", "Not yet", publish_at="2026-11-14 00:00:00")
        self.bbs.post(self.deals, "jess", "Gone", publish_at="2026-11-01 00:00:00", expires_at="2026-11-12 00:00:00")
        self.ending = self.bbs.post(self.deals, "jess", "Ends soon", expires_at="2026-11-20 09:00:00")
        self.bbs.pin_post(self.ending)
        self.bbs.post(self.staff_board, "jess", "Safe code is 1234")
        customers = CustomerBook(self.db)
        self.sam = customers.add("Sam", actor=STAFF)
        customers.approve(self.sam.id, STAFF, True)
        self.customers = customers
        self.phones = PhoneBook(self.db)
        self.device, self.key = self.phones.pair(self.sam.id, STAFF)
        self.clock = Clock()
        self.feed = NoticesFeed(self.db, "Vapor Board", clock=self.clock)

    def get(self, **kwargs):
        nonce, headers = signed_headers(self.device, self.key, now=self.clock.now, **kwargs)
        status, out_headers, body = self.feed.handle("GET", ROUTE, headers)
        return nonce, status, out_headers, body

    def test_snapshot_is_the_kiosk_view_only(self):
        data = snapshot(self.db, "Vapor Board", datetime.fromtimestamp(NOW, timezone.utc))
        self.assertEqual([b["name"] for b in data["boards"]], ["Deals"])
        posts = data["boards"][0]["posts"]
        self.assertEqual([p["body"] for p in posts], ["Ends soon", "Open late Friday"])
        self.assertTrue(posts[0]["pinned"])
        self.assertEqual(posts[0]["until"], "2026-11-20T09:00:00Z")
        self.assertEqual(data["server_time"], "2026-11-13T10:00:00Z")
        text = json.dumps(data)
        for secret in ("Safe code", "Staff notes", "jess", "Not yet", "Gone", "Sam"):
            self.assertNotIn(secret, text)

    def test_signed_request_gets_signed_notices(self):
        nonce, status, headers, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-VB-Signature"], sign(self.key, response_message(nonce, 200, body)))
        self.assertEqual([b["name"] for b in json.loads(body)["boards"]], ["Deals"])
        self.assertIsNotNone(self.phones.phones(self.sam.id)[0]["last_seen_at"])

    def test_refusals(self):
        _n, headers = signed_headers(self.device, self.key)
        self.assertEqual(self.feed.handle("GET", "/v1/customers", headers)[0], 404)
        self.assertEqual(self.feed.handle("POST", ROUTE, headers)[0], 405)
        self.assertEqual(self.feed.handle("GET", ROUTE, {})[0], 400)
        _n, stranger = signed_headers("0123456789ab", self.key)
        status, out, body = self.feed.handle("GET", ROUTE, stranger)
        self.assertEqual((status, json.loads(body)["error"]), (401, "unknown_phone"))
        self.assertNotIn("X-VB-Signature", out)
        _n, forged = signed_headers(self.device, secrets.token_bytes(32))
        self.assertEqual(json.loads(self.feed.handle("GET", ROUTE, forged)[2])["error"], "bad_signature")
        _n, other_path = signed_headers(self.device, self.key, path="/v1/other")
        self.assertEqual(json.loads(self.feed.handle("GET", ROUTE, other_path)[2])["error"], "bad_signature")

    def test_replay_and_clock(self):
        nonce, status, _h, _b = self.get()
        self.assertEqual(status, 200)
        _n, status, headers, body = self.get(nonce=nonce)
        self.assertEqual((status, json.loads(body)["error"]), (401, "replay"))
        self.assertIn("X-VB-Signature", headers)
        nonce, headers = signed_headers(self.device, self.key, now=NOW - CLOCK_SKEW - 5)
        status, out, body = self.feed.handle("GET", ROUTE, headers)
        self.assertEqual((status, json.loads(body)["error"], json.loads(body)["server_time"]), (401, "clock", "2026-11-13T10:00:00Z"))
        self.assertEqual(out["X-VB-Signature"], sign(self.key, response_message(nonce, 401, body)))

    def test_rate_limit(self):
        for _ in range(PER_PHONE_PER_MINUTE):
            self.assertEqual(self.get()[1], 200)
        self.assertEqual(self.get()[1], 429)
        self.clock.now += 61
        self.assertEqual(self.get()[1], 200)

    def test_removing_access_cuts_the_phone_off(self):
        self.customers.revoke(self.sam.id, STAFF)
        nonce, status, headers, body = self.get()
        self.assertEqual((status, json.loads(body)["error"]), (403, "access_removed"))
        self.assertEqual(headers["X-VB-Signature"], sign(self.key, response_message(nonce, 403, body)))
        self.assertNotIn("Deals", body.decode())
        self.customers.approve(self.sam.id, STAFF, True)
        self.assertEqual(self.get()[1], 200)
        self.phones.remove(self.device, STAFF)
        self.assertEqual(self.get()[1], 401)

    def test_deleting_the_customer_forgets_their_phones(self):
        self.customers.remove(self.sam.id, STAFF)
        self.assertEqual(self.phones.phones(self.sam.id), [])
        self.assertIsNone(self.phones.lookup(self.device))

    def test_pairing_rules(self):
        pending = self.customers.add("Pat", actor=STAFF)
        with self.assertRaisesRegex(PhoneError, "Approve"):
            self.phones.pair(pending.id, STAFF)
        with self.assertRaisesRegex(PhoneError, "Sign in"):
            self.phones.pair(self.sam.id, None)
        self.phones.pair(self.sam.id, STAFF)
        self.phones.pair(self.sam.id, STAFF)
        with self.assertRaisesRegex(PhoneError, "already has 3"):
            self.phones.pair(self.sam.id, STAFF)
        for bad in ("", "../etc", "A1B2C3D4E5F6", "a1b2c3", None):
            self.assertIsNone(self.phones.lookup(bad))

    def test_over_a_real_socket(self):
        self.feed.clock = __import__("time").time
        server = NoticesServer(self.feed, port=0, host="127.0.0.1").start()
        self.addCleanup(server.stop)
        nonce, headers = signed_headers(self.device, self.key, now=__import__("time").time())
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{server.port}{ROUTE}", headers=headers), timeout=5) as reply:
            body = reply.read()
            self.assertEqual(reply.headers["X-VB-Signature"], sign(self.key, response_message(nonce, 200, body)))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{server.port}{ROUTE}", data=b"x", headers=headers), timeout=5)
        self.assertEqual(caught.exception.code, 405)


class QrTests(unittest.TestCase):
    def test_shape_and_finder_patterns(self):
        from vapor_board import qr
        matrix = qr.encode(VECTORS["pairing"]["link"])
        size = len(matrix)
        self.assertTrue(all(len(row) == size for row in matrix))
        self.assertEqual((size - 17) % 4, 0)
        finder = [[max(abs(x - 3), abs(y - 3)) not in (2, 4) for x in range(7)] for y in range(7)]
        for ox, oy in ((0, 0), (size - 7, 0), (0, size - 7)):
            self.assertEqual([row[ox:ox + 7] for row in matrix[oy:oy + 7]], finder)
        with self.assertRaises(ValueError):
            qr.encode("x" * 1000)

    def test_matches_the_qrcode_package_when_installed(self):
        try:
            import qrcode
            from qrcode import constants, util
        except ImportError:
            self.skipTest("qrcode package not installed")
        from vapor_board import qr
        for length in (1, 9, 14, 40, 150, 260, 400):
            text = (VECTORS["pairing"]["link"] * 4)[:length]
            for mask in range(8):
                ref = qrcode.QRCode(error_correction=constants.ERROR_CORRECT_M, border=0, mask_pattern=mask)
                ref.add_data(util.QRData(text.encode(), mode=util.MODE_8BIT_BYTE))
                ref.make(fit=True)
                self.assertEqual(qr.encode(text, mask=mask), [[bool(v) for v in row] for row in ref.get_matrix()], (length, mask))


if __name__ == "__main__":
    unittest.main()
