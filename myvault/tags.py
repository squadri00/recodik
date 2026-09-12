"""Cross-category tags: a free-form label attached to any record in any
category, so records that are related in a way the category/field structure
doesn't capture (e.g. "Q4 renewal" spanning a Domain, a Hosting plan and a
Subscription) can still be browsed together.

Independent of `link` fields on purpose -- a `link` field is a fixed,
one-category-to-another relationship an admin configures ahead of time; a tag
is whatever the person entering data wants to group things by, right now,
across any categories at all.
"""

from __future__ import annotations

import json
import sqlite3

from flask import Blueprint, abort, render_template

from .auth import login_required
from .db import get_db
from .store import record_label

bp = Blueprint("tags", __name__, url_prefix="/tags")

MAX_TAG_LEN = 40
MAX_TAGS_PER_RECORD = 20


def parse_tags_input(raw: str) -> list[str]:
    """Comma-separated free text -> a clean, deduped (case-insensitive) list."""
    seen: set[str] = set()
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()[:MAX_TAG_LEN]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
        if len(out) >= MAX_TAGS_PER_RECORD:
            break
    return out


def set_record_tags(db: sqlite3.Connection, record_id: int, names: list[str]) -> None:
    """Replace a record's tags with exactly `names`. Unreferenced tags are
    left in place (harmless, and cheap to reuse if the same name comes back)."""
    db.execute("DELETE FROM record_tags WHERE record_id = ?", (record_id,))
    for name in names:
        db.execute(
            "INSERT INTO tags(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (name,)
        )
        tag_id = db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?, ?)",
            (record_id, tag_id),
        )


def get_record_tags(record_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT t.id, t.name FROM tags t "
        "JOIN record_tags rt ON rt.tag_id = t.id "
        "WHERE rt.record_id = ? ORDER BY t.name COLLATE NOCASE",
        (record_id,),
    ).fetchall()


def tags_input_value(record_id: int) -> str:
    return ", ".join(t["name"] for t in get_record_tags(record_id))


def all_tags() -> list[sqlite3.Row]:
    """Every tag with how many (non-trashed) records currently carry it."""
    return get_db().execute(
        "SELECT t.id, t.name, COUNT(rt.record_id) AS record_count "
        "FROM tags t "
        "JOIN record_tags rt ON rt.tag_id = t.id "
        "JOIN records r ON r.id = rt.record_id AND r.deleted_at IS NULL "
        "GROUP BY t.id ORDER BY t.name COLLATE NOCASE"
    ).fetchall()


def records_with_tag(tag_id: int) -> list[dict]:
    """Every (non-trashed) record carrying this tag, across all categories,
    grouped for display the same way referencing_records()/group_references() is."""
    db = get_db()
    rows = db.execute(
        "SELECT r.id, r.category_id, r.data, "
        "c.name AS category_name, c.icon AS category_icon, c.sort_order AS category_sort "
        "FROM records r "
        "JOIN record_tags rt ON rt.record_id = r.id "
        "JOIN categories c ON c.id = r.category_id "
        "WHERE rt.tag_id = ? AND r.deleted_at IS NULL",
        (tag_id,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            data = json.loads(r["data"] or "{}")
        except ValueError:
            data = {}
        out.append({
            "id": r["id"],
            "category_id": r["category_id"],
            "category_name": r["category_name"],
            "category_icon": r["category_icon"] or "📁",
            "category_sort": r["category_sort"],
            "label": record_label(r["category_id"], data) or f"Record #{r['id']}",
        })
    out.sort(key=lambda r: (r["category_sort"], r["category_name"], r["label"].lower()))
    return out


def group_by_category(records: list[dict]) -> list[dict]:
    groups: dict[int, dict] = {}
    for r in records:
        cid = r["category_id"]
        if cid not in groups:
            groups[cid] = {"category_id": cid, "category_name": r["category_name"],
                           "category_icon": r["category_icon"], "items": []}
        groups[cid]["items"].append(r)
    return list(groups.values())


@bp.route("/")
@login_required
def browse():
    return render_template("tags_browse.html", tags=all_tags())


@bp.route("/<int:tag_id>")
@login_required
def view(tag_id: int):
    tag = get_db().execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    if tag is None:
        abort(404)
    records = records_with_tag(tag_id)
    return render_template("tag_detail.html", tag=tag, records=records,
                           groups=group_by_category(records))
