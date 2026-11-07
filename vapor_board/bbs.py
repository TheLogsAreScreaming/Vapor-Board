"""Offline-first local bulletin board engine. No radio transport or network I/O."""

import sqlite3
from pathlib import Path


class BulletinBoard:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS boards (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
            db.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, board_id INTEGER NOT NULL REFERENCES boards(id), author TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS mail (id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, read_at TEXT)")
            # Databases created before read tracking lack read_at; add it in place.
            if "read_at" not in self._columns(db, "mail"):
                db.execute("ALTER TABLE mail ADD COLUMN read_at TEXT")
            # Board order and pinned posts arrived later too; existing boards keep their creation order.
            if "position" not in self._columns(db, "boards"):
                db.execute("ALTER TABLE boards ADD COLUMN position INTEGER")
            db.execute("UPDATE boards SET position = id WHERE position IS NULL")
            if "pinned_at" not in self._columns(db, "posts"):
                db.execute("ALTER TABLE posts ADD COLUMN pinned_at TEXT")

    @staticmethod
    def _columns(db, table):
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _text(value, field, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{field} must contain 1–{limit} characters")
        return value.strip()

    def create_board(self, name):
        name = self._text(name, "board name", 80)
        with self._connect() as db:
            cursor = db.execute("INSERT INTO boards (name, position) VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM boards))", (name,))
            return cursor.lastrowid

    def list_boards(self):
        """Boards in the operator's chosen order (creation order until moved)."""
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, name FROM boards ORDER BY position, id")]

    def move_board(self, board_id, offset):
        """Move a board one place up (-1) or down (+1). Returns False when it is already at that end."""
        if type(board_id) is not int or board_id < 1:
            raise ValueError("invalid board id")
        if offset not in (-1, 1):
            raise ValueError("offset must be -1 or 1")
        with self._connect() as db:
            order = [row["id"] for row in db.execute("SELECT id FROM boards ORDER BY position, id")]
            if board_id not in order:
                raise ValueError("board not found")
            index = order.index(board_id)
            target = index + offset
            if not 0 <= target < len(order):
                return False
            order[index], order[target] = order[target], order[index]
            db.executemany("UPDATE boards SET position = ? WHERE id = ?", [(n, i) for n, i in enumerate(order, start=1)])
            return True

    def post(self, board_id, author, body):
        author = self._text(author, "author", 80)
        body = self._text(body, "post", 4000)
        if type(board_id) is not int or board_id < 1:
            raise ValueError("invalid board id")
        with self._connect() as db:
            cursor = db.execute("INSERT INTO posts (board_id, author, body) VALUES (?, ?, ?)", (board_id, author, body))
            return cursor.lastrowid

    def edit_post(self, post_id, body):
        """Replace a post's body; the original author is kept."""
        body = self._text(body, "post", 4000)
        if type(post_id) is not int or post_id < 1:
            raise ValueError("invalid post id")
        with self._connect() as db:
            if db.execute("UPDATE posts SET body = ? WHERE id = ?", (body, post_id)).rowcount != 1:
                raise ValueError("post not found")

    def delete_post(self, post_id):
        if type(post_id) is not int or post_id < 1:
            raise ValueError("invalid post id")
        with self._connect() as db:
            if db.execute("DELETE FROM posts WHERE id = ?", (post_id,)).rowcount != 1:
                raise ValueError("post not found")

    def pin_post(self, post_id, pinned=True):
        """Pin a post to the top of its board, or unpin it. Pinning twice keeps the first pin time."""
        if type(post_id) is not int or post_id < 1:
            raise ValueError("invalid post id")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone() is None:
                raise ValueError("post not found")
            if pinned:
                db.execute("UPDATE posts SET pinned_at = CURRENT_TIMESTAMP WHERE id = ? AND pinned_at IS NULL", (post_id,))
            else:
                db.execute("UPDATE posts SET pinned_at = NULL WHERE id = ?", (post_id,))

    def list_posts(self, board_id, limit=50):
        if type(board_id) is not int or board_id < 1:
            raise ValueError("invalid board id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, board_id, author, body, created_at, pinned_at FROM posts WHERE board_id = ? "
                "ORDER BY pinned_at IS NULL, pinned_at DESC, id DESC LIMIT ?", (board_id, limit))]

    def send_mail(self, sender, recipient, body):
        sender = self._text(sender, "sender", 80)
        recipient = self._text(recipient, "recipient", 80)
        body = self._text(body, "mail", 4000)
        with self._connect() as db:
            cursor = db.execute("INSERT INTO mail (sender, recipient, body) VALUES (?, ?, ?)", (sender, recipient, body))
            return cursor.lastrowid

    def inbox(self, recipient, limit=50):
        recipient = self._text(recipient, "recipient", 80)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, sender, recipient, body, created_at, read_at FROM mail WHERE recipient = ? ORDER BY id DESC LIMIT ?", (recipient, limit))]

    def sent(self, sender, limit=50):
        sender = self._text(sender, "sender", 80)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, sender, recipient, body, created_at, read_at FROM mail WHERE sender = ? ORDER BY id DESC LIMIT ?", (sender, limit))]

    def unread_count(self, recipient):
        recipient = self._text(recipient, "recipient", 80)
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM mail WHERE recipient = ? AND read_at IS NULL", (recipient,)).fetchone()[0]

    def mark_read(self, recipient, mail_id):
        """Mark one of recipient's own messages read; marking twice is harmless."""
        recipient = self._text(recipient, "recipient", 80)
        if type(mail_id) is not int or mail_id < 1:
            raise ValueError("invalid message id")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM mail WHERE id = ? AND recipient = ?", (mail_id, recipient)).fetchone() is None:
                raise ValueError("message not found")
            db.execute("UPDATE mail SET read_at = CURRENT_TIMESTAMP WHERE id = ? AND read_at IS NULL", (mail_id,))

    def conversations(self, user, limit=50):
        """One row per person user has written to or heard from, most recent first.

        Each row: other, last_body, last_at, last_from_user (bool), unread (messages from
        other that user hasn't read), total.
        """
        user = self._text(user, "user", 80)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        query = """
            SELECT other, COUNT(*) AS total,
                   SUM(CASE WHEN recipient = :user AND read_at IS NULL THEN 1 ELSE 0 END) AS unread,
                   MAX(id) AS last_id
            FROM (SELECT id, recipient, read_at,
                         CASE WHEN sender = :user THEN recipient ELSE sender END AS other
                  FROM mail WHERE sender = :user OR recipient = :user)
            GROUP BY other ORDER BY last_id DESC LIMIT :limit"""
        with self._connect() as db:
            rows = []
            for row in db.execute(query, {"user": user, "limit": limit}).fetchall():
                last = db.execute("SELECT sender, body, created_at FROM mail WHERE id = ?", (row["last_id"],)).fetchone()
                rows.append({"other": row["other"], "last_body": last["body"], "last_at": last["created_at"],
                             "last_from_user": last["sender"] == user, "unread": row["unread"], "total": row["total"]})
            return rows

    def conversation(self, user, other, limit=100):
        """The latest messages between user and other, oldest first (read top to bottom)."""
        user = self._text(user, "user", 80)
        other = self._text(other, "other person", 80)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1–200")
        with self._connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT id, sender, recipient, body, created_at, read_at FROM mail "
                "WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?) ORDER BY id DESC LIMIT ?",
                (user, other, other, user, limit))]
        return rows[::-1]

    def mark_conversation_read(self, user, other):
        """Mark everything other sent to user as read; returns how many changed."""
        user = self._text(user, "user", 80)
        other = self._text(other, "other person", 80)
        with self._connect() as db:
            return db.execute("UPDATE mail SET read_at = CURRENT_TIMESTAMP WHERE recipient = ? AND sender = ? AND read_at IS NULL",
                              (user, other)).rowcount

    def search(self, user, query, limit=50):
        """Posts on any board, plus user's own messages (sent or received), containing query.

        Case-insensitive plain-text match (no wildcards) on bodies, authors and names.
        Results are newest first; each has kind "post" or "message". Other people's
        private messages are never searched.
        """
        user = self._text(user, "user", 80)
        query = self._text(query, "search", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        pattern = "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        like = "LIKE :pattern ESCAPE '\\'"
        with self._connect() as db:
            posts = [dict(row, kind="post") for row in db.execute(
                f"""SELECT posts.id, posts.board_id, boards.name AS board_name, posts.author, posts.body, posts.created_at
                    FROM posts JOIN boards ON boards.id = posts.board_id
                    WHERE lower(posts.body) {like} OR lower(posts.author) {like}
                    ORDER BY posts.created_at DESC, posts.id DESC LIMIT :limit""",
                {"pattern": pattern, "limit": limit})]
            messages = [dict(row, kind="message") for row in db.execute(
                f"""SELECT id, sender, recipient, body, created_at, read_at FROM mail
                    WHERE (sender = :user OR recipient = :user)
                      AND (lower(body) {like} OR lower(CASE WHEN sender = :user THEN recipient ELSE sender END) {like})
                    ORDER BY created_at DESC, id DESC LIMIT :limit""",
                {"user": user, "pattern": pattern, "limit": limit})]
        found = sorted(posts + messages, key=lambda r: (r["created_at"], r["kind"] == "message", r["id"]), reverse=True)
        return found[:limit]

    def command(self, user, command):
        """Read-only commands only; writes require explicit application authorization."""
        user = self._text(user, "user", 80)
        command = self._text(command, "command", 200).lower().strip()
        if command in ("/help", "/menu"):
            return "Commands: /help, /menu, /boards, /inbox"
        if command == "/boards":
            boards = self.list_boards()
            return "\n".join(f"{board['id']}: {board['name']}" for board in boards) or "No boards yet."
        if command == "/inbox":
            return f"{len(self.inbox(user))} message(s) in inbox."
        return "Unknown command. Use /help."
