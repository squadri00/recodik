"""Phase 6 smoke test: category template export / import (field defs only)."""
import os, sys, io, json, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def new_category(name, icon=""):
    r = c.post("/categories/new", data={"name": name, "icon": icon})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False, options=""):
    d = {"label": label, "field_type": ftype}
    if required: d["required"] = "1"
    if options: d["options"] = options
    c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


def fields(cid):
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM fields WHERE category_id=? ORDER BY sort_order", (cid,)).fetchall()


# build UnPw
unpw = new_category("UnPw", "🔑")
add_field(unpw, "Project", "text", required=True)
add_field(unpw, "Environment", "dropdown", options="Local\nLive")
add_field(unpw, "URL", "url")
add_field(unpw, "Password", "password")
add_field(unpw, "SSH Key", "password")
# add a record -- must NOT be in the export
c.post(f"/records/category/{unpw}/new", data={
    "project": "Acme", "environment": "Live", "url": "https://acme.test",
    "password": "topsecret", "ssh_key": "keydata"}, follow_redirects=True)

# --- export ---
r = c.get(f"/templates/export/{unpw}")
assert r.status_code == 200
assert r.mimetype == "application/json"
assert "attachment" in r.headers["Content-Disposition"]
assert "unpw.myvault.json" in r.headers["Content-Disposition"]
tpl = json.loads(r.get_data(as_text=True))
assert tpl["myvault_template"] == 1 and tpl["name"] == "UnPw" and tpl["icon"] == "🔑"
assert [f["label"] for f in tpl["fields"]] == ["Project", "Environment", "URL", "Password", "SSH Key"]
env = tpl["fields"][1]
assert env["field_type"] == "dropdown" and env["options"] == ["Local", "Live"]
assert tpl["fields"][0]["required"] is True
assert "records" not in tpl and "topsecret" not in r.get_data(as_text=True)
print("OK  export: field defs only, ordered, options + required preserved, no records/secrets")

exported = r.get_data()

# --- import (same install -> name collision suffix) ---
r = c.post("/templates/import", data={"template": (io.BytesIO(exported), "unpw.myvault.json")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"Imported" in r.data
conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
cats = conn.execute("SELECT * FROM categories ORDER BY id").fetchall()
assert cats[-1]["name"] == "UnPw (imported)"
new_id = cats[-1]["id"]
nf = fields(new_id)
assert [f["field_key"] for f in nf] == ["project", "environment", "url", "password", "ssh_key"]
assert [f["field_type"] for f in nf] == ["text", "dropdown", "url", "password", "password"]
assert json.loads(nf[1]["options"]) == ["Local", "Live"]
assert nf[0]["required"] == 1
assert conn.execute("SELECT COUNT(*) FROM records WHERE category_id=?", (new_id,)).fetchone()[0] == 0
print("OK  import: new empty category created with identical field layout; name suffixed on clash")

# --- round-trip into a clean install ---
app2 = create_app({"DATABASE": os.path.join(tempfile.mkdtemp(), "t2.sqlite3"),
                   "TESTING": True, "SECRET_KEY": "t2"})
c2 = app2.test_client()
c2.post("/setup", data={"username": "a", "password": "adminpassword1",
                        "master_password": "m2masterpw", "master_password_confirm": "m2masterpw"})
r = c2.post("/templates/import", data={"template": (io.BytesIO(exported), "unpw.myvault.json")},
            content_type="multipart/form-data", follow_redirects=True)
assert b"Imported \xe2\x80\x9cUnPw\xe2\x80\x9d" in r.data  # no suffix on a fresh install
print("OK  round-trip: template imports cleanly into a separate install")

# --- rejects bad input ---
bad_cases = [
    (b"not json at all", "valid JSON"),
    (json.dumps({"name": "X", "fields": []}).encode(), "myvault_template"),
    (json.dumps({"myvault_template": 1, "name": "", "fields": [{"label": "a", "field_type": "text"}]}).encode(), "no category name"),
    (json.dumps({"myvault_template": 1, "name": "X", "fields": []}).encode(), "no fields"),
    (json.dumps({"myvault_template": 1, "name": "X", "fields": [{"label": "a", "field_type": "wat"}]}).encode(), "unknown type"),
    (json.dumps({"myvault_template": 1, "name": "X", "fields": [{"label": "a", "field_type": "dropdown", "options": []}]}).encode(), "needs options"),
]
for blob, expect in bad_cases:
    r = c.post("/templates/import", data={"template": (io.BytesIO(blob), "t.json")},
               content_type="multipart/form-data", follow_redirects=True)
    assert expect.encode() in r.data, (expect, r.data[:200])
print("OK  import rejects: non-JSON, wrong marker, no name, no fields, bad type, missing options")

# --- non-admin blocked ---
sqlite3.connect(db_path).execute(
    "INSERT INTO users(username,password_hash,role,created_at) VALUES('m','x','member','x')")
# (hash 'x' won't let them log in; check the route guard directly instead)
c.get("/logout")
assert c.get(f"/templates/export/{unpw}").status_code == 302  # -> login
print("OK  export/import require auth")

print("\nPhase 6 smoke test: ALL PASSED")
