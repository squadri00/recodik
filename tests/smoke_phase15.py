"""v6 smoke test: sortable columns + a per-column filter bar on the record list."""
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
    try:
        return conn.execute(sql, a).fetchall()
    finally:
        conn.close()


def order_of(html, needles):
    """Index of each needle's first appearance, in the order given."""
    return [html.find(n) for n in needles]


r = c.post("/categories/new", data={"name": "Customers"})
cust_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{cust_id}/fields/add", data={"label": "Name", "field_type": "text", "required": "1"})

r = c.post("/categories/new", data={"name": "Domains"})
dom_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Domain", "field_type": "text", "required": "1"})
c.post(f"/categories/{dom_id}/fields/add",
       data={"label": "Registrar", "field_type": "dropdown", "options": "GoDaddy\nNamecheap\nr10host"})
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Expires", "field_type": "date"})
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Cost", "field_type": "number"})
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Auto-renew", "field_type": "checkbox"})
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Customer", "field_type": "link",
                                                 "target_category_id": str(cust_id)})

c.post(f"/records/category/{cust_id}/new", data={"name": "Acme Corp"})
c.post(f"/records/category/{cust_id}/new", data={"name": "Zenith LLC"})
acme = raw("SELECT id FROM records WHERE data LIKE '%Acme%'")[0]["id"]
zenith = raw("SELECT id FROM records WHERE data LIKE '%Zenith%'")[0]["id"]

def add_domain(domain, registrar, expires, cost, renew, customer):
    c.post(f"/records/category/{dom_id}/new", data={
        "domain": domain, "registrar": registrar, "expires": expires, "cost": cost,
        "auto_renew": "1" if renew else "", "customer": str(customer),
    })

add_domain("zeta.com", "Namecheap", "2027-05-17", "12.50", True, acme)
add_domain("alpha.com", "r10host", "2027-01-01", "8.00", False, zenith)
add_domain("mid.com", "GoDaddy", "2027-03-15", "20.00", True, acme)

list_url = f"/records/category/{dom_id}"

# --- default view: no sort applied, all records shown ---
html = c.get(list_url).get_data(as_text=True)
assert "3 record" in html and "alpha.com" in html and "zeta.com" in html and "mid.com" in html
print("OK  unsorted/unfiltered list shows all records")

# --- sort by domain name ascending ---
html = c.get(list_url, query_string={"sort": "domain", "dir": "asc"}).get_data(as_text=True)
pos = order_of(html, ["alpha.com", "mid.com", "zeta.com"])
assert pos == sorted(pos)
assert "▲" in html
print("OK  sorting by text field (Domain) ascending orders alphabetically")

# --- sort by expiry date descending ---
html = c.get(list_url, query_string={"sort": "expires", "dir": "desc"}).get_data(as_text=True)
pos = order_of(html, ["zeta.com", "mid.com", "alpha.com"])  # 05-17, 03-15, 01-01
assert pos == sorted(pos)
assert "▼" in html
print("OK  sorting by date field descending orders latest-first")

# --- sort by number (cost) ascending ---
html = c.get(list_url, query_string={"sort": "cost", "dir": "asc"}).get_data(as_text=True)
pos = order_of(html, ["alpha.com", "zeta.com", "mid.com"])  # 8.00, 12.50, 20.00
assert pos == sorted(pos)
print("OK  sorting by number field is numeric, not alphabetical")

# --- sort by linked-record column (Customer) sorts by the linked label ---
html = c.get(list_url, query_string={"sort": "customer", "dir": "asc"}).get_data(as_text=True)
acme_positions = [i for i in [html.find("alpha.com"), html.find("zeta.com"), html.find("mid.com")]]
# Acme Corp (zeta, mid) should both come before Zenith LLC (alpha) alphabetically
assert html.find("zeta.com") < html.find("alpha.com")
assert html.find("mid.com") < html.find("alpha.com")
print("OK  sorting by a linked-record column orders by the linked record's label")

# --- an unsortable/unknown sort key is ignored, not a crash ---
r = c.get(list_url, query_string={"sort": "nonexistent_field"})
assert r.status_code == 200
print("OK  an invalid sort key is silently ignored")

# --- filter: text 'contains' on Domain ---
html = c.get(list_url, query_string={"f_domain": "com"}).get_data(as_text=True)
assert "3 record" in html
html = c.get(list_url, query_string={"f_domain": "zeta"}).get_data(as_text=True)
assert "1 record" in html and "zeta.com" in html and "alpha.com" not in html
print("OK  text filter matches by substring")

# --- filter: dropdown exact match ---
html = c.get(list_url, query_string={"f_registrar": "r10host"}).get_data(as_text=True)
assert "1 record" in html and "alpha.com" in html
print("OK  dropdown filter matches exactly")

# --- filter: checkbox Yes/No ---
html = c.get(list_url, query_string={"f_auto_renew": "1"}).get_data(as_text=True)
assert "2 record" in html and "zeta.com" in html and "mid.com" in html and "alpha.com" not in html
html = c.get(list_url, query_string={"f_auto_renew": "0"}).get_data(as_text=True)
assert "1 record" in html and "alpha.com" in html
print("OK  checkbox filter matches Yes/No")

# --- filter: link column by the linked record ---
html = c.get(list_url, query_string={"f_customer": str(acme)}).get_data(as_text=True)
assert "2 record" in html and "zeta.com" in html and "mid.com" in html and "alpha.com" not in html
print("OK  link-column filter matches the exact linked record")

# --- combined: filter + sort together ---
html = c.get(list_url, query_string={"f_customer": str(acme), "sort": "cost", "dir": "asc"}).get_data(as_text=True)
assert "2 record" in html  # only Acme's two domains
assert html.find("zeta.com") < html.find("mid.com")  # 12.50 before 20.00
print("OK  filter and sort combine")

# --- no matches: distinguished from a truly empty category ---
html = c.get(list_url, query_string={"f_domain": "nope-does-not-exist"}).get_data(as_text=True)
assert "No records match these filters" in html
empty_cat = c.post("/categories/new", data={"name": "Empty"})
empty_id = int(empty_cat.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{empty_id}/fields/add", data={"label": "X", "field_type": "text"})
html = c.get(f"/records/category/{empty_id}").get_data(as_text=True)
assert "No records yet" in html and "No records match these filters" not in html
print("OK  'no matches' and 'truly empty category' show different messages")

# --- password/file/multiselect columns are not sortable or offered as filters ---
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Login", "field_type": "password"})
html = c.get(list_url).get_data(as_text=True)
assert 'name="f_login"' not in html
r = c.get(list_url, query_string={"sort": "login"})
assert r.status_code == 200  # ignored, not an error
print("OK  password fields aren't offered as sortable/filterable")

print("\nv6 sort/filter smoke test: ALL PASSED")
