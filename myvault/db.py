"""SQLite access + first-run schema application.

No ORM. Every query in the app uses parameter substitution -- never string
formatting -- per the build spec's non-negotiables.
"""

from __future__ import annotations

import os
import secrets
import sqlite3

from flask import current_app, g

SCHEMA_VERSION = 1

# Future schema bumps: {from_version: callable(sqlite3.Connection) -> None}
MIGRATIONS: dict[int, "callable"] = {}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def init_db() -> None:
    """Create the schema on a fresh DB, or run migrations on an older one."""
    path = current_app.config["DATABASE"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if not _table_exists(conn, "meta"):
            with current_app.open_resource("schema.sql") as f:
                conn.executescript(f.read().decode("utf-8"))
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
            return

        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row[0]) if row and row[0] else 0
        while current < SCHEMA_VERSION:
            migrate = MIGRATIONS.get(current)
            if migrate is None:
                break
            migrate(conn)
            current += 1
            conn.execute(
                "UPDATE meta SET value=? WHERE key='schema_version'", (str(current),)
            )
            conn.commit()
    finally:
        conn.close()


# --- meta helpers ------------------------------------------------------------

def get_meta(key: str, default: str | None = None) -> str | None:
    row = get_db().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row is not None else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_or_create_secret_key() -> str:
    """Flask session signing key; persisted so sessions survive a restart."""
    db = get_db()
    row = db.execute("SELECT value FROM meta WHERE key='session_secret'").fetchone()
    if row is not None:
        return row[0]
    value = secrets.token_hex(32)
    set_meta(db, "session_secret", value)
    db.commit()
    return value
