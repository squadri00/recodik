"""Phase 5 smoke test: multi-user, roles, access control."""
import os, sys, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})


def client():
    return app.test_client()


admin = client()
admin.post("/setup", data={"username": "alice", "password": "alicepassword1",
                           "master_password": "masterpw123", "master_password_confirm": "masterpw123"})

# admin builds a category with fields + one record
r = admin.post("/categories/new", data={"name": "Notes"})
cid = int(r.headers["Location"].rstrip("/").split("/")[-1])
admin.post(f"/categories/{cid}/fields/add", data={"label": "Body", "field_type": "text", "required": "1"},
           follow_redirects=True)

# --- create a member ---
r = admin.post("/settings/users", data={"username": "bob", "password": "bobpassword1", "role": "member"},
               follow_redirects=True)
assert b"Created member" in r.data
print("OK  admin creates a member user")

# --- duplicate username rejected ---
r = admin.post("/settings/users", data={"username": "bob", "password": "another12345", "role": "member"},
               follow_redirects=True)
assert b"username is taken" in r.data
print("OK  duplicate username rejected")

# --- short password rejected ---
r = admin.post("/settings/users", data={"username": "carol", "password": "short", "role": "member"},
               follow_redirects=True)
assert b"at least 8" in r.data
print("OK  short password rejected")

# --- member session ---
bob = client()
bob.post("/login", data={"username": "bob", "password": "bobpassword1"})

# dashboard: no admin controls
r = bob.get("/")
assert r.status_code == 200 and b"New category" not in r.data
print("OK  member dashboard hides 'New category'")

# category / user management routes are 403 for member
for path in ["/categories/", "/categories/new", f"/categories/{cid}",
             "/settings/", "/templates/export/%d" % cid]:
    assert bob.get(path).status_code == 403, path
for path, data in [(f"/categories/{cid}/fields/add", {"label": "X", "field_type": "text"}),
                   (f"/categories/{cid}/update", {"name": "Hacked"}),
                   (f"/categories/{cid}/delete", {}),
                   ("/settings/users", {"username": "mallory", "password": "mallory12345"}),
                   ("/search/reindex", {})]:
    assert bob.post(path, data=data).status_code == 403, path
print("OK  member gets 403 on every category/field/user-management route")

# member CAN do records
r = bob.post(f"/records/category/{cid}/new", data={"body": "bob's first note"},
             follow_redirects=True)
assert r.status_code == 200 and b"bob&#39;s first note" in r.data or b"bob's first note" in r.data
rid = sqlite3.connect(db_path).execute("SELECT id FROM records").fetchone()[0]
r = bob.post(f"/records/{rid}/edit", data={"body": "edited by bob"}, follow_redirects=True)
assert b"edited by bob" in r.data
# member CAN search
assert bob.get("/search", query_string={"q": "edited"}).status_code == 200
print("OK  member can create/edit records and search")

# category structure untouched by member attempts
assert sqlite3.connect(db_path).execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()[0] == "Notes"
print("OK  member's write attempts left category structure intact")

# --- last-admin guards ---
alice_id = sqlite3.connect(db_path).execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
r = admin.post(f"/settings/users/{alice_id}/delete", follow_redirects=True)
assert b"your own account" in r.data
r = admin.post(f"/settings/users/{alice_id}/role", data={"role": "member"}, follow_redirects=True)
assert b"last remaining admin" in r.data
print("OK  can't delete self; can't demote the last admin")

# promote bob to admin, then alice can be demoted/deleted
bob_id = sqlite3.connect(db_path).execute("SELECT id FROM users WHERE username='bob'").fetchone()[0]
admin.post(f"/settings/users/{bob_id}/role", data={"role": "admin"}, follow_redirects=True)
r = admin.post(f"/settings/users/{alice_id}/role", data={"role": "member"}, follow_redirects=True)
assert b"is now member" in r.data
# alice is now a member -> she loses admin routes; bob is the admin now
assert admin.get("/settings/").status_code == 403
admin.post(f"/settings/users/{alice_id}/role", data={"role": "admin"})  # (still 403, no-op)
print("OK  second admin promoted; first admin can then be demoted (and loses access)")

# switch admin actions to bob's session
admin = client()
admin.post("/login", data={"username": "bob", "password": "bobpassword1"})
admin.post(f"/settings/users/{alice_id}/role", data={"role": "admin"}, follow_redirects=True)

# --- password reset ---
r = admin.post(f"/settings/users/{bob_id}/password", data={"password": "bobs-new-pw-9"},
               follow_redirects=True)
assert b"Password reset" in r.data
stale = client()
r = stale.post("/login", data={"username": "bob", "password": "bobpassword1"})
assert b"Invalid username or password" in r.data
fresh = client()
r = fresh.post("/login", data={"username": "bob", "password": "bobs-new-pw-9"}, follow_redirects=True)
assert b"Welcome back" in r.data
print("OK  admin password reset invalidates old password, new one works")

# --- delete a user keeps their records (created_by -> NULL) ---
carol = client()
admin.post("/settings/users", data={"username": "carol", "password": "carolpassword1", "role": "member"})
carol.post("/login", data={"username": "carol", "password": "carolpassword1"})
carol.post(f"/records/category/{cid}/new", data={"body": "carol note"}, follow_redirects=True)
carol_id = sqlite3.connect(db_path).execute("SELECT id FROM users WHERE username='carol'").fetchone()[0]
crec = sqlite3.connect(db_path).execute(
    "SELECT id FROM records WHERE created_by=?", (carol_id,)).fetchone()[0]
admin.post(f"/settings/users/{carol_id}/delete", follow_redirects=True)
row = sqlite3.connect(db_path).execute("SELECT created_by, data FROM records WHERE id=?", (crec,)).fetchone()
assert row is not None and row[0] is None and "carol note" in row[1]
print("OK  deleting a user nulls created_by but keeps their records")

print("\nPhase 5 smoke test: ALL PASSED")
