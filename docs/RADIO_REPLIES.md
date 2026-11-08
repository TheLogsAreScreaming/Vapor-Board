# Radio replies (opt-in)

Vapor Board can answer **direct messages** from **approved customers** over a Meshtastic radio. It is off by default.

## Turning it on
Set `"transmissions_enabled": true` in `~/.vapor-board/shop.json` and restart. Settings shows *Radio transmit: On*, and the sidebar says *Replies to approved customers*. Demo mode never transmits.

## What customers send (as a direct message to the shop's radio)
| Message | Reply |
|---|---|
| `help` | The command list |
| `boards` | Numbered list of boards marked Visible |
| `read 2` | Up to three current posts from board 2 (scheduled/expired posts left out) |
| `more` | The next three older posts of the board being read |
| `msg Do you have size 10?` | Stores the message in the shop's Messages inbox from the customer's name |
| `inbox` | Up to three unread staff replies to that customer, then marks them read |

A leading `/` is fine. Replies longer than 200 bytes are split into at most three messages.

## Rules (enforced in `vapor_board/radio_replies.py`)
- Only direct text messages to this radio. Channel broadcasts are never answered, and Vapor Board never broadcasts.
- Only from a node ID registered to an **approved** customer (Customers page). Unknown, pending or removed customers get no reply; the attempt is logged.
- Messages relayed through MQTT are ignored: no internet-to-radio bridge.
- A packet heard twice is answered once.
- Rate limits: 3 replies per customer and 12 for the whole shop per minute; extra messages get no reply.
- Every handled message is in the Staff ▸ Activity log as `radio`.
- When a customer sends `msg`, staff get a sound and a Mac notification (at most one per 30 seconds) and, when signed in, an on-screen notice. The Mac notification shows no name or message text. Set `message_alerts` to false in shop.json to turn this off. Alerts are local and never use the radio.
- Staff reply to customers in Messages as usual; customers fetch replies with `inbox`. Nothing is pushed to customers unasked.

## How the radio link works
On connect Vapor Board sends the radio's network API a `want_config` request and, every five minutes, a `heartbeat`. These go to the radio over Wi-Fi only; nothing is sent on the air. Mesh transmission goes through one path (`RadioSession.send_text`), which refuses unless transmit is on and only sends to a single node.

The Meshtastic messages are encoded and decoded by `vapor_board/meshwire.py` (no third-party packages). Tests check it against the official `meshtastic` bindings when those are installed.

## Not yet verified
Replies have been tested against the official protobuf definitions and with simulated radios, not yet on the air with real hardware. Do an on-air test with two radios before relying on it.
