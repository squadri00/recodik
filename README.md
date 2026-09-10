# MyVault

A self-hosted, no-code, fully customizable record keeper. You define your own
**categories** (like tables) and, for each, your own **fields**, field types, and
order. Nothing about the categories or fields is hardcoded — the app ships only
the engine. Password-type fields are **encrypted at rest**.

- No third-party services. No telemetry. No analytics. No outbound calls of any kind.
- Two deployment targets from one codebase:
  1. a double-click **desktop executable** (no install, for non-technical users);
  2. a **Docker** container for always-on, multi-user use.

## Feature overview

| Area | What you get |
|---|---|
| First-run setup | Create the first admin + a master password (derives the encryption key). |
| Categories | Create / rename / delete / reorder; emoji icon; admin-only. |
| Field builder | Per category: add / edit / remove / reorder fields. 11 field types. |
| Field types | text, textarea, password (encrypted), url, email, number, date, dropdown, multi-select, checkbox, code. |
| Records | Dynamic form per category; list + detail views; any signed-in user can edit. |
| Encryption | `password` fields are Fernet-encrypted; decrypted only on an explicit **Reveal**. |
| Search | FTS5 global search across every category; encrypted values are never indexed. |
| Templates | Export a category's field definitions to JSON; import to re-create it elsewhere. |
| Users | Admin manages members; members edit records but can't restructure categories. |

Relational / linked-record fields (a field pointing at a record in another
category) are **not** in v1 — a candidate for v2.

---

## 1. Run from source

Requires **Python 3.11+**.

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:5000>. The first screen creates the admin account and the
master password.

- Database location: `instance/myvault.sqlite3` by default. Override with the
  `MYVAULT_DB` environment variable.
- For an always-on process instead of the dev server, use `python serve.py`
  (waitress); see the environment variables at the top of that file.

### Master password

The master password derives the Fernet key for all `password`-type field values
(PBKDF2-HMAC-SHA256, per-install random salt). **It is never stored anywhere.**
If you lose it, encrypted values cannot be recovered — there is no reset. The key
lives only in the server process's memory; after a restart the vault is
**locked** until someone re-enters the master password on the unlock screen.

---

## 2. Build the desktop executable

The desktop build starts a local server on a free port and opens your browser to
it. Data is stored under your per-user application-data directory
(`%APPDATA%\MyVault` on Windows, `~/Library/Application Support/MyVault` on macOS,
`~/.local/share/MyVault` on Linux).

```bash
python -m venv .venv && source .venv/bin/activate   # or the Windows equivalent
pip install -r requirements-dev.txt
pyinstaller myvault.spec
```

Output: `dist/MyVault` (`dist/MyVault.exe` on Windows). It is a single file with
no dependencies — copy it anywhere and double-click.

> **PyInstaller does not cross-compile.** A Windows `.exe` must be built on
> Windows, a macOS binary on macOS, a Linux binary on Linux. Run the three
> builds on three machines (or CI runners) to ship all platforms.

To stop the app, close its console window.

---

## 3. Server deployment with Docker

Requires Docker with Compose v2.

```bash
docker compose up -d --build
```

- Serves on <http://localhost:8000>. Change the host port with a `.env` file:
  `MYVAULT_PORT=9000`.
- The SQLite database lives in the named volume `myvault-data` (mounted at
  `/data` in the container) and survives `docker compose down` / rebuilds.
  Remove it with `docker compose down -v` (this deletes all data).
- The container runs as a non-root user and makes no outbound network calls.

```bash
docker compose logs -f       # follow logs
docker compose down          # stop, keep data
docker compose down -v       # stop, DELETE the data volume
```

### Backups

The entire application state is the single SQLite file. To back it up:

```bash
docker compose cp myvault:/data/myvault.sqlite3 ./myvault-backup.sqlite3
```

For the desktop / source setups, copy the `.sqlite3` file from the locations
noted above.

---

## Project layout

```
myvault/            application package (Flask app factory + blueprints)
  __init__.py       create_app(), template filter, error handlers
  db.py             sqlite connection, schema application, migrations hook
  crypto.py         PBKDF2 key derivation + Fernet encrypt/decrypt
  auth.py           setup / login / logout / unlock, access-control decorators
  categories.py     category CRUD + field builder (admin)
  records.py        dynamic record forms, CRUD, reveal endpoint
  search.py         FTS5 index maintenance + search UI
  templates_io.py   category template export / import
  settings.py       user management
  fieldtypes.py     the 11 v1 field types
  schema.sql        versioned schema (applied on a fresh DB)
  templates/  static/
run.py              dev server entry
serve.py            waitress entry (server / always-on)
desktop.py          PyInstaller entry (local server + opens browser)
myvault.spec        PyInstaller build spec
Dockerfile  docker-compose.yml
```

## Security notes

- All SQL uses parameter substitution — no string-built queries.
- `password`-type values are encrypted before they touch the database and are
  returned in plaintext only by `POST /records/<id>/reveal`, one field at a time,
  and only while the vault is unlocked.
- Session cookies are `HttpOnly` + `SameSite=Lax`; the signing key is stored in
  the database and persists across restarts.
- The master key is never written to disk or placed in a cookie.
