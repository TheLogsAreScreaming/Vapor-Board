"""Local read-only BBS inspection via SQLite read-only URI."""
import argparse
import json
import sqlite3
from pathlib import Path


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def inspect_database(path, board_id=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("BBS database does not exist")
    if board_id is not None and (type(board_id) is not int or board_id < 1):
        raise ValueError("invalid board id")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        if board_id is None:
            # Read-only, so a database from an older version can't be upgraded here: order by what exists.
            order = "position, id" if "position" in _columns(db, "boards") else "id"
            rows = db.execute(f"SELECT id, name FROM boards ORDER BY {order}").fetchall()
            return {"boards": [dict(row) for row in rows]}
        columns = _columns(db, "posts")
        optional = ", ".join(name if name in columns else f"NULL AS {name}" for name in ("pinned_at", "publish_at", "expires_at"))
        order = "pinned_at IS NULL, pinned_at DESC, id DESC" if "pinned_at" in columns else "id DESC"
        query = f"SELECT id, board_id, author, body, created_at, {optional} FROM posts WHERE board_id = ? ORDER BY {order} LIMIT 50"
        rows = db.execute(query, (board_id,)).fetchall()
        return {"posts": [dict(row) for row in rows]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect local Vapor Board BBS data (read-only)")
    parser.add_argument("database", help="existing SQLite database path")
    parser.add_argument("--board", type=int, help="board ID for recent posts")
    args = parser.parse_args(argv)
    print(json.dumps(inspect_database(args.database, args.board), indent=2))


if __name__ == "__main__":
    main()
