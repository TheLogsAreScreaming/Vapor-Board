# Changelog

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
