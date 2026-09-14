"""Where Recodik stores its database when no MYVAULT_DB is given.

Per-user, per-OS application-data location so the desktop build persists data
between runs without writing next to the executable.
"""

from __future__ import annotations

import os
import sys


def default_data_dir() -> str:
    override = os.environ.get("MYVAULT_DATA_DIR")
    if override:
        return override

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Recodik")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Recodik")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "Recodik")


def default_db_path() -> str:
    return os.path.join(default_data_dir(), "recodik.sqlite3")
