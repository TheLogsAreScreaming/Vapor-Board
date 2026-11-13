# Phone notices (opt-in)

Approved customers can read the shop's notices on an Android phone with the **Vapor Board Notices** app
(`TheLogsAreScreaming/Vapor-Board-Android`). The phone reads over the **shop's own Wi-Fi** from this Mac. It is off by default.

## What a phone can see
Exactly what the kiosk shows: boards marked **Visible**, and posts inside their *Show from* / *Until* window, pinned first.
Nothing else: no staff-only boards, no post authors, no messages, no customer list, no questions. A phone can't post, ask or send anything.

## Turning it on
1. In `~/.vapor-board/shop.json` set `"phone_notices_enabled": true` and restart Vapor Board. Settings ▸ Customer access shows *Phone notices: On*.
2. macOS may ask whether Vapor Board may accept incoming network connections. Choose **Allow**.
3. Reserve this Mac's address in the shop router so it doesn't change, or set `phone_notices_address` to a fixed name or address. Pairing codes contain this address.
4. Optional: `phone_notices_port` (default 8765).

## Pairing a phone
Customers ▸ select an **approved** customer ▸ **Phones…** ▸ **Pair a new phone**. The customer scans the code in the app while their phone is on the shop's Wi-Fi.
The code is shown once and holds a key for that phone only. Up to three phones per customer. Pairing and removal are in the activity log.

## Cutting a phone off
- **Phones… ▸ Remove phone** removes one phone.
- **Remove access** on the customer stops every phone they have. Approving them again lets the same phones read again.
- **Delete** on the customer forgets their phones.

The phone finds out on its next refresh, and then deletes the notices it kept.

## How it works
One route, `GET /v1/notices`, answered by `vapor_board/phone_notices.py` from `customer_boards()` and `customer_posts()`.

- Each request carries `X-VB-Device`, `X-VB-Time` (Unix seconds), `X-VB-Nonce` (32 hex characters) and `X-VB-Signature`:
  HMAC-SHA256 with the phone's key over `VBN1\nGET\n<path>\n<time>\n<nonce>`, as lowercase hex.
- The answer carries `X-VB-Signature`: HMAC-SHA256 over `VBN1\nRESP\n<nonce>\n<status>\n<sha256 hex of the body>`. The phone drops any answer whose signature doesn't match, so nobody else on the Wi-Fi can feed it fake notices.
- Requests more than 5 minutes off this Mac's clock, reused nonces and more than 20 refreshes a minute per phone are refused.
- Every request re-checks that the customer is still approved.
- Errors are JSON `{"error": code, "message": text}`: `unknown_phone` and `bad_signature` (401, unsigned), `clock` (401, signed, includes `server_time`), `replay` (401), `access_removed` (403), `rate_limited` (429).

Test vectors shared with the Android app: `tests/data/phone_notices_vectors.json`.

## Limits
- Phones get new notices only on the shop's Wi-Fi while this Mac is running Vapor Board. Between visits the app shows what it saved, hiding each post when its *Until* time passes.
- Notices travel **unencrypted** on the shop Wi-Fi. They are signed, not secret: the same text the kiosk shows on the counter. Anyone on the Wi-Fi can read them in transit.
- Keys are stored in `bbs.sqlite`, so backups contain them. Restoring an older backup brings back phones paired at that time, so check **Phones…** after a restore.
- Not yet tested with a real phone on a shop network.
