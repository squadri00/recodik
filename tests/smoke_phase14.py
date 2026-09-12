"""v5 smoke test: full-database backup download + restore."""
import os, sys, io, json, sqlite3, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def raw(sql, *a):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, a).fetchall()
    finally:
        conn.close()


def cat_names():
    return sorted(r["name"] for r in raw("SELECT name FROM categories"))


# --- seed "before" state and take the real backup ---
c.post("/categories/new", data={"name": "Alpha"})
r = c.get("/settings/backup/download")
assert r.status_code == 200
assert r.headers["Content-Type"] == "application/octet-stream"
assert "attachment" in r.headers["Content-Disposition"]
backup_bytes = r.get_data()
print("OK  download returns a file")

# the downloaded bytes are themselves a valid, openable MyVault database
tmp_check = os.path.join(tempfile.mkdtemp(), "check.sqlite3")
open(tmp_check, "wb").write(backup_bytes)
check_conn = sqlite3.connect(tmp_check)
assert {"meta", "users", "categories", "fields", "records"} <= {
    r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert check_conn.execute("SELECT name FROM categories").fetchone()[0] == "Alpha"
check_conn.close()
print("OK  the downloaded file is itself a complete, valid MyVault database")

# --- non-admin is refused ---
c.post("/settings/users", data={"username": "bob", "password": "bobpassword1", "role": "member"})
bob = app.test_client()
bob.post("/login", data={"username": "bob", "password": "bobpassword1"})
assert bob.get("/settings/backup/download").status_code == 403
assert bob.post("/settings/backup/restore", data={"confirm": "RESTORE"}).status_code == 403
print("OK  members can't download or restore backups")

# --- restore validation: wrong confirmation phrase changes nothing ---
r = c.post("/settings/backup/restore",
           data={"confirm": "restore", "backup_file": (io.BytesIO(backup_bytes), "b.sqlite3")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"Type" in r.data and b"exactly" in r.data
assert "Alpha" in cat_names()
print("OK  wrong (case-sensitive) confirmation phrase blocks the restore")

# --- restore validation: not a database at all ---
r = c.post("/settings/backup/restore",
           data={"confirm": "RESTORE", "backup_file": (io.BytesIO(b"not a database"), "b.sqlite3")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"Restore cancelled" in r.data
print("OK  a non-database upload is rejected")

# --- restore validation: valid sqlite file, but not a MyVault schema ---
bogus = os.path.join(tempfile.mkdtemp(), "bogus.sqlite3")
bogus_conn = sqlite3.connect(bogus)
bogus_conn.execute("CREATE TABLE whatever (x INTEGER)")
bogus_conn.commit()
bogus_conn.close()
r = c.post("/settings/backup/restore",
           data={"confirm": "RESTORE", "backup_file": (open(bogus, "rb"), "bogus.sqlite3")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"doesn" in r.data and b"look like a MyVault database" in r.data
print("OK  a valid SQLite file that isn't a MyVault database is rejected")

# --- restore validation: a schema from a newer, not-yet-understood version ---
future = os.path.join(tempfile.mkdtemp(), "future.sqlite3")
fconn = sqlite3.connect(future)
fconn.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
    CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE fields (id INTEGER PRIMARY KEY);
    CREATE TABLE records (id INTEGER PRIMARY KEY);
    INSERT INTO meta VALUES ('schema_version', '999');
    INSERT INTO users VALUES (1, 'x');
""")
fconn.commit(); fconn.close()
r = c.post("/settings/backup/restore",
           data={"confirm": "RESTORE", "backup_file": (open(future, "rb"), "future.sqlite3")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"newer version of MyVault" in r.data
assert "Alpha" in cat_names()
print("OK  a backup from a newer schema version is rejected; live vault untouched")

# --- the real restore: build a DIFFERENT state, back it up, change the live
# vault again, then restore the earlier backup and confirm it wins ---
c.post("/categories/new", data={"name": "Beta"})
r = c.get("/settings/backup/download")  # backup #2: has both Alpha and Beta
backup_2 = r.get_data()
c.post("/categories/new", data={"name": "Gamma"})  # live vault now: Alpha, Beta, Gamma
assert cat_names() == ["Alpha", "Beta", "Gamma"]

r = c.post("/settings/backup/restore",
           data={"confirm": "RESTORE", "backup_file": (io.BytesIO(backup_2), "b2.sqlite3")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"Vault restored" in r.data
assert cat_names() == ["Alpha", "Beta"]  # Gamma is gone -- backup_2 predates it
print("OK  restoring a backup replaces the live vault with exactly that backup's contents")

# --- a safety copy of the pre-restore state (with Gamma) was saved to disk ---
backups_dir = os.path.join(os.path.dirname(db_path), "backups")
safety_files = [f for f in os.listdir(backups_dir) if f.startswith("pre-restore-")]
assert safety_files, "expected a pre-restore safety backup on disk"
safety_conn = sqlite3.connect(os.path.join(backups_dir, sorted(safety_files)[-1]))
assert sorted(r[0] for r in safety_conn.execute("SELECT name FROM categories")) == \
       ["Alpha", "Beta", "Gamma"]
print("OK  the pre-restore state (including Gamma) was saved to a safety backup on disk")

# --- the vault is locked and the session cleared after a restore ---
r = c.get("/", follow_redirects=True)
assert b"Sign in" in r.data or b"Username" in r.data  # bounced to /login
print("OK  restoring clears the session and locks the vault (fresh unlock required)")

print("\nv5 backup/restore smoke test: ALL PASSED")
