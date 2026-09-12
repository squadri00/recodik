"""v3 smoke test: encrypted file/image attachments (the `file` field type)."""
import os, sys, io, json, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keep test uploads tiny: cap files at 1 MB for this process only.
os.environ["MYVAULT_MAX_FILE_MB"] = "1"

db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})


def new_category(name):
    r = c.post("/categories/new", data={"name": name})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def add_field(cid, label, ftype, required=False):
    d = {"label": label, "field_type": ftype}
    if required:
        d["required"] = "1"
    return c.post(f"/categories/{cid}/fields/add", data=d, follow_redirects=True)


def raw(sql, *a):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, a).fetchall()


def data_of(rid):
    return json.loads(raw("SELECT data FROM records WHERE id=?", rid)[0]["data"])


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF_BYTES = b"%PDF-1.4 fake pdf content for testing, not a real document\n%%EOF"
SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"

docs = new_category("Documents")
add_field(docs, "Title", "text", required=True)
add_field(docs, "Attachment", "file", required=True)

# --- required file field blocks creation without a file ---
r = c.post(f"/records/category/{docs}/new", data={"title": "No file"},
           content_type="multipart/form-data", follow_redirects=True)
assert b"is required" in r.data
assert not raw("SELECT 1 FROM records WHERE category_id=?", docs)
print("OK  required file field blocks record creation without an upload")

# --- upload an image ---
r = c.post(f"/records/category/{docs}/new",
           data={"title": "Logo", "attachment": (io.BytesIO(PNG_BYTES), "logo.png")},
           content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
rid = raw("SELECT id FROM records WHERE category_id=?", docs)[0]["id"]
file_id = data_of(rid)["attachment"]
assert isinstance(file_id, int)
print("OK  uploading a file stores its id (int) in the record")

# --- ciphertext at rest: plaintext bytes never appear in the DB file ---
frow = raw("SELECT * FROM files WHERE id=?", file_id)[0]
assert frow["filename"] == "logo.png" and frow["content_type"] == "image/png"
assert frow["size_bytes"] == len(PNG_BYTES)
assert bytes(frow["data"]) != PNG_BYTES
blob = open(db_path, "rb").read()
assert PNG_BYTES not in blob
print("OK  file bytes are encrypted at rest (plaintext absent from the DB file)")

# --- locked vault: masked, no bytes served ---
c.get("/lock")
r = c.get(f"/records/{rid}")
assert b"\xf0\x9f\x94\x92" in r.data or "🔒".encode() in r.data  # lock glyph
assert b"logo.png" in r.data  # filename metadata visible even locked
r = c.get(f"/records/files/{file_id}/download")
assert r.status_code == 403
c.post("/unlock", data={"master_password": "masterpw123"})
print("OK  locked vault: filename shown, download refused (403)")

# --- unlocked: download returns the exact original bytes ---
r = c.get(f"/records/files/{file_id}/download")
assert r.status_code == 200 and r.data == PNG_BYTES
assert r.headers["Content-Type"] == "image/png"
assert "inline" in r.headers["Content-Disposition"]
assert r.headers.get("X-Content-Type-Options") == "nosniff"
print("OK  unlocked download returns the exact original bytes, inline for images")

# --- rendered as an <img> thumbnail in the record view ---
r = c.get(f"/records/{rid}")
assert f'/records/files/{file_id}/download'.encode() in r.data and b"file-thumb" in r.data
print("OK  image field renders as an inline <img> thumbnail")

# --- a PDF is a download, not inline ---
add_field(docs, "Scan", "file")
c.post(f"/records/{rid}/edit", data={
    "title": "Logo", "scan": (io.BytesIO(PDF_BYTES), "contract.pdf")},
    content_type="multipart/form-data", follow_redirects=True)
pdf_id = data_of(rid)["scan"]
r = c.get(f"/records/files/{pdf_id}/download")
assert r.data == PDF_BYTES and "attachment" in r.headers["Content-Disposition"]
r = c.get(f"/records/{rid}")
assert b"contract.pdf" in r.data
print("OK  a non-image document downloads as an attachment (not inline)")

# --- SVG is never rendered inline, even though it's an image/* type (XSS guard) ---
c.post(f"/records/{rid}/edit", data={
    "title": "Logo", "scan": (io.BytesIO(SVG_BYTES), "evil.svg")},
    content_type="multipart/form-data", follow_redirects=True)
svg_id = data_of(rid)["scan"]
r = c.get(f"/records/files/{svg_id}/download")
assert "attachment" in r.headers["Content-Disposition"]
r = c.get(f"/records/{rid}")
assert f'src="/records/files/{svg_id}/download"'.encode() not in r.data
assert f'href="/records/files/{svg_id}/download">📄'.encode() in r.data
print("OK  SVG uploads are never rendered inline (avoids stored-script risk)")

# --- replacing a file deletes the old files row ---
assert not raw("SELECT 1 FROM files WHERE id=?", pdf_id)  # superseded by the SVG upload
print("OK  uploading a replacement deletes the old file row")

# --- removing a file clears the field and deletes the row ---
c.post(f"/records/{rid}/edit", data={
    "title": "Logo", "scan__remove": "1"}, content_type="multipart/form-data",
    follow_redirects=True)
assert data_of(rid).get("scan") in ("", None)
assert not raw("SELECT 1 FROM files WHERE id=?", svg_id)
print("OK  the 'remove' checkbox clears the field and deletes the file row")

# --- size cap (set to 1 MB above) ---
big = b"x" * (2 * 1024 * 1024)
r = c.post(f"/records/{rid}/edit",
           data={"title": "Logo", "scan": (io.BytesIO(big), "big.bin")},
           content_type="multipart/form-data", follow_redirects=True)
assert b"larger than 1 MB" in r.data
print("OK  a file over the configured size cap is rejected")

# --- search indexes the filename, never the content ---
r = c.get("/search", query_string={"q": "logo.png"})
assert "1 match" in r.get_data(as_text=True)
assert "No matches" in c.get("/search", query_string={"q": "fake pdf content"}).get_data(as_text=True)
print("OK  search finds a file by name; never by its (encrypted) content")

# --- permanently deleting (purging) the record cascades to its files ---
# (a plain /delete now only trashes it -- see smoke_phase17.py for that)
last_file_id = data_of(rid).get("attachment")
c.post(f"/records/{rid}/delete")
c.post(f"/records/{rid}/purge")
assert not raw("SELECT 1 FROM records WHERE id=?", rid)
assert not raw("SELECT 1 FROM files WHERE record_id=?", rid)
if last_file_id:
    assert not raw("SELECT 1 FROM files WHERE id=?", last_file_id)
print("OK  purging a record cascades to delete its attached files")

# --- 404 on a nonexistent file id ---
r = c.get("/records/files/999999/download")
assert r.status_code == 404
print("OK  downloading a nonexistent file id returns 404")

# --- schema migration: an existing v1 database gains the `files` table ---
v1_path = os.path.join(tempfile.mkdtemp(), "v1.sqlite3")
conn = sqlite3.connect(v1_path)
conn.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', created_at TEXT NOT NULL);
    CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        icon TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT NOT NULL);
    CREATE TABLE fields (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
        label TEXT NOT NULL, field_key TEXT NOT NULL, field_type TEXT NOT NULL,
        options TEXT DEFAULT '[]', required INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0);
    CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
        data TEXT NOT NULL DEFAULT '{}', created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE VIRTUAL TABLE records_fts USING fts5(record_id UNINDEXED, category_id UNINDEXED,
        category_name, content, tokenize='porter');
    INSERT INTO meta(key, value) VALUES ('schema_version', '1');
    INSERT INTO users(username, password_hash, role, created_at)
        VALUES ('legacy', 'x', 'admin', '2020-01-01');
    INSERT INTO categories(name, icon, sort_order, created_at) VALUES ('Old Cat', '', 0, '2020-01-01');
""")
conn.commit()
conn.close()

app2 = create_app({"DATABASE": v1_path, "TESTING": True, "SECRET_KEY": "t2"})
conn = sqlite3.connect(v1_path)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "files" in tables and "alert_dismissals" in tables and "audit_log" in tables
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
assert ver == "4"
assert conn.execute("SELECT username FROM users").fetchone()[0] == "legacy"
assert conn.execute("SELECT name FROM categories").fetchone()[0] == "Old Cat"
print("OK  an existing v1 database is upgraded in place, all the way to v4 (files + "
      "alert_dismissals + audit_log added, data kept)")

print("\nv3 file-attachments smoke test: ALL PASSED")
