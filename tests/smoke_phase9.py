"""v2 smoke test: the linked-record ('link') field type."""
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


def add_field(cid, label, ftype, required=False, options="", target_category_id=""):
    d = {"label": label, "field_type": ftype}
    if required:
        d["required"] = "1"
    if options:
        d["options"] = options
    if target_category_id:
        d["target_category_id"] = str(target_category_id)
    return c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


def raw(sql, *a):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, a).fetchall()


def data_of(rid):
    return json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])


# --- categories ---
customers = new_category("Customers", "👤")
add_field(customers, "Customer", "text", required=True)

projects = new_category("Projects", "📁")
add_field(projects, "Project", "text", required=True)

# link field with no target -> rejected
r = add_field(projects, "Customer", "link")
assert b"needs a target category" in r.data
assert not raw("SELECT 1 FROM fields WHERE category_id=? AND field_type='link'", projects)
print("OK  link field without a target category is rejected")

# link field with a target -> created, options holds {"category_id": ...}
add_field(projects, "Customer", "link", required=True, target_category_id=customers)
lf = raw("SELECT * FROM fields WHERE category_id=? AND field_type='link'", projects)[0]
assert json.loads(lf["options"]) == {"category_id": customers}
print("OK  link field stores its target as {\"category_id\": N}")

subprojects = new_category("Sub-projects", "🧩")
add_field(subprojects, "Name", "text", required=True)
add_field(subprojects, "Parent project", "link", target_category_id=projects)

# --- records: build the hierarchy ---
c.post(f"/records/category/{customers}/new", data={"customer": "Acme Corp"}, follow_redirects=True)
acme = raw("SELECT id FROM records WHERE category_id=?", customers)[0]["id"]

# the Project new-record form offers Acme as a <select> option
r = c.get(f"/records/category/{projects}/new")
assert f'value="{acme}"'.encode() in r.data and b"Acme Corp" in r.data
assert b"<select" in r.data and b"customer" in r.data
print("OK  linked-record field renders a <select> of the target category's records")

# invalid link target -> rejected
r = c.post(f"/records/category/{projects}/new",
           data={"project": "X", "customer": "99999"}, follow_redirects=True)
assert b"must be an existing record" in r.data
assert not raw("SELECT 1 FROM records WHERE category_id=?", projects)
print("OK  a link to a non-existent record is rejected")

# valid link -> stored as the target id (int)
c.post(f"/records/category/{projects}/new",
       data={"project": "Online Shop", "customer": str(acme)}, follow_redirects=True)
shop = raw("SELECT id FROM records WHERE category_id=?", projects)[0]["id"]
assert data_of(shop)["customer"] == acme and isinstance(data_of(shop)["customer"], int)
print("OK  a linked-record value is stored as the target record id")

# detail + list render it as a link to that record
r = c.get(f"/records/{shop}")
assert f'href="/records/{acme}"'.encode() in r.data and b"Acme Corp" in r.data
r = c.get(f"/records/category/{projects}")
assert f'href="/records/{acme}"'.encode() in r.data
print("OK  a linked value renders as a clickable link to the target record")

# sub-project -> project
c.post(f"/records/category/{subprojects}/new",
       data={"name": "Checkout rebuild", "parent_project": str(shop)}, follow_redirects=True)
sub = raw("SELECT id FROM records WHERE category_id=?", subprojects)[0]["id"]
assert data_of(sub)["parent_project"] == shop
print("OK  three-level hierarchy: customer <- project <- sub-project")

# --- 'Referenced by' back-reference ---
r = c.get(f"/records/{acme}")
assert b"Referenced by" in r.data and b"Online Shop" in r.data and b"via Customer" in r.data
r = c.get(f"/records/{shop}")
assert b"Referenced by" in r.data and b"Checkout rebuild" in r.data
print("OK  the target record shows a 'Referenced by' list of records linking to it")

# --- search resolves the link to the parent's label ---
r = c.get("/search", query_string={"q": "Acme"})
body = r.get_data(as_text=True)
assert "Online Shop" in body or "Projects" in body   # the project is found via its linked customer
assert "Customers" in body                           # and the customer record itself
print("OK  searching the customer name finds records that link to it")

# --- template export references the target by NAME ---
r = c.get(f"/templates/export/{projects}")
tpl = json.loads(r.get_data(as_text=True))
link_fld = next(f for f in tpl["fields"] if f["field_type"] == "link")
assert link_fld["target_category"] == "Customers"
blob = r.get_data()
print("OK  template export references the link target by category name")

# --- import: target name resolved against this install ---
r = c.post("/templates/import",
           data={"template": (io.BytesIO(blob), "projects.myvault.json")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"Imported" in r.data
imp = raw("SELECT id FROM categories WHERE name='Projects (imported)'")[0]["id"]
imp_lf = raw("SELECT options FROM fields WHERE category_id=? AND field_type='link'", imp)[0]
assert json.loads(imp_lf["options"]) == {"category_id": customers}
print("OK  template import re-wires the link to the matching local category")

# --- import: unknown target name -> field created unconfigured + warning ---
orphan = {"myvault_template": 1, "name": "Orphans", "fields": [
    {"label": "Owner", "field_type": "link", "target_category": "Nonexistent Category"}]}
r = c.post("/templates/import",
           data={"template": (io.BytesIO(json.dumps(orphan).encode()), "o.json")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"need a target category set" in r.data
oc = raw("SELECT id FROM categories WHERE name='Orphans'")[0]["id"]
assert json.loads(raw("SELECT options FROM fields WHERE category_id=?", oc)[0]["options"]) == {}
print("OK  import with an unknown target name leaves the field unconfigured + warns")

# --- delete guard: category that is a link target can't be deleted ---
r = c.post(f"/categories/{customers}/delete", follow_redirects=True)
assert b"linked-record fields point at it" in r.data
assert raw("SELECT 1 FROM categories WHERE id=?", customers)
print("OK  deleting a category other fields link to is blocked")

# retarget the blocking fields away, then delete succeeds
for fid in [row["id"] for row in raw(
        "SELECT id FROM fields WHERE field_type='link'")]:
    cat = raw("SELECT category_id FROM fields WHERE id=?", fid)[0]["category_id"]
    c.post(f"/categories/{cat}/fields/{fid}/delete")
r = c.post(f"/categories/{customers}/delete", follow_redirects=True)
assert not raw("SELECT 1 FROM categories WHERE id=?", customers)
print("OK  once nothing links to it, the category deletes normally")

print("\nv2 linked-record smoke test: ALL PASSED")
