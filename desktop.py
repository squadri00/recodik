"""Desktop launcher -- the entry point baked into the PyInstaller executable.

Double-clicking the executable:
  1. uses a fixed port on localhost (so the URL stays the same every launch),
     falling back to a free one if that port is already taken,
  2. stores the database under the per-user app-data directory,
  3. keeps a Desktop shortcut pointed at this exe (the built filename carries
     a version + date, so it changes on every rebuild -- the shortcut target
     is refreshed on every launch rather than created once, so it never goes
     stale),
  4. starts the waitress WSGI server in a background thread,
  5. opens the default web browser at the app,
  6. keeps running until the console window is closed.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 51423


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_port() -> int:
    env_port = os.environ.get("MYVAULT_PORT")
    if env_port:
        return int(env_port)
    return DEFAULT_PORT if _port_available(DEFAULT_PORT) else _free_port()


def _ensure_desktop_shortcut(data_dir: str) -> None:
    """Point the Desktop shortcut at this exe, refreshed on every launch.

    The built filename carries a version + date (see myvault.spec), so it's
    different on every rebuild. Re-pointing the shortcut every launch (instead
    of once, via a marker file) means it's never left targeting a build that
    no longer exists after a rebuild + folder swap.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        exe_path = sys.executable
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        shortcut_path = os.path.join(desktop, "Recodik.lnk")
        ps_script = (
            "$s = New-Object -ComObject WScript.Shell; "
            f"$sc = $s.CreateShortcut('{shortcut_path}'); "
            f"$sc.TargetPath = '{exe_path}'; "
            f"$sc.WorkingDirectory = '{os.path.dirname(exe_path)}'; "
            f"$sc.IconLocation = '{exe_path},0'; "
            "$sc.Description = 'Recodik - self-hosted record keeper'; "
            "$sc.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, timeout=10, check=False,
        )
    except Exception:
        pass  # a shortcut failure must never stop the app from starting


def main() -> None:
    from myvault.paths import default_data_dir, default_db_path

    data_dir = default_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.environ.setdefault("MYVAULT_DB", default_db_path())

    _ensure_desktop_shortcut(data_dir)

    host = "127.0.0.1"
    port = _resolve_port()
    url = f"http://{host}:{port}/"

    logging.getLogger("waitress").setLevel(logging.ERROR)

    from waitress import serve

    from myvault import create_app

    app = create_app()

    print("Recodik", flush=True)
    print(f"  data:  {app.config['DATABASE']}", flush=True)
    print(f"  url:   {url}", flush=True)
    print("  Close this window to stop Recodik.", flush=True)

    server = threading.Thread(
        target=serve,
        args=(app,),
        kwargs={"host": host, "port": port, "threads": 6, "ident": "Recodik"},
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
        print("\nStopping Recodik.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
