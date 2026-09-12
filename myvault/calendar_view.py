"""A read-only month calendar of every date across every category.

Nothing new is stored. This reads `date` and `date_alert` field values already
in records.data -- the same source search and alerts already read from -- and
lays them out on a standard month grid, one tag per event, color-coded by
category. `date_alert` events additionally carry their current alert tier
(matching myvault/alerts.py exactly) so a day can show which reminders are
actually active, without duplicating that logic.
"""

from __future__ import annotations

import calendar as _calendar
import json
from datetime import date, datetime

from flask import Blueprint, render_template, request

from .alerts import TIER_OVERDUE, TIER_UPCOMING, alert_window
from .auth import login_required
from .db import get_db
from .store import record_label

bp = Blueprint("calendar_view", __name__)

MIN_YEAR, MAX_YEAR = 1970, 2200

# A day cell's tags are colored by category, not by anything the user
# configures -- deterministic from the category id so it's stable across
# reloads without needing a new "category color" setting.
PALETTE_SIZE = 8


def _color_index(category_id: int) -> int:
    return category_id % PALETTE_SIZE


def _events_by_date() -> dict[str, list[dict]]:
    """Every date/date_alert value, across every category, keyed by its
    YYYY-MM-DD string. Not windowed -- callers decide which dates to show."""
    db = get_db()
    fields = db.execute(
        "SELECT f.*, c.name AS category_name, c.icon AS category_icon "
        "FROM fields f JOIN categories c ON c.id = f.category_id "
        "WHERE f.field_type IN ('date', 'date_alert')"
    ).fetchall()

    today = date.today()
    by_date: dict[str, list[dict]] = {}

    for f in fields:
        key = f["field_key"]
        is_alert_field = f["field_type"] == "date_alert"
        window = alert_window(f) if is_alert_field else None

        records = db.execute(
            "SELECT id, category_id, data FROM records "
            "WHERE category_id = ? AND deleted_at IS NULL",
            (f["category_id"],),
        ).fetchall()

        for r in records:
            data = json.loads(r["data"] or "{}")
            raw = data.get(key)
            if not raw:
                continue
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            tier = None
            if window is not None:
                days_left = (parsed - today).days
                if days_left <= 0:
                    tier = TIER_OVERDUE
                elif days_left <= window:
                    tier = TIER_UPCOMING

            by_date.setdefault(raw, []).append({
                "record_id": r["id"],
                "category_id": f["category_id"],
                "category_name": f["category_name"],
                "category_icon": f["category_icon"] or "📁",
                "color": _color_index(f["category_id"]),
                "field_label": f["label"],
                "label": record_label(f["category_id"], data) or f"Record #{r['id']}",
                "is_alert_field": is_alert_field,
                "tier": tier,
            })

    return by_date


def clamp_month(year: int, month: int) -> tuple[int, int]:
    """Roll a possibly out-of-range month into the right adjacent year."""
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def adjacent(year: int, month: int, delta_months: int) -> tuple[int, int]:
    return clamp_month(year, month + delta_months)


def month_grid(year: int, month: int) -> list[list[dict]]:
    """Weeks (Sunday-first) x 7 days, each day carrying its date and events.
    Includes the leading/trailing days of adjacent months that fill the grid."""
    events = _events_by_date()
    today = date.today()
    cal = _calendar.Calendar(firstweekday=6)  # 6 = Sunday

    weeks = []
    for week in cal.monthdatescalendar(year, month):
        row = []
        for d in week:
            iso = d.isoformat()
            row.append({
                "date": d,
                "iso": iso,
                "in_month": d.month == month,
                "is_today": d == today,
                "events": sorted(events.get(iso, ()), key=lambda e: e["label"].lower()),
            })
        weeks.append(row)
    return weeks


@bp.route("/calendar")
@login_required
def view():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    year, month = clamp_month(year, month)
    if not (MIN_YEAR <= year <= MAX_YEAR):
        year, month = today.year, today.month

    prev_year, prev_month = adjacent(year, month, -1)
    next_year, next_month = adjacent(year, month, 1)

    return render_template(
        "calendar.html",
        year=year, month=month, month_name=_calendar.month_name[month],
        weeks=month_grid(year, month),
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
    )
