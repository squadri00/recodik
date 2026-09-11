"""Lightweight formatting for `textarea` fields: Markdown in, sanitized HTML out.

Only the *display* changes. The value stored in records.data is always plain
Markdown text -- same as any other text field -- so search indexing, template
export, and the edit form all stay exactly as simple as before.

Rendering runs through bleach with a small tag/attribute allowlist, so raw HTML
typed or pasted into the field (a <script>, an onerror= handler, a javascript:
link) never reaches the page -- it's stripped or escaped, never executed.
"""

from __future__ import annotations

import re

import bleach
import markdown as _markdown
from markupsafe import Markup

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "ul", "ol", "li", "h2", "h3",
    "a", "code", "pre", "blockquote",
]
ALLOWED_ATTRS = {"a": ["href"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

_A_HREF = re.compile(r'<a href="([^"]*)">')


def render_markdown(text: str | None) -> Markup:
    """Markdown -> sanitized, safe-to-embed HTML. Empty input -> empty Markup."""
    if not text:
        return Markup("")
    html = _markdown.markdown(text, extensions=["nl2br"])
    clean = bleach.clean(
        html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS, strip=True,
    )
    # bleach can keep hrefs but not add new attributes -- open links in a new
    # tab without leaking a referrer/opener back to this app.
    clean = _A_HREF.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer">', clean)
    return Markup(clean)
