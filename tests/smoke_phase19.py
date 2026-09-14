"""v10 smoke test: the dashboard summary (alerts / costs / recent activity)."""
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

# Precise markers (not the nav bar, which always says "Costs"/"Tags"/etc.)
ALERTS_MARK = "⚠ Alerts"  # the card heading includes its emoji; nav has no "Alerts" link
COSTS_CARD_MARK = "<h2>Costs</h2>"  # nav's Costs link isn't an <h2>
ACTIVITY_MARK = "Recent activity"

# --- 1. a fresh vault shows no summary cards at all ---
html = c.get("/").get_data(as_text=True)
assert ALERTS_MARK not in html
assert COSTS_CARD_MARK not in html
assert ACTIVITY_MARK not in html
print("OK  a fresh vault's dashboard shows no summary cards (nothing to summarize yet)")

# --- build a category with a date_alert field, a cost field, and a plain field ---
r = c.post("/categories/new", data={"name": "Domains"})
cat = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{cat}/fields/add", data={"label": "Name", "field_type": "text", "required": "1"})
c.post(f"/categories/{cat}/fields/add",
       data={"label": "Renewal", "field_type": "date_alert", "alert_days_before": "365"})
c.post(f"/categories/{cat}/fields/add",
       data={"label": "Fee", "field_type": "cost", "frequency": "yearly"})

import datetime
soon = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
c.post(f"/records/category/{cat}/new", data={"name": "example.com", "renewal": soon, "fee": "12"})

# --- 2. after adding an alert + cost, both cards appear with correct numbers ---
html = c.get("/").get_data(as_text=True)
assert ALERTS_MARK in html and "example.com" in html
assert COSTS_CARD_MARK in html and "1.00" in html  # 12/yr -> 1.00/mo equivalent
assert "12.00" in html  # /yr total
print("OK  the dashboard's Alerts and Costs cards appear with the right numbers")

# --- 3. admin sees Recent activity; a member does not ---
admin_html = c.get("/").get_data(as_text=True)
assert ACTIVITY_MARK in admin_html and "example.com" in admin_html

c.post("/settings/users", data={"username": "bob", "password": "bobpassword1", "role": "member"})
member = app.test_client()
member.post("/login", data={"username": "bob", "password": "bobpassword1"})
member_html = member.get("/").get_data(as_text=True)
assert ACTIVITY_MARK not in member_html
assert ALERTS_MARK in member_html and COSTS_CARD_MARK in member_html  # not admin-gated
print("OK  Recent activity is admin-only; Alerts/Costs show for any logged-in user")

# --- 4. more than 5 active alerts shows a '+N more' hint ---
for i in range(6):
    d = (datetime.date.today() + datetime.timedelta(days=20 + i)).isoformat()
    c.post(f"/records/category/{cat}/new", data={"name": f"site{i}.com", "renewal": d, "fee": "5"})
html = c.get("/").get_data(as_text=True)
assert "more in the header" in html
print("OK  more than 5 active alerts shows a '+N more' hint instead of an ever-growing list")

print("\nv10 dashboard-summary smoke test: ALL PASSED")
