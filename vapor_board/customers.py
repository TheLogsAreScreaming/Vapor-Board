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

    def remove(self, customer_id, actor):
        """Delete the record entirely (for a customer who asks to be forgotten)."""
        self._require_staff(actor)
        with self._connect() as db:
            if db.execute("DELETE FROM customers WHERE id = ?", (customer_id,)).rowcount != 1:
                raise CustomerError("Customer not found")
