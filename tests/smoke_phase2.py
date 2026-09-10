"""Phase 2 smoke test: category CRUD + field builder."""
import os, sys, tempfile, json, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()

c.post("/setup", data={"username": "admin", "password": "longenough1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def new_category(name, icon=""):
    r = c.post("/categories/new", data={"name": name, "icon": icon})
    assert r.status_code == 302, r.data[:300]
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False, options=""):
    data = {"label": label, "field_type": ftype}
    if required:
        data["required"] = "1"
    if options:
        data["options"] = options
    return c.post(f"/categories/{cid}/fields/add", data=data, follow_redirects=True)


def fields(cid):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM fields WHERE category_id=? ORDER BY sort_order, id", (cid,)
    ).fetchall()


# --- Commands category ---
commands = new_category("Commands", "💻")
add_field(commands, "Title", "text", required=True)
add_field(commands, "Command", "code")
add_field(commands, "Description", "textarea")
f = fields(commands)
assert [x["field_key"] for x in f] == ["title", "command", "description"], [dict(x) for x in f]
assert f[0]["required"] == 1
print("OK  Commands: 3 fields, keys + required correct")

# --- UnPw category (the spec's exact field list) ---
unpw = new_category("UnPw", "🔑")
add_field(unpw, "Project", "text")
r = add_field(unpw, "Environment", "dropdown", options="Local\nLive\nLive\n")  # dupe dropped
add_field(unpw, "URL", "url")
add_field(unpw, "Username", "text")
add_field(unpw, "Password", "password")
add_field(unpw, "SSH Key", "password")
add_field(unpw, "Email", "email")
f = fields(unpw)
keys = [x["field_key"] for x in f]
assert keys == ["project", "environment", "url", "username", "password", "ssh_key", "email"], keys
env = f[1]
assert env["field_type"] == "dropdown" and json.loads(env["options"]) == ["Local", "Live"], dict(env)
print("OK  UnPw: 7 fields incl. ssh_key, dropdown options de-duplicated")

# --- validation: dropdown without options ---
r = add_field(unpw, "Region", "dropdown", options="")
assert b"needs at least one option" in r.data
assert "region" not in [x["field_key"] for x in fields(unpw)]
print("OK  dropdown without options rejected")

# --- validation: bad type ---
r = add_field(unpw, "Bad", "not_a_type")
assert b"valid field type" in r.data
print("OK  invalid field type rejected")

# --- duplicate label rejected (Phase 8 hardening) ---
r = add_field(unpw, "project", "text")
assert b"already has a field called" in r.data
assert [x["field_key"] for x in fields(unpw)].count("project") == 1
print("OK  duplicate field label rejected")

# --- distinct labels that slugify to the same key -> uniquified key ---
add_field(unpw, "Sign in URL", "url")
add_field(unpw, "Sign-in URL", "url")   # different label, same slug 'sign_in_url'
keys_now = [x["field_key"] for x in fields(unpw)]
assert "sign_in_url" in keys_now and "sign_in_url_2" in keys_now, keys_now
print("OK  same-slug distinct labels -> sign_in_url / sign_in_url_2")

# --- reorder: move URL up one (index 2 -> 1) ---
url_field = fields(unpw)[2]
assert url_field["field_key"] == "url"
c.post(f"/categories/{unpw}/fields/{url_field['id']}/move", data={"dir": "up"})
assert [x["field_key"] for x in fields(unpw)][:3] == ["project", "url", "environment"]
c.post(f"/categories/{unpw}/fields/{url_field['id']}/move", data={"dir": "down"})
assert [x["field_key"] for x in fields(unpw)][:3] == ["project", "environment", "url"]
print("OK  field reorder up/down")

# --- edit field: change label, key stays put ---
pw_field = next(x for x in fields(unpw) if x["field_key"] == "password")
c.post(f"/categories/{unpw}/fields/{pw_field['id']}/update",
       data={"label": "Account Password", "field_type": "password"})
pw_field2 = next(x for x in fields(unpw) if x["id"] == pw_field["id"])
assert pw_field2["label"] == "Account Password" and pw_field2["field_key"] == "password"
print("OK  field edit keeps machine key stable")

# --- rename category + reorder categories ---
c.post(f"/categories/{commands}/update", data={"name": "Snippets", "icon": "✂️"})
conn = sqlite3.connect(db_path)
assert conn.execute("SELECT name FROM categories WHERE id=?", (commands,)).fetchone()[0] == "Snippets"
c.post(f"/categories/{unpw}/move", data={"dir": "up"})
order = [row[0] for row in sqlite3.connect(db_path).execute(
    "SELECT name FROM categories ORDER BY sort_order, name")]
assert order == ["UnPw", "Snippets"], order
print("OK  category rename + reorder")

# --- delete field ---
email_field = next(x for x in fields(unpw) if x["field_key"] == "email")
c.post(f"/categories/{unpw}/fields/{email_field['id']}/delete")
assert "email" not in [x["field_key"] for x in fields(unpw)]
print("OK  field delete")

# --- delete category cascades fields ---
c.post(f"/categories/{commands}/delete")
conn = sqlite3.connect(db_path)
assert conn.execute("SELECT COUNT(*) FROM categories WHERE id=?", (commands,)).fetchone()[0] == 0
assert conn.execute("SELECT COUNT(*) FROM fields WHERE category_id=?", (commands,)).fetchone()[0] == 0
print("OK  category delete cascades to fields")

# --- manage page renders ---
r = c.get("/categories/")
assert r.status_code == 200 and b"UnPw" in r.data
print("OK  manage page renders")

# --- anonymous cannot reach the builder ---
c.get("/logout")
r = c.get("/categories/")
assert r.status_code == 302 and "/login" in r.headers["Location"]
print("OK  builder requires auth")

print("\nPhase 2 smoke test: ALL PASSED")
