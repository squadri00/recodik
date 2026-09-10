"""Dynamic record forms, record CRUD, and encrypted-field reveal.

Phase 1 ships a placeholder route so navigation resolves; the real record CRUD
and password encryption/reveal land in Phase 3.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import login_required

bp = Blueprint("records", __name__, url_prefix="/records")


@bp.route("/category/<int:category_id>")
@login_required
def list_records(category_id: int):
    return render_template("coming_soon.html", feature="Records", phase=3)
