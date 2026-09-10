"""Phase 1 smoke test: fresh install -> setup -> login -> lock/unlock."""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "t.sqlite3")

from myvault import create_app
from myvault import crypto

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()

# 1. root redirects to setup on a fresh db
r = c.get("/")
assert r.status_code == 302 and "/setup" in r.headers["Location"], r.headers
print("OK  / -> /setup on fresh db")

# 2. setup rejects short master password
r = c.post("/setup", data={"username": "admin", "password": "longenough1",
                           "master_password": "short", "master_password_confirm": "short"})
assert b"at least 8" in r.data, r.data[:400]
print("OK  setup rejects short master password")

# 3. setup rejects mismatch
r = c.post("/setup", data={"username": "admin", "password": "longenough1",
                           "master_password": "masterpw123", "master_password_confirm": "different99"})
assert b"do not match" in r.data
print("OK  setup rejects master mismatch")

# 4. successful setup
r = c.post("/setup", data={"username": "admin", "password": "longenough1",
                           "master_password": "masterpw123",
                           "master_password_confirm": "masterpw123"},
           follow_redirects=True)
assert r.status_code == 200 and b"Your categories" in r.data, r.data[:400]
assert crypto.is_unlocked(), "vault should be unlocked right after setup"
print("OK  setup creates admin, logs in, unlocks, dashboard renders")

# 5. setup is now closed
r = c.get("/setup")
assert r.status_code == 302 and r.headers["Location"].rstrip("/").endswith("")  # -> index
print("OK  /setup closed after completion")

# 6. dashboard shows admin-only 'New category'
r = c.get("/")
assert b"New category" in r.data
print("OK  dashboard shows admin controls")

# 7. logout then protected route redirects to login
c.get("/logout")
r = c.get("/")
assert r.status_code == 302 and "/login" in r.headers["Location"]
r = c.get("/settings/")
assert r.status_code == 302 and "/login" in r.headers["Location"]
print("OK  logout clears session; protected routes redirect to /login")

# 8. bad login
r = c.post("/login", data={"username": "admin", "password": "wrong"})
assert b"Invalid username or password" in r.data
print("OK  bad login rejected")

# 9. good login
r = c.post("/login", data={"username": "admin", "password": "longenough1"},
           follow_redirects=True)
assert b"Your categories" in r.data
print("OK  good login")

# 10. lock -> unlock roundtrip
c.get("/lock")
assert not crypto.is_unlocked()
r = c.post("/unlock", data={"master_password": "nope"})
assert b"Incorrect master password" in r.data
r = c.post("/unlock", data={"master_password": "masterpw123"}, follow_redirects=True)
assert crypto.is_unlocked() and b"Your categories" in r.data
print("OK  lock/unlock roundtrip, wrong master rejected")

# 11. open-redirect guard on ?next=
c.get("/logout")
r = c.post("/login", data={"username": "admin", "password": "longenough1"},
           query_string={"next": "https://evil.example/"})
assert r.status_code == 302 and r.headers["Location"].endswith("/")
assert "evil.example" not in r.headers["Location"]
print("OK  ?next= open-redirect blocked")

# 12. schema + parameterization sanity
import sqlite3
conn = sqlite3.connect(db_path)
tables = {row[0] for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
assert {"meta", "users", "categories", "fields", "records", "records_fts"} <= tables, tables
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
assert ver == "1"
salt = conn.execute("SELECT value FROM meta WHERE key='kdf_salt'").fetchone()[0]
assert salt and "masterpw" not in open(db_path, "rb").read().decode("latin-1")
print("OK  schema created, version=1, master password not present in db file")

print("\nPhase 1 smoke test: ALL PASSED")
