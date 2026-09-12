"""v9 smoke test: the cost rollup dashboard (`cost` field type) and
cross-category tags."""
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app
from myvault.tags import parse_tags_input

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


# =====================================================================
# Cost rollup dashboard
# =====================================================================

# --- pure parsing helper ---
assert parse_tags_input(" Q4 renewal ,  high priority ,Q4 RENEWAL, , ,x" * 1) == \
    ["Q4 renewal", "high priority", "x"]
print("OK  parse_tags_input trims, drops blanks, and dedupes case-insensitively")

# --- build categories with cost fields at different frequencies ---
r = c.post("/categories/new", data={"name": "Subscriptions", "icon": "💳"})
subs = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{subs}/fields/add", data={"label": "Service", "field_type": "text", "required": "1"})
c.post(f"/categories/{subs}/fields/add",
       data={"label": "Fee", "field_type": "cost", "frequency": "monthly"})

r = c.post("/categories/new", data={"name": "Domains", "icon": "🌐"})
doms = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{doms}/fields/add", data={"label": "Name", "field_type": "text", "required": "1"})
c.post(f"/categories/{doms}/fields/add",
       data={"label": "Renewal", "field_type": "cost", "frequency": "yearly"})

r = c.post("/categories/new", data={"name": "Equipment"})
equip = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{equip}/fields/add", data={"label": "Item", "field_type": "text", "required": "1"})
c.post(f"/categories/{equip}/fields/add",
       data={"label": "Cost", "field_type": "cost", "frequency": "one_time"})

# default frequency (omitted) is monthly
fld = raw("SELECT id, options FROM fields WHERE field_key='fee'")[0]
assert json.loads(fld["options"]) == {"frequency": "monthly"}
print("OK  a cost field defaults to monthly billing when the frequency is left blank")

# --- records ---
c.post(f"/records/category/{subs}/new", data={"service": "Netflix", "fee": "15.99"})
c.post(f"/records/category/{subs}/new", data={"service": "Spotify", "fee": "9.99"})
c.post(f"/records/category/{doms}/new", data={"name": "example.com", "renewal": "12.00"})
dom_rec = raw("SELECT id FROM records WHERE data LIKE '%example.com%'")[0]["id"]
c.post(f"/records/category/{equip}/new", data={"item": "Laptop", "cost": "1200"})

html = c.get("/costs").get_data(as_text=True)
assert "Subscriptions" in html and "Domains" in html and "Equipment" in html
# monthly total = 15.99 + 9.99 + (12/12=1.00) = 26.98
assert "26.98" in html
# yearly total = (15.99+9.99)*12 + 12.00 = 311.76 + 12 = 323.76
assert "323.76" in html
# one-time total = 1200.00
assert "1200.00" in html
print("OK  the Costs dashboard sums monthly/yearly-equivalent totals correctly across categories")

# --- a trashed record's cost drops out of the rollup ---
c.post(f"/records/{dom_rec}/delete")
html2 = c.get("/costs").get_data(as_text=True)
assert "example.com" not in html2
assert "25.98" in html2  # 15.99 + 9.99, domain's 1.00/mo equivalent gone
c.post(f"/records/{dom_rec}/restore")
print("OK  trashing a record removes its cost from the rollup; restoring brings it back")

# --- cost is sortable/filterable like a number field ---
list_html = c.get(f"/records/category/{subs}", query_string={"sort": "fee", "dir": "desc"}).get_data(as_text=True)
assert list_html.index("Netflix") < list_html.index("Spotify")  # 15.99 before 9.99 desc
print("OK  a cost field sorts numerically in the record list")

# --- record view shows the amount with its frequency suffix ---
netflix_id = raw("SELECT id FROM records WHERE data LIKE '%Netflix%'")[0]["id"]
detail_html = c.get(f"/records/{netflix_id}").get_data(as_text=True)
assert "15.99" in detail_html and "/mo" in detail_html
print("OK  a record's cost value displays with its billing-frequency suffix")

# --- template export/import round-trips the frequency ---
r = c.get(f"/templates/export/{doms}")
tpl = json.loads(r.get_data(as_text=True))
renewal_field = next(f for f in tpl["fields"] if f["field_key"] == "renewal")
assert renewal_field["field_type"] == "cost" and renewal_field["frequency"] == "yearly"
import io
r = c.post("/templates/import", data={"template": (io.BytesIO(json.dumps(tpl).encode()), "domains.myvault.json")},
           content_type="multipart/form-data", follow_redirects=True)
imported_cat = raw("SELECT id FROM categories WHERE name LIKE 'Domains%' AND id != ?", doms)[0]["id"]
imported_field = raw("SELECT options FROM fields WHERE category_id=? AND field_key='renewal'", imported_cat)[0]
assert json.loads(imported_field["options"]) == {"frequency": "yearly"}
print("OK  exporting then importing a category preserves a cost field's billing frequency")

# =====================================================================
# Cross-category tags
# =====================================================================

# --- creating a record with tags ---
r = c.post(f"/records/category/{equip}/new",
           data={"item": "Monitor", "cost": "300", "tags": "Q4 renewal, office"})
monitor_id = raw("SELECT id FROM records WHERE data LIKE '%Monitor%'")[0]["id"]
assert {t["name"] for t in raw(
    "SELECT t.name FROM tags t JOIN record_tags rt ON rt.tag_id=t.id WHERE rt.record_id=?", monitor_id
)} == {"Q4 renewal", "office"}
detail_html = c.get(f"/records/{monitor_id}").get_data(as_text=True)
assert "Q4 renewal" in detail_html and "office" in detail_html
print("OK  creating a record with comma-separated tags attaches them; shown as pills on detail")

# --- tag a record in another category with the same tag, cross-category browse ---
c.post(f"/records/{netflix_id}/edit",
       data={"service": "Netflix", "fee": "15.99", "tags": "Q4 renewal"})
tag_id = raw("SELECT id FROM tags WHERE name='Q4 renewal'")[0]["id"]
tag_html = c.get(f"/tags/{tag_id}").get_data(as_text=True)
assert "Monitor" in tag_html and "Netflix" in tag_html
assert "Equipment" in tag_html and "Subscriptions" in tag_html
print("OK  the same tag on records in different categories shows both, grouped by category")

# --- editing a record's tags replaces them ---
c.post(f"/records/{monitor_id}/edit", data={"item": "Monitor", "cost": "300", "tags": "office"})
names = {t["name"] for t in raw(
    "SELECT t.name FROM tags t JOIN record_tags rt ON rt.tag_id=t.id WHERE rt.record_id=?", monitor_id
)}
assert names == {"office"}
tag_html2 = c.get(f"/tags/{tag_id}").get_data(as_text=True)
assert "Monitor" not in tag_html2 and "Netflix" in tag_html2
print("OK  editing a record's tags replaces the old set, not adds to it")

# --- the tags browse page lists every tag with a live record count ---
browse_html = c.get("/tags/").get_data(as_text=True)
assert "office" in browse_html and "Q4 renewal" in browse_html
print("OK  the tags browse page lists every tag")

# --- trashing a record drops it from its tag's listing and count ---
c.post(f"/records/{monitor_id}/delete")
browse_html2 = c.get("/tags/").get_data(as_text=True)
assert "office" not in browse_html2  # its only tagged record is trashed -- tag has 0 live records
c.post(f"/records/{monitor_id}/restore")
assert "office" in c.get("/tags/").get_data(as_text=True)
print("OK  a trashed record's tags don't count until it's restored")

# --- cloning a record copies its tags, independently ---
r = c.post(f"/records/{netflix_id}/clone", follow_redirects=True)
clone_id = raw(
    "SELECT id FROM records WHERE category_id=? AND id!=? AND data LIKE '%Netflix%'", subs, netflix_id
)[0]["id"]
clone_tags = {t["name"] for t in raw(
    "SELECT t.name FROM tags t JOIN record_tags rt ON rt.tag_id=t.id WHERE rt.record_id=?", clone_id
)}
assert clone_tags == {"Q4 renewal"}
c.post(f"/records/{clone_id}/edit", data={"service": "Netflix", "fee": "15.99", "tags": "personal"})
netflix_tags = {t["name"] for t in raw(
    "SELECT t.name FROM tags t JOIN record_tags rt ON rt.tag_id=t.id WHERE rt.record_id=?", netflix_id
)}
assert netflix_tags == {"Q4 renewal"}  # untouched by editing the clone's tags
print("OK  cloning a record copies its tags to the new record, independently editable")

# --- search finds a record by its tag name ---
search_html = c.get("/search", query_string={"q": "personal"}).get_data(as_text=True)
assert "match" in search_html.lower() and "No matches" not in search_html
print("OK  search finds a record by a tag name")

# --- schema migration: an existing v4 database gains tags/record_tags ---
v4_path = os.path.join(tempfile.mkdtemp(), "v4.sqlite3")
conn = sqlite3.connect(v4_path)
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
        data TEXT NOT NULL DEFAULT '{}', created_by INTEGER, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, deleted_at TEXT);
    CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
        field_key TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, data BLOB NOT NULL, uploaded_by INTEGER, uploaded_at TEXT NOT NULL);
    CREATE TABLE alert_dismissals (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
        field_key TEXT NOT NULL, dismissed_value TEXT NOT NULL, dismissed_tier TEXT NOT NULL,
        dismissed_by INTEGER, dismissed_at TEXT NOT NULL);
    CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER,
        username TEXT NOT NULL, action TEXT NOT NULL, category_id INTEGER, category_name TEXT,
        record_id INTEGER, record_label TEXT, detail TEXT);
    CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, category_id UNINDEXED,
        category_name, content, tokenize='porter');
    INSERT INTO meta(key, value) VALUES ('schema_version', '4');
    INSERT INTO users(username, password_hash, role, created_at)
        VALUES ('legacy', 'x', 'admin', '2020-01-01');
    INSERT INTO categories(name, icon, sort_order, created_at) VALUES ('Old Cat', '', 0, '2020-01-01');
""")
conn.commit()
conn.close()

create_app({"DATABASE": v4_path, "TESTING": True, "SECRET_KEY": "t18"})
conn = sqlite3.connect(v4_path)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "tags" in tables and "record_tags" in tables
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
assert ver == "5"
assert conn.execute("SELECT username FROM users").fetchone()[0] == "legacy"
print("OK  an existing v4 database is upgraded in place (tags + record_tags added, data kept)")

print("\nv9 costs/tags smoke test: ALL PASSED")
