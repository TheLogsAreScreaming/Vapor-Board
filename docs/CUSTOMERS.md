# Customers and visible boards

The Customers page keeps the shop's customer list and decides what customers can read.

- **Add a customer:** name, optional phone or email, optional Meshtastic node ID (`!a1b2c3d4`, needed only for radio replies). New customers wait for approval.
- **Approve…** asks staff to confirm they checked a government photo ID **in person** showing the customer is 21 or older (`minimum_customer_age`). Vapor Board records *who* checked and *when*, never the ID, date of birth or photo.
- **Remove access** keeps the record but stops access; **Delete** removes the record (for a customer who asks to be forgotten).
- **Visible boards** tab: every board is visible to customers until marked *Staff only*. Staff always see every board. Customer-facing views (kiosk, radio replies) show only visible boards.
- Every change is written to the activity log under the signed-in staff member.

Customer records live in `bbs.sqlite` (table `customers`), so board backups include them.
