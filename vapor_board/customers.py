"""Customer records, in-person 21+ checks and approvals, stored with the boards in bbs.sqlite.

Only signed-in staff change these records (the desktop passes the staff Account). No ID
documents, dates of birth or photos are stored: only that a named staff member checked a
customer's ID in person, and when. Approval is required before a customer can read
anything through the kiosk or radio replies.
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from .bbs import BulletinBoard

MAX_QUESTION, MAX_ANSWER, MAX_WAITING_PER_CUSTOMER, MAX_WAITING = 200, 1000, 3, 200
PENDING, APPROVED, REVOKED = "pending", "approved", "revoked"
STATUS_LABELS = {PENDING: "Waiting for approval", APPROVED: "Approved", REVOKED: "Access removed"}
_NODE = re.compile(r"^!?([0-9a-f]{8})$")


class CustomerError(ValueError):
    """A customer change was refused; the message is shown to the operator."""


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    contact: str
    node_id: str
    status: str
    verified_by: str
    verified_at: str
    created_at: str

    @property
    def approved(self):
        return self.status == APPROVED and bool(self.verified_by and self.verified_at)

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)


def normalise_node(value):
    """'!a1b2c3d4' form of a Meshtastic node ID, '' when blank. Raises CustomerError when malformed."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    match = _NODE.fullmatch(text)
    if not match:
        raise CustomerError("Radio node IDs look like !a1b2c3d4 (8 letters or digits after the !)")
    return "!" + match.group(1)


@dataclass(frozen=True)
class Question:
    """A customer's question, held for staff. Nothing reaches a board until staff answer it."""
    id: int
    customer_id: int
    customer_name: str
    board_id: int
    body: str
    created_at: str


class CustomerBook:
    def __init__(self, database_path):
        self.path = Path(database_path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            verified_by TEXT NOT NULL DEFAULT '', verified_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_questions (
            id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, customer_name TEXT NOT NULL, board_id INTEGER NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE TABLE IF NOT EXISTS customer_follows (customer_id INTEGER NOT NULL, board_id INTEGER NOT NULL, PRIMARY KEY (customer_id, board_id))")
        db.execute("CREATE TABLE IF NOT EXISTS customer_seen (customer_id INTEGER NOT NULL, post_id INTEGER NOT NULL, PRIMARY KEY (customer_id, post_id))")
        return db

    @staticmethod
    def _row(row):
        return Customer(row["id"], row["name"], row["contact"], row["node_id"], row["status"],
                        row["verified_by"], row["verified_at"], row["created_at"])

    @staticmethod
    def _require_staff(actor):
        if actor is None or not getattr(actor, "active", False) or not getattr(actor, "username", ""):
            raise CustomerError("Sign in as staff first")

    def customers(self):
        if not self.path.exists():
            return []
        with self._connect() as db:
            rows = db.execute("SELECT * FROM customers ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, "
                              "name COLLATE NOCASE, id")
            return [self._row(row) for row in rows]

    def get(self, customer_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return self._row(row) if row else None

    def by_node(self, node_id):
        """The customer registered with this radio node, or None."""
        try:
            node = normalise_node(node_id)
        except CustomerError:
            return None
        if not node or not self.path.exists():
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM customers WHERE node_id = ?", (node,)).fetchone()
        return self._row(row) if row else None

    def pending_count(self):
        if not self.path.exists():
            return 0
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM customers WHERE status = 'pending'").fetchone()[0]

    def add(self, name, contact="", node_id="", actor=None):
        self._require_staff(actor)
        name = " ".join(str(name or "").split())
        if not 1 <= len(name) <= 60:
            raise CustomerError("Enter the customer's name (1–60 characters)")
        contact = " ".join(str(contact or "").split())
        if len(contact) > 80:
            raise CustomerError("Keep contact details under 80 characters")
        node = normalise_node(node_id)
        with self._connect() as db:
            if node and db.execute("SELECT 1 FROM customers WHERE node_id = ?", (node,)).fetchone():
                raise CustomerError(f"Radio node {node} already belongs to another customer")
            cursor = db.execute("INSERT INTO customers (name, contact, node_id) VALUES (?, ?, ?)", (name, contact, node))
        return self.get(cursor.lastrowid)

    def approve(self, customer_id, actor, id_checked_21_plus):
        """Approve after a staff member has checked a government ID in person showing 21 or older."""
        self._require_staff(actor)
        if id_checked_21_plus is not True:
            raise CustomerError("Check the customer's ID in person (21 or older) before approving")
        customer = self.get(customer_id)
        if customer is None:
            raise CustomerError("Customer not found")
        with self._connect() as db:
            db.execute("UPDATE customers SET status = 'approved', verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (actor.username, customer.id))
        return self.get(customer.id)

    def revoke(self, customer_id, actor):
        self._require_staff(actor)
        customer = self.get(customer_id)
        if customer is None:
            raise CustomerError("Customer not found")
        with self._connect() as db:
            db.execute("UPDATE customers SET status = 'revoked' WHERE id = ?", (customer.id,))
        return self.get(customer.id)

    def remove(self, customer_id, actor, protected_names=()):
        """Delete the record entirely (for a customer who asks to be forgotten), with their messages.

        Messages are filed by name, so they stay when the name also belongs to another customer
        or to anything in protected_names (staff accounts, the shop mailbox).
        Returns True when the customer's name was unique and their messages were deleted.
        """
        self._require_staff(actor)
        customer = self.get(customer_id)
        unique = customer is not None and customer.name.casefold() not in {str(name).casefold() for name in protected_names} \
            and sum(c.name.casefold() == customer.name.casefold() for c in self.customers()) == 1
        with self._connect() as db:
            if db.execute("DELETE FROM customers WHERE id = ?", (customer_id,)).rowcount != 1:
                raise CustomerError("Customer not found")
            for table in ("customer_questions", "customer_follows", "customer_seen"):
                db.execute(f"DELETE FROM {table} WHERE customer_id = ?", (customer_id,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'phone_devices'").fetchone():
                db.execute("DELETE FROM phone_devices WHERE customer_id = ?", (customer_id,))  # paired phones
        if unique:
            BulletinBoard(self.path).delete_mail_for(customer.name)
        return unique

    # ---- questions held for staff ---------------------------------------------------------
    def add_question(self, customer, board_id, text):
        """Hold a question for staff. It stays private until a staff member answers it."""
        body = " ".join(str(text or "").split())
        if not 1 <= len(body) <= MAX_QUESTION:
            raise CustomerError(f"Keep questions to {MAX_QUESTION} characters")
        with self._connect() as db:
            if db.execute("SELECT COUNT(*) FROM customer_questions WHERE customer_id = ?", (customer.id,)).fetchone()[0] >= MAX_WAITING_PER_CUSTOMER:
                raise CustomerError("You have questions waiting already. Staff will answer those first.")
            if db.execute("SELECT COUNT(*) FROM customer_questions").fetchone()[0] >= MAX_WAITING:
                raise CustomerError("The question list is full right now. Try again later.")
            cursor = db.execute("INSERT INTO customer_questions (customer_id, customer_name, board_id, body) VALUES (?, ?, ?, ?)",
                                (customer.id, customer.name, board_id, body))
            return cursor.lastrowid

    def questions(self):
        """Questions waiting for staff, oldest first."""
        if not self.path.exists():
            return []
        with self._connect() as db:
            return [Question(r["id"], r["customer_id"], r["customer_name"], r["board_id"], r["body"], r["created_at"])
                    for r in db.execute("SELECT * FROM customer_questions ORDER BY id")]

    def answer_question(self, question_id, answer, author, actor):
        """Post the question and answer on its board, without the customer's name, and drop it from the list."""
        self._require_staff(actor)
        answer = str(answer or "").strip()
        if not 1 <= len(answer) <= MAX_ANSWER:
            raise CustomerError(f"Enter an answer (1–{MAX_ANSWER} characters)")
        question = next((q for q in self.questions() if q.id == question_id), None)
        if question is None:
            raise CustomerError("That question is no longer waiting")
        try:
            post_id = BulletinBoard(self.path).post(question.board_id, author, f"Q: {question.body}\nA: {answer}")
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise CustomerError("That question's board no longer exists. Decline the question instead.") from exc
        with self._connect() as db:
            db.execute("DELETE FROM customer_questions WHERE id = ?", (question_id,))
        return question, post_id

    def decline_question(self, question_id, actor):
        """Delete a question without posting anything."""
        self._require_staff(actor)
        with self._connect() as db:
            if db.execute("DELETE FROM customer_questions WHERE id = ?", (question_id,)).rowcount != 1:
                raise CustomerError("That question is no longer waiting")

    # ---- boards a customer follows ---------------------------------------------------------
    def follow(self, customer_id, board_id, current_post_ids=()):
        """Follow a board. Posts already there count as seen, so `new` starts from now."""
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO customer_follows VALUES (?, ?)", (customer_id, board_id))
            db.executemany("INSERT OR IGNORE INTO customer_seen VALUES (?, ?)", [(customer_id, post) for post in current_post_ids])

    def unfollow(self, customer_id, board_id):
        with self._connect() as db:
            return db.execute("DELETE FROM customer_follows WHERE customer_id = ? AND board_id = ?", (customer_id, board_id)).rowcount == 1

    def followed_boards(self, customer_id):
        with self._connect() as db:
            return {row[0] for row in db.execute("SELECT board_id FROM customer_follows WHERE customer_id = ?", (customer_id,))}

    def seen_posts(self, customer_id):
        with self._connect() as db:
            return {row[0] for row in db.execute("SELECT post_id FROM customer_seen WHERE customer_id = ?", (customer_id,))}

    def mark_seen(self, customer_id, post_ids):
        with self._connect() as db:
            db.executemany("INSERT OR IGNORE INTO customer_seen VALUES (?, ?)", [(customer_id, post) for post in post_ids])
