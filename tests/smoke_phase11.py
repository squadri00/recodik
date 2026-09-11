"""v3.1 smoke test: converting an existing text field to encrypted in place."""
import os, sys, json, tempfile, sqlite3

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
    return conn.execute(sql, a).fetchall()


r = c.post("/categories/new", data={"name": "Banking"})
cid = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{cid}/fields/add", data={"label": "Bank name", "field_type": "text", "required": "1"})
c.post(f"/categories/{cid}/fields/add", data={"label": "Account number", "field_type": "text"})
fid = raw("SELECT id FROM fields WHERE category_id=? AND field_key='account_number'", cid)[0]["id"]

SECRET = "0123456789-real-account-number"
c.post(f"/records/category/{cid}/new", data={"bank_name": "Acme Bank", "account_number": SECRET},
       follow_redirects=True)
rid = raw("SELECT id FROM records WHERE category_id=?", cid)[0]["id"]

# --- sanity: it's stored in the clear today, and IS searchable (the bug) ---
assert raw("SELECT data FROM records WHERE id=?", rid)[0]["data"].find(SECRET) != -1
assert "1 match" in c.get("/search", query_string={"q": "real-account-number"}).get_data(as_text=True)
print("OK  before the fix: value is plaintext in the DB and searchable (reproduces the real bug)")

# --- convert to password WITHOUT the checkbox: type changes, value is untouched ---
c.post(f"/categories/{cid}/fields/{fid}/update",
       data={"label": "Account number", "field_type": "password"})  # no encrypt_existing
assert raw("SELECT field_type FROM fields WHERE id=?", fid)[0]["field_type"] == "password"
assert raw("SELECT data FROM records WHERE id=?", rid)[0]["data"].find(SECRET) != -1
print("OK  switching type alone (no checkbox) leaves the stored value untouched")

# revert for the real test
c.post(f"/categories/{cid}/fields/{fid}/update", data={"label": "Account number", "field_type": "text"})

# --- vault locked: the encrypt-and-convert is refused ---
c.get("/lock")
r = c.post(f"/categories/{cid}/fields/{fid}/update",
           data={"label": "Account number", "field_type": "password", "encrypt_existing": "1"},
           follow_redirects=True)
assert b"Unlock the vault" in r.data
assert raw("SELECT field_type FROM fields WHERE id=?", fid)[0]["field_type"] == "text"
c.post("/unlock", data={"master_password": "masterpw123"})
print("OK  converting+encrypting while locked is refused; the field type is NOT changed either")

# --- the real fix: convert + encrypt existing values ---
r = c.post(f"/categories/{cid}/fields/{fid}/update",
           data={"label": "Account number", "field_type": "password", "encrypt_existing": "1"},
           follow_redirects=True)
assert b"1 existing value" in r.data
assert raw("SELECT field_type FROM fields WHERE id=?", fid)[0]["field_type"] == "password"
stored = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])["account_number"]
assert stored != SECRET and stored.startswith("gAAAAA")
blob = open(db_path, "rb").read()
assert SECRET.encode() not in blob
print("OK  the fix converts the type AND encrypts the existing value; plaintext removed from the DB")

# --- reveal proves it round-trips correctly ---
r = c.post(f"/records/{rid}/reveal", data={"field_key": "account_number"})
assert r.get_json()["value"] == SECRET
print("OK  the re-encrypted value reveals back to the original plaintext")

# --- it's no longer searchable by its old plaintext value ---
assert "No matches" in c.get("/search", query_string={"q": "real-account-number"}).get_data(as_text=True)
print("OK  the plaintext is purged from the search index (reindexed as part of the fix)")

# --- idempotent: the field is already `password`, so re-submitting with the
# checkbox checked doesn't re-touch (or double-encrypt) the value at all ---
r = c.post(f"/categories/{cid}/fields/{fid}/update",
           data={"label": "Account number", "field_type": "password", "encrypt_existing": "1"},
           follow_redirects=True)
assert b"Updated field" in r.data and b"existing value" not in r.data
after = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])["account_number"]
assert after == stored
r = c.post(f"/records/{rid}/reveal", data={"field_key": "account_number"})
assert r.get_json()["value"] == SECRET
print("OK  re-running the fix on an already-encrypted field is a no-op; value still reveals correctly")

print("\nv3.1 field-encryption-fix smoke test: ALL PASSED")
