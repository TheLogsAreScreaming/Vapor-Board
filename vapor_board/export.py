"""Spreadsheet (CSV) export of boards, messages, customers and the activity log.

An export is for reading, archiving or handing to an accountant, not for restoring:
use backups for that. Files are written to a new folder; nothing is uploaded.
Cells that a spreadsheet would treat as a formula are prefixed with an apostrophe.
"""
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def _rows(path, query, columns):
    if not Path(path).is_file():
        return []
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        needed = query.split(" FROM ")[1].split()[0]
        if needed not in tables:
            return []
        present = {row[1] for row in db.execute(f"PRAGMA table_info({needed})")}
        return list(db.execute(query.format(**{c: (c if c in present else f"NULL AS {c}") for c in columns})))


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:  # BOM so Excel reads UTF-8
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([safe_cell(value) for value in row])
    return len(rows)


def export_csv(database, staff_database, folder, now=None):
    """Write posts.csv, messages.csv, customers.csv and activity.csv into a new dated folder.

    Returns (folder path, {file name: row count}). Times are UTC, as stored.
    """
    target = Path(folder) / f"vapor-board-export-{(now or datetime.now()):%Y%m%d-%H%M%S}"
    target.mkdir(parents=True, exist_ok=False)
    counts = {
        "posts.csv": _write(target / "posts.csv",
                            ["board", "post id", "author", "posted (UTC)", "pinned (UTC)", "shows from (UTC)", "until (UTC)", "text"],
                            _rows(database, "SELECT b.name, p.id, p.author, p.created_at, p.{pinned_at}, p.{publish_at}, p.{expires_at}, p.body "
                                  "FROM posts p JOIN boards b ON b.id = p.board_id ORDER BY b.id, p.id",
                                  ("pinned_at", "publish_at", "expires_at"))),
        "messages.csv": _write(target / "messages.csv", ["message id", "from", "to", "sent (UTC)", "read (UTC)", "text"],
                               _rows(database, "SELECT id, sender, recipient, created_at, {read_at}, body FROM mail ORDER BY id", ("read_at",))),
        "customers.csv": _write(target / "customers.csv",
                                ["name", "phone or email", "radio node", "status", "ID checked by", "ID checked (UTC)", "added (UTC)"],
                                _rows(database, "SELECT name, contact, node_id, status, verified_by, verified_at, created_at FROM customers ORDER BY id", ())),
        "activity.csv": _write(target / "activity.csv", ["when (UTC)", "staff", "action", "detail"],
                               _rows(staff_database, "SELECT at, actor, action, detail FROM activity ORDER BY id", ())),
    }
    return target, counts
