"""v8 smoke test: trash (soft-delete), the audit log, global quick-add, and
record clone."""
import io
import json
import os
import sqlite3
import sys
import tempfile

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


def data_of(rid):
    return json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])


# --- build a category with a plain field, a link field, and a file field ---
r = c.post("/categories/new", data={"name": "Widgets"})
wcat = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{wcat}/fields/add", data={"label": "Name", "field_type": "text", "required": "1"})
c.post(f"/categories/{wcat}/fields/add", data={"label": "Notes", "field_type": "textarea"})

r = c.post("/categories/new", data={"name": "Parts"})
pcat = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{pcat}/fields/add", data={"label": "Title", "field_type": "text", "required": "1"})
c.post(f"/categories/{pcat}/fields/add",
       data={"label": "Widget", "field_type": "link", "target_category_id": str(wcat)})

# --- 1. record_create is audited ---
c.post(f"/records/category/{wcat}/new", data={"name": "Sprocket", "notes": "spins"})
wid = raw("SELECT id FROM records WHERE category_id=? AND data LIKE '%Sprocket%'", wcat)[0]["id"]
entries = raw("SELECT * FROM audit_log WHERE action='record_create' AND record_id=?", wid)
assert len(entries) == 1 and entries[0]["username"] == "admin"
assert entries[0]["record_label"] == "Sprocket" and entries[0]["category_name"] == "Widgets"
print("OK  creating a record writes an audit_log entry (who/what/label)")

# --- 2. record_update is audited ---
c.post(f"/records/{wid}/edit", data={"name": "Sprocket", "notes": "spins fast"})
assert len(raw("SELECT * FROM audit_log WHERE action='record_update' AND record_id=?", wid)) == 1
print("OK  editing a record writes an audit_log entry")

# --- link a Part at the Widget, so we can check trashing breaks the reference cleanly ---
c.post(f"/records/category/{pcat}/new", data={"title": "Gear", "widget": str(wid)})
pid = raw("SELECT id FROM records WHERE category_id=? AND data LIKE '%Gear%'", pcat)[0]["id"]
html = c.get(f"/records/{wid}").get_data(as_text=True)
assert "Gear" in html and "Referenced by" in html
print("OK  before trashing: the Part shows up under the Widget's 'Referenced by'")

# --- 3. delete moves to trash: hidden from list/search/links, row + audit kept ---
# (search for "spins", from Sprocket's own `notes` field -- searching "Sprocket"
# itself would still hit the Part's FTS row, which snapshotted the linked
# label at index time; that's an existing, unrelated resolved-link quirk)
c.post(f"/records/{wid}/delete")
assert raw("SELECT deleted_at FROM records WHERE id=?", wid)[0]["deleted_at"]
list_html = c.get(f"/records/category/{wcat}").get_data(as_text=True)
assert "Sprocket" not in list_html
assert "No matches" in c.get("/search", query_string={"q": "spins"}).get_data(as_text=True)
assert c.get(f"/records/{wid}").status_code == 404
trash_entries = raw("SELECT * FROM audit_log WHERE action='record_trash' AND record_id=?", wid)
assert len(trash_entries) == 1 and trash_entries[0]["record_label"] == "Sprocket"
print("OK  trashing a record hides it from the list, search and direct view; audited")

# --- a link field's target list, and the Part's own detail page, drop the trashed record ---
new_form = c.get(f"/records/category/{pcat}/new").get_data(as_text=True)
assert "Sprocket" not in new_form
part_html = c.get(f"/records/{pid}").get_data(as_text=True)
assert "Sprocket" not in part_html
print("OK  a trashed record disappears from link-field choices and resolved links")

# --- 4. the trash page lists it, with Restore / Delete forever ---
trash_html = c.get("/records/trash").get_data(as_text=True)
assert "Sprocket" in trash_html and "Widgets" in trash_html
assert f'action="/records/{wid}/restore"' in trash_html
assert f'action="/records/{wid}/purge"' in trash_html
print("OK  the trash page lists the trashed record with restore/purge actions")

# --- 5. restore brings it back everywhere, and is audited ---
c.post(f"/records/{wid}/restore")
assert raw("SELECT deleted_at FROM records WHERE id=?", wid)[0]["deleted_at"] is None
assert "Sprocket" in c.get(f"/records/category/{wcat}").get_data(as_text=True)
assert "match" in c.get("/search", query_string={"q": "spins"}).get_data(as_text=True).lower()
assert "Gear" in c.get(f"/records/{wid}").get_data(as_text=True)  # back-reference restored too
assert len(raw("SELECT * FROM audit_log WHERE action='record_restore' AND record_id=?", wid)) == 1
print("OK  restoring a record un-hides it everywhere (list, search, back-references); audited")

# --- 6. purge is permanent, and only reachable for an already-trashed record ---
assert c.post(f"/records/{wid}/purge").status_code == 404  # not trashed yet
c.post(f"/records/{wid}/delete")
c.post(f"/records/{wid}/purge")
assert not raw("SELECT 1 FROM records WHERE id=?", wid)
purge_entries = raw("SELECT * FROM audit_log WHERE action='record_purge' AND record_id=?", wid)
assert len(purge_entries) == 1 and purge_entries[0]["record_label"] == "Sprocket"
print("OK  purge only works on a trashed record, is permanent, and is audited")

# --- 7. clone duplicates a record's data into a new one, independently editable ---
r = c.post(f"/records/category/{wcat}/new", data={"name": "Widget A", "notes": "original"})
aid = raw("SELECT id FROM records WHERE category_id=? AND data LIKE '%Widget A%'", wcat)[0]["id"]
r = c.post(f"/records/{aid}/clone", follow_redirects=True)
assert b"cloned" in r.data.lower()
clone_id = raw(
    "SELECT id FROM records WHERE category_id=? AND id!=? AND data LIKE '%Widget A%'", wcat, aid
)[0]["id"]
assert data_of(clone_id)["notes"] == "original"
c.post(f"/records/{aid}/edit", data={"name": "Widget A", "notes": "changed on the original"})
assert data_of(clone_id)["notes"] == "original"  # editing the original never touches the clone
clone_entries = raw("SELECT * FROM audit_log WHERE action='record_clone' AND record_id=?", clone_id)
assert len(clone_entries) == 1 and str(aid) in (clone_entries[0]["detail"] or "")
print("OK  cloning a record copies its data into an independent new record; audited")

# --- 8. clone duplicates an attached file into its own `files` row ---
c.post(f"/categories/{wcat}/fields/add", data={"label": "Attachment", "field_type": "file"})
c.post(f"/records/{aid}/edit",
       data={"name": "Widget A", "notes": "changed on the original",
             "attachment": (io.BytesIO(b"hello"), "note.txt")},
       content_type="multipart/form-data")
orig_file_id = data_of(aid)["attachment"]
r = c.post(f"/records/{aid}/clone", follow_redirects=True)
clone2_id = raw(
    "SELECT id FROM records WHERE category_id=? AND id NOT IN (?, ?) AND data LIKE '%Widget A%'",
    wcat, aid, clone_id,
)[0]["id"]
clone2_file_id = data_of(clone2_id)["attachment"]
assert clone2_file_id != orig_file_id
assert raw("SELECT record_id FROM files WHERE id=?", clone2_file_id)[0]["record_id"] == clone2_id
c.post(f"/records/{aid}/delete")
c.post(f"/records/{aid}/purge")
assert raw("SELECT 1 FROM files WHERE id=?", clone2_file_id)  # the clone's own file survives
print("OK  cloning a record with a file field duplicates the file row, not just its id")

# --- 9. category create/delete are audited (the "did someone delete this?" case) ---
r = c.post("/categories/new", data={"name": "Temp Category"})
tcat = int(r.headers["Location"].rstrip("/").split("/")[-1])
assert len(raw("SELECT * FROM audit_log WHERE action='category_create' AND category_id=?", tcat)) == 1
c.post(f"/categories/{tcat}/fields/add", data={"label": "X", "field_type": "text"})
c.post(f"/records/category/{tcat}/new", data={"x": "one"})
c.post(f"/categories/{tcat}/delete")
del_entries = raw("SELECT * FROM audit_log WHERE action='category_delete' AND category_id=?", tcat)
assert len(del_entries) == 1 and "1 record" in del_entries[0]["detail"]
print("OK  category create/delete are audited, including how many records went with it")

# --- 10. the audit log page (admin) renders recent entries with friendly labels ---
log_html = c.get("/settings/audit-log").get_data(as_text=True)
assert "Moved to trash" in log_html and "Cloned" in log_html and "Category deleted" in log_html
print("OK  the admin audit-log page renders friendly action labels")

# --- 11. global quick-add: every category appears in the header dropdown, for any user ---
dash_html = c.get("/").get_data(as_text=True)
assert "quickadd" in dash_html and "Widgets" in dash_html and "Parts" in dash_html
assert f'/records/category/{wcat}/new' in dash_html
print("OK  the global quick-add dropdown lists every category, from any page")

# --- 12. schema migration: an existing v3 database gains deleted_at + audit_log ---
v3_path = os.path.join(tempfile.mkdtemp(), "v3.sqlite3")
conn = sqlite3.connect(v3_path)
conn.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', created_at TEXT NOT NULL);
    CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        icon TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
    CREATE TABLE fields (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
        label TEXT NOT NULL, field_key TEXT NOT NULL, field_type TEXT NOT NULL,
        options TEXT DEFAULT '[]', required INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0);
    CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
        data TEXT NOT NULL DEFAULT '{}', created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
        field_key TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, data BLOB NOT NULL, uploaded_by INTEGER, uploaded_at TEXT NOT NULL);
    CREATE TABLE alert_dismissals (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
        field_key TEXT NOT NULL, dismissed_value TEXT NOT NULL, dismissed_tier TEXT NOT NULL,
        dismissed_by INTEGER, dismissed_at TEXT NOT NULL);
    CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, category_id UNINDEXED,
        category_name, content, tokenize='porter');
    INSERT INTO meta(key, value) VALUES ('schema_version', '3');
    INSERT INTO users(username, password_hash, role, created_at)
        VALUES ('legacy', 'x', 'admin', '2020-01-01');
    INSERT INTO categories(name, icon, sort_order, created_at) VALUES ('Old Cat', '', 0, '2020-01-01');
    INSERT INTO records(category_id, data, created_at, updated_at)
        VALUES (1, '{}', '2020-01-01', '2020-01-01');
""")
conn.commit()
conn.close()

create_app({"DATABASE": v3_path, "TESTING": True, "SECRET_KEY": "t17"})
conn = sqlite3.connect(v3_path)
conn.row_factory = sqlite3.Row
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "audit_log" in tables
cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}
assert "deleted_at" in cols
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
assert ver == "5"
assert conn.execute("SELECT data FROM records WHERE id=1").fetchone()["data"] == "{}"
print("OK  an existing v3 database is upgraded in place (deleted_at + audit_log added, data kept)")

print("\nv8 trash/audit/quick-add/clone smoke test: ALL PASSED")
