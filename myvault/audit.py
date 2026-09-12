"""Append-only audit trail for record and category lifecycle events.

No FKs to categories/records -- an entry must outlive the thing it describes
being deleted, which is the entire point of an audit trail. Category/record
identity is denormalized (id + name/label as plain columns) instead of a live
join, so a deleted category's own audit history stays readable.

Callers pass an already-open db connection's transaction along: `log()` does
NOT commit -- it's meant to be the last `db.execute()` in the same route that
commits its own change, so the audit row and the change it describes land in
one transaction together.
"""

from __future__ import annotations

from flask import g

from .db import get_db
from .util import now_iso

ACTION_LABELS = {
    "record_create": "Created",
    "record_update": "Updated",
    "record_trash": "Moved to trash",
    "record_restore": "Restored from trash",
    "record_purge": "Permanently deleted",
    "record_clone": "Cloned",
    "category_create": "Category created",
    "category_delete": "Category deleted",
}


def log(action: str, *, category_id: int | None = None, category_name: str | None = None,
        record_id: int | None = None, record_label: str | None = None,
        detail: str | None = None) -> None:
    user = g.get("user")
    get_db().execute(
        "INSERT INTO audit_log(ts, user_id, username, action, category_id, "
        "category_name, record_id, record_label, detail) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), user["id"] if user else None, user["username"] if user else "system",
         action, category_id, category_name, record_id, record_label, detail),
    )


def recent(limit: int = 300) -> list:
    return get_db().execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
