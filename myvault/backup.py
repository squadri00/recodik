"""Full-database backup and restore.

The whole vault is one SQLite file, so a "full export" is just a consistent
copy of it, and "import into a new installation" is just putting that copy
where this app expects a database. This module turns both into one click
instead of a manual file-copy -- using sqlite3's own online backup API, so the
snapshot is consistent even while the app is being used, never a raw
filesystem copy of a file that might be mid-write.

Restoring is the dangerous half: it replaces the live database outright. Every
restore first takes a safety snapshot of whatever was live, then validates the
uploaded file actually looks like a MyVault database before touching anything.
"""

from __future__ import annotations

import gc
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone

from flask import current_app

from .db import SCHEMA_VERSION

REQUIRED_TABLES = {"meta", "users", "categories", "fields", "records"}


def _db_path() -> str:
    return current_app.config["DATABASE"]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def backup_filename() -> str:
    return f"myvault-backup-{_timestamp()}.sqlite3"


def make_consistent_copy(dest_path: str, source_path: str | None = None) -> None:
    """A safe copy of a (possibly live) database, via sqlite3's backup API --
    never a raw file copy, which could grab a half-written page."""
    src = sqlite3.connect(source_path or _db_path())
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def make_download_copy() -> str:
    """Write a consistent snapshot to a new temp file. Caller deletes it."""
    fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    make_consistent_copy(tmp_path)
    return tmp_path


def upload_temp_path() -> str:
    """A temp path for a just-uploaded file, on the SAME filesystem as the live
    database -- so the eventual os.replace() is a true atomic rename rather
    than a cross-volume copy+delete."""
    fd, tmp_path = tempfile.mkstemp(
        suffix=".sqlite3.upload", dir=os.path.dirname(os.path.abspath(_db_path())) or None
    )
    os.close(fd)
    return tmp_path


def backups_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(_db_path())), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def validate_backup(path: str) -> str | None:
    """None if `path` looks like a legitimate, restorable MyVault database,
    otherwise a human-readable reason it was refused."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return "That file isn't readable as a database."
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES.issubset(tables):
            return "That file doesn't look like a MyVault database."

        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row and row[0] else 0
        if version > SCHEMA_VERSION:
            return (
                f"That backup is from a newer version of MyVault (schema v{version}; "
                f"this install understands up to v{SCHEMA_VERSION}). Update MyVault "
                "before restoring it."
            )
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return "That database has no users in it -- refusing to restore an empty vault."
        return None
    except sqlite3.DatabaseError:
        return "That file isn't a valid SQLite database."
    finally:
        conn.close()


def safety_backup_current() -> str:
    """Snapshot the currently-live database before it gets overwritten."""
    path = os.path.join(backups_dir(), "pre-restore-" + backup_filename())
    make_consistent_copy(path, source_path=_db_path())
    return path


def restore(uploaded_path: str) -> str:
    """Replace the live database with an already-validated `uploaded_path`.

    Returns the path of the safety backup taken beforehand. The caller is
    responsible for calling validate_backup() first and for clearing any
    request-local DB handle / session before this runs.
    """
    safety_path = safety_backup_current()

    # On Windows, os.replace() fails outright (WinError 5/32) if anything --
    # including a not-yet-garbage-collected sqlite3.Connection from earlier in
    # this process -- still holds the destination file open. A gc pass plus a
    # short, small retry covers that without weakening the operation itself:
    # it's still a single atomic rename, just given a moment to become possible.
    gc.collect()
    last_error: OSError | None = None
    for attempt in range(5):
        try:
            os.replace(uploaded_path, _db_path())
            break
        except OSError as e:
            last_error = e
            time.sleep(0.2 * (attempt + 1))
    else:
        raise last_error

    from . import crypto

    crypto.clear_master_key()  # the in-memory key belongs to the database just replaced

    from . import db as _db

    _db.init_db()  # bring an older-schema restored file up to date, in place

    return safety_path
