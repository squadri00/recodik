"""Category template export / import (field definitions only).

Phase 2 ships placeholder routes so the Categories page links resolve; the real
export/import lands in Phase 6.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from .auth import admin_required

bp = Blueprint("templates_io", __name__, url_prefix="/templates")


@bp.route("/export/<int:category_id>")
@admin_required
def export_category(category_id: int):
    return render_template("coming_soon.html", feature="Template export", phase=6)


@bp.route("/import", methods=("GET", "POST"))
@admin_required
def import_category():
    flash("Template import arrives in Phase 6.", "warn")
    return redirect(url_for("categories.manage"))
