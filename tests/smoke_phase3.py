"""Phase 3 smoke test: dynamic record forms, CRUD, encryption + reveal."""
import os, sys, json, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app
from myvault import crypto

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "longenough1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})

SECRET = "s3cr3t P@ss!"
SSHKEY = "ssh-rsa AAAAB3Nz-not-real-key user@host"


def raw(sql, *a):
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    return conn.execute(sql, a).fetchall()


def new_category(name):
    r = c.post("/categories/new", data={"name": name})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False, options=""):
    d = {"label": label, "field_type": ftype}
    if required: d["required"] = "1"
    if options: d["options"] = options
    c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


commands = new_category("Commands")
add_field(commands, "Title", "text", required=True)
add_field(commands, "Command", "code")
add_field(commands, "Description", "textarea")

unpw = new_category("UnPw")
add_field(unpw, "Project", "text")
add_field(unpw, "Environment", "dropdown", options="Local\nLive")
add_field(unpw, "URL", "url")
add_field(unpw, "Username", "text")
add_field(unpw, "Password", "password", required=True)
add_field(unpw, "SSH Key", "password")
add_field(unpw, "Email", "email")

misc = new_category("Misc")
add_field(misc, "Tags", "multiselect", options="red\ngreen\nblue")
add_field(misc, "Active", "checkbox")
add_field(misc, "Count", "number")
add_field(misc, "When", "date")

# --- create a Commands record ---
r = c.post(f"/records/category/{commands}/new", data={
    "title": "Restart nginx", "command": "sudo systemctl restart nginx",
    "description": "prod web tier"}, follow_redirects=True)
assert r.status_code == 200 and b"Restart nginx" in r.data
print("OK  create record (text/code/textarea) shows in list")

# --- required validation ---
r = c.post(f"/records/category/{commands}/new", data={"command": "x"})
assert b"is required" in r.data
assert len(raw("SELECT id FROM records WHERE category_id=?", commands)) == 1
print("OK  missing required field blocks create")

# --- create a UnPw record with two encrypted fields ---
r = c.post(f"/records/category/{unpw}/new", data={
    "project": "Acme", "environment": "Live", "url": "https://acme.test",
    "username": "root", "password": SECRET, "ssh_key": SSHKEY,
    "email": "a@acme.test"}, follow_redirects=True)
assert r.status_code == 200
rid = raw("SELECT id FROM records WHERE category_id=?", unpw)[0]["id"]

# --- ciphertext at rest ---
data = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])
assert data["password"] != SECRET and data["ssh_key"] != SSHKEY
assert data["password"].startswith("gAAAAA") and data["ssh_key"].startswith("gAAAAA")
assert data["environment"] == "Live" and data["url"] == "https://acme.test"
blob = open(db_path, "rb").read()
assert SECRET.encode() not in blob and SSHKEY.encode() not in blob
print("OK  password + ssh_key stored as Fernet tokens; plaintext absent from DB file")

# --- list & detail never leak plaintext ---
r = c.get(f"/records/category/{unpw}")
assert SECRET.encode() not in r.data and SSHKEY.encode() not in r.data
assert b'data-reveal' in r.data and "••••••••".encode() in r.data
r = c.get(f"/records/{rid}")
assert SECRET.encode() not in r.data
assert f'action="/records/{rid}/delete"'.encode() in r.data
print("OK  list + detail render masked, no plaintext; detail page has a Delete control")

# --- reveal endpoint returns plaintext (vault unlocked) ---
r = c.post(f"/records/{rid}/reveal", data={"field_key": "password"})
assert r.status_code == 200 and r.get_json()["value"] == SECRET
r = c.post(f"/records/{rid}/reveal", data={"field_key": "ssh_key"})
assert r.get_json()["value"] == SSHKEY
print("OK  reveal decrypts each encrypted field on demand")

# --- reveal refuses non-encrypted field ---
r = c.post(f"/records/{rid}/reveal", data={"field_key": "username"})
assert r.status_code == 404
print("OK  reveal refuses non-encrypted field")

# --- reveal blocked while locked ---
c.get("/lock")
r = c.post(f"/records/{rid}/reveal", data={"field_key": "password"})
assert r.status_code == 409 and "locked" in r.get_json()["error"].lower()
# editing a category with encrypted fields redirects to unlock while locked
r = c.get(f"/records/{rid}/edit")
assert r.status_code == 302 and "/unlock" in r.headers["Location"]
c.post("/unlock", data={"master_password": "masterpw123"})
print("OK  locked vault: reveal 409, edit form redirects to /unlock")

# --- edit: blank password keeps existing ciphertext ---
before = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])["password"]
c.post(f"/records/{rid}/edit", data={
    "project": "Acme", "environment": "Local", "url": "https://acme.test",
    "username": "root", "password": "", "ssh_key": "", "email": "a@acme.test"})
after = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])
assert after["password"] == before, "blank password must keep the stored value"
assert after["environment"] == "Local"
assert c.post(f"/records/{rid}/reveal", data={"field_key": "password"}).get_json()["value"] == SECRET
print("OK  edit with blank password preserves encrypted value")

# --- edit: new password re-encrypts ---
c.post(f"/records/{rid}/edit", data={
    "project": "Acme", "environment": "Local", "url": "https://acme.test",
    "username": "root", "password": "brand-new-pw", "ssh_key": "", "email": "a@acme.test"})
after2 = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])
assert after2["password"] != before
assert c.post(f"/records/{rid}/reveal", data={"field_key": "password"}).get_json()["value"] == "brand-new-pw"
print("OK  edit with new password re-encrypts")

# --- misc types round-trip ---
r = c.post(f"/records/category/{misc}/new", data={
    "tags": ["red", "blue", "bogus"], "active": "1", "count": "42", "when": "2026-09-10"},
    follow_redirects=True)
mrec = json.loads(raw("SELECT data FROM records WHERE category_id=?", misc)[0]["data"])
assert mrec["tags"] == ["red", "blue"] and mrec["active"] is True
assert mrec["count"] == "42" and mrec["when"] == "2026-09-10"
print("OK  multiselect (filtered), checkbox, number, date round-trip")

# --- number validation ---
r = c.post(f"/records/category/{misc}/new", data={"count": "abc"})
assert b"must be a number" in r.data
print("OK  number field rejects non-numeric")

# --- FTS kept in sync, no secrets indexed ---
fts = raw("SELECT content FROM records_fts")
assert any("Restart nginx" in row["content"] for row in fts)
assert all(SECRET not in row["content"] and "brand-new-pw" not in row["content"] for row in fts)
hit = raw("SELECT record_id FROM records_fts WHERE records_fts MATCH 'nginx*'")
assert len(hit) == 1
print("OK  FTS synced on write; encrypted values not indexed; MATCH works")

# --- delete record clears FTS row ---
c.post(f"/records/{rid}/delete")
assert len(raw("SELECT id FROM records WHERE id=?", rid)) == 0
assert len(raw("SELECT record_id FROM records_fts WHERE record_id=?", rid)) == 0
print("OK  delete removes record + its FTS row")

print("\nPhase 3 smoke test: ALL PASSED")
