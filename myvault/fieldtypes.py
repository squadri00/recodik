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
FIELD_TYPES: dict[str, dict] = {
    "text":        {"label": "Text",                "options": False, "encrypted": False, "target": False},
    "textarea":    {"label": "Text area",           "options": False, "encrypted": False, "target": False},
    "password":    {"label": "Password (encrypted)", "options": False, "encrypted": True, "target": False},
    "url":         {"label": "URL",                 "options": False, "encrypted": False, "target": False},
    "email":       {"label": "Email",               "options": False, "encrypted": False, "target": False},
    "number":      {"label": "Number",              "options": False, "encrypted": False, "target": False},
    "date":        {"label": "Date",                "options": False, "encrypted": False, "target": False},
    "dropdown":    {"label": "Dropdown (single-select)", "options": True, "encrypted": False, "target": False},
    "multiselect": {"label": "Multi-select",        "options": True,  "encrypted": False, "target": False},
    "link":        {"label": "Linked record",       "options": False, "encrypted": False, "target": True},
    "checkbox":    {"label": "Checkbox",            "options": False, "encrypted": False, "target": False},
    "code":        {"label": "Code (monospace)",    "options": False, "encrypted": False, "target": False},
    "file":        {"label": "File (image or document)", "options": False, "encrypted": True, "target": False},
}

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
