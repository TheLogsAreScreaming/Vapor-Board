# Changelog

## Unreleased
- **Accessibility:** placeholders, checklist marks and section labels are easier to read. See docs/ACCESSIBILITY.md for what is and isn't covered.
- **Customer questions:** `ask` holds a question for staff, and the answer is posted without the customer's name.
- **Following boards:** `follow`, `unfollow` and `new`. Replies only when asked, so no extra radio traffic.

## 1.0.0 RC 3
- **Apple Silicon:** a separate DMG for M-series Macs alongside the Intel one. Both are unsigned.
- **USB radios:** *Find USB radio* on the Overview page. Listen-only by default, the same as Wi-Fi. Not yet tested on a real radio.
- **Shop profile:** hours and contact details in Settings, on the kiosk, and through the radio `info` command.
- **Update check:** off by default. File ▸ Check for Updates runs it when asked.
- **Staff message alerts:** a Mac notification when a customer's radio message arrives.
- **Settings** now has four tabs: Shop, Storage, Radio, Customer access.
- **Kiosk branding:** logo, tagline and text size.
- Radio replies: `more` reads older posts on a board.
- Getting started shows every step at the smallest window size.

## 1.0.0 RC 2
- **Owner recovery code:** shown once at set-up; *Forgot password?* on the sign-in screen resets an owner or admin password.
- **Backups include staff accounts** and the activity log. Restoring them is a separate choice for owners and admins.

## 1.0.0 RC 1
First release candidate.

- **Staff sign-in:** owner set-up, staff/admin accounts, lock and auto-lock, activity log (Staff page).
- **Customers:** records, approval after an in-person 21+ ID check, remove access/delete, boards marked Visible or Staff only.
- **Kiosk mode** for the shop counter.
- **Scheduled and expiring posts** (*Show from / Until*).
- **File menu:** back up, restore, CSV export, start kiosk, lock. **About** box in the app menu.
- **Demo mode** (`--demo`) with a sample shop; the radio can't connect.
- **Radio:** built-in Meshtastic codec (the packaged app no longer needs the `meshtastic` package), want_config handshake and heartbeat so the radio actually streams, quiet radios no longer drop the connection. Opt-in replies to approved customers' direct messages.
- Earlier work in this cycle: UI overhaul with light/dark and text sizes, private inbox and threaded conversations, board ordering and pinned posts, backup/restore, search.
