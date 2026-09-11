"""FTS5-backed global search + index maintenance.

Index-sync helpers are used from record CRUD (Phase 3 onward). The search UI and
the full reindex command land in Phase 4. Encrypted (password) field values are
never written to the index.
"""

from __future__ import annotations

import json
import sqlite3

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import admin_required, login_required
from .db import get_db
from .fieldtypes import is_encrypted
from .store import record_label

bp = Blueprint("search", __name__)


def record_search_text(fields, data: dict) -> str:
    parts: list[str] = []
    for f in fields:
        if is_encrypted(f["field_type"]):
            continue
        value = data.get(f["field_key"])
        if value is None or value == "":
            continue
        if isinstance(value, list):
            parts.append(" ".join(str(v) for v in value))
        elif isinstance(value, bool):
            if value:
                parts.append(f["label"])
        else:
            parts.append(str(value))
    return "  ".join(p for p in parts if p)


def _resolve_links(db: sqlite3.Connection, fields, data: dict) -> dict:
    """Replace `link` field ids with the linked record's label, so a search for
    the parent's name finds this record. Unresolvable links become empty."""
    aug = dict(data)
    for f in fields:
        if f["field_type"] != "link":
            continue
        key = f["field_key"]
        rid = data.get(key)
        aug[key] = ""
        if not rid:
            continue
        tgt = db.execute(
            "SELECT category_id, data FROM records WHERE id = ?", (int(rid),)
        ).fetchone()
        if tgt is not None:
            aug[key] = record_label(tgt["category_id"],
                                    json.loads(tgt["data"] or "{}")) or ""
    return aug


def reindex_record(db: sqlite3.Connection, record_id: int) -> None:
    db.execute("DELETE FROM records_fts WHERE record_id = ?", (record_id,))
    row = db.execute(
        "SELECT r.id, r.category_id, r.data, c.name AS category_name "
        "FROM records r JOIN categories c ON c.id = r.category_id WHERE r.id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        return
    fields = db.execute(
        "SELECT * FROM fields WHERE category_id = ?", (row["category_id"],)
    ).fetchall()
    data = _resolve_links(db, fields, json.loads(row["data"] or "{}"))
    text = record_search_text(fields, data)
    db.execute(
        "INSERT INTO records_fts(record_id, category_id, category_name, content) "
        "VALUES(?, ?, ?, ?)",
        (row["id"], row["category_id"], row["category_name"], text),
    )


def remove_record(db: sqlite3.Connection, record_id: int) -> None:
    db.execute("DELETE FROM records_fts WHERE record_id = ?", (record_id,))


def reindex_all(db: sqlite3.Connection) -> int:
    db.execute("DELETE FROM records_fts")
    ids = [r["id"] for r in db.execute("SELECT id FROM records").fetchall()]
    for rid in ids:
        reindex_record(db, rid)
    return len(ids)


def _highlight(snip: str):
    """Escape the snippet, then turn the STX/ETX match markers into <mark>.

    Everything except our own <mark> tags is escaped, so record content can't
    inject HTML into the results page.
    """
    from markupsafe import Markup, escape

    return Markup(str(escape(snip)).replace("\x02", "<mark>").replace("\x03", "</mark>"))


def _fts_query(raw: str) -> str:
    """Turn a plain user string into a safe FTS5 MATCH expression (prefix-AND)."""
    tokens = [t for t in "".join(
        ch if ch.isalnum() or ch.isspace() else " " for ch in raw
    ).split() if t]
    return " AND ".join(f'{t}*' for t in tokens)


@bp.route("/search")
@login_required
def search_page():
    query = (request.args.get("q") or "").strip()
    results = None
    if query:
        match = _fts_query(query)
        results = []
        if match:
            db = get_db()
            rows = db.execute(
                "SELECT record_id, category_id, category_name, "
                "snippet(records_fts, 3, char(2), char(3), ' … ', 12) AS snip "
                "FROM records_fts WHERE records_fts MATCH ? ORDER BY rank LIMIT 100",
                (match,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["snip_html"] = _highlight(d.pop("snip") or "")
                results.append(d)
    return render_template("search.html", query=query, results=results,
                           coming_soon=False)


@bp.route("/search/reindex", methods=("POST",))
@admin_required
def reindex():
    """Rebuild the whole FTS index. Handy after template imports or field edits."""
    db = get_db()
    count = reindex_all(db)
    db.commit()
    flash(f"Search index rebuilt from {count} record(s).", "success")
    return redirect(request.referrer or url_for("categories.manage"))
