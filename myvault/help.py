"""The in-app Help guide -- a single static page, no dynamic data beyond the
usual template globals (app_title, current_user, etc. via inject_globals)."""

from __future__ import annotations

from flask import Blueprint, render_template

from .auth import login_required

bp = Blueprint("help", __name__)


@bp.route("/help")
@login_required
def guide():
    return render_template("help.html")
