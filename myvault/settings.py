"""Settings: user management, master-password change, app title.

Phase 1 ships a placeholder page so navigation resolves; user management lands in
Phase 5 and master-password change / title customization in Phase 9.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import admin_required

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/")
@admin_required
def index():
    return render_template("settings.html", coming_soon=True, users=None)
