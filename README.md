# MyVault

A self-hosted, no-code, fully customizable record keeper. You define your own
**categories** (like tables) and, for each, your own **fields**, field types, and
order. Nothing about the categories or fields is hardcoded — the app ships only
the engine. Password-type fields and uploaded files are **encrypted at rest**.

- No third-party services. No telemetry. No analytics. No outbound calls of any kind.
- Two deployment targets from one codebase:
  1. a double-click **desktop executable** (no install, for non-technical users);
  2. a **Docker** container for always-on, multi-user use.

## Feature overview

| Area | What you get |
|---|---|
| First-run setup | Create the first admin + a master password (derives the encryption key). |
| Categories | Create / rename / delete / reorder; emoji icon; admin-only. |
| Field builder | Per category: add / edit / remove / reorder fields. 14 field types. |
| Field types | text, textarea (Markdown), password (encrypted), url, email, number, date, **expiry/reminder date**, dropdown, multi-select, **linked record**, **file**, checkbox, code. |
| Linked records (v2) | A `link` field points each record at one record in another category; renders as a dropdown of that category's records and a clickable link. The target record's detail page lists everything that references it. |
| File attachments (v3) | A `file` field uploads one image or document per record, encrypted at rest in the same `.sqlite3` file (no separate folder to back up). Images preview inline; everything else downloads. Content requires the vault unlocked; filename/size stay visible either way. |
| Text formatting | A small toolbar on `textarea` fields inserts Markdown (bold, italic, headings, lists, links, code); rendered as sanitized HTML on the record's detail page. |
| Expiry / reminder alerts (v4) | A `date_alert` field warns N days before (and after) its date — a pulsing badge in the header, on every page, with a dismissible list. Re-alerts if dismissed early and later becomes overdue. |
| Records | Dynamic form per category; list + detail views; any signed-in user can edit. |
| Encryption | `password` values and `file` bytes are Fernet-encrypted; decrypted only on an explicit **Reveal** / **Download**. |
| Search | FTS5 global search across every category; encrypted values and file contents are never indexed (filenames are). |
| Templates | Export a category's field definitions to JSON; import to re-create it elsewhere. |
| Backup & restore (v5) | Settings → download a full, consistent snapshot of the entire vault, or restore one — see [Backups](#backups) below. |
| Sort & filter (v6) | Click a record-list column header to sort; a filter bar above it narrows by any column (text "contains", or a dropdown for choice/checkbox/linked-record fields). Both are shareable URLs. |
| Calendar view (v7) | A month grid plotting every `date` and `date_alert` field, from every category, on its actual day — a domain's expiry, an invoice due date, a calendar event, all in one screen. Each category gets its own tag color; a `date_alert` tag carries the same overdue/upcoming styling as the header badge. Read-only; click a tag to open the record. |
| Trash (v8) | Deleting a record moves it to **Trash** instead of erasing it — restore it, or delete it forever from there. Search, links, and back-references all hide a trashed record until it's restored. |
| Activity log (v8) | Settings → **Activity log**: who created, edited, trashed, restored, purged, or cloned a record — or created/deleted a category — and when. Answers "did someone delete this?" |
| Quick-add (v8) | A **+ Add** button in the header, on every page, opens every category in one dropdown — no need to navigate into a category first to add a record. |
| Clone (v8) | A **Clone** button on a record's detail page duplicates it (including any attached file, as its own independent copy) into a new record in the same category, ready to edit. |
| Users | Admin manages members; members edit records but can't restructure categories. |

Relational / linked-record fields shipped in **v2** as the `link` field type
(above). Use it to model hierarchies — e.g. one customer, many projects, each
project many sub-projects: a `link` on Projects points at Customers, a `link` on
Sub-projects points at Projects (or at Projects itself for a self-nested tree).

**File attachments (v3):** each upload is capped at 15 MB by default (raise it
with the `MYVAULT_MAX_FILE_MB` env var; also bump `MYVAULT_MAX_UPLOAD_MB`, the
whole-request cap, to match). Existing v1/v2 databases upgrade automatically —
on first start after updating, MyVault adds the `files` table in place; no
manual migration step.

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

The entire application state is the single SQLite file, so backing it up (or
moving the whole vault to a new installation) is one file-copy.

**In-app (recommended, any deployment):** Settings → **Backup & restore**, as
an admin.
- **Download backup** streams a consistent snapshot straight from the browser
  (safe to run any time, including while others are using the vault).
- **Restore** uploads a `.sqlite3` to replace the current one — used to bring
  the download from *this* section into a brand-new installation, or to roll
  back. It validates the file first, automatically saves the current database
  before overwriting it, and locks the vault afterward (whoever restored it
  unlocks again with the restored database's own master password). Treat it
  as one-way: type `RESTORE` to confirm.

**From the command line (Docker):**

```bash
docker compose cp myvault:/data/myvault.sqlite3 ./myvault-backup.sqlite3
```

For the desktop / source setups, copy the `.sqlite3` file from the locations
noted above — with the app closed if you want to skip the in-app download.

---

## Tests

End-to-end smoke tests (no external test framework — they drive the app through
Flask's test client and inspect the SQLite file directly):

```bash
python tests/run_all.py
```

They cover: first-run setup / auth / lock-unlock, the category + field builder,
record CRUD with encryption-at-rest and reveal, FTS search sync, multi-user role
enforcement, template export/import round-trips, input validation, a full
"no plaintext or ciphertext in any rendered view" audit, linked records, file
attachments (upload/replace/remove, size caps, inline vs. download, cascade
delete), converting a field to encrypted in place, Markdown rendering (incl.
the XSS guards), expiry/reminder alerts (escalation, dismissal, the header
badge), full-database backup/restore (validation, the safety snapshot, session
reset), sort/filter on record lists, the calendar view (month/year rollover,
per-category colors, alert-tier styling), trash/restore/purge (search, links
and back-references all hiding a trashed record), the audit log, record
cloning (including its own copy of an attached file), and every schema
migration along the way (v1→v2→v3→v4) on a hand-built legacy database.

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
  fieldtypes.py     the 14 field types (11 v1 + link/file/date_alert in v2-4)
  alerts.py         v4: expiry/reminder alert computation + dismissal
  backup.py         v5: full-database backup download + validated restore
  richtext.py       Markdown -> sanitized HTML for textarea fields
  calendar_view.py  v7: month-grid calendar of every date-like field
  audit.py          v8: append-only audit trail for record/category actions
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
- `file`-type uploads are encrypted before they touch the database and are
  decrypted only by `GET /records/files/<id>/download`, while the vault is
  unlocked; SVG uploads are never rendered inline (a `<script>` inside one
  can't run in the app's origin).
- Session cookies are `HttpOnly` + `SameSite=Lax`; the signing key is stored in
  the database and persists across restarts.
- The master key is never written to disk or placed in a cookie.
