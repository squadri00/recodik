"""First-run setup, login/logout, vault unlock, and access-control decorators."""

from __future__ import annotations

import functools

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import crypto, demo_data
from .db import get_db, get_meta, set_meta
from .util import now_iso, safe_next

bp = Blueprint("auth", __name__)

MIN_PASSWORD_LEN = 8


def any_user_exists() -> bool:
    return get_db().execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def setup_complete() -> bool:
    return any_user_exists() and get_meta("kdf_salt") is not None


@bp.before_app_request
def load_logged_in_user() -> None:
    uid = session.get("user_id")
    if uid is None:
        g.user = None
        return
    g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if g.user is None:
        session.clear()


# --- decorators ---------------------------------------------------------------

def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(**kwargs)

    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user["role"] != "admin":
            abort(403)
        return view(**kwargs)

    return wrapped


def unlock_required(view):
    """Routes that must decrypt/encrypt data need the vault unlocked."""

    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if not crypto.is_unlocked():
            return redirect(url_for("auth.unlock", next=request.full_path.rstrip("?")))
        return view(**kwargs)

    return wrapped


# --- routes ----------------------------------------------------------------

@bp.route("/setup", methods=("GET", "POST"))
def setup():
    if setup_complete():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        master = request.form.get("master_password", "")
        master_confirm = request.form.get("master_password_confirm", "")

        errors = []
        if not username:
            errors.append("Username is required.")
        if len(password) < MIN_PASSWORD_LEN:
            errors.append(
                f"Account password must be at least {MIN_PASSWORD_LEN} characters."
            )
        if len(master) < MIN_PASSWORD_LEN:
            errors.append(
                f"Master password must be at least {MIN_PASSWORD_LEN} characters."
            )
        if master != master_confirm:
            errors.append("Master passwords do not match.")
        if password and master and password == master:
            errors.append("Use a different value for the master password.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("setup.html", username=username)

        db = get_db()
        salt = crypto.new_salt()
        key = crypto.derive_key(master, salt)
        db.execute(
            "INSERT INTO users(username, password_hash, role, created_at) "
            "VALUES(?, ?, 'admin', ?)",
            (username, generate_password_hash(password), now_iso()),
        )
        set_meta(db, "kdf_salt", salt.hex())
        set_meta(db, "key_verifier", crypto.make_verifier(key))
        set_meta(db, "app_title", current_app.config["APP_TITLE"])
        db.commit()

        crypto.set_master_key(key)
        user = db.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

        # Brand-new install (this is the very first admin ever created): load
        # sample data so there's something real to explore instead of a blank
        # dashboard. See Settings -> Sample data to remove it later.
        if demo_data.is_untouched_install(db):
            from . import search  # local import: search.py imports this module

            record_ids = demo_data.seed(db, created_by=user["id"])
            db.commit()
            for rid in record_ids:
                search.reindex_record(db, rid)
            db.commit()

        session.clear()
        session["user_id"] = user["id"]
        flash("Setup complete. Your vault is unlocked.", "success")
        return redirect(url_for("index"))

    return render_template("setup.html", username="")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if not setup_complete():
        return redirect(url_for("auth.setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username)

        session.clear()
        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['username']}.", "success")
        return redirect(safe_next(request.args.get("next")) or url_for("index"))

    return render_template("login.html", username="")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/unlock", methods=("GET", "POST"))
@login_required
def unlock():
    if crypto.is_unlocked():
        return redirect(safe_next(request.args.get("next")) or url_for("index"))

    if request.method == "POST":
        master = request.form.get("master_password", "")
        salt_hex = get_meta("kdf_salt")
        verifier = get_meta("key_verifier")
        if not salt_hex or not verifier:
            abort(500, "Vault is not set up.")
        key = crypto.derive_key(master, bytes.fromhex(salt_hex))
        if crypto.check_key(key, verifier):
            crypto.set_master_key(key)
            flash("Vault unlocked.", "success")
            return redirect(safe_next(request.args.get("next")) or url_for("index"))
        flash("Incorrect master password.", "error")

    return render_template("unlock.html")


@bp.route("/lock")
@login_required
def lock():
    crypto.clear_master_key()
    flash("Vault locked. Encrypted fields are hidden until you unlock again.", "success")
    return redirect(url_for("index"))
