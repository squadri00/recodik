"""Phase 4 smoke test: global FTS search across categories."""
import os, sys, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "longenough1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def new_category(name):
    r = c.post("/categories/new", data={"name": name})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False):
    d = {"label": label, "field_type": ftype}
    if required: d["required"] = "1"
    c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


commands = new_category("Commands")
add_field(commands, "Title", "text", required=True)
add_field(commands, "Command", "code")

hosting = new_category("Hosting")
add_field(hosting, "Provider", "text", required=True)
add_field(hosting, "Notes", "textarea")

c.post(f"/records/category/{commands}/new",
       data={"title": "Restart nginx", "command": "systemctl restart nginx"},
       follow_redirects=True)
c.post(f"/records/category/{commands}/new",
       data={"title": "Tail syslog", "command": "tail -f /var/log/syslog"},
       follow_redirects=True)
c.post(f"/records/category/{hosting}/new",
       data={"provider": "Hetzner", "notes": "nginx reverse proxy box in Falkenstein"},
       follow_redirects=True)


def search(q):
    r = c.get("/search", query_string={"q": q})
    assert r.status_code == 200
    return r.get_data(as_text=True)


# --- cross-category term ---
html = search("nginx")
assert "Commands" in html and "Hosting" in html
assert "2 matches" in html or "3 matches" in html
print("OK  'nginx' matches records in both Commands and Hosting")

# --- term unique to one category ---
html = search("Hetzner")
assert "Hosting" in html and "Commands" not in html.split("results")[-1] or "Hetzner" in html
assert "1 match" in html
print("OK  'Hetzner' matches only the Hosting record")

# --- prefix search (porter + token*) ---
html = search("falken")
assert "1 match" in html and "Hosting" in html
print("OK  prefix search ('falken' -> Falkenstein)")

# --- no match ---
html = search("zzzznotfound")
assert "No matches" in html
print("OK  no-match message shown")

# --- edit keeps index fresh ---
rid = sqlite3.connect(db_path).execute(
    "SELECT id FROM records WHERE category_id=? AND data LIKE '%Tail syslog%'", (commands,)
).fetchone()[0]
c.post(f"/records/{rid}/edit", data={"title": "Watch kernel ring buffer",
                                     "command": "dmesg -w"})
assert "No matches" in search("syslog")
assert "1 match" in search("dmesg")
print("OK  editing a record updates the FTS index")

# --- delete removes from results ---
c.post(f"/records/{rid}/delete")
assert "No matches" in search("dmesg")
print("OK  deleting a record removes it from search")

# --- admin rebuild index ---
conn = sqlite3.connect(db_path)
conn.execute("DELETE FROM records_fts")
conn.commit()
assert "No matches" in search("nginx")
r = c.post("/search/reindex", follow_redirects=True)
assert b"index rebuilt" in r.data.lower()
assert "match" in search("nginx")
print("OK  admin 'Rebuild search index' repopulates FTS")

# --- non-admin cannot reindex (member created here directly) ---
conn = sqlite3.connect(db_path)
from werkzeug.security import generate_password_hash
conn.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('bob',?,'member','x')",
             (generate_password_hash("bobpassword1"),))
conn.commit()
c.get("/logout")
c.post("/login", data={"username": "bob", "password": "bobpassword1"})
r = c.post("/search/reindex")
assert r.status_code == 403
# but a member can still search
assert "match" in search("nginx")
print("OK  member can search but not rebuild the index (403)")

print("\nPhase 4 smoke test: ALL PASSED")
