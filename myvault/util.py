"""Small shared helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import request


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_next(target: str | None) -> str | None:
    """Return ``target`` only if it is a same-site relative path.

    Guards the ``?next=`` redirect params against open-redirect abuse.
    """
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


_slug_strip = re.compile(r"[^a-z0-9]+")


def slugify_key(label: str) -> str:
    """Machine key from a human label: 'SSH Key' -> 'ssh_key'."""
    slug = _slug_strip.sub("_", label.strip().lower()).strip("_")
    if not slug:
        slug = "field"
    if slug[0].isdigit():
        slug = "f_" + slug
    return slug[:60]


def uniquify_key(base: str, taken: set[str]) -> str:
    """Append _2, _3, ... until the key is unused within a category."""
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def wants_json() -> bool:
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )
