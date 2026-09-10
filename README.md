# MyVault

A self-hosted, no-code, fully customizable record keeper. You define your own
categories (like tables) and their fields, types, and order. Nothing about the
categories is hardcoded &mdash; the app only ships the engine. Password-type fields
are encrypted at rest.

- No third-party services, no telemetry, no tracking.
- Two deployment targets from one codebase: a double-click desktop executable, or
  a Docker container for always-on multi-user use.

## Status

Built in phases. Currently: **Phase 1 &mdash; Foundation** (project scaffold, SQLite
schema, first-run setup, login/logout, vault lock/unlock).

## Run from source

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Then open <http://127.0.0.1:5000>. On first launch you'll be asked to create the
admin account and the master password.

The SQLite database is written to `instance/myvault.sqlite3` by default. Override
with the `MYVAULT_DB` environment variable.

## Master password

The master password derives the encryption key for password-type fields (PBKDF2,
per-install random salt). It is never stored. **If you lose it, encrypted field
values cannot be recovered.**

## Desktop build / Docker deployment

Documented in Phase 7.
