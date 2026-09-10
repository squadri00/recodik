"""Category template export / import -- field definitions only, never records.

A template is a small JSON document describing a category's name, icon, and
ordered field list. It's how a finished "Commands" or "UnPw" layout gets shared
with someone else. Importing one creates a brand-new empty category.
"""

from __future__ import annotations

import json

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    request,
    url_for,
)

from .auth import admin_required
from .db import get_db
from .fieldtypes import FIELD_TYPES, is_valid_type, needs_options
from .store import get_category, get_fields
from .util import now_iso, slugify_key, uniquify_key

bp = Blueprint("templates_io", __name__, url_prefix="/templates")

TEMPLATE_FORMAT = 1
MAX_FIELDS = 200
MAX_NAME = 80


# --- export ---------------------------------------------------------------

def build_template(category, fields) -> dict:
    return {
        "myvault_template": TEMPLATE_FORMAT,
        "name": category["name"],
        "icon": category["icon"] or "",
        "exported_at": now_iso(),
        "fields": [
            {
                "label": f["label"],
                "field_key": f["field_key"],
                "field_type": f["field_type"],
                "required": bool(f["required"]),
                "options": json.loads(f["options"] or "[]"),
            }
            for f in fields
        ],
    }


@bp.route("/export/<int:category_id>")
@admin_required
def export_category(category_id: int):
    category = get_category(category_id)
    if category is None:
        abort(404)
    payload = build_template(category, get_fields(category_id))
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    filename = (slugify_key(category["name"]) or "category") + ".myvault.json"
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- import ---------------------------------------------------------------

def parse_template(text: str) -> tuple[dict | None, str | None]:
    try:
        doc = json.loads(text)
    except ValueError:
        return None, "That file isn't valid JSON."
    if not isinstance(doc, dict) or doc.get("myvault_template") != TEMPLATE_FORMAT:
        return None, "Not a MyVault template file (missing \"myvault_template\": 1)."

    name = str(doc.get("name") or "").strip()
    if not name:
        return None, "Template has no category name."
    name = name[:MAX_NAME]
    icon = str(doc.get("icon") or "").strip()[:8]

    raw_fields = doc.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        return None, "Template has no fields."
    if len(raw_fields) > MAX_FIELDS:
        return None, f"Template has too many fields (max {MAX_FIELDS})."

    clean: list[dict] = []
    taken: set[str] = set()
    for i, rf in enumerate(raw_fields, 1):
        if not isinstance(rf, dict):
            return None, f"Field #{i} is malformed."
        label = str(rf.get("label") or "").strip()[:MAX_NAME]
        if not label:
            return None, f"Field #{i} has no label."
        ftype = str(rf.get("field_type") or "")
        if not is_valid_type(ftype):
            return None, f"Field “{label}” has an unknown type “{ftype}”."
        options = rf.get("options") or []
        if not isinstance(options, list):
            return None, f"Field “{label}” has malformed options."
        options = [str(o).strip() for o in options if str(o).strip()]
        # de-dupe, keep order
        seen: set[str] = set()
        options = [o for o in options if not (o in seen or seen.add(o))]
        if needs_options(ftype) and not options:
            return None, f"Field “{label}” ({FIELD_TYPES[ftype]['label']}) needs options."

        key = uniquify_key(slugify_key(label), taken)
        taken.add(key)
        clean.append({
            "label": label,
            "field_key": key,
            "field_type": ftype,
            "required": 1 if rf.get("required") else 0,
            "options": options if needs_options(ftype) else [],
        })

    return {"name": name, "icon": icon, "fields": clean}, None


@bp.route("/import", methods=("GET", "POST"))
@admin_required
def import_category():
    if request.method == "GET":
        return redirect(url_for("categories.manage"))

    file = request.files.get("template")
    if file is None or not file.filename:
        flash("Choose a template file to import.", "error")
        return redirect(url_for("categories.manage"))
    try:
        text = file.read().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        flash("Could not read that file.", "error")
        return redirect(url_for("categories.manage"))

    tpl, error = parse_template(text)
    if error:
        flash(error, "error")
        return redirect(url_for("categories.manage"))

    db = get_db()
    name = tpl["name"]
    if db.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        name = f"{name} (imported)"[:MAX_NAME]

    cur = db.execute(
        "INSERT INTO categories(name, icon, sort_order, created_by, created_at) "
        "VALUES(?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories), ?, ?)",
        (name, tpl["icon"], g.user["id"], now_iso()),
    )
    category_id = cur.lastrowid
    for order, f in enumerate(tpl["fields"]):
        db.execute(
            "INSERT INTO fields(category_id, label, field_key, field_type, options, required, sort_order) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (category_id, f["label"], f["field_key"], f["field_type"],
             json.dumps(f["options"]), f["required"], order),
        )
    db.commit()
    flash(f"Imported “{name}” with {len(tpl['fields'])} field(s). Add records to it now.",
          "success")
    return redirect(url_for("categories.edit", category_id=category_id))
