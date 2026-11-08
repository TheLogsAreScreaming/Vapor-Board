"""Local database backups: consistent snapshots, verification and an all-or-nothing restore.

Backups are plain SQLite files kept beside the database (``~/.vapor-board/backups``).
Nothing is uploaded or sent anywhere. A restore never deletes data: the current
database is snapshotted first, so the restore itself can be undone.

Staff accounts and the activity log are saved beside each board backup in a ``.staff`` file
with the same name. Restoring them is a separate choice; a board restore leaves them alone.
"""
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REQUIRED_TABLES = ("boards", "posts", "mail")
PREFIX = "bbs-"
SUFFIX = ".sqlite"
STAFF_SUFFIX = ".staff"
STAFF_TABLES = ("staff", "activity")


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created: datetime
    size: int
    boards: int
    posts: int
    messages: int
    label: str = ""  # "before restore" for the automatic safety copy

    @property
    def summary(self):
        def count(n, word):
            return f"{n} {word}" + ("" if n == 1 else "s")
        return ", ".join((count(self.boards, "board"), count(self.posts, "post"), count(self.messages, "message")))


@dataclass(frozen=True)
class StaffBackup:
    path: Path
    accounts: int
    admins: int  # active owners/admins: someone must be able to sign in after a restore


class BackupError(ValueError):
    """A backup could not be made, read or restored; the message is shown to the operator."""


def _copy(source, destination):
    """Consistent copy with SQLite's online backup API (safe even while the source is open)."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def inspect(path):
    """Counts for a backup file, or BackupError if it is not a usable Vapor Board database."""
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"{path.name} doesn't exist")
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError(f"{path.name} is damaged")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing = [name for name in REQUIRED_TABLES if name not in tables]
            if missing:
                raise BackupError(f"{path.name} isn't a Vapor Board backup (no {', '.join(missing)} table)")
            counts = [db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in REQUIRED_TABLES]
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path.name} isn't a readable database ({exc})") from exc
    stem = path.stem[len(PREFIX):] if path.stem.startswith(PREFIX) else ""
    stamp, _, label = stem.partition("-before-")
    try:
        created = datetime.strptime(stamp[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        created = datetime.fromtimestamp(path.stat().st_mtime)
    return BackupInfo(path, created, path.stat().st_size, *counts,
                      label="before restore" if label.startswith("restore") else "")


def staff_file(backup):
    """Where the staff accounts for a board backup are kept."""
    return Path(backup).with_suffix(STAFF_SUFFIX)


def inspect_staff(path):
    """Counts for a staff backup file, or BackupError if it isn't one."""
    path = Path(path)
    if not path.is_file():
        raise BackupError("This backup has no staff accounts")
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError(f"{path.name} is damaged")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not set(STAFF_TABLES) <= tables:
                raise BackupError(f"{path.name} isn't a staff accounts backup")
            accounts = db.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
            admins = db.execute("SELECT COUNT(*) FROM staff WHERE role = 'admin' AND active = 1").fetchone()[0]
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path.name} isn't a readable database ({exc})") from exc
    return StaffBackup(path, accounts, admins)


def staff_in_backup(backup):
    """The restorable staff accounts saved with a board backup, or None."""
    try:
        found = inspect_staff(staff_file(backup))
    except BackupError:
        return None
    return found if found.admins else None


def _new_path(folder, now, tag=""):
    name = f"{PREFIX}{now:%Y%m%d-%H%M%S}{tag}"
    candidate = folder / f"{name}{SUFFIX}"
    number = 2
    while candidate.exists():  # two backups in the same second
        candidate = folder / f"{name}-{number}{SUFFIX}"
        number += 1
    return candidate


def create_backup(database, folder, now=None, tag="", staff_database=None):
    """Snapshot the database (and staff accounts, if given) into folder and verify it. Returns the BackupInfo."""
    database, folder = Path(database), Path(folder)
    if not database.is_file():
        raise BackupError("There's no database to back up yet")
    folder.mkdir(parents=True, exist_ok=True)
    target = _new_path(folder, now or datetime.now(), tag)
    partial = target.with_suffix(".partial")
    staff_partial = target.with_suffix(".staff-partial")
    include_staff = staff_database is not None and Path(staff_database).is_file()
    try:
        _copy(database, partial)
        inspect(partial)
        if include_staff:
            _copy(staff_database, staff_partial)
            inspect_staff(staff_partial)
            os.chmod(staff_partial, 0o600)  # holds password hashes
            os.replace(staff_partial, staff_file(target))
        os.replace(partial, target)
    except (OSError, sqlite3.DatabaseError, BackupError) as exc:
        partial.unlink(missing_ok=True)
        staff_partial.unlink(missing_ok=True)
        staff_file(target).unlink(missing_ok=True)
        raise BackupError(f"Backup failed: {exc}") from exc
    return inspect(target)


def list_backups(folder):
    """Valid backups in folder, newest first. Unreadable files are skipped."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob(f"{PREFIX}*{SUFFIX}"):
        try:
            found.append(inspect(path))
        except BackupError:
            continue
    return sorted(found, key=lambda info: (info.created, info.path.name), reverse=True)


def restore_backup(backup, database, folder, now=None, staff_database=None, restore_staff=False):
    """Replace the database with backup, all or nothing.

    The backup is verified first and copied to a temporary file that is swapped in with an
    atomic rename, so a failure leaves the current database untouched. The current database
    is saved to folder beforehand; its BackupInfo is returned (None if there was none).
    Staff accounts are replaced only with restore_staff, and only if an admin could still sign in.
    """
    backup, database = Path(backup), Path(database)
    inspect(backup)
    if database.exists() and backup.resolve() == database.resolve():
        raise BackupError("That file is the live database, not a backup")
    if restore_staff:
        if staff_database is None:
            raise BackupError("No staff accounts file was given")
        if not inspect_staff(staff_file(backup)).admins:
            raise BackupError("That backup has no active owner or admin, so nobody could sign in")
    safety = create_backup(database, folder, now, tag="-before-restore", staff_database=staff_database) if database.is_file() else None
    database.parent.mkdir(parents=True, exist_ok=True)
    staged = database.with_name(database.name + ".restoring")
    staged_staff = Path(staff_database).with_name(Path(staff_database).name + ".restoring") if restore_staff else None
    try:
        _copy(backup, staged)
        inspect(staged)
        if restore_staff:
            _copy(staff_file(backup), staged_staff)
            inspect_staff(staged_staff)
            os.replace(staged_staff, staff_database)
        os.replace(staged, database)
    except (OSError, sqlite3.DatabaseError, BackupError) as exc:
        staged.unlink(missing_ok=True)
        if staged_staff is not None:
            staged_staff.unlink(missing_ok=True)
        raise BackupError(f"Restore failed, nothing was changed: {exc}") from exc
    return safety
