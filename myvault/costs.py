"""Cost rollup dashboard: every `cost` field, from every category, normalized
onto one monthly/annual total.

Nothing new is stored -- same read-only, recompute-on-request approach as
search, alerts and the calendar. A `cost` field's billing cadence is fixed at
the field level (fields.options = {"frequency": ...}), not per record, same
as a `date_alert` field's alert window.
"""

from __future__ import annotations

import json

from flask import Blueprint, render_template

from .auth import login_required
from .db import get_db
from .fieldtypes import DEFAULT_FREQUENCY
from .store import record_label

bp = Blueprint("costs", __name__)


def cost_frequency(field) -> str:
    try:
        cfg = json.loads(field["options"] or "{}")
        if not isinstance(cfg, dict):
            return DEFAULT_FREQUENCY
        freq = cfg.get("frequency", DEFAULT_FREQUENCY)
        return freq if freq in ("monthly", "yearly", "one_time") else DEFAULT_FREQUENCY
    except (ValueError, TypeError):
        return DEFAULT_FREQUENCY


def cost_rollup() -> dict:
    """{'categories': [...], 'grand_monthly', 'grand_yearly', 'grand_one_time'}.

    Monthly/yearly totals are recurring-cost equivalents (a yearly amount
    contributes amount/12 to the monthly total, and vice versa); one-time
    costs are tracked separately since they aren't a recurring commitment.
    """
    db = get_db()
    fields = db.execute(
        "SELECT f.*, c.name AS category_name, c.icon AS category_icon "
        "FROM fields f JOIN categories c ON c.id = f.category_id "
        "WHERE f.field_type = 'cost'"
    ).fetchall()

    by_category: dict[int, dict] = {}
    grand_monthly = grand_yearly = grand_one_time = 0.0

    for f in fields:
        freq = cost_frequency(f)
        records = db.execute(
            "SELECT id, category_id, data FROM records "
            "WHERE category_id = ? AND deleted_at IS NULL",
            (f["category_id"],),
        ).fetchall()

        for r in records:
            data = json.loads(r["data"] or "{}")
            raw = data.get(f["field_key"])
            if raw in (None, ""):
                continue
            try:
                amount = float(raw)
            except (TypeError, ValueError):
                continue

            cat = by_category.setdefault(f["category_id"], {
                "category_id": f["category_id"],
                "category_name": f["category_name"],
                "category_icon": f["category_icon"] or "📁",
                "monthly_total": 0.0, "yearly_total": 0.0, "one_time_total": 0.0,
                "items": [],
            })
            cat["items"].append({
                "record_id": r["id"],
                "label": record_label(r["category_id"], data) or f"Record #{r['id']}",
                "field_label": f["label"],
                "amount": amount,
                "frequency": freq,
            })

            if freq == "monthly":
                cat["monthly_total"] += amount
                cat["yearly_total"] += amount * 12
                grand_monthly += amount
                grand_yearly += amount * 12
            elif freq == "yearly":
                cat["monthly_total"] += amount / 12
                cat["yearly_total"] += amount
                grand_monthly += amount / 12
                grand_yearly += amount
            else:
                cat["one_time_total"] += amount
                grand_one_time += amount

    categories = sorted(by_category.values(), key=lambda c: c["category_name"].lower())
    for cat in categories:
        cat["items"].sort(key=lambda i: i["label"].lower())

    return {
        "categories": categories,
        "grand_monthly": grand_monthly,
        "grand_yearly": grand_yearly,
        "grand_one_time": grand_one_time,
    }


@bp.route("/costs")
@login_required
def dashboard():
    return render_template("costs.html", rollup=cost_rollup())
