"""Dynamic record forms, record CRUD, and encrypted-field reveal (Phase 3).

Any authenticated user can add/edit/delete records. Restructuring the category
(fields) stays admin-only in categories.py.

Encryption contract:
* ``password``-type values are encrypted with Fernet before insert/update.
* ``file``-type values are stored as an id into the `files` table, whose bytes
  are Fernet-encrypted (v3); metadata (filename/size/type) stays plain.
* Plaintext / file bytes are returned ONLY by the explicit ``/reveal`` and
  ``/files/<id>/download`` endpoints, and only while the vault is unlocked.
* List and detail views never emit the ciphertext or the plaintext.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from . import alerts, audit, crypto, search
from .auth import login_required
from .db import get_db
from .fieldtypes import is_date_like, is_encrypted
from .store import (
    get_category,
    get_fields,
    link_choices,
    link_target_id,
    record_label,
    referencing_records,
    resolve_link,
)
from .util import now_iso, safe_next

bp = Blueprint("records", __name__, url_prefix="/records")

MASK = "••••••••"

# Per-file cap for the `file` field type. Everything lives as a BLOB in the
# single myvault.sqlite3 file, so this is deliberately conservative -- it's
# built for documents, scans and photos, not a media library.
MAX_FILE_SIZE = int(os.environ.get("MYVAULT_MAX_FILE_MB", "15")) * 1024 * 1024

# Rendered as an inline <img> thumbnail. Anything else (including SVG, which
# can carry a <script>) is served as a download instead of inline HTML.
INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _category_or_404(category_id: int):
    cat = get_category(category_id)
    if cat is None:
        abort(404)
    return cat


def _record_or_404(record_id: int, include_deleted: bool = False):
    row = get_db().execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None:
        abort(404)
    if not include_deleted and row["deleted_at"] is not None:
        abort(404)
    return row


def _has_encrypted_field(fields) -> bool:
    return any(is_encrypted(f["field_type"]) for f in fields)


# --- form parsing / validation ------------------------------------------------

def parse_form(fields, form, files, existing: dict | None) -> tuple[dict, list[str], dict]:
    """Build the record's data dict from submitted form + file values.

    For encrypted fields: a non-empty value is encrypted now; an empty value
    keeps the existing ciphertext (edit) or is omitted (create).

    Returns (data, errors, pending_files). `pending_files` maps field_key ->
    (raw_bytes, filename, content_type) for newly uploaded files -- the caller
    inserts these into the `files` table once it knows the record's id, then
    patches data[key] with the resulting file id (see _save_pending_files).
    """
    existing = existing or {}
    data: dict = {}
    errors: list[str] = []
    pending: dict = {}

    for f in fields:
        key, ftype = f["field_key"], f["field_type"]

        if ftype == "checkbox":
            data[key] = bool(form.get(key))
            continue

        if ftype == "file":
            upload = files.get(key)
            remove = bool(form.get(key + "__remove"))
            if upload is not None and upload.filename:
                blob = upload.read()
                if len(blob) > MAX_FILE_SIZE:
                    errors.append(
                        f"“{f['label']}” is larger than {MAX_FILE_SIZE // (1024 * 1024)} MB."
                    )
                elif not blob:
                    errors.append(f"“{f['label']}”: that file is empty.")
                else:
                    pending[key] = (
                        blob,
                        secure_filename(upload.filename) or "file",
                        upload.mimetype or "application/octet-stream",
                    )
            elif remove:
                data[key] = ""
            elif existing.get(key):
                data[key] = existing[key]  # keep the current file
            elif f["required"]:
                errors.append(f"“{f['label']}” is required.")
            else:
                data[key] = ""
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

        if ftype == "link":
            target = link_target_id(f)
            ok = get_db().execute(
                "SELECT 1 FROM records WHERE id = ? AND category_id = ?",
                (raw, target),
            ).fetchone() if (raw.isdigit() and target) else None
            if ok is None:
                errors.append(f"“{f['label']}” must be an existing record.")
                data[key] = ""
            else:
                data[key] = int(raw)
        elif ftype == "number":
            try:
                float(raw)
            except ValueError:
                errors.append(f"“{f['label']}” must be a number.")
            data[key] = raw
        elif is_date_like(ftype):
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

    return data, errors, pending


def _save_pending_files(db, record_id: int, data: dict, pending: dict) -> None:
    """Insert newly uploaded files and patch data[key] with each new file id."""
    for key, (blob, filename, content_type) in pending.items():
        token = crypto.encrypt_bytes(blob)
        cur = db.execute(
            "INSERT INTO files(record_id, field_key, filename, content_type, "
            "size_bytes, data, uploaded_by, uploaded_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (record_id, key, filename, content_type, len(blob), token,
             g.user["id"], now_iso()),
        )
        data[key] = cur.lastrowid


def _drop_superseded_files(db, existing: dict, data: dict, fields) -> None:
    """Delete the old `files` row for any file field that was replaced or removed."""
    for f in fields:
        if f["field_type"] != "file":
            continue
        old = existing.get(f["field_key"])
        new = data.get(f["field_key"])
        if isinstance(old, int) and old != new:
            db.execute("DELETE FROM files WHERE id = ?", (old,))


# --- display helpers --------------------------------------------------------

def display_cell(field, data: dict) -> dict:
    """A view-model for one field value. Never includes ciphertext/plaintext."""
    key, ftype = field["field_key"], field["field_type"]
    value = data.get(key)
    cell = {"type": ftype, "label": field["label"], "key": key,
            "encrypted": is_encrypted(ftype), "has_value": False, "raw": None,
            "items": None, "checked": False, "link": None, "file": None}
    if ftype == "file":
        file_row = get_db().execute(
            "SELECT id, filename, content_type, size_bytes FROM files WHERE id = ?",
            (int(value),),
        ).fetchone() if value else None
        cell["file"] = dict(file_row) if file_row else None
        if cell["file"] is not None:
            cell["file"]["inline"] = cell["file"]["content_type"] in INLINE_IMAGE_TYPES
        cell["has_value"] = cell["file"] is not None
        return cell
    if ftype == "password":
        cell["has_value"] = bool(value)
        return cell
    if ftype == "link":
        cell["link"] = resolve_link(value) if value else None
        cell["has_value"] = cell["link"] is not None
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


def link_options_for(fields) -> dict:
    """field_key -> [{id, label}] choices for every `link` field in the form."""
    return {
        f["field_key"]: link_choices(link_target_id(f))
        for f in fields if f["field_type"] == "link"
    }


def file_meta_for(fields, data: dict) -> dict:
    """field_key -> {id, filename, content_type, size_bytes, inline} for the
    form's `file` fields, so the edit page can show what's currently attached."""
    return {
        f["field_key"]: display_cell(f, data)["file"]
        for f in fields if f["field_type"] == "file"
    }


# --- list-view sort & filter -------------------------------------------------
# `multiselect` (a record can match/hold several values at once), `password`
# and `file` (hidden content, nothing meaningful to compare) are deliberately
# left out of both -- there's no well-defined single order or match for them.
_SORT_FILTER_KIND = {
    "text": "text", "textarea": "text", "url": "text", "email": "text",
    "code": "text", "date": "text", "date_alert": "text", "number": "number",
    "dropdown": "select", "checkbox": "select", "link": "select",
}


def _sf_kind(field_type: str) -> str | None:
    return _SORT_FILTER_KIND.get(field_type)


def _sort_key(cell: dict, kind: str):
    if kind == "number":
        try:
            return (0, float(cell.get("raw") or 0))
        except (TypeError, ValueError):
            return (1, 0.0)  # unparsable numbers sort after real ones, not crash
    if kind == "select":
        if cell["type"] == "checkbox":
            return (0, 1 if cell.get("checked") else 0)
        if cell["type"] == "link":
            label = (cell.get("link") or {}).get("label") or ""
            return (0 if cell.get("link") else 1, label.lower())
        return (0 if cell.get("has_value") else 1, (cell.get("raw") or "").lower())
    return (0 if cell.get("has_value") else 1, (cell.get("raw") or "").lower())


def _matches_filter(cell: dict, kind: str, value: str) -> bool:
    if kind == "text":
        return value.lower() in (cell.get("raw") or "").lower()
    if kind == "number":
        return value.lower() in (cell.get("raw") or "").lower()
    if kind == "select":
        if cell["type"] == "checkbox":
            return bool(cell.get("checked")) == (value == "1")
        if cell["type"] == "link":
            link = cell.get("link")
            return str(link["id"]) == value if link else False
        return cell.get("raw") == value
    return True


def group_references(refs: list[dict]) -> list[dict]:
    """referencing_records()'s flat, pre-sorted list -> one group per category,
    in the order categories first appear (already category_sort order)."""
    groups: dict[int, dict] = {}
    for r in refs:
        cid = r["category_id"]
        if cid not in groups:
            groups[cid] = {"category_id": cid, "category_name": r["category_name"],
                           "category_icon": r["category_icon"], "items": []}
        groups[cid]["items"].append(r)
    return list(groups.values())


def filter_options_for(fields) -> dict:
    """field_key -> choices for a filter <select>, for dropdown/link fields."""
    out: dict = {}
    for f in fields:
        if f["field_type"] == "dropdown":
            out[f["field_key"]] = [(o, o) for o in json.loads(f["options"] or "[]")]
        elif f["field_type"] == "link":
            out[f["field_key"]] = [
                (str(c["id"]), c["label"]) for c in link_choices(link_target_id(f))
            ]
    return out


# --- routes ---------------------------------------------------------------

@bp.route("/category/<int:category_id>")
@login_required
def list_records(category_id: int):
    category = _category_or_404(category_id)
    fields = get_fields(category_id)
    rows = get_db().execute(
        "SELECT * FROM records WHERE category_id = ? AND deleted_at IS NULL "
        "ORDER BY updated_at DESC, id DESC",
        (category_id,),
    ).fetchall()
    records = [record_view(r, fields) for r in rows]
    total_count = len(records)

    # --- filters: ?f_<field_key>=value, one per sortable/filterable field ---
    active_filters = {
        f["field_key"]: request.args.get(f"f_{f['field_key']}", "").strip()
        for f in fields if _sf_kind(f["field_type"])
    }
    active_filters = {k: v for k, v in active_filters.items() if v}
    if active_filters:
        by_key = {f["field_key"]: (i, _sf_kind(f["field_type"]))
                  for i, f in enumerate(fields)}
        records = [
            r for r in records
            if all(_matches_filter(r["cells"][by_key[k][0]], by_key[k][1], v)
                  for k, v in active_filters.items())
        ]

    # --- sort: ?sort=<field_key>&dir=asc|desc ---
    sort_key = request.args.get("sort", "")
    sort_dir = "desc" if request.args.get("dir") == "desc" else "asc"
    sort_idx = next((i for i, f in enumerate(fields) if f["field_key"] == sort_key), None)
    if sort_idx is not None:
        kind = _sf_kind(fields[sort_idx]["field_type"])
        if kind:
            records.sort(key=lambda r: _sort_key(r["cells"][sort_idx], kind),
                        reverse=(sort_dir == "desc"))
        else:
            sort_key = ""

    return render_template(
        "records_list.html", category=category, fields=fields, records=records,
        total_count=total_count, sort=sort_key, sort_dir=sort_dir,
        active_filters=active_filters, filter_options=filter_options_for(fields),
        filter_query_args={f"f_{k}": v for k, v in active_filters.items()},
        sortable=lambda ft: bool(_sf_kind(ft)),
    )


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
        data, errors, pending = parse_form(fields, request.form, request.files, None)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("record_form.html", category=category,
                                   fields=fields,
                                   values=form_values(fields, request.form, True),
                                   link_options=link_options_for(fields),
                                   file_meta=file_meta_for(fields, {}),
                                   mode="new")
        db = get_db()
        cur = db.execute(
            "INSERT INTO records(category_id, data, created_by, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (category_id, json.dumps(data), g.user["id"], now_iso(), now_iso()),
        )
        record_id = cur.lastrowid
        if pending:
            _save_pending_files(db, record_id, data, pending)
            db.execute("UPDATE records SET data = ? WHERE id = ?",
                       (json.dumps(data), record_id))
        search.reindex_record(db, record_id)
        audit.log("record_create", category_id=category_id, category_name=category["name"],
                  record_id=record_id, record_label=record_label(category_id, data))
        db.commit()
        flash("Record added.", "success")
        return redirect(url_for("records.list_records", category_id=category_id))

    return render_template("record_form.html", category=category, fields=fields,
                           values=form_values(fields, {}, False),
                           link_options=link_options_for(fields),
                           file_meta=file_meta_for(fields, {}), mode="new")


@bp.route("/<int:record_id>")
@login_required
def view(record_id: int):
    record = _record_or_404(record_id)
    category = _category_or_404(record["category_id"])
    fields = get_fields(category["id"])
    refs = referencing_records(category["id"], record_id)
    return render_template("record_detail.html", category=category,
                           record=record_view(record, fields),
                           referenced_by=refs, reference_groups=group_references(refs))


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
        data, errors, pending = parse_form(fields, request.form, request.files, existing)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("record_form.html", category=category,
                                   fields=fields,
                                   values=form_values(fields, request.form, True),
                                   link_options=link_options_for(fields),
                                   file_meta=file_meta_for(fields, existing),
                                   mode="edit", record_id=record_id,
                                   existing=existing)
        db = get_db()
        if pending:
            _save_pending_files(db, record_id, data, pending)
        _drop_superseded_files(db, existing, data, fields)
        db.execute(
            "UPDATE records SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data), now_iso(), record_id),
        )
        search.reindex_record(db, record_id)
        audit.log("record_update", category_id=category["id"], category_name=category["name"],
                  record_id=record_id, record_label=record_label(category["id"], data))
        db.commit()
        flash("Record saved.", "success")
        return redirect(url_for("records.view", record_id=record_id))

    # Pre-fill: encrypted fields are shown blank (never decrypted into HTML).
    return render_template("record_form.html", category=category, fields=fields,
                           values=form_values(fields, existing, False),
                           link_options=link_options_for(fields),
                           file_meta=file_meta_for(fields, existing), mode="edit",
                           record_id=record_id, existing=existing)


@bp.route("/<int:record_id>/delete", methods=("POST",))
@login_required
def delete(record_id: int):
    """Move a record to the trash. It stays recoverable until purged."""
    record = _record_or_404(record_id)
    category = _category_or_404(record["category_id"])
    data = json.loads(record["data"] or "{}")
    db = get_db()
    db.execute("UPDATE records SET deleted_at = ? WHERE id = ?", (now_iso(), record_id))
    search.remove_record(db, record_id)
    audit.log("record_trash", category_id=category["id"], category_name=category["name"],
              record_id=record_id, record_label=record_label(category["id"], data))
    db.commit()
    flash("Record moved to trash.", "success")
    return redirect(url_for("records.list_records", category_id=record["category_id"]))


@bp.route("/trash")
@login_required
def trash():
    rows = get_db().execute(
        "SELECT r.id, r.category_id, r.data, r.deleted_at, "
        "c.name AS category_name, c.icon AS category_icon "
        "FROM records r JOIN categories c ON c.id = r.category_id "
        "WHERE r.deleted_at IS NOT NULL ORDER BY r.deleted_at DESC"
    ).fetchall()
    items = []
    for r in rows:
        data = json.loads(r["data"] or "{}")
        items.append({
            "id": r["id"],
            "category_id": r["category_id"],
            "category_name": r["category_name"],
            "category_icon": r["category_icon"] or "📁",
            "label": record_label(r["category_id"], data) or f"Record #{r['id']}",
            "deleted_at": r["deleted_at"],
        })
    return render_template("trash.html", items=items)


@bp.route("/<int:record_id>/restore", methods=("POST",))
@login_required
def restore(record_id: int):
    record = _record_or_404(record_id, include_deleted=True)
    if record["deleted_at"] is None:
        abort(404)
    category = _category_or_404(record["category_id"])
    data = json.loads(record["data"] or "{}")
    db = get_db()
    db.execute("UPDATE records SET deleted_at = NULL WHERE id = ?", (record_id,))
    search.reindex_record(db, record_id)
    audit.log("record_restore", category_id=category["id"], category_name=category["name"],
              record_id=record_id, record_label=record_label(category["id"], data))
    db.commit()
    flash("Record restored.", "success")
    return redirect(url_for("records.trash"))


@bp.route("/<int:record_id>/purge", methods=("POST",))
@login_required
def purge(record_id: int):
    """Permanently delete a trashed record. Only reachable from the trash --
    a record must be moved there first, so this is never a one-click action."""
    record = _record_or_404(record_id, include_deleted=True)
    if record["deleted_at"] is None:
        abort(404)
    category = get_category(record["category_id"])
    data = json.loads(record["data"] or "{}")
    db = get_db()
    db.execute("DELETE FROM records WHERE id = ?", (record_id,))  # cascades its files
    search.remove_record(db, record_id)
    audit.log("record_purge",
              category_id=record["category_id"],
              category_name=category["name"] if category else None,
              record_id=record_id,
              record_label=record_label(record["category_id"], data) if category else None)
    db.commit()
    flash("Record permanently deleted.", "success")
    return redirect(url_for("records.trash"))


@bp.route("/<int:record_id>/clone", methods=("POST",))
@login_required
def clone(record_id: int):
    """Duplicate a record into a new one in the same category, including its
    own copies of any attached files (never sharing a `files` row with the
    original -- deleting one clone must not break the other)."""
    record = _record_or_404(record_id)
    category = _category_or_404(record["category_id"])
    fields = get_fields(category["id"])
    if _has_encrypted_field(fields) and not crypto.is_unlocked():
        return redirect(url_for("auth.unlock", next=request.path))

    data = json.loads(record["data"] or "{}")
    db = get_db()
    cur = db.execute(
        "INSERT INTO records(category_id, data, created_by, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (category["id"], json.dumps(data), g.user["id"], now_iso(), now_iso()),
    )
    new_id = cur.lastrowid

    changed = False
    for f in fields:
        if f["field_type"] != "file":
            continue
        old_file_id = data.get(f["field_key"])
        if not old_file_id:
            continue
        old_file = db.execute("SELECT * FROM files WHERE id = ?", (int(old_file_id),)).fetchone()
        if old_file is None:
            continue
        new_cur = db.execute(
            "INSERT INTO files(record_id, field_key, filename, content_type, size_bytes, "
            "data, uploaded_by, uploaded_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, f["field_key"], old_file["filename"], old_file["content_type"],
             old_file["size_bytes"], old_file["data"], g.user["id"], now_iso()),
        )
        data[f["field_key"]] = new_cur.lastrowid
        changed = True
    if changed:
        db.execute("UPDATE records SET data = ? WHERE id = ?", (json.dumps(data), new_id))

    search.reindex_record(db, new_id)
    audit.log("record_clone", category_id=category["id"], category_name=category["name"],
              record_id=new_id, record_label=record_label(category["id"], data),
              detail=f"cloned from record #{record_id}")
    db.commit()
    flash("Record cloned. Edit the copy below.", "success")
    return redirect(url_for("records.edit", record_id=new_id))


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
    # `file` fields are also `is_encrypted` but go through /files/<id>/download
    # (binary, not JSON) -- only `password` reveals through this endpoint.
    if field is None or field["field_type"] != "password":
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


@bp.route("/files/<int:file_id>/download")
@login_required
def download_file(file_id: int):
    """Decrypt and stream one uploaded file. Requires the vault unlocked.

    GET (not POST) deliberately -- this is what lets an <img> tag preview an
    image inline. Still gated by login + unlock; never cached by the browser.
    """
    row = get_db().execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        abort(404)
    if not crypto.is_unlocked():
        abort(403)
    try:
        plaintext = crypto.decrypt_bytes(row["data"])
    except crypto.VaultLocked:
        abort(403)
    except Exception:
        abort(500)

    disposition = "inline" if row["content_type"] in INLINE_IMAGE_TYPES else "attachment"
    safe_name = row["filename"].replace('"', "")
    resp = Response(plaintext, mimetype=row["content_type"])
    resp.headers["Content-Disposition"] = f'{disposition}; filename="{safe_name}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/<int:record_id>/dismiss-alert", methods=("POST",))
@login_required
def dismiss_alert(record_id: int):
    """Hide one expiry alert until its date changes or it becomes more urgent."""
    _record_or_404(record_id)
    field_key = (request.form.get("field_key") or "").strip()
    value = (request.form.get("value") or "").strip()
    tier = (request.form.get("tier") or "").strip()
    if not field_key or not value:
        abort(400)
    alerts.dismiss(record_id, field_key, value, tier, g.user["id"])
    flash("Alert dismissed.", "success")
    return redirect(safe_next(request.form.get("next")) or url_for("index"))
