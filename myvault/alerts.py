"""Expiry / reminder alerts for `date_alert` fields.

No scheduler and no background job: a self-hosted vault's dataset is small, so
every active alert is recomputed fresh on each request (see the context
processor in __init__.py) straight from records.data -- there is no separate
alerts table, only a small table recording what's been dismissed.

Severity has two tiers:
  upcoming -- the date is in the future, within the field's configured window
  overdue  -- the date is today or in the past

A dismissal is keyed to (record_id, field_key) plus the exact date value and
tier it was dismissed at. It stops applying -- the alert reappears -- if
either the record's date value changes, or its severity has since increased
(dismissing a 30-day warning does not silence the overdue alert later).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from .db import get_db
from .fieldtypes import DEFAULT_ALERT_DAYS
from .store import record_label
from .util import now_iso

TIER_UPCOMING = "upcoming"
TIER_OVERDUE = "overdue"
_SEVERITY = {TIER_UPCOMING: 0, TIER_OVERDUE: 1}


def alert_window(field) -> int:
    """The configured alert window for a `date_alert` field (default if unset
    or if `field` isn't actually one -- callers should still guard by type)."""
    try:
        cfg = json.loads(field["options"] or "{}")
        if not isinstance(cfg, dict):
            return DEFAULT_ALERT_DAYS
        return max(0, int(cfg.get("alert_days_before", DEFAULT_ALERT_DAYS)))
    except (ValueError, TypeError):
        return DEFAULT_ALERT_DAYS


def _tier(days_left: int) -> str:
    return TIER_OVERDUE if days_left <= 0 else TIER_UPCOMING


def active_alerts() -> list[dict]:
    """Every currently-active (non-dismissed) alert, most urgent first."""
    db = get_db()
    fields = db.execute(
        "SELECT f.*, c.name AS category_name, c.icon AS category_icon "
        "FROM fields f JOIN categories c ON c.id = f.category_id "
        "WHERE f.field_type = 'date_alert'"
    ).fetchall()
    if not fields:
        return []

    today = date.today()
    out: list[dict] = []

    for f in fields:
        window = alert_window(f)
        key = f["field_key"]
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
                d = datetime.strptime(raw, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            days_left = (d - today).days
            if days_left > window:
                continue
            tier = _tier(days_left)

            dismissal = db.execute(
                "SELECT dismissed_value, dismissed_tier FROM alert_dismissals "
                "WHERE record_id = ? AND field_key = ?", (r["id"], key),
            ).fetchone()
            if dismissal is not None:
                same_value = dismissal["dismissed_value"] == raw
                escalated = _SEVERITY[tier] > _SEVERITY.get(dismissal["dismissed_tier"], 0)
                if same_value and not escalated:
                    continue

            out.append({
                "record_id": r["id"],
                "category_id": r["category_id"],
                "category_name": f["category_name"],
                "category_icon": f["category_icon"],
                "field_key": key,
                "field_label": f["label"],
                "date": raw,
                "days_left": days_left,
                "tier": tier,
                "label": record_label(r["category_id"], data) or f"Record #{r['id']}",
            })

    out.sort(key=lambda a: a["days_left"])
    return out


def dismiss(record_id: int, field_key: str, value: str, tier: str,
            user_id: int | None) -> None:
    if tier not in _SEVERITY:
        tier = TIER_UPCOMING
    db: sqlite3.Connection = get_db()
    db.execute(
        "INSERT INTO alert_dismissals"
        "(record_id, field_key, dismissed_value, dismissed_tier, dismissed_by, dismissed_at) "
        "VALUES(?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(record_id, field_key) DO UPDATE SET "
        "dismissed_value = excluded.dismissed_value, "
        "dismissed_tier = excluded.dismissed_tier, "
        "dismissed_by = excluded.dismissed_by, "
        "dismissed_at = excluded.dismissed_at",
        (record_id, field_key, value, tier, user_id, now_iso()),
    )
    db.commit()
