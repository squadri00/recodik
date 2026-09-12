"""MyVault -- a self-hosted, no-code, customizable record keeper.

Application factory. Blueprints are registered per build phase.
"""

from __future__ import annotations

import os

from flask import Flask, g, redirect, render_template, url_for

__version__ = "0.8.0"


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        APP_TITLE="MyVault",
        DATABASE=os.environ.get(
            "MYVAULT_DB", os.path.join(app.instance_path, "myvault.sqlite3")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Whole-request cap. Must comfortably exceed both records.MAX_FILE_SIZE
        # (one uploaded file) and a full-database backup upload (Settings ->
        # Restore), which can be much larger once a vault has many attachments.
        MAX_CONTENT_LENGTH=int(os.environ.get("MYVAULT_MAX_UPLOAD_MB", "300")) * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    # Best effort: the instance dir only matters when the DB lives inside it.
    # In a container the app dir is often read-only and the DB is on a volume
    # (MYVAULT_DB), so a failure here must not be fatal -- db.init_db() creates
    # the actual database directory.
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    import json as _json

    @app.template_filter("fromjson")
    def _fromjson(value):
        try:
            return _json.loads(value) if value else []
        except (ValueError, TypeError):
            return []

    from .richtext import render_markdown

    app.add_template_filter(render_markdown, name="markdown")

    from . import db

    with app.app_context():
        db.init_db()
        app.config["SECRET_KEY"] = db.get_or_create_secret_key()

    app.teardown_appcontext(db.close_db)

    from . import auth

    app.register_blueprint(auth.bp)

    # Phase 2+: categories/fields, records, search, templates, settings.
    from . import categories

    app.register_blueprint(categories.bp)

    from . import records

    app.register_blueprint(records.bp)

    from . import search

    app.register_blueprint(search.bp)

    from . import calendar_view

    app.register_blueprint(calendar_view.bp)

    from . import templates_io

    app.register_blueprint(templates_io.bp)

    from . import settings

    app.register_blueprint(settings.bp)

    @app.route("/")
    def index():
        if not auth.setup_complete():
            return redirect(url_for("auth.setup"))
        if g.user is None:
            return redirect(url_for("auth.login"))
        cats = db.get_db().execute(
            "SELECT c.*, (SELECT COUNT(*) FROM records r WHERE r.category_id=c.id) "
            "AS record_count FROM categories c ORDER BY c.sort_order, c.name"
        ).fetchall()
        return render_template("dashboard.html", categories=cats)

    @app.context_processor
    def inject_globals():
        title = app.config["APP_TITLE"]
        try:
            if auth.setup_complete():
                title = db.get_meta("app_title", title) or title
        except Exception:
            pass
        from . import crypto
        from .records import MAX_FILE_SIZE

        header_alerts = []
        nav_categories = []
        if g.get("user") is not None:
            try:
                from . import alerts as _alerts

                header_alerts = _alerts.active_alerts()
            except Exception:
                header_alerts = []  # never let a broken date value break every page
            try:
                from .store import get_categories

                nav_categories = get_categories()
            except Exception:
                nav_categories = []

        return {
            "app_title": title,
            "current_user": g.get("user"),
            "vault_unlocked": crypto.is_unlocked(),
            "app_version": __version__,
            "max_file_mb": MAX_FILE_SIZE // (1024 * 1024),
            "header_alerts": header_alerts,
            "nav_categories": nav_categories,
        }

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403,
                               message="You do not have access to that."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404,
                               message="Nothing here."), 404

    @app.errorhandler(413)
    def too_large(_e):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template("error.html", code=413,
                               message=f"That upload is too large (limit {limit_mb} MB)."), 413

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500,
                               message="Something went wrong on the server."), 500

    return app
