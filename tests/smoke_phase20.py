"""v11 smoke test: the in-app Help guide."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app

app = create_app({"DATABASE": db_path, "TESTING": True, "SECRET_KEY": "test"})
c = app.test_client()
c.post("/setup", data={"username": "admin", "password": "adminpassword1",
                       "master_password": "masterpw123", "master_password_confirm": "masterpw123"})

# --- unauthenticated visitors are redirected to login ---
anon = app.test_client()
assert anon.get("/help").status_code == 302
print("OK  the Help guide requires login")

# --- the nav link is present on every page ---
dash_html = c.get("/").get_data(as_text=True)
assert 'href="/help"' in dash_html
print("OK  a 'Help' link is in the header nav")

# --- the guide covers every major feature area (anchors present) ---
html = c.get("/help").get_data(as_text=True)
expected_anchors = [
    "quick-start", "getting-started", "categories", "fields", "records",
    "quick-add", "linked-records", "tags", "files", "passwords-vault",
    "trash", "backup", "search", "sort-filter", "alerts", "calendar",
    "costs", "dashboard-summary", "activity-log", "templates", "users",
    "troubleshooting",
]
missing = [a for a in expected_anchors if f'id="{a}"' not in html]
assert not missing, f"missing sections: {missing}"
print(f"OK  the guide has all {len(expected_anchors)} expected sections")

# --- every ToC link points at a real anchor on the same page ---
import re
toc_block = html.split('<div class="help-toc">')[1].split("<!-- ====")[0]
hrefs = re.findall(r'href="#([\w-]+)"', toc_block)
assert set(hrefs) <= set(expected_anchors), set(hrefs) - set(expected_anchors)
assert len(hrefs) >= 15
print(f"OK  the table of contents links ({len(hrefs)}) all resolve to real sections")

# --- a member (non-admin) can read it too -- it's not gated to admins ---
c.post("/settings/users", data={"username": "bob", "password": "bobpassword1", "role": "member"})
member = app.test_client()
member.post("/login", data={"username": "bob", "password": "bobpassword1"})
r = member.get("/help")
assert r.status_code == 200 and "Quick start" in r.get_data(as_text=True)
print("OK  a member (non-admin) can open the Help guide too")

# --- admin-only sections are clearly marked as such, in plain text ---
assert html.count("(admin only)") >= 4
print("OK  admin-only sections are labeled as such")

print("\nv11 help-guide smoke test: ALL PASSED")
