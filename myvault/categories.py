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

from . import alerts, audit, costs, crypto, search
from .auth import admin_required
from .db import get_db
from .fieldtypes import (
    COST_FREQUENCIES,
    DEFAULT_ALERT_DAYS,
    DEFAULT_FREQUENCY,
    FIELD_TYPES,
    is_valid_type,
    needs_alert_config,
    needs_frequency,
    needs_options,
    needs_target,
)
from .store import (
    get_categories,
    get_category,
    get_field,
    get_fields,
    link_target_id,
    move_row,
)
from .util import now_iso, slugify_key, uniquify_key

bp = Blueprint("categories", __name__, url_prefix="/categories")

# Field types whose stored value is a plain string, and so can be encrypted in
# place when an admin switches the type to `password` -- e.g. fixing a field
# that was built before its data turned out to be sensitive.
_ENCRYPTABLE_FROM = {"text", "textarea", "url", "email", "number", "cost", "date", "date_alert",
                    "code", "dropdown"}

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


def _options_json(ftype: str, options: list[str], target_id: int | None,
                  alert_days: int | None = None, frequency: str | None = None) -> str:
    """The value for fields.options given the field type."""
    if needs_target(ftype):
        return json.dumps({"category_id": int(target_id)}) if target_id else "{}"
    if needs_alert_config(ftype):
        days = alert_days if alert_days is not None else DEFAULT_ALERT_DAYS
        return json.dumps({"alert_days_before": days})
    if needs_frequency(ftype):
        return json.dumps({"frequency": frequency or DEFAULT_FREQUENCY})
    if needs_options(ftype):
        return json.dumps(options)
    return "[]"


def _target_from_form() -> int | None:
    raw = (request.form.get("target_category_id") or "").strip()
    if not raw.isdigit():
        return None
    return int(raw) if get_category(int(raw)) is not None else None


def _alert_days_from_form() -> tuple[int | None, str | None]:
    """(days, error). Blank -> default; a present-but-invalid value errors."""
    raw = (request.form.get("alert_days_before") or "").strip()
    if not raw:
        return DEFAULT_ALERT_DAYS, None
    if not raw.isdigit():
        return None, "“Remind me N days before” must be a whole number."
    return int(raw), None


def _frequency_from_form() -> tuple[str | None, str | None]:
    """(frequency, error). Blank -> default; a present-but-invalid value errors."""
    raw = (request.form.get("frequency") or "").strip()
    if not raw:
        return DEFAULT_FREQUENCY, None
    if raw not in COST_FREQUENCIES:
        return None, "Choose a valid billing frequency."
    return raw, None


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
            audit.log("category_create", category_id=cur.lastrowid, category_name=name)
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
    fields = get_fields(category_id)
    return render_template(
        "category_edit.html",
        category=category,
        fields=fields,
        field_types=FIELD_TYPES,
        all_categories=get_categories(),
        link_targets={f["id"]: link_target_id(f) for f in fields
                      if f["field_type"] == "link"},
        alert_days={f["id"]: alerts.alert_window(f) for f in fields
                    if f["field_type"] == "date_alert"},
        field_frequency={f["id"]: costs.cost_frequency(f) for f in fields
                         if f["field_type"] == "cost"},
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

    # Block deletion while other categories link to this one.
    blockers = []
    for lf in db.execute(
        "SELECT f.label, f.options, c.name AS cat FROM fields f "
        "JOIN categories c ON c.id = f.category_id "
        "WHERE f.field_type = 'link' AND f.category_id != ?", (category_id,)
    ).fetchall():
        if link_target_id(lf) == category_id:
            blockers.append(f"“{lf['label']}” in {lf['cat']}")
    if blockers:
        flash(
            "Can't delete this category — these linked-record fields point at it: "
            + "; ".join(blockers) + ". Remove or retarget them first.",
            "error",
        )
        return redirect(url_for("categories.edit", category_id=category_id))

    record_count = db.execute(
        "SELECT COUNT(*) FROM records WHERE category_id = ?", (category_id,)
    ).fetchone()[0]

    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    db.execute("DELETE FROM records_fts WHERE category_id = ?", (category_id,))
    audit.log("category_delete", category_id=category_id, category_name=category["name"],
              detail=f"{record_count} record(s) permanently deleted with it")
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
    target_id = _target_from_form()
    alert_days, alert_error = _alert_days_from_form()
    frequency, frequency_error = _frequency_from_form()

    existing = get_fields(category_id)
    error = (_validate_field(label, ftype, options, target_id)
             or alert_error or frequency_error or _dup_label(label, existing))
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
         _options_json(ftype, options, target_id, alert_days, frequency), required, category_id),
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
    try:
        opts = json.loads(field["options"] or "[]")
    except ValueError:
        opts = []
    return render_template(
        "field_edit.html",
        category=get_category(category_id),
        field=field,
        options_text="\n".join(opts) if isinstance(opts, list) else "",
        field_types=FIELD_TYPES,
        all_categories=get_categories(),
        current_target=link_target_id(field),
        current_alert_days=(alerts.alert_window(field)
                           if field["field_type"] == "date_alert" else DEFAULT_ALERT_DAYS),
        current_frequency=(costs.cost_frequency(field)
                           if field["field_type"] == "cost" else DEFAULT_FREQUENCY),
        can_encrypt=field["field_type"] in _ENCRYPTABLE_FROM,
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
    target_id = _target_from_form()
    alert_days, alert_error = _alert_days_from_form()
    frequency, frequency_error = _frequency_from_form()

    others = [f for f in get_fields(category_id) if f["id"] != field_id]
    error = (_validate_field(label, ftype, options, target_id)
             or alert_error or frequency_error or _dup_label(label, others))
    if error:
        flash(error, "error")
        return redirect(
            url_for("categories.field_edit", category_id=category_id, field_id=field_id)
        )

    newly_encrypted = (
        ftype == "password"
        and field["field_type"] != "password"
        and field["field_type"] in _ENCRYPTABLE_FROM
        and request.form.get("encrypt_existing")
    )
    if newly_encrypted and not crypto.is_unlocked():
        flash("Unlock the vault first — encrypting existing values needs the master key.",
              "error")
        return redirect(url_for(
            "auth.unlock",
            next=url_for("categories.field_edit", category_id=category_id, field_id=field_id),
        ))

    # field_key stays immutable after creation -- records.data is keyed by it.
    db = get_db()
    db.execute(
        "UPDATE fields SET label = ?, field_type = ?, options = ?, required = ? "
        "WHERE id = ? AND category_id = ?",
        (label, ftype, _options_json(ftype, options, target_id, alert_days, frequency),
         required, field_id, category_id),
    )

    reencrypted = 0
    if newly_encrypted:
        field_key = field["field_key"]
        for rec in db.execute(
            "SELECT id, data FROM records WHERE category_id = ?", (category_id,)
        ).fetchall():
            data = json.loads(rec["data"] or "{}")
            value = data.get(field_key)
            if not isinstance(value, str) or not value:
                continue
            try:
                crypto.decrypt_value(value)
                continue  # already a valid token for this key -- leave it (idempotent)
            except Exception:
                pass
            data[field_key] = crypto.encrypt_value(value)
            db.execute("UPDATE records SET data = ? WHERE id = ?",
                       (json.dumps(data), rec["id"]))
            search.reindex_record(db, rec["id"])  # drop the old plaintext from the index
            reencrypted += 1

    db.commit()
    msg = f"Updated field “{label}”."
    if newly_encrypted:
        msg += f" {reencrypted} existing value(s) encrypted." if reencrypted else \
               " No existing values needed encrypting."
    flash(msg, "success")
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


def _validate_field(label: str, ftype: str, options: list[str],
                    target_id: int | None = None) -> str | None:
    if not label:
        return "Field label is required."
    if len(label) > MAX_LABEL:
        return f"Field label must be {MAX_LABEL} characters or fewer."
    if not is_valid_type(ftype):
        return "Choose a valid field type."
    if needs_options(ftype) and not options:
        return f"“{FIELD_TYPES[ftype]['label']}” needs at least one option."
    if needs_target(ftype) and not target_id:
        return f"“{FIELD_TYPES[ftype]['label']}” needs a target category."
    return None
