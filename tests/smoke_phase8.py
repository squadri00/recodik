"""Phase 8 smoke test: validation hardening + a full no-plaintext-leak audit."""
import os, sys, io, json, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})

SECRET1 = "Hunter2-the-password"
SECRET2 = "ssh-ed25519 AAAAC3-super-secret-key"


def new_category(name, icon=""):
    r = c.post("/categories/new", data={"name": name, "icon": icon})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False, options=""):
    d = {"label": label, "field_type": ftype}
    if required: d["required"] = "1"
    if options: d["options"] = options
    return c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


unpw = new_category("UnPw", "🔑")
add_field(unpw, "Project", "text", required=True)
add_field(unpw, "Login URL", "url")
add_field(unpw, "When", "date")
add_field(unpw, "Password", "password", required=True)
add_field(unpw, "SSH Key", "password")

# --- duplicate field label rejected (add) ---
r = add_field(unpw, "project", "text")
assert b"already has a field called" in r.data
print("OK  duplicate field label rejected on add (case-insensitive)")

# --- duplicate field label rejected (edit) ---
fid = sqlite3.connect(db_path).execute(
    "SELECT id FROM fields WHERE category_id=? AND field_key='login_url'", (unpw,)).fetchone()[0]
r = c.post(f"/categories/{unpw}/fields/{fid}/update",
           data={"label": "Project", "field_type": "url"}, follow_redirects=True)
assert b"already has a field called" in r.data
print("OK  duplicate field label rejected on edit")

# --- date validation ---
r = c.post(f"/records/category/{unpw}/new", data={
    "project": "X", "login_url": "https://x.test", "when": "not-a-date",
    "password": "p", "ssh_key": ""}, follow_redirects=True)
assert b"must be a date" in r.data
print("OK  invalid date rejected")

# --- create a good record ---
c.post(f"/records/category/{unpw}/new", data={
    "project": "Acme", "login_url": "https://acme.test", "when": "2026-09-10",
    "password": SECRET1, "ssh_key": SECRET2}, follow_redirects=True)
rid = sqlite3.connect(db_path).execute("SELECT id FROM records").fetchone()[0]
cipher = json.loads(sqlite3.connect(db_path).execute(
    "SELECT data FROM records WHERE id=?", (rid,)).fetchone()[0])
tok_pw, tok_ssh = cipher["password"], cipher["ssh_key"]

# --- exhaustive leak audit: no plaintext AND no ciphertext token in any view ---
def body(path, **kw):
    return c.get(path, **kw).get_data(as_text=True)

views = {
    "dashboard": body("/"),
    "records list": body(f"/records/category/{unpw}"),
    "record detail": body(f"/records/{rid}"),
    "record edit form": body(f"/records/{rid}/edit"),
    "search (project)": body("/search", query_string={"q": "Acme"}),
    "search (secret word)": body("/search", query_string={"q": "Hunter2"}),
    "category editor": body(f"/categories/{unpw}"),
    "template export": body(f"/templates/export/{unpw}"),
    "settings": body("/settings/"),
}
for name, html in views.items():
    assert SECRET1 not in html, f"PLAINTEXT password leaked in {name}"
    assert SECRET2 not in html, f"PLAINTEXT ssh key leaked in {name}"
    assert tok_pw not in html, f"ciphertext token leaked in {name}"
    assert tok_ssh not in html, f"ciphertext token leaked in {name}"
print(f"OK  no plaintext or ciphertext in any of {len(views)} rendered views")

# --- the ONE endpoint that returns plaintext ---
assert c.post(f"/records/{rid}/reveal", data={"field_key": "password"}).get_json()["value"] == SECRET1
assert c.post(f"/records/{rid}/reveal", data={"field_key": "ssh_key"}).get_json()["value"] == SECRET2
print("OK  /reveal is the only path to plaintext (works)")

# --- search never indexes the secret even as a substring ---
assert "No matches" in body("/search", query_string={"q": "Hunter2"})
assert "No matches" in body("/search", query_string={"q": "ed25519"})
print("OK  encrypted values are not in the search index")

# --- error pages ---
r = c.get("/records/999999")
assert r.status_code == 404 and b"Nothing here" in r.data
print("OK  404 renders the styled error page")

# --- empty states present ---
empty_cat = new_category("Empty")
assert "no fields yet" in body(f"/records/category/{empty_cat}").lower()
add_field(empty_cat, "Note", "text")
assert "No records yet" in body(f"/records/category/{empty_cat}")
print("OK  empty states for no-fields and no-records")

# --- search snippet: highlight is <mark>, record content stays escaped ---
xss = new_category("XSS")
add_field(xss, "Note", "text", required=True)
c.post(f"/records/category/{xss}/new",
       data={"note": "<script>alert(1)</script> danger zone"}, follow_redirects=True)
html = body("/search", query_string={"q": "danger"})
assert "<script>alert(1)</script>" not in html, "record content must be escaped on the search page"
assert "&lt;script&gt;" in html
assert "<mark>danger</mark>" in html, "match should be wrapped in <mark>"
print("OK  search highlights with <mark> and escapes record HTML")

print("\nPhase 8 smoke test: ALL PASSED")
