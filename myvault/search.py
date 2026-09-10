"""FTS5-backed global search + index maintenance.

Phase 1 ships a placeholder page so navigation resolves; the real search UI and
the index-sync hooks land in Phase 4.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import login_required

bp = Blueprint("search", __name__)


@bp.route("/search")
@login_required
def search_page():
    return render_template("search.html", query="", results=None, coming_soon=True)
