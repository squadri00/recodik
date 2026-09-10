"""Category CRUD and the per-category field builder.

Phase 1 ships placeholder routes so navigation resolves; the real category CRUD
and field builder land in Phase 2.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import admin_required

bp = Blueprint("categories", __name__, url_prefix="/categories")


@bp.route("/new")
@admin_required
def new():
    return render_template("coming_soon.html", feature="Category builder", phase=2)
