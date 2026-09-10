"""Category CRUD and the per-category field builder (Phase 2).

Restructuring categories/fields is admin-only. Adding/editing records (Phase 3)
is not gated here.
"""

from __future__ import annotations

import json

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import admin_required
from .db import get_db
from .fieldtypes import FIELD_TYPES, is_valid_type, needs_options
from .store import get_categories, get_category, get_field, get_fields, move_row
from .util import now_iso, slugify_key, uniquify_key

bp = Blueprint("categories", __name__, url_prefix="/categories")

MAX_NAME = 80
MAX_LABEL = 80


def _parse_options(raw: str) -> list[str]:
    """One option per line; trimmed; blanks and dupes dropped, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for line in (raw or "").replace("\r\n", "\n").split("\n"):
        v = line.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


# --- category CRUD ---------------------------------------------------------

@bp.route("/")
@admin_required
def manage():
    return render_template("categories_manage.html", categories=get_categories())


@bp.route("/new", methods=("GET", "POST"))
@admin_required
def new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        icon = request.form.get("icon", "").strip()[:8]
        if not name:
            flash("Category name is required.", "error")
        elif len(name) > MAX_NAME:
            flash(f"Category name must be {MAX_NAME} characters or fewer.", "error")
        else:
            db = get_db()
            cur = db.execute(
                "INSERT INTO categories(name, icon, sort_order, created_by, created_at) "
                "VALUES(?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories), ?, ?)",
                (name, icon, g.user["id"], now_iso()),
            )
            db.commit()
            flash("Category created. Now add its fields.", "success")
            return redirect(url_for("categories.edit", category_id=cur.lastrowid))
    return render_template("category_new.html")


@bp.route("/<int:category_id>", methods=("GET",))
@admin_required
def edit(category_id: int):
    category = get_category(category_id)
    if category is None:
        abort(404)
    return render_template(
        "category_edit.html",
        category=category,
        fields=get_fields(category_id),
        field_types=FIELD_TYPES,
    )


@bp.route("/<int:category_id>/update", methods=("POST",))
@admin_required
def update(category_id: int):
    category = get_category(category_id)
    if category is None:
        abort(404)
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "").strip()[:8]
    if not name:
        flash("Category name is required.", "error")
    elif len(name) > MAX_NAME:
        flash(f"Category name must be {MAX_NAME} characters or fewer.", "error")
    else:
        db = get_db()
        db.execute(
            "UPDATE categories SET name = ?, icon = ? WHERE id = ?",
            (name, icon, category_id),
        )
        db.commit()
        flash("Category updated.", "success")
    return redirect(url_for("categories.edit", category_id=category_id))


@bp.route("/<int:category_id>/delete", methods=("POST",))
@admin_required
def delete(category_id: int):
    category = get_category(category_id)
    if category is None:
        abort(404)
    db = get_db()
    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    db.execute("DELETE FROM records_fts WHERE category_id = ?", (category_id,))
    db.commit()
    flash(f"Deleted “{category['name']}” and all its records.", "success")
    return redirect(url_for("categories.manage"))


@bp.route("/<int:category_id>/move", methods=("POST",))
@admin_required
def move(category_id: int):
    if get_category(category_id) is None:
        abort(404)
    move_row("categories", category_id, request.form.get("dir", ""))
    return redirect(url_for("categories.manage"))


# --- field builder -------------------------------------------------------

@bp.route("/<int:category_id>/fields/add", methods=("POST",))
@admin_required
def field_add(category_id: int):
    if get_category(category_id) is None:
        abort(404)
    label = request.form.get("label", "").strip()
    ftype = request.form.get("field_type", "")
    required = 1 if request.form.get("required") else 0
    options = _parse_options(request.form.get("options", ""))

    existing = get_fields(category_id)
    error = _validate_field(label, ftype, options) or _dup_label(label, existing)
    if error:
        flash(error, "error")
        return redirect(url_for("categories.edit", category_id=category_id))

    db = get_db()
    taken = {r["field_key"] for r in existing}
    field_key = uniquify_key(slugify_key(label), taken)
    db.execute(
        "INSERT INTO fields(category_id, label, field_key, field_type, options, required, sort_order) "
        "VALUES(?, ?, ?, ?, ?, ?, "
        "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM fields WHERE category_id = ?))",
        (category_id, label, field_key, ftype,
         json.dumps(options if needs_options(ftype) else []), required, category_id),
    )
    db.commit()
    flash(f"Added field “{label}”.", "success")
    return redirect(url_for("categories.edit", category_id=category_id))


@bp.route("/<int:category_id>/fields/<int:field_id>", methods=("GET",))
@admin_required
def field_edit(category_id: int, field_id: int):
    if get_category(category_id) is None:
        abort(404)
    field = get_field(category_id, field_id)
    if field is None:
        abort(404)
    return render_template(
        "field_edit.html",
        category=get_category(category_id),
        field=field,
        options_text="\n".join(json.loads(field["options"] or "[]")),
        field_types=FIELD_TYPES,
    )


@bp.route("/<int:category_id>/fields/<int:field_id>/update", methods=("POST",))
@admin_required
def field_update(category_id: int, field_id: int):
    if get_category(category_id) is None:
        abort(404)
    field = get_field(category_id, field_id)
    if field is None:
        abort(404)

    label = request.form.get("label", "").strip()
    ftype = request.form.get("field_type", "")
    required = 1 if request.form.get("required") else 0
    options = _parse_options(request.form.get("options", ""))

    others = [f for f in get_fields(category_id) if f["id"] != field_id]
    error = _validate_field(label, ftype, options) or _dup_label(label, others)
    if error:
        flash(error, "error")
        return redirect(
            url_for("categories.field_edit", category_id=category_id, field_id=field_id)
        )

    # field_key stays immutable after creation -- records.data is keyed by it.
    db = get_db()
    db.execute(
        "UPDATE fields SET label = ?, field_type = ?, options = ?, required = ? "
        "WHERE id = ? AND category_id = ?",
        (label, ftype, json.dumps(options if needs_options(ftype) else []),
         required, field_id, category_id),
    )
    db.commit()
    flash(f"Updated field “{label}”.", "success")
    return redirect(url_for("categories.edit", category_id=category_id))


@bp.route("/<int:category_id>/fields/<int:field_id>/delete", methods=("POST",))
@admin_required
def field_delete(category_id: int, field_id: int):
    if get_category(category_id) is None:
        abort(404)
    field = get_field(category_id, field_id)
    if field is None:
        abort(404)
    db = get_db()
    db.execute(
        "DELETE FROM fields WHERE id = ? AND category_id = ?", (field_id, category_id)
    )
    db.commit()
    flash(
        f"Removed field “{field['label']}”. Existing record values for it are kept "
        "in the database but no longer shown.",
        "success",
    )
    return redirect(url_for("categories.edit", category_id=category_id))


@bp.route("/<int:category_id>/fields/<int:field_id>/move", methods=("POST",))
@admin_required
def field_move(category_id: int, field_id: int):
    if get_category(category_id) is None:
        abort(404)
    if get_field(category_id, field_id) is None:
        abort(404)
    move_row(
        "fields", field_id, request.form.get("dir", ""),
        scope_sql="AND category_id = ?", scope_args=(category_id,),
    )
    return redirect(url_for("categories.edit", category_id=category_id))


# --- validation --------------------------------------------------------

def _dup_label(label: str, existing) -> str | None:
    if any((f["label"] or "").strip().lower() == label.strip().lower() for f in existing):
        return f"This category already has a field called “{label}”."
    return None


def _validate_field(label: str, ftype: str, options: list[str]) -> str | None:
    if not label:
        return "Field label is required."
    if len(label) > MAX_LABEL:
        return f"Field label must be {MAX_LABEL} characters or fewer."
    if not is_valid_type(ftype):
        return "Choose a valid field type."
    if needs_options(ftype) and not options:
        return f"“{FIELD_TYPES[ftype]['label']}” needs at least one option."
    return None
