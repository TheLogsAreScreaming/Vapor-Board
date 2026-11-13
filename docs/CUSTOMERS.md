# Customers and visible boards

The Customers page keeps the shop's customer list and decides what customers can read.

- **Add a customer:** name, optional phone or email, optional Meshtastic node ID (`!a1b2c3d4`, needed only for radio replies). New customers wait for approval.
- **Approve…** asks staff to confirm they checked a government photo ID **in person** showing the customer is 21 or older (`minimum_customer_age`). Vapor Board records *who* checked and *when*, never the ID, date of birth or photo.
- **Remove access** keeps the record but stops access; **Delete** removes the record, their messages, questions, follows and read history, and takes their name and radio ID out of the activity log (for a customer who asks to be forgotten). Messages are filed by name, so they stay if another customer or staff member has the same name; the app says when that happens.
- **Visible boards** tab: every board is visible to customers until marked *Staff only*. Staff always see every board. Customer-facing views (kiosk, radio replies) show only visible boards.
- **Phones…** pairs an approved customer's Android phone for read-only notices over the shop Wi-Fi (docs/PHONE_NOTICES.md).
- Every change is written to the activity log under the signed-in staff member.

Customer records live in `bbs.sqlite` (table `customers`), so board backups include them.

## Questions

Approved customers can send `ask N <question>` by radio, where N is a board number. A question is held on the **Questions** tab and customers can't see it. **Answer…** posts the question and answer to that board under the shop's name, without the customer's name. **Decline** deletes it and posts nothing. A customer can have 3 questions waiting, and the shop 200.

## Following boards

`follow N` and `unfollow N` choose boards; `new` sends unseen posts from them, 3 at a time. Vapor Board only answers when asked, so following a board adds no radio traffic of its own. Deleting a customer also deletes their questions, follows and read history.
