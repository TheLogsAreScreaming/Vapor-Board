# Staff sign-in, accounts and activity log

Vapor Board now asks for a staff sign-in before it shows anything.

- **First launch:** a set-up screen creates the owner account (name, username, password twice). The first account is always an owner/admin.
- **Sign-in:** username (not case-sensitive) and password. Five wrong passwords in a row pause sign-in for a minute.
- **Lock:** the *Lock* link in the sidebar or ⌘L returns to the sign-in screen. After `auto_lock_minutes` (shop.json, default 15, 0 = never) without a key press or click, the window locks on its own.
- **Staff page:** owners/admins add staff (Staff or Admin role), disable/re-enable accounts and reset passwords. Staff can change only their own password. You can't disable yourself or the last active admin.
- **Activity log:** sign-ins, failed sign-ins, locks, account changes, board/post/pin changes, messages sent, backups and restores, newest first, on the Staff page.

## Storage and security

- Accounts and the log are in `~/.vapor-board/staff.sqlite`, separate from `bbs.sqlite`. Restoring a board backup never changes who can sign in.
- Passwords are stored as salted PBKDF2-SHA256 hashes (600,000 rounds), never in plain text.
- The shop mailbox (`operator_name` in shop.json) is shared: every signed-in staff member reads and sends private messages as it. Posts default to the signed-in person's name as author.
- This protects the board from casual access on a shared shop Mac. It is not disk encryption: anyone with the Mac's user account can copy the files. Use FileVault and a macOS login password.
- Forgotten owner password with no other admin: quit Vapor Board and move `staff.sqlite` aside; the next launch asks for a new owner account. Boards and messages are untouched.
