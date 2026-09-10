"""Category template export / import (field definitions only). Built in Phase 6."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("templates_io", __name__, url_prefix="/templates")
