"""v7 smoke test: the read-only month calendar view."""
import os, re, sys, sqlite3, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from myvault import create_app
from myvault.calendar_view import adjacent, clamp_month

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


# --- month/year rollover helpers ---
assert clamp_month(2026, 13) == (2027, 1)
assert clamp_month(2026, 0) == (2025, 12)
assert clamp_month(2026, 9) == (2026, 9)
assert adjacent(2026, 12, 1) == (2027, 1)
assert adjacent(2026, 1, -1) == (2025, 12)
print("OK  month/year rollover math is correct at both year boundaries")

# --- unauthenticated access redirects to login ---
anon = app.test_client()
assert anon.get("/calendar").status_code == 302
print("OK  the calendar requires login")

# --- build categories with a plain date and a date_alert field ---
r = c.post("/categories/new", data={"name": "Domains"})
dom_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Domain", "field_type": "text", "required": "1"})
c.post(f"/categories/{dom_id}/fields/add", data={"label": "Expires", "field_type": "date"})

r = c.post("/categories/new", data={"name": "Events", "icon": "🎉"})
evt_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
c.post(f"/categories/{evt_id}/fields/add", data={"label": "Title", "field_type": "text", "required": "1"})
c.post(f"/categories/{evt_id}/fields/add",
       data={"label": "When", "field_type": "date_alert", "alert_days_before": "3"})

c.post(f"/records/category/{dom_id}/new", data={"domain": "example.com", "expires": "2026-09-14"})
c.post(f"/records/category/{evt_id}/new", data={"title": "Team Meeting", "when": "2026-09-14"})
c.post(f"/records/category/{evt_id}/new", data={"title": "Later Thing", "when": "2026-10-02"})
dom_rec = raw("SELECT id FROM records WHERE category_id=?", dom_id)[0]["id"]
evt_rec = raw("SELECT id FROM records WHERE data LIKE '%Team Meeting%'")[0]["id"]

# --- September 2026: both same-day events show on the 14th ---
html = c.get("/calendar", query_string={"year": 2026, "month": 9}).get_data(as_text=True)
assert "September 2026" in html
assert "example.com" in html and "Team Meeting" in html
assert f'href="/records/{dom_rec}"' in html
assert f'href="/records/{evt_rec}"' in html
print("OK  both a plain-date and a date_alert event render on the correct day")

# --- a plain `date` field never carries an alert tier, even matching a
# date_alert field's date and window ---
assert "cal-tag-upcoming" not in html.split("example.com")[0][-400:]
print("OK  a plain `date` field is shown without any alert styling")

# --- different categories get visibly different tag colors ---
import re
colors = set(re.findall(r'cal-tag cal-c(\d)', html))
assert len(colors) >= 2
print("OK  events from different categories use different tag colors")

def calendar_tag_record_ids(html):
    """Record ids linked from an actual calendar tag -- not the header's
    active-alerts dropdown, which also shows on every page regardless of
    month and can legitimately mention the same record."""
    return {int(m) for m in re.findall(r'class="cal-tag[^"]*"\s+href="/records/(\d+)"', html)}


# --- October: the later event's tag appears there; the September one doesn't ---
html_oct = c.get("/calendar", query_string={"year": 2026, "month": 10}).get_data(as_text=True)
oct_ids = calendar_tag_record_ids(html_oct)
assert "Later Thing" in html_oct
later_rec = raw("SELECT id FROM records WHERE data LIKE '%Later Thing%'")[0]["id"]
assert later_rec in oct_ids and evt_rec not in oct_ids
print("OK  events appear only in their own month's grid")

# --- navigation math on the page matches real prev/next links ---
assert 'year=2026&amp;month=8' in html or "year=2026&month=8" in html
assert 'year=2026&amp;month=10' in html or "year=2026&month=10" in html
print("OK  Prev/Next links point at the adjacent months")

# --- garbage year/month query params don't crash; fall back gracefully ---
r = c.get("/calendar", query_string={"year": "not-a-year", "month": "nope"})
assert r.status_code == 200
r = c.get("/calendar", query_string={"year": 99999, "month": 1})
assert r.status_code == 200
print("OK  invalid or out-of-range year/month falls back instead of erroring")

# --- December -> January year rollover renders without error ---
r = c.get("/calendar", query_string={"year": 2026, "month": 12})
html_dec = r.get_data(as_text=True)
assert r.status_code == 200 and "December 2026" in html_dec
assert "year=2027&amp;month=1" in html_dec or "year=2027&month=1" in html_dec
print("OK  December's Next link correctly rolls over into January 2027")

print("\nv7 calendar-view smoke test: ALL PASSED")
