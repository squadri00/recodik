"""Production server entry point (used by Docker and any always-on deployment).

Serves the app with waitress, a pure-Python WSGI server. Configuration is via
environment variables:

    MYVAULT_HOST   bind address           (default 0.0.0.0)
    MYVAULT_PORT   bind port              (default 8000)
    MYVAULT_DB     path to the SQLite DB  (default ./instance/myvault.sqlite3)
    MYVAULT_THREADS  waitress worker threads (default 8)
"""

from __future__ import annotations

import os

from waitress import serve

from myvault import create_app


def main() -> None:
    host = os.environ.get("MYVAULT_HOST", "0.0.0.0")
    port = int(os.environ.get("MYVAULT_PORT", "8000"))
    threads = int(os.environ.get("MYVAULT_THREADS", "8"))
    app = create_app()
    print(f"MyVault serving on http://{host}:{port}  (db: {app.config['DATABASE']})",
          flush=True)
    serve(app, host=host, port=port, threads=threads, ident="MyVault")


if __name__ == "__main__":
    main()
