# Privacy and data retention (draft)

**Draft for the shop owner to review with a lawyer. It is not legal advice.** It describes what Vapor Board does today. Rules for age checks, customer records and marketing differ by state.

## What is stored

Everything is stored on the shop's Mac, in `~/.vapor-board`.

| Data | Where | Removed by |
|---|---|---|
| Customer name, optional phone or email, optional radio node ID | `bbs.sqlite` | *Delete* on the Customers page |
| Who checked a customer's ID, and when | `bbs.sqlite` | *Delete* on the Customers page |
| A customer's waiting questions, followed boards and read history | `bbs.sqlite` | *Delete* on the Customers page, or staff answering or declining the question |
| Board posts, including answered questions (no customer name) | `bbs.sqlite` | Staff deleting the post |
| Private messages between customers and staff | `bbs.sqlite` | *Delete* on the Messages page, or deleting the customer |
| Staff accounts and password hashes | `staff.sqlite` | Staff page |
| Activity log, which can include customer names and radio node IDs | `staff.sqlite` | Admins can delete entries older than 90 days. Deleting a customer takes their name and radio ID out of it |

Vapor Board does **not** store ID documents, photos or dates of birth. Staff check ID in person and the app records only that it was done.

## Retention

Nothing is deleted automatically. Records stay until staff delete them.

Backups are separate copies. Deleting a customer doesn't change backups already made, so restoring an older backup brings that customer back.

## What leaves the Mac

- **Radio:** Radio traffic can be received by others on the mesh. Direct messages may be readable by anyone who has the relevant channel key, depending on the radio's settings, so customers shouldn't send sensitive details. Replies are off by default.
- **Update check:** off by default. When used, it asks GitHub for the list of releases and sends no shop data. GitHub sees the Mac's IP address.
- **MQTT status:** off by default. When used, it connects to a broker on the shop's network, sends no shop data and doesn't keep what it receives.
- **Phone notices:** off by default. When used, paired customer phones on the shop's Wi-Fi can fetch the Visible boards and current posts. Nothing else is served and nothing is sent outside the shop network. Notices travel unencrypted on the Wi-Fi.
- **Staff alerts:** shown by macOS on the same Mac.
- **Backups and exports:** go wherever staff save them. They're not encrypted, so store them as carefully as the Mac itself. CSV exports can contain customer details.

There are no analytics and no accounts with an outside service.

## If a customer asks to be forgotten

1. Delete them on the Customers page. This also removes their messages, questions, follows and read history, and takes their name and radio ID out of the activity log.
2. If the app says messages were kept because someone else has that name, delete that customer's conversations on the Messages page.
3. Replace or delete older backups that still contain them, following the shop's own schedule.

## For the owner to decide

- How long to keep customer records, messages, the activity log and backups.
- Whether any state law requires keeping age-check records for a set period, or forbids it.
- What to tell customers when they sign up, and who answers privacy requests.
