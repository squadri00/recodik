"""Settings hub.

Phase 5: user management (admin only) + role checks.
Phase 9 adds: change master password, app-title customization.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.security import generate_password_hash

from .auth import MIN_PASSWORD_LEN, admin_required
from .db import get_db
from .util import now_iso

bp = Blueprint("settings", __name__, url_prefix="/settings")

VALID_ROLES = ("admin", "member")


def _users():
    return get_db().execute(
        "SELECT id, username, role, created_at FROM users ORDER BY role, username"
    ).fetchall()


def _admin_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]


@bp.route("/")
@admin_required
def index():
    return render_template("settings.html", users=_users(), coming_soon=False)


@bp.route("/users", methods=("POST",))
@admin_required
def user_create():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "member")

    if not username:
        flash("Username is required.", "error")
    elif role not in VALID_ROLES:
        flash("Invalid role.", "error")
    elif len(password) < MIN_PASSWORD_LEN:
        flash(f"Password must be at least {MIN_PASSWORD_LEN} characters.", "error")
    else:
        db = get_db()
        exists = db.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            flash("That username is taken.", "error")
        else:
            db.execute(
                "INSERT INTO users(username, password_hash, role, created_at) "
                "VALUES(?, ?, ?, ?)",
                (username, generate_password_hash(password), role, now_iso()),
            )
            db.commit()
            flash(f"Created {role} “{username}”.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/users/<int:user_id>/role", methods=("POST",))
@admin_required
def user_role(user_id: int):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    new_role = request.form.get("role", "")
    if new_role not in VALID_ROLES:
        flash("Invalid role.", "error")
    elif user["role"] == "admin" and new_role == "member" and _admin_count(db) <= 1:
        flash("You can't demote the last remaining admin.", "error")
    else:
        db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        db.commit()
        flash(f"“{user['username']}” is now {new_role}.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/users/<int:user_id>/password", methods=("POST",))
@admin_required
def user_password(user_id: int):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    password = request.form.get("password", "")
    if len(password) < MIN_PASSWORD_LEN:
        flash(f"Password must be at least {MIN_PASSWORD_LEN} characters.", "error")
    else:
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
        db.commit()
        flash(f"Password reset for “{user['username']}”.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/users/<int:user_id>/delete", methods=("POST",))
@admin_required
def user_delete(user_id: int):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    if user["id"] == g.user["id"]:
        flash("You can't delete your own account.", "error")
    elif user["role"] == "admin" and _admin_count(db) <= 1:
        flash("You can't delete the last remaining admin.", "error")
    else:
        # records.created_by is ON DELETE SET NULL -- their records are kept.
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash(f"Deleted “{user['username']}”. Their records were kept.", "success")
    return redirect(url_for("settings.index"))
