"""Dynamic record forms, record CRUD, and encrypted-field reveal (Phase 3).

Any authenticated user can add/edit/delete records. Restructuring the category
(fields) stays admin-only in categories.py.

Encryption contract:
* ``password``-type values are encrypted with Fernet before insert/update.
* Plaintext is returned ONLY by the explicit ``/reveal`` endpoint, one field at
  a time, and only while the vault is unlocked.
* List and detail views never emit the ciphertext or the plaintext.
"""

from __future__ import annotations

import json
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from . import crypto, search
from .auth import login_required
from .db import get_db
from .fieldtypes import is_encrypted
from .store import get_category, get_fields
from .util import now_iso

bp = Blueprint("records", __name__, url_prefix="/records")

MASK = "••••••••"


def _category_or_404(category_id: int):
    cat = get_category(category_id)
    if cat is None:
        abort(404)
    return cat


def _record_or_404(record_id: int):
    row = get_db().execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _has_encrypted_field(fields) -> bool:
    return any(is_encrypted(f["field_type"]) for f in fields)


# --- form parsing / validation ------------------------------------------------

def parse_form(fields, form, existing: dict | None) -> tuple[dict, list[str]]:
    """Build the record's data dict from submitted form values.

    For encrypted fields: a non-empty value is encrypted now; an empty value
    keeps the existing ciphertext (edit) or is omitted (create).
    """
    existing = existing or {}
    data: dict = {}
    errors: list[str] = []

    for f in fields:
        key, ftype = f["field_key"], f["field_type"]

        if ftype == "checkbox":
            data[key] = bool(form.get(key))
            continue

        if ftype == "multiselect":
            chosen = [v for v in form.getlist(key) if v]
            allowed = set(json.loads(f["options"] or "[]"))
            chosen = [v for v in chosen if v in allowed]
            if f["required"] and not chosen:
                errors.append(f"“{f['label']}” is required.")
            data[key] = chosen
            continue

        raw = (form.get(key) or "").strip()

        if ftype == "password":
            if raw:
                data[key] = crypto.encrypt_value(raw)
            elif existing.get(key):
                data[key] = existing[key]  # keep current ciphertext
            elif f["required"]:
                errors.append(f"“{f['label']}” is required.")
            continue

        if not raw:
            if f["required"]:
                errors.append(f"“{f['label']}” is required.")
            data[key] = ""
            continue

        if ftype == "number":
            try:
                float(raw)
            except ValueError:
                errors.append(f"“{f['label']}” must be a number.")
            data[key] = raw
        elif ftype == "date":
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                errors.append(f"“{f['label']}” must be a date (YYYY-MM-DD).")
            data[key] = raw
        elif ftype == "dropdown":
            allowed = set(json.loads(f["options"] or "[]"))
            if raw not in allowed:
                errors.append(f"“{f['label']}” has an invalid choice.")
            data[key] = raw
        else:
            data[key] = raw

    return data, errors


# --- display helpers --------------------------------------------------------

def display_cell(field, data: dict) -> dict:
    """A view-model for one field value. Never includes ciphertext/plaintext."""
    key, ftype = field["field_key"], field["field_type"]
    value = data.get(key)
    cell = {"type": ftype, "label": field["label"], "key": key,
            "encrypted": is_encrypted(ftype), "has_value": False, "raw": None,
            "items": None, "checked": False}
    if is_encrypted(ftype):
        cell["has_value"] = bool(value)
        return cell
    if ftype == "checkbox":
        cell["checked"] = bool(value)
        cell["has_value"] = True
        return cell
    if ftype == "multiselect":
        cell["items"] = value or []
        cell["has_value"] = bool(cell["items"])
        return cell
    if value not in (None, ""):
        cell["raw"] = value
        cell["has_value"] = True
    return cell


def form_values(fields, source, is_form: bool) -> dict:
    """Normalized prefill dict for record_form.html.

    ``source`` is either a decoded data dict (GET edit) or ``request.form``
    (re-render after a validation error). Encrypted fields are always blank.
    """
    out: dict = {}
    for f in fields:
        key, ftype = f["field_key"], f["field_type"]
        if is_encrypted(ftype):
            out[key] = ""
        elif ftype == "checkbox":
            out[key] = bool(source.get(key))
        elif ftype == "multiselect":
            out[key] = source.getlist(key) if is_form else list(source.get(key) or [])
        else:
            v = source.get(key)
            out[key] = "" if v is None else str(v)
    return out


def record_view(record, fields) -> dict:
    data = json.loads(record["data"] or "{}")
    return {
        "id": record["id"],
        "category_id": record["category_id"],
        "updated_at": record["updated_at"],
        "cells": [display_cell(f, data) for f in fields],
    }


# --- routes ---------------------------------------------------------------

@bp.route("/category/<int:category_id>")
@login_required
def list_records(category_id: int):
    category = _category_or_404(category_id)
    fields = get_fields(category_id)
    rows = get_db().execute(
        "SELECT * FROM records WHERE category_id = ? ORDER BY updated_at DESC, id DESC",
        (category_id,),
    ).fetchall()
    records = [record_view(r, fields) for r in rows]
    return render_template("records_list.html", category=category, fields=fields,
                           records=records)


@bp.route("/category/<int:category_id>/new", methods=("GET", "POST"))
@login_required
def create(category_id: int):
    category = _category_or_404(category_id)
    fields = get_fields(category_id)
    if not fields:
        flash("Add at least one field to this category first.", "warn")
        return redirect(url_for("categories.edit", category_id=category_id))
    if _has_encrypted_field(fields) and not crypto.is_unlocked():
        return redirect(url_for("auth.unlock", next=request.path))

    if request.method == "POST":
        data, errors = parse_form(fields, request.form, None)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("record_form.html", category=category,
                                   fields=fields,
                                   values=form_values(fields, request.form, True),
                                   mode="new")
        db = get_db()
        cur = db.execute(
            "INSERT INTO records(category_id, data, created_by, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (category_id, json.dumps(data), g.user["id"], now_iso(), now_iso()),
        )
        search.reindex_record(db, cur.lastrowid)
        db.commit()
        flash("Record added.", "success")
        return redirect(url_for("records.list_records", category_id=category_id))

    return render_template("record_form.html", category=category, fields=fields,
                           values=form_values(fields, {}, False), mode="new")


@bp.route("/<int:record_id>")
@login_required
def view(record_id: int):
    record = _record_or_404(record_id)
    category = _category_or_404(record["category_id"])
    fields = get_fields(category["id"])
    return render_template("record_detail.html", category=category,
                           record=record_view(record, fields))


@bp.route("/<int:record_id>/edit", methods=("GET", "POST"))
@login_required
def edit(record_id: int):
    record = _record_or_404(record_id)
    category = _category_or_404(record["category_id"])
    fields = get_fields(category["id"])
    existing = json.loads(record["data"] or "{}")
    if _has_encrypted_field(fields) and not crypto.is_unlocked():
        return redirect(url_for("auth.unlock", next=request.path))

    if request.method == "POST":
        data, errors = parse_form(fields, request.form, existing)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("record_form.html", category=category,
                                   fields=fields,
                                   values=form_values(fields, request.form, True),
                                   mode="edit", record_id=record_id,
                                   existing=existing)
        db = get_db()
        db.execute(
            "UPDATE records SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data), now_iso(), record_id),
        )
        search.reindex_record(db, record_id)
        db.commit()
        flash("Record saved.", "success")
        return redirect(url_for("records.view", record_id=record_id))

    # Pre-fill: encrypted fields are shown blank (never decrypted into HTML).
    return render_template("record_form.html", category=category, fields=fields,
                           values=form_values(fields, existing, False), mode="edit",
                           record_id=record_id, existing=existing)


@bp.route("/<int:record_id>/delete", methods=("POST",))
@login_required
def delete(record_id: int):
    record = _record_or_404(record_id)
    db = get_db()
    db.execute("DELETE FROM records WHERE id = ?", (record_id,))
    search.remove_record(db, record_id)
    db.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("records.list_records", category_id=record["category_id"]))


@bp.route("/<int:record_id>/reveal", methods=("POST",))
@login_required
def reveal(record_id: int):
    """Decrypt ONE encrypted field of a record. JSON in, JSON out.

    Uses login_required (not unlock_required) so a locked vault returns a JSON
    409 the client can show inline, rather than an HTML redirect.
    """
    record = _record_or_404(record_id)
    field_key = (request.form.get("field_key") or "").strip()
    fields = {f["field_key"]: f for f in get_fields(record["category_id"])}
    field = fields.get(field_key)
    if field is None or not is_encrypted(field["field_type"]):
        abort(404)
    if not crypto.is_unlocked():
        return jsonify({"error": "Vault is locked. Unlock it to reveal values."}), 409
    data = json.loads(record["data"] or "{}")
    token = data.get(field_key)
    if not token:
        return jsonify({"value": ""})
    try:
        return jsonify({"value": crypto.decrypt_value(token)})
    except crypto.VaultLocked:
        return jsonify({"error": "Vault is locked."}), 409
    except Exception:
        return jsonify({"error": "Could not decrypt this value."}), 500
