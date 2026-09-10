"""Shared read helpers for categories / fields / records."""

from __future__ import annotations

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
