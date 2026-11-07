# Search

A search box sits under the shop name in the sidebar (⌘F focuses it). Press Return to search.

## What is searched
- Posts on every board: body and author.
- The operator mailbox's own messages, sent and received: body and the other person's name.
- Never other mailboxes' private messages.
- Plain text, case-insensitive for English letters; `%` and `_` are matched literally. Up to 50 results, newest first.

## Search page
- Not in the sidebar list; it opens when you search. The header says how many posts and messages matched.
- Picking a result previews it with the matches highlighted. **Open** (or Return / double-click) jumps to the post on its board, or to the conversation in Messages → Threads.
- ⌘R reruns the search. Esc in the box clears it; ↓ moves into the results.

## Engine
`BulletinBoard.search(user, query, limit=50)` returns dicts with `kind` = `"post"` (plus `board_id`, `board_name`, `author`) or `"message"` (plus `sender`, `recipient`).

## Tests
`tests/test_search.py` (engine, privacy, wildcards), `tests/test_desktop_search_ui.py` (results, preview, open, fit at default and 900×600).

## Not yet verified
- Accented letters: SQLite's `lower()` only folds A–Z, so "CAFÉ" won't find "café".
- Speed on very large databases (no full-text index yet).
