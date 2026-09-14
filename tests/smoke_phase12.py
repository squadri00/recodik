"""v3.2 smoke test: Markdown formatting for `textarea` fields."""
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


r = c.post("/categories/new", data={"name": "Notes"})
cid = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{cid}/fields/add", data={"label": "Body", "field_type": "textarea", "required": "1"})

MD = ("**bold** and _italic_\n\n## Heading\n\n- one\n- two\n\n"
      "[Anthropic](https://anthropic.com) and `inline code`")
c.post(f"/records/category/{cid}/new", data={"body": MD}, follow_redirects=True)
rid = raw("SELECT id FROM records WHERE category_id=?", cid)[0]["id"]

# --- stored value is unchanged plain markdown, not HTML ---
stored = json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])["body"]
assert stored == MD and "<strong>" not in stored
print("OK  the stored value is plain Markdown text, unchanged")

# --- detail view renders real formatting ---
detail_html = c.get(f"/records/{rid}").get_data(as_text=True)
assert "<strong>bold</strong>" in detail_html
assert "<em>italic</em>" in detail_html
assert "<h2>Heading</h2>" in detail_html
assert "<li>one</li>" in detail_html and "<li>two</li>" in detail_html
assert '<a href="https://anthropic.com" target="_blank" rel="noopener noreferrer">Anthropic</a>' in detail_html
assert "<code>inline code</code>" in detail_html
print("OK  the detail page renders bold/italic/heading/list/link/code as real HTML")

# --- list view stays plain (raw markdown text, not rendered HTML) ---
list_html = c.get(f"/records/category/{cid}").get_data(as_text=True)
assert "<strong>bold</strong>" not in list_html
assert "**bold**" in list_html  # shown as literal text, e.g. in the title= tooltip
print("OK  the list view shows raw markdown text, not rendered HTML (avoids layout breakage)")

# --- XSS: a <script> tag is stripped, never executes (the page's own
# app.js <script> tag is legitimate and expected to remain) ---
c.post(f"/records/{rid}/edit", data={"body": "hello <script>alert(1)</script> world"},
       follow_redirects=True)
html = c.get(f"/records/{rid}").get_data(as_text=True)
assert "<script>alert(1)</script>" not in html
assert "<script>alert(1)" not in html.replace("\n", "")
print("OK  a <script> tag is stripped from rendered output")

# --- XSS: an <img onerror=...> never survives ---
# (scoped to the record's own rendered field, not the whole page -- the page
# legitimately has its own <img> tags now, for the header/footer brand logo)
c.post(f"/records/{rid}/edit", data={"body": '<img src=x onerror="alert(1)">'},
       follow_redirects=True)
html = c.get(f"/records/{rid}").get_data(as_text=True)
body_html = html.split('<dl class="detail">')[1].split("Last updated")[0]
assert "onerror" not in body_html.lower() and "<img" not in body_html.lower()
print("OK  an <img onerror=...> is stripped, not rendered")

# --- a javascript: link is neutered ---
c.post(f"/records/{rid}/edit", data={"body": "[click me](javascript:alert(1))"},
       follow_redirects=True)
html = c.get(f"/records/{rid}").get_data(as_text=True)
assert "javascript:" not in html.lower()
print("OK  a javascript: URL is stripped from the rendered link")

# --- search still finds the record by its raw markdown content ---
c.post(f"/records/{rid}/edit", data={"body": MD}, follow_redirects=True)
r = c.get("/search", query_string={"q": "Anthropic"})
assert "1 match" in r.get_data(as_text=True)
print("OK  search still indexes and finds the field by its plain-text content")

print("\nv3.2 markdown-formatting smoke test: ALL PASSED")
