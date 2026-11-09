"""Staff accounts, sign-in and the activity log, kept in their own local database.

Passwords are stored only as salted PBKDF2-SHA256 hashes. Accounts live in
``~/.vapor-board/staff.sqlite``, apart from the boards database, so restoring a board
backup never changes who can sign in. Nothing here is sent over the network or radio.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

ADMIN = "admin"
STAFF = "staff"
ROLES = (ADMIN, STAFF)
ITERATIONS = 600_000  # OWASP 2023 guidance for PBKDF2-SHA256
MIN_PASSWORD = 8
MAX_FAILURES = 5  # wrong passwords in a row before sign-in pauses
LOCKOUT_SECONDS = 60
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # no I, L, O or U: hard to misread
CODE_LENGTH = 20  # 100 random bits
_RECOVERY_KEY = "\0recovery"  # failure counter shared by all recovery attempts; can't be a username


class AccountError(ValueError):
    """An account change was refused; the message is shown to the operator."""


@dataclass(frozen=True)
class Account:
    id: int
    username: str
    display_name: str
    role: str
    active: bool
    created_at: str
    last_sign_in: str

    @property
    def is_admin(self):
        return self.role == ADMIN

    @property
    def role_label(self):
        return "Owner / admin" if self.is_admin else "Staff"


def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class StaffDirectory:
    def __init__(self, path, clock=time.monotonic):
        self.path = Path(path)
        self._clock = clock
        self._failures = {}  # username -> (count, last failure time); in memory only

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
            role TEXT NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL, iterations INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_sign_in TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')""")
        db.execute("""CREATE TABLE IF NOT EXISTS recovery (
            id INTEGER PRIMARY KEY CHECK (id = 1), code_hash TEXT NOT NULL, salt TEXT NOT NULL,
            iterations INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        return db

    # ---- reading ---------------------------------------------------------------------------
    def exists(self):
        """True once any account has been made (the first launch asks for the owner account)."""
        if not self.path.exists():
            return False
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM staff").fetchone()[0] > 0

    @staticmethod
    def _account(row):
        return Account(row["id"], row["username"], row["display_name"], row["role"], bool(row["active"]),
                       row["created_at"], row["last_sign_in"] or "")

    def accounts(self):
        if not self.path.exists():
            return []
        with self._connect() as db:
            rows = db.execute("SELECT * FROM staff ORDER BY active DESC, role = 'staff', display_name COLLATE NOCASE")
            return [self._account(row) for row in rows]

    def get(self, username):
        with self._connect() as db:
            row = db.execute("SELECT * FROM staff WHERE username = ?", (str(username).strip().lower(),)).fetchone()
        return self._account(row) if row else None

    # ---- validation ------------------------------------------------------------------------
    @staticmethod
    def _username(value):
        value = str(value or "").strip().lower()
        if not _USERNAME.fullmatch(value):
            raise AccountError("Usernames are 2–32 letters, numbers, dots, dashes or underscores")
        return value

    @staticmethod
    def _display(value):
        value = " ".join(str(value or "").split())
        if not 1 <= len(value) <= 40:
            raise AccountError("Enter a name of 1–40 characters")
        return value

    @staticmethod
    def _password(value):
        if not isinstance(value, str) or len(value) < MIN_PASSWORD:
            raise AccountError(f"Passwords need at least {MIN_PASSWORD} characters")
        if len(value) > 256:
            raise AccountError("That password is too long")
        return value

    @staticmethod
    def _require_admin(actor):
        if actor is None or not actor.active or not actor.is_admin:
            raise AccountError("Only an owner or admin can do that")

    # ---- changes ---------------------------------------------------------------------------
    def create(self, username, display_name, password, role=STAFF, actor=None, iterations=None):
        """Add an account. The very first account is always the owner (admin) and needs no actor."""
        username, display_name, password = self._username(username), self._display(display_name), self._password(password)
        first = not self.exists()
        if first:
            role = ADMIN
        else:
            self._require_admin(actor)
        if role not in ROLES:
            raise AccountError("Unknown role")
        salt = secrets.token_bytes(16)
        rounds = iterations or ITERATIONS
        try:
            with self._connect() as db:
                db.execute("INSERT INTO staff (username, display_name, role, password_hash, salt, iterations) VALUES (?, ?, ?, ?, ?, ?)",
                           (username, display_name, role, _hash(password, salt, rounds), salt.hex(), rounds))
        except sqlite3.IntegrityError as exc:
            raise AccountError(f"The username “{username}” is already taken") from exc
        account = self.get(username)
        self.log(actor.username if actor else username, "account created" if not first else "owner account created",
                 f"{display_name} ({username}, {account.role_label})")
        return account

    def authenticate(self, username, password):
        """The account for a correct username and password, else None. Repeated failures pause sign-in."""
        key = str(username or "").strip().lower()
        count, last = self._failures.get(key, (0, 0.0))
        if count >= MAX_FAILURES and self._clock() - last < LOCKOUT_SECONDS:
            raise AccountError(f"Too many wrong passwords. Try again in {int(LOCKOUT_SECONDS - (self._clock() - last)) + 1} seconds")
        if not self.path.exists():
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM staff WHERE username = ?", (key,)).fetchone()
        ok = bool(row) and isinstance(password, str) and hmac.compare_digest(
            _hash(password, bytes.fromhex(row["salt"]), row["iterations"]), row["password_hash"])
        if not ok or not row["active"]:
            self._failures[key] = (count + 1 if count < MAX_FAILURES else 1, self._clock())
            if key:
                self.log(key, "sign-in failed", "account disabled" if ok else "wrong username or password")
            return None
        self._failures.pop(key, None)
        with self._connect() as db:
            db.execute("UPDATE staff SET last_sign_in = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
        self.log(key, "signed in")
        return self.get(key)

    def set_password(self, username, password, actor, iterations=None):
        """Admins may reset anyone's password; staff may change only their own."""
        target = self.get(username)
        if target is None:
            raise AccountError("No such account")
        if actor is None or not actor.active or (actor.username != target.username and not actor.is_admin):
            raise AccountError("You can only change your own password")
        password = self._password(password)
        salt = secrets.token_bytes(16)
        rounds = iterations or ITERATIONS
        with self._connect() as db:
            db.execute("UPDATE staff SET password_hash = ?, salt = ?, iterations = ? WHERE id = ?",
                       (_hash(password, salt, rounds), salt.hex(), rounds, target.id))
        self.log(actor.username, "password changed", target.username)

    def set_active(self, username, active, actor):
        """Disable or re-enable an account. The last active admin and yourself can't be disabled."""
        self._require_admin(actor)
        target = self.get(username)
        if target is None:
            raise AccountError("No such account")
        if not active:
            if target.username == actor.username:
                raise AccountError("You can't disable the account you're signed in with")
            admins = [a for a in self.accounts() if a.active and a.is_admin]
            if target.is_admin and len(admins) <= 1:
                raise AccountError("Keep at least one active owner or admin")
        with self._connect() as db:
            db.execute("UPDATE staff SET active = ? WHERE id = ?", (int(bool(active)), target.id))
        self.log(actor.username, "account enabled" if active else "account disabled", target.username)
        return self.get(target.username)

    # ---- owner recovery code ---------------------------------------------------------------
    @staticmethod
    def new_recovery_code():
        """A fresh code like ABCD-EFGH-JKMN-PQRS-TV01. Nothing is stored until save_recovery_code."""
        raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
        return "-".join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))

    @staticmethod
    def _normal_code(code):
        """Upper case, no spaces or dashes, and the look-alike letters read as the digits they resemble."""
        text = re.sub(r"[\s-]", "", str(code or "")).upper()
        return text.translate(str.maketrans("OIL", "011"))

    def has_recovery_code(self):
        if not self.path.exists():
            return False
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM recovery").fetchone()[0] > 0

    def save_recovery_code(self, code, actor, iterations=None):
        """Store a code's hash, replacing any earlier code. Owners and admins only."""
        self._require_admin(actor)
        normal = self._normal_code(code)
        if len(normal) != CODE_LENGTH or set(normal) - set(_CODE_ALPHABET):
            raise AccountError("That isn't a valid recovery code")
        salt = secrets.token_bytes(16)
        rounds = iterations or ITERATIONS
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO recovery (id, code_hash, salt, iterations) VALUES (1, ?, ?, ?)",
                       (_hash(normal, salt, rounds), salt.hex(), rounds))
        self.log(actor.username, "recovery code saved")

    def recover(self, username, code, new_password, iterations=None):
        """Reset an active owner/admin's password with the recovery code, which is then used up.

        Returns the account, or None when the username or code is wrong. Repeated failures pause recovery.
        """
        count, last = self._failures.get(_RECOVERY_KEY, (0, 0.0))
        if count >= MAX_FAILURES and self._clock() - last < LOCKOUT_SECONDS:
            raise AccountError(f"Too many wrong attempts. Try again in {int(LOCKOUT_SECONDS - (self._clock() - last)) + 1} seconds")
        new_password = self._password(new_password)
        key = str(username or "").strip().lower()
        if not self.path.exists():
            return None
        with self._connect() as db:
            stored = db.execute("SELECT * FROM recovery").fetchone()
            target = db.execute("SELECT * FROM staff WHERE username = ? AND role = ? AND active = 1", (key, ADMIN)).fetchone()
        ok = bool(stored) and hmac.compare_digest(
            _hash(self._normal_code(code), bytes.fromhex(stored["salt"]), stored["iterations"]), stored["code_hash"])
        if not ok or target is None:
            self._failures[_RECOVERY_KEY] = (count + 1 if count < MAX_FAILURES else 1, self._clock())
            self.log(key[:40] or "unknown", "password recovery failed", "wrong username or recovery code")
            return None
        salt = secrets.token_bytes(16)
        rounds = iterations or ITERATIONS
        with self._connect() as db:  # one transaction: the code can't survive a successful reset
            db.execute("UPDATE staff SET password_hash = ?, salt = ?, iterations = ?, last_sign_in = CURRENT_TIMESTAMP WHERE id = ?",
                       (_hash(new_password, salt, rounds), salt.hex(), rounds, target["id"]))
            db.execute("DELETE FROM recovery")
        self._failures.pop(_RECOVERY_KEY, None)
        self._failures.pop(key, None)
        self.log(key, "password reset with recovery code")
        return self.get(key)

    # ---- activity log ----------------------------------------------------------------------
    def log(self, actor, action, detail=""):
        with self._connect() as db:
            db.execute("INSERT INTO activity (actor, action, detail) VALUES (?, ?, ?)",
                       (str(actor)[:40], str(action)[:60], str(detail)[:200]))

    def forget_in_activity(self, *names):
        """Replace these names and radio IDs in the log with a marker, keeping what happened and when."""
        terms = [re.escape(str(name)) for name in names if str(name or "").strip()]
        if not terms or not self.path.exists():
            return 0
        pattern = re.compile(r"(?<![\w!])(?:" + "|".join(terms) + r")(?!\w)", re.IGNORECASE)
        changed = 0
        with self._connect() as db:
            for row in db.execute("SELECT id, detail FROM activity").fetchall():
                detail = pattern.sub("[deleted customer]", row["detail"])
                if detail != row["detail"]:
                    db.execute("UPDATE activity SET detail = ? WHERE id = ?", (detail, row["id"]))
                    changed += 1
        return changed

    def clear_activity_older_than(self, days, actor):
        """Admins only. Deletes old entries and records that it was done."""
        if actor is None or not actor.active or not actor.is_admin:
            raise AccountError("Only an owner or admin can delete the activity log")
        with self._connect() as db:
            removed = db.execute("DELETE FROM activity WHERE at < datetime('now', ?)", (f"-{int(days)} days",)).rowcount
        self.log(actor.username, "activity log cleared", f"{removed} entries older than {int(days)} days")
        return removed

    def activity(self, limit=100):
        if not self.path.exists():
            return []
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))]
