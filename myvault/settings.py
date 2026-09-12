"""Settings hub.

Phase 5: user management (admin only) + role checks.
v5 adds: full-database backup download + restore.
Phase 9 adds: change master password, app-title customization.
"""

from __future__ import annotations

import os

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from . import backup
from .auth import MIN_PASSWORD_LEN, admin_required
from .db import close_db, get_db
from .util import now_iso

bp = Blueprint("settings", __name__, url_prefix="/settings")

RESTORE_CONFIRM_PHRASE = "RESTORE"

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


# --- full-database backup / restore -----------------------------------------

@bp.route("/backup/download")
@admin_required
def backup_download():
    """A consistent snapshot of the entire vault -- one file, drop it into any
    MyVault installation (same deployment or a brand new one) to restore it."""
    tmp_path = backup.make_download_copy()
    resp = send_file(
        tmp_path,
        as_attachment=True,
        download_name=backup.backup_filename(),
        mimetype="application/octet-stream",
        conditional=False,
    )
    resp.call_on_close(lambda: os.path.exists(tmp_path) and os.remove(tmp_path))
    return resp


@bp.route("/backup/restore", methods=("POST",))
@admin_required
def backup_restore():
    """Replace the live vault with an uploaded backup file.

    Deliberately heavy on safety checks: this is the one action in the app
    that can discard everything currently in the vault.
    """
    if (request.form.get("confirm") or "").strip() != RESTORE_CONFIRM_PHRASE:
        flash(f'Type "{RESTORE_CONFIRM_PHRASE}" (exactly) to confirm. Nothing was changed.',
              "error")
        return redirect(url_for("settings.index"))

    file = request.files.get("backup_file")
    if file is None or not file.filename:
        flash("Choose a .sqlite3 backup file to restore.", "error")
        return redirect(url_for("settings.index"))

    tmp_path = backup.upload_temp_path()
    file.save(tmp_path)

    error = backup.validate_backup(tmp_path)
    if error:
        os.remove(tmp_path)
        flash(f"Restore cancelled: {error}", "error")
        return redirect(url_for("settings.index"))

    close_db()  # this request's own connection must let go of the file first
    safety_path = backup.restore(tmp_path)
    session.clear()  # the logged-in user id may not exist in the restored database

    flash(
        "Vault restored from the uploaded backup. Your previous database was saved "
        f"to {safety_path} in case anything looks wrong. The vault is now locked -- "
        "sign in and unlock it with the restored database's own credentials.",
        "success",
    )
    return redirect(url_for("auth.login"))
