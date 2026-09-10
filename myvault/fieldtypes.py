"""The v1 field-type catalogue.

Shared by the field builder (Phase 2), the dynamic record form (Phase 3),
search indexing (Phase 4) and template import/export (Phase 6).

Relational / linked-record fields (a field pointing at a record in another
category) are intentionally NOT in v1 -- flagged as a possible v2 feature.
"""

from __future__ import annotations

# key -> metadata. `options` = uses fields.options; `encrypted` = value stored
# encrypted at rest and masked in the UI.
FIELD_TYPES: dict[str, dict] = {
    "text":        {"label": "Text",                "options": False, "encrypted": False},
    "textarea":    {"label": "Text area",           "options": False, "encrypted": False},
    "password":    {"label": "Password (encrypted)", "options": False, "encrypted": True},
    "url":         {"label": "URL",                 "options": False, "encrypted": False},
    "email":       {"label": "Email",               "options": False, "encrypted": False},
    "number":      {"label": "Number",              "options": False, "encrypted": False},
    "date":        {"label": "Date",                "options": False, "encrypted": False},
    "dropdown":    {"label": "Dropdown (single-select)", "options": True, "encrypted": False},
    "multiselect": {"label": "Multi-select",        "options": True,  "encrypted": False},
    "checkbox":    {"label": "Checkbox",            "options": False, "encrypted": False},
    "code":        {"label": "Code (monospace)",    "options": False, "encrypted": False},
}

FIELD_TYPE_ORDER: list[str] = list(FIELD_TYPES)


def is_valid_type(t: str) -> bool:
    return t in FIELD_TYPES


def needs_options(t: str) -> bool:
    return FIELD_TYPES.get(t, {}).get("options", False)


def is_encrypted(t: str) -> bool:
    return FIELD_TYPES.get(t, {}).get("encrypted", False)
