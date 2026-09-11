"""Shared read helpers for categories / fields / records."""

from __future__ import annotations

import json
import sqlite3

from .db import get_db


def get_categories() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT c.*, "
        "(SELECT COUNT(*) FROM records r WHERE r.category_id = c.id) AS record_count "
        "FROM categories c ORDER BY c.sort_order, c.name"
    ).fetchall()


def get_category(category_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM categories WHERE id = ?", (category_id,)
    ).fetchone()


def get_fields(category_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM fields WHERE category_id = ? ORDER BY sort_order, id",
        (category_id,),
    ).fetchall()


def get_field(category_id: int, field_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM fields WHERE id = ? AND category_id = ?",
        (field_id, category_id),
    ).fetchone()


# --- linked-record helpers (v2) -----------------------------------------------

def link_target_id(field) -> int | None:
    """The category a `link`-type field points at, or None if unconfigured."""
    try:
        cfg = json.loads(field["options"] or "{}")
    except (ValueError, TypeError):
        return None
    tid = cfg.get("category_id") if isinstance(cfg, dict) else None
    return int(tid) if tid else None


def first_field(category_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM fields WHERE category_id = ? ORDER BY sort_order, id LIMIT 1",
        (category_id,),
    ).fetchone()


def record_label(category_id: int, data: dict) -> str | None:
    """A human label for a record: the value of its category's first field."""
    ff = first_field(category_id)
    if ff is not None:
        v = data.get(ff["field_key"])
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if v not in (None, "", []):
            return str(v)
    return None


def link_choices(target_category_id: int) -> list[dict]:
    """`{id, label}` for every record in the target category, for a <select>."""
    if not target_category_id:
        return []
    rows = get_db().execute(
        "SELECT id, data FROM records WHERE category_id = ? ORDER BY id",
        (target_category_id,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["data"] or "{}")
        except ValueError:
            d = {}
        out.append({"id": r["id"],
                    "label": record_label(target_category_id, d) or f"Record #{r['id']}"})
    return out


def resolve_link(record_id: int) -> dict | None:
    """`{id, label}` for one linked record, or None if it's gone."""
    if not record_id:
        return None
    row = get_db().execute(
        "SELECT id, category_id, data FROM records WHERE id = ?", (int(record_id),)
    ).fetchone()
    if row is None:
        return None
    try:
        d = json.loads(row["data"] or "{}")
    except ValueError:
        d = {}
    return {"id": row["id"],
            "label": record_label(row["category_id"], d) or f"Record #{row['id']}"}


def referencing_records(category_id: int, record_id: int) -> list[dict]:
    """Records in any category whose `link` field points at this record."""
    db = get_db()
    link_fields = db.execute(
        "SELECT f.*, c.name AS category_name "
        "FROM fields f JOIN categories c ON c.id = f.category_id "
        "WHERE f.field_type = 'link'"
    ).fetchall()
    out: list[dict] = []
    for lf in link_fields:
        if link_target_id(lf) != category_id:
            continue
        path = "$." + lf["field_key"]  # field_key is a slug -> safe to build
        rows = db.execute(
            "SELECT id, category_id, data FROM records "
            "WHERE category_id = ? AND json_extract(data, ?) = ?",
            (lf["category_id"], path, record_id),
        ).fetchall()
        for r in rows:
            try:
                d = json.loads(r["data"] or "{}")
            except ValueError:
                d = {}
            out.append({
                "category_name": lf["category_name"],
                "via": lf["label"],
                "id": r["id"],
                "label": record_label(r["category_id"], d) or f"Record #{r['id']}",
            })
    return out


def move_row(table: str, row_id: int, direction: str, scope_sql: str = "",
             scope_args: tuple = ()) -> None:
    """Swap sort_order with the adjacent row in the same scope.

    `table` is a trusted literal from this module -- never user input.
    """
    assert table in {"categories", "fields"}
    assert direction in {"up", "down"}
    db = get_db()
    row = db.execute(
        f"SELECT id, sort_order FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        return
    op = "<" if direction == "up" else ">"
    order = "DESC" if direction == "up" else "ASC"
    neighbor = db.execute(
        f"SELECT id, sort_order FROM {table} "
        f"WHERE sort_order {op} ? {scope_sql} ORDER BY sort_order {order}, id {order} LIMIT 1",
        (row["sort_order"], *scope_args),
    ).fetchone()
    if neighbor is None:
        return
    db.execute(
        f"UPDATE {table} SET sort_order = ? WHERE id = ?",
        (neighbor["sort_order"], row["id"]),
    )
    db.execute(
        f"UPDATE {table} SET sort_order = ? WHERE id = ?",
        (row["sort_order"], neighbor["id"]),
    )
    db.commit()
