# Scheduled posts, spreadsheet export and demo mode

## Scheduled and expiring posts
The post composer has optional **Show from** and **Until** fields (local time): `2026-11-20`, `2026-11-20 9:30 AM` or `2026-11-20 21:30`. A date alone in *Until* means the end of that day.

- Customers (kiosk, radio replies) see a post only between those times. Staff always see every post.
- On the Boards page, scheduled and expired posts are marked ◷, and the reading pane says *Shows from…*, *Until…* or *Expired, hidden from customers*.
- Edit a post to change or clear its dates. Times are stored in UTC (`posts.publish_at`, `posts.expires_at`); older databases gain the columns on first launch.

## Export as spreadsheets
**File ▸ Export as Spreadsheets (CSV)** writes `posts.csv`, `messages.csv`, `customers.csv` and `activity.csv` into a new folder in `~/Documents/Vapor Board Exports/`. It's for reading and archiving; use **Back Up Now** to make something you can restore. Cells that a spreadsheet would run as a formula are prefixed with `'`.

The File menu also has Back Up Now, Restore From Backup…, Start Kiosk and Lock.

## Demo mode
Start with `--demo`, e.g. `open -a "Vapor Board" --args --demo`. Vapor Board opens a sample shop (“Corner Shop”) already signed in, with boards, posts, messages and customers.

- Everything lives in `~/.vapor-board-demo`, wiped and re-seeded on every demo launch. Your real `~/.vapor-board` is never opened.
- The radio cannot be connected in demo mode, and nothing is ever transmitted.
