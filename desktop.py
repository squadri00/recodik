"""Desktop launcher -- the entry point baked into the PyInstaller executable.

Double-clicking the executable:
  1. picks a free port on localhost,
  2. stores the database under the per-user app-data directory,
  3. starts the waitress WSGI server in a background thread,
  4. opens the default web browser at the app,
  5. keeps running until the console window is closed.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    from myvault.paths import default_data_dir, default_db_path

    data_dir = default_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.environ.setdefault("MYVAULT_DB", default_db_path())

    host = "127.0.0.1"
    port = int(os.environ.get("MYVAULT_PORT") or _free_port())
    url = f"http://{host}:{port}/"

    logging.getLogger("waitress").setLevel(logging.ERROR)

    from waitress import serve

    from myvault import create_app

    app = create_app()

    print("MyVault", flush=True)
    print(f"  data:  {app.config['DATABASE']}", flush=True)
    print(f"  url:   {url}", flush=True)
    print("  Close this window to stop MyVault.", flush=True)

    server = threading.Thread(
        target=serve,
        args=(app,),
        kwargs={"host": host, "port": port, "threads": 6, "ident": "MyVault"},
        daemon=True,
    )
    server.start()

    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        while server.is_alive():
            server.join(1.0)
    except KeyboardInterrupt:
        print("\nStopping MyVault.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
