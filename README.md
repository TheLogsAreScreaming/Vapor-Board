# Vapor Board

A private bulletin board for **one shop**, running on the shop's Intel Mac. Staff post notices (opening hours, closures, new stock), message each other and customers, and keep a customer list with in-person age checks. A counter kiosk shows customer-facing notices, and an optional Meshtastic radio lets approved customers read the board from the mesh.

Everything is stored on the Mac. Nothing goes to the internet, and the radio only transmits if you turn that on.

![Boards page](docs/screenshots/light-boards.jpg)

## Features
- **Staff sign-in.** Owner set-up on first launch, staff and admin accounts, auto-lock, activity log. → [docs/STAFF_SIGN_IN.md](docs/STAFF_SIGN_IN.md)
- **Boards and posts.** Write, edit, delete, pin, reorder boards, schedule posts with *Show from / Until*. → [docs/BOARD_ORDER_AND_PINS.md](docs/BOARD_ORDER_AND_PINS.md), [docs/SCHEDULE_EXPORT_DEMO.md](docs/SCHEDULE_EXPORT_DEMO.md)
- **Messages.** A shared shop inbox with threaded conversations. → [docs/MESSAGE_THREADS.md](docs/MESSAGE_THREADS.md)
- **Customers.** Records, approval after an in-person 21+ ID check (no ID details stored), and per-board *Visible / Staff only*. → [docs/CUSTOMERS.md](docs/CUSTOMERS.md)
- **Kiosk.** A full-screen, read-only notice screen for the counter; leaving it needs a staff sign-in. → [docs/KIOSK.md](docs/KIOSK.md)
- **Search** across posts and messages (⌘F). → [docs/SEARCH.md](docs/SEARCH.md)
- **Backups and restore**, plus **CSV export** for spreadsheets. → [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md)
- **Meshtastic radio over Wi-Fi or USB.** Listen-only by default. Opt-in replies to approved customers' direct messages, with rate limits and no broadcasts. → [docs/RADIO_REPLIES.md](docs/RADIO_REPLIES.md)
- **Demo mode** with a sample shop: `open -a "Vapor Board" --args --demo`.
- Light/dark appearance, larger text sizes, keyboard shortcuts (⌘1–6 pages, ⌘N new, ⌘F search, ⌘L lock).

## Install (Intel Mac)
1. Download `Vapor-Board-<version>-Intel.dmg` from **[Vapor-Board-Releases](https://github.com/TheLogsAreScreaming/Vapor-Board-Releases/releases)**.
2. Open the DMG and drag **Vapor Board** to Applications.
3. The app is not yet signed by Apple. The first time, **right-click it ▸ Open ▸ Open**. (Or System Settings ▸ Privacy & Security ▸ *Open Anyway*.)
4. Create the owner account. Then add boards, staff and customers.

To run from source (Python 3.10+ with Tk): `python3 -m vapor_board.desktop`. No other packages are needed.

## Settings (`~/.vapor-board/shop.json`)
Edit the file and restart. Settings ▸ *Show in Finder* opens it. Unknown keys are refused, and Vapor Board falls back to defaults if the file can't be read.

| Key | Default | Meaning |
|---|---|---|
| `shop_name` | `"Vapor Board"` | Name in the sidebar, kiosk and radio replies |
| `operator_name` | `"Operator"` | The shared shop mailbox in Messages |
| `accent_color` | `"#238C9C"` | Six-digit hex colour |
| `appearance` | `"system"` | `system`, `light` or `dark` |
| `text_size` | `"standard"` | `standard`, `large` or `larger` |
| `auto_lock_minutes` | `15` | Lock after this many idle minutes (0 = never) |
| `kiosk_fullscreen` | `true` | Kiosk fills the screen |
| `kiosk_rotate_seconds` | `30` | Kiosk moves to the next board when idle (0 = never) |
| `transmissions_enabled` | `false` | Reply to approved customers over the radio |
| `minimum_customer_age` | `21` | Age staff confirm before approving (21 or higher) |
| `customer_access_requires_approval` | `true` | Shown in Settings; approval is always required |
| `mqtt_enabled`, `notices_enabled` | `false`, `true` | Reserved; there is no MQTT bridge |

## Your data
| File | Holds |
|---|---|
| `~/.vapor-board/bbs.sqlite` | Boards, posts, messages, customers |
| `~/.vapor-board/staff.sqlite` | Staff accounts (hashed passwords) and the activity log |
| `~/.vapor-board/backups/` | Backups from *Back up now* and the safety copies made before a restore |
| `~/Documents/Vapor Board Exports/` | CSV exports |
| `~/.vapor-board-demo/` | Demo mode only, wiped every demo launch |

Use FileVault and a macOS login password: Vapor Board's sign-in keeps casual users out of the app, but the files themselves aren't encrypted.

## Safety and compliance
- Notices and customer service only. **Age-restricted product promotion is out of scope** and needs its own legal review (health warnings, age gating, local rules).
- Customer access needs staff approval after an in-person ID check. No IDs, dates of birth or photos are stored.
- No automatic broadcasting, no MQTT, no internet bridge. Radio replies are opt-in, direct-only and rate-limited.
- A radio node ID is not proof of identity. Keep anything sensitive off customer-visible boards.

## Status
**1.0 release candidate.** Every feature has automated tests (unit tests on Linux and macOS, plus window tests on an Intel macOS runner). Still to do before 1.0 final:
- [ ] Click-through on a real Intel Mac (install, first launch, each page, kiosk, backup/restore, export)
- [ ] Listen-only test with a real Meshtastic radio over Wi-Fi
- [ ] Two-radio on-air test of replies (if you plan to turn transmit on)
- [ ] Apple signing and notarization (needs a paid Apple Developer account)

See [CHANGELOG.md](CHANGELOG.md) and [docs/MIGRATION_ROADMAP.md](docs/MIGRATION_ROADMAP.md).

## Development
```sh
python3 -m unittest discover -s tests -v      # window tests skip without a display
sh packaging/build_macos.sh                    # builds dist/Vapor Board.app and the DMG for this Mac's chip
```
Vapor Board is a separate project inspired by the engineering of [THE SITDOWN BBS](https://github.com/TheLogsAreScreaming/The-Sitdown-BBS), which remains independent.
