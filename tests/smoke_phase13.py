"""v4 smoke test: expiry/reminder alerts (the `date_alert` field type)."""
import os, sys, io, json, tempfile, sqlite3
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app, alerts

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def raw(sql, *a):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, a).fetchall()


def iso(days_from_today):
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def get_active():
    with app.app_context():
        return alerts.active_alerts()


def do_dismiss(record_id, field_key, value, tier, user_id=None):
    with app.app_context():
        alerts.dismiss(record_id, field_key, value, tier, user_id)


r = c.post("/categories/new", data={"name": "Domains", "icon": "🌐"})
cid = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{cid}/fields/add", data={"label": "Domain", "field_type": "text", "required": "1"})

# --- field builder validation ---
r = c.post(f"/categories/{cid}/fields/add",
           data={"label": "Bad", "field_type": "date_alert", "alert_days_before": "not-a-number"},
           follow_redirects=True)
assert b"must be a whole number" in r.data
assert not raw("SELECT 1 FROM fields WHERE field_key='bad'")
print("OK  a non-numeric alert window is rejected")

# --- default alert window when left blank ---
c.post(f"/categories/{cid}/fields/add", data={"label": "Registered", "field_type": "date_alert"})
fld = raw("SELECT id, options FROM fields WHERE field_key='registered'")[0]
assert json.loads(fld["options"]) == {"alert_days_before": 30}
c.post(f"/categories/{cid}/fields/{fld['id']}/delete")
print("OK  omitting the alert window defaults to 30 days")

# --- the real field: 15-day window ---
c.post(f"/categories/{cid}/fields/add",
       data={"label": "Expires", "field_type": "date_alert", "alert_days_before": "15"})
fid = raw("SELECT id FROM fields WHERE field_key='expires'")[0]["id"]
assert json.loads(raw("SELECT options FROM fields WHERE id=?", fid)[0]["options"]) == {"alert_days_before": 15}
print("OK  a configured alert window is stored as {\"alert_days_before\": 15}")

# --- three records: far future / within window / overdue ---
c.post(f"/records/category/{cid}/new", data={"domain": "far-future.example", "expires": iso(400)})
c.post(f"/records/category/{cid}/new", data={"domain": "soon.example", "expires": iso(10)})
c.post(f"/records/category/{cid}/new", data={"domain": "lapsed.example", "expires": iso(-3)})
soon_id = raw("SELECT id FROM records WHERE data LIKE '%soon.example%'")[0]["id"]
lapsed_id = raw("SELECT id FROM records WHERE data LIKE '%lapsed.example%'")[0]["id"]

active = get_active()
assert [a["record_id"] for a in active] == [lapsed_id, soon_id], active  # overdue first
assert active[0]["tier"] == "overdue" and active[0]["days_left"] == -3
assert active[1]["tier"] == "upcoming" and active[1]["days_left"] == 10
assert active[0]["label"] == "lapsed.example" and active[1]["label"] == "soon.example"
print("OK  active_alerts(): far-future excluded, upcoming + overdue included, soonest/most-overdue first")

# --- the header shows the badge + both entries ---
html = c.get("/").get_data(as_text=True)
assert "⚠ 2" in html
assert "lapsed.example" in html and "soon.example" in html and "far-future.example" not in html
assert "overdue by 3 day" in html and "in 10 day" in html
print("OK  the dashboard header renders the badge and both active alerts")

# --- dismiss the upcoming one ---
r = c.post(f"/records/{soon_id}/dismiss-alert",
           data={"field_key": "expires", "value": iso(10), "tier": "upcoming"},
           follow_redirects=True)
assert b"Alert dismissed" in r.data
active = get_active()
assert [a["record_id"] for a in active] == [lapsed_id]
print("OK  dismissing an alert removes it from active_alerts()")

# --- editing the record's date brings the dismissal's target value out of date -> reappears ---
c.post(f"/records/{soon_id}/edit", data={"domain": "soon.example", "expires": iso(5)})
active = get_active()
assert soon_id in [a["record_id"] for a in active]
print("OK  changing the dismissed field's value makes the alert reappear")

# --- escalation: dismissed while 'upcoming', now computes as 'overdue' (same value) ---
stale_value = iso(-1)  # a date that is now in the past
c.post(f"/records/{soon_id}/edit", data={"domain": "soon.example", "expires": stale_value})
do_dismiss(soon_id, "expires", stale_value, "upcoming")  # simulate a stale dismissal
active = get_active()
matched = [a for a in active if a["record_id"] == soon_id]
assert matched and matched[0]["tier"] == "overdue"
print("OK  a dismissal recorded at 'upcoming' does not suppress the same value once it's overdue")

# --- same tier, not escalated: stays dismissed ---
do_dismiss(soon_id, "expires", stale_value, "overdue")
active = get_active()
assert soon_id not in [a["record_id"] for a in active]
print("OK  dismissing at the current (matching) tier keeps it hidden")

# --- search still indexes the plain date value ---
r = c.get("/search", query_string={"q": "lapsed.example"})
assert "1 match" in r.get_data(as_text=True)
print("OK  date_alert values are indexed like any other plain field")

# --- template export/import carries the alert window ---
r = c.get(f"/templates/export/{cid}")
tpl = json.loads(r.get_data(as_text=True))
expires_field = next(f for f in tpl["fields"] if f["field_key"] == "expires")
assert expires_field["alert_days_before"] == 15
blob = r.get_data()

app2 = create_app({"DATABASE": os.path.join(tempfile.mkdtemp(), "t2.sqlite3"),
                   "TESTING": True, "SECRET_KEY": "t2"})
c2 = app2.test_client()
c2.post("/setup", data={"username": "a", "password": "adminpassword1",
                        "master_password": "m2masterpw", "master_password_confirm": "m2masterpw"})
c2.post("/templates/import", data={"template": (io.BytesIO(blob), "domains.myvault.json")},
        content_type="multipart/form-data", follow_redirects=True)
db2 = app2.config["DATABASE"]
conn2 = sqlite3.connect(db2)
opts = conn2.execute("SELECT options FROM fields WHERE field_key='expires'").fetchone()[0]
assert json.loads(opts) == {"alert_days_before": 15}
print("OK  template export/import carries the alert window across installs")

# --- migration: an existing v2 database gains alert_dismissals ---
v2_path = os.path.join(tempfile.mkdtemp(), "v2.sqlite3")
conn = sqlite3.connect(v2_path)
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
    CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, category_id UNINDEXED,
        category_name, content, tokenize='porter');
    INSERT INTO meta(key, value) VALUES ('schema_version', '2');
    INSERT INTO users(username, password_hash, role, created_at)
        VALUES ('legacy', 'x', 'admin', '2020-01-01');
""")
conn.commit()
conn.close()

create_app({"DATABASE": v2_path, "TESTING": True, "SECRET_KEY": "t3"})
conn = sqlite3.connect(v2_path)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "alert_dismissals" in tables
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
assert ver == "5"
assert conn.execute("SELECT username FROM users").fetchone()[0] == "legacy"
print("OK  an existing v2 database is upgraded in place (alert_dismissals added, data kept)")

print("\nv4 expiry-alert smoke test: ALL PASSED")
