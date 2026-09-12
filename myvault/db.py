"""SQLite access + first-run schema application.

No ORM. Every query in the app uses parameter substitution -- never string
formatting -- per the build spec's non-negotiables.
"""

from __future__ import annotations

import os
import secrets
import sqlite3

from flask import current_app, g

SCHEMA_VERSION = 4


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    """v3: encrypted file/image attachments (a new `files` table)."""
    conn.executescript(
        """
        CREATE TABLE files (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id    INTEGER NOT NULL,
          field_key    TEXT NOT NULL,
          filename     TEXT NOT NULL,
          content_type TEXT NOT NULL,
          size_bytes   INTEGER NOT NULL,
          data         BLOB NOT NULL,   -- Fernet-encrypted file bytes
          uploaded_by  INTEGER,
          uploaded_at  TEXT NOT NULL,
          FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
          FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX idx_files_record ON files(record_id, field_key);
        """
    )


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    """v4: expiry/reminder alerts (`date_alert` fields) -- dismissal state."""
    conn.executescript(
        """
        CREATE TABLE alert_dismissals (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id       INTEGER NOT NULL,
          field_key       TEXT NOT NULL,
          dismissed_value TEXT NOT NULL,   -- the date (YYYY-MM-DD) current when dismissed
          dismissed_tier  TEXT NOT NULL,   -- 'upcoming' | 'overdue' -- severity at dismiss time
          dismissed_by    INTEGER,
          dismissed_at    TEXT NOT NULL,
          FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
          FOREIGN KEY (dismissed_by) REFERENCES users(id) ON DELETE SET NULL,
          UNIQUE (record_id, field_key)
        );
        """
    )


def _migrate_3_to_4(conn: sqlite3.Connection) -> None:
    """v7: soft-delete (trash) for records, plus an append-only audit log.

    `audit_log` deliberately has no foreign keys to categories/records -- an
    entry must survive the thing it describes being deleted (that's the whole
    point of an audit trail), so category/record identity is denormalized as
    plain id + name/label columns instead of relying on a live join.
    """
    conn.executescript(
        """
        ALTER TABLE records ADD COLUMN deleted_at TEXT;
        CREATE INDEX idx_records_deleted ON records(deleted_at);

        CREATE TABLE audit_log (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          ts            TEXT NOT NULL,
          user_id       INTEGER,
          username      TEXT NOT NULL,
          action        TEXT NOT NULL,
          category_id   INTEGER,
          category_name TEXT,
          record_id     INTEGER,
          record_label  TEXT,
          detail        TEXT,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX idx_audit_ts ON audit_log(id DESC);
        """
    )


# {from_version: callable(sqlite3.Connection) -> None} -- applied in order,
# each bumping meta.schema_version by one, until SCHEMA_VERSION is reached.
MIGRATIONS: dict[int, "callable"] = {
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
    3: _migrate_3_to_4,
}


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
