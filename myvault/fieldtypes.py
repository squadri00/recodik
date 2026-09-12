"""The v1 field-type catalogue.

Shared by the field builder (Phase 2), the dynamic record form (Phase 3),
search indexing (Phase 4) and template import/export (Phase 6).

Relational / linked-record fields (a field pointing at a record in another
category) are intentionally NOT in v1 -- flagged as a possible v2 feature.
"""

from __future__ import annotations

# key -> metadata.
#   options  = uses fields.options as a JSON array of choice strings
#   encrypted = value stored encrypted at rest and masked in the UI
#   target   = uses fields.options as {"category_id": N}; value is a record id
#              in that category (v2 linked-record field)
#   alert    = uses fields.options as {"alert_days_before": N}; the header
#              shows an expiry/reminder alert once the date is within N days
#              (v4 field -- see myvault/alerts.py)
#   frequency = uses fields.options as {"frequency": "monthly"|"yearly"|"one_time"};
#               a plain numeric amount, billed on this cadence -- rolled up
#               across every category on the Costs dashboard (v9 field --
#               see myvault/costs.py)
FIELD_TYPES: dict[str, dict] = {
    "text":        {"label": "Text",                "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "textarea":    {"label": "Text area",           "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "password":    {"label": "Password (encrypted)", "options": False, "encrypted": True, "target": False, "alert": False, "frequency": False},
    "url":         {"label": "URL",                 "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "email":       {"label": "Email",               "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "number":      {"label": "Number",              "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "cost":        {"label": "Cost (recurring)",    "options": False, "encrypted": False, "target": False, "alert": False, "frequency": True},
    "date":        {"label": "Date",                "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "date_alert":  {"label": "Expiry / reminder date", "options": False, "encrypted": False, "target": False, "alert": True, "frequency": False},
    "dropdown":    {"label": "Dropdown (single-select)", "options": True, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "multiselect": {"label": "Multi-select",        "options": True,  "encrypted": False, "target": False, "alert": False, "frequency": False},
    "link":        {"label": "Linked record",       "options": False, "encrypted": False, "target": True, "alert": False, "frequency": False},
    "checkbox":    {"label": "Checkbox",            "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "code":        {"label": "Code (monospace)",    "options": False, "encrypted": False, "target": False, "alert": False, "frequency": False},
    "file":        {"label": "File (image or document)", "options": False, "encrypted": True, "target": False, "alert": False, "frequency": False},
}

DEFAULT_ALERT_DAYS = 30

COST_FREQUENCIES = ("monthly", "yearly", "one_time")
DEFAULT_FREQUENCY = "monthly"
FREQUENCY_LABELS = {"monthly": "/mo", "yearly": "/yr", "one_time": "one-time"}

FIELD_TYPE_ORDER: list[str] = list(FIELD_TYPES)


def is_valid_type(t: str) -> bool:
    return t in FIELD_TYPES


def needs_options(t: str) -> bool:
    return FIELD_TYPES.get(t, {}).get("options", False)


def needs_target(t: str) -> bool:
    """True for field types configured with a target category (linked records)."""
    return FIELD_TYPES.get(t, {}).get("target", False)


def is_encrypted(t: str) -> bool:
    return FIELD_TYPES.get(t, {}).get("encrypted", False)


def needs_alert_config(t: str) -> bool:
    """True for field types configured with an alert window (expiry dates)."""
    return FIELD_TYPES.get(t, {}).get("alert", False)


def is_date_like(t: str) -> bool:
    """Both date types share the same input widget and YYYY-MM-DD validation."""
    return t in ("date", "date_alert")


def needs_frequency(t: str) -> bool:
    """True for field types configured with a billing cadence (recurring costs)."""
    return FIELD_TYPES.get(t, {}).get("frequency", False)
