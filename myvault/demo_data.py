"""Sample data loaded into every brand-new install, so a first-time user has
something real to click through instead of a blank dashboard. Meant to be
explored, then wiped via Settings -> Sample data -> Reset once the person is
ready to build their own categories (see settings.reset_demo_data).
"""

from __future__ import annotations

import json
import sqlite3

from .util import now_iso, slugify_key

TAG_NAME = "Demo data"


def _add_category(db: sqlite3.Connection, name: str, icon: str, created_by: int | None) -> int:
    cur = db.execute(
        "INSERT INTO categories(name, icon, sort_order, created_by, created_at) "
        "VALUES(?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories), ?, ?)",
        (name, icon, created_by, now_iso()),
    )
    return cur.lastrowid


def _add_field(db: sqlite3.Connection, category_id: int, label: str, ftype: str,
                required: int = 0, target_id: int | None = None,
                alert_days: int | None = None, frequency: str | None = None) -> str:
    key = slugify_key(label)
    if ftype == "link":
        opts = json.dumps({"category_id": int(target_id)})
    elif ftype == "date_alert":
        opts = json.dumps({"alert_days_before": alert_days if alert_days is not None else 30})
    elif ftype == "cost":
        opts = json.dumps({"frequency": frequency or "monthly"})
    else:
        opts = "[]"
    db.execute(
        "INSERT INTO fields(category_id, label, field_key, field_type, options, required, sort_order) "
        "VALUES(?, ?, ?, ?, ?, ?, "
        "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM fields WHERE category_id = ?))",
        (category_id, label, key, ftype, opts, required, category_id),
    )
    return key


def _add_record(db: sqlite3.Connection, category_id: int, data: dict, created_by: int | None) -> int:
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO records(category_id, data, created_by, created_at, updated_at, deleted_at) "
        "VALUES(?, ?, ?, ?, ?, NULL)",
        (category_id, json.dumps(data), created_by, ts, ts),
    )
    return cur.lastrowid


def _tag_record(db: sqlite3.Connection, tag_id: int, record_id: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?, ?)",
        (record_id, tag_id),
    )


def seed(db: sqlite3.Connection, created_by: int | None = None) -> list[int]:
    """Create the demo categories/fields/records. Returns every record id
    created, so the caller can feed the search index without a full reindex.
    """
    record_ids: list[int] = []

    def record(category_id, data):
        rid = _add_record(db, category_id, data, created_by)
        record_ids.append(rid)
        return rid

    customers_cat = _add_category(db, "Customers", "\U0001F464", created_by)
    k_biz = _add_field(db, customers_cat, "Business name", "text", required=1)
    k_contact = _add_field(db, customers_cat, "Contact person", "text")
    k_email = _add_field(db, customers_cat, "Email", "email")
    k_phone = _add_field(db, customers_cat, "Phone number", "text")

    types_cat = _add_category(db, "Project Types", "\U0001F3F7", created_by)
    k_typename = _add_field(db, types_cat, "Type name", "text", required=1)

    domains_cat = _add_category(db, "Domains", "\U0001F310", created_by)
    k_domname = _add_field(db, domains_cat, "Domain name", "text", required=1)
    k_registrar = _add_field(db, domains_cat, "Registrar", "text")
    k_domexpiry = _add_field(db, domains_cat, "Expiry date", "date_alert", alert_days=30)
    k_domcust = _add_field(db, domains_cat, "Customer", "link", target_id=customers_cat)

    hosting_cat = _add_category(db, "Hosting", "\U0001F5A5", created_by)
    k_hcompany = _add_field(db, hosting_cat, "Company name", "text", required=1)
    k_hcust = _add_field(db, hosting_cat, "Customer", "link", target_id=customers_cat)
    k_hcustid = _add_field(db, hosting_cat, "Customer ID", "text")
    k_hpass = _add_field(db, hosting_cat, "Password", "password")
    k_hemail = _add_field(db, hosting_cat, "Email address", "email")
    k_hsupport = _add_field(db, hosting_cat, "Support number", "text")

    projects_cat = _add_category(db, "Projects", "\U0001F4C1", created_by)
    k_pname = _add_field(db, projects_cat, "Project name", "text", required=1)
    k_pcust = _add_field(db, projects_cat, "Customer", "link", target_id=customers_cat)
    k_ptype = _add_field(db, projects_cat, "Project type", "link", target_id=types_cat)
    k_pstart = _add_field(db, projects_cat, "Start date", "date")
    k_pcost = _add_field(db, projects_cat, "Cost", "cost", frequency="one_time")
    k_pinvoice = _add_field(db, projects_cat, "Invoice due date", "date_alert", alert_days=7)
    k_pdomain = _add_field(db, projects_cat, "Domain", "link", target_id=domains_cat)
    k_phosting = _add_field(db, projects_cat, "Hosting", "link", target_id=hosting_cat)
    k_pdocs = _add_field(db, projects_cat, "Project docs", "file")

    customers = [
        ("Bright Leaf Bakery", "Maria Gonzalez", "maria@brightleafbakery.com", "(416) 555-0148"),
        ("Harborview Dental", "Dr. Aiden Cole", "aiden@harborviewdental.com", "(647) 555-0193"),
        ("Northgate Fitness", "Priya Nair", "priya@northgatefitness.com", "(905) 555-0177"),
        ("Summit Legal Group", "James Whitfield", "james@summitlegalgroup.com", "(416) 555-0212"),
        ("Cedar & Vine Realty", "Olivia Brooks", "olivia@cedarvinerealty.com", "(647) 555-0256"),
        ("BlueWave Logistics", "Marcus Reyes", "marcus@bluewavelogistics.com", "(905) 555-0289"),
        ("Silverline Retail Co.", "Emma Chen", "emma@silverlineretail.com", "(416) 555-0301"),
    ]
    cust_id = {}
    for biz, contact, email, phone in customers:
        cust_id[biz] = record(customers_cat, {
            k_biz: biz, k_contact: contact, k_email: email, k_phone: phone,
        })

    type_names = [
        "Website Development", "Mobile App Development", "Cloud Migration",
        "Cybersecurity Audit", "Network Infrastructure Setup",
        "Software Integration", "IT Support & Maintenance", "Data Backup & Recovery",
    ]
    type_id = {name: record(types_cat, {k_typename: name}) for name in type_names}

    domains = [
        ("brightleafbakery.com", "Namecheap", "2026-10-05", "Bright Leaf Bakery"),
        ("harborviewdental.com", "GoDaddy", "2026-11-20", "Harborview Dental"),
        ("northgatefitness.com", "Namecheap", "2026-10-01", "Northgate Fitness"),
        ("summitlegalgroup.com", "GoDaddy", "2027-01-15", "Summit Legal Group"),
        ("cedarvinerealty.com", "Google Domains", "2026-09-30", "Cedar & Vine Realty"),
        ("bluewavelogistics.com", "Namecheap", "2026-12-10", "BlueWave Logistics"),
        ("silverlineretail.com", "GoDaddy", "2026-10-08", "Silverline Retail Co."),
    ]
    domain_id = {}
    for dom, registrar, expiry, cust in domains:
        domain_id[dom] = record(domains_cat, {
            k_domname: dom, k_registrar: registrar, k_domexpiry: expiry,
            k_domcust: cust_id[cust],
        })

    hosting = [
        ("Hostinger", "Bright Leaf Bakery", "HST-88213", "hosting@brightleafbakery.com", "1-800-555-0101"),
        ("SiteGround", "Harborview Dental", "SG-55210", "admin@harborviewdental.com", "1-800-555-0199"),
        ("Bluehost", "Northgate Fitness", "BH-34021", "hosting@northgatefitness.com", "1-800-555-0155"),
        ("HostGator", "Summit Legal Group", "HG-77890", "it@summitlegalgroup.com", "1-800-555-0166"),
        ("Kinsta", "Cedar & Vine Realty", "KN-12045", "hosting@cedarvinerealty.com", "1-800-555-0177"),
        ("DigitalOcean", "BlueWave Logistics", "DO-66210", "devops@bluewavelogistics.com", "1-800-555-0188"),
        ("WP Engine", "Silverline Retail Co.", "WPE-90112", "hosting@silverlineretail.com", "1-800-555-0199"),
    ]
    hosting_id = {}
    for company, cust, custid, email, support in hosting:
        hosting_id[cust] = record(hosting_cat, {
            k_hcompany: company, k_hcust: cust_id[cust], k_hcustid: custid,
            k_hpass: "", k_hemail: email, k_hsupport: support,
        })

    projects = [
        ("Bright Leaf Website Redesign", "Bright Leaf Bakery", "Website Development",
         "2026-08-01", "2400", "2026-09-20", "brightleafbakery.com"),
        ("Bright Leaf POS Integration", "Bright Leaf Bakery", "Software Integration",
         "2026-08-15", "1800", "2026-10-01", "brightleafbakery.com"),
        ("Harborview Online Booking System", "Harborview Dental", "Software Integration",
         "2026-07-15", "3800", "2026-09-23", "harborviewdental.com"),
        ("Harborview Network Upgrade", "Harborview Dental", "Network Infrastructure Setup",
         "2026-06-01", "5200", "2026-11-01", "harborviewdental.com"),
        ("Northgate Fitness Mobile App", "Northgate Fitness", "Mobile App Development",
         "2026-05-10", "12000", "2026-09-23", "northgatefitness.com"),
        ("Northgate Fitness Website Refresh", "Northgate Fitness", "Website Development",
         "2026-08-20", "2200", "2026-10-05", "northgatefitness.com"),
        ("Summit Legal Cloud Migration", "Summit Legal Group", "Cloud Migration",
         "2026-06-15", "9800", "2026-09-30", "summitlegalgroup.com"),
        ("Summit Legal Cybersecurity Audit", "Summit Legal Group", "Cybersecurity Audit",
         "2026-08-01", "4500", "2026-09-19", "summitlegalgroup.com"),
        ("Cedar & Vine Realty Website Launch", "Cedar & Vine Realty", "Website Development",
         "2026-07-01", "3100", "2026-09-22", "cedarvinerealty.com"),
        ("Cedar & Vine CRM Integration", "Cedar & Vine Realty", "Software Integration",
         "2026-08-10", "2700", "2026-10-10", "cedarvinerealty.com"),
        ("BlueWave Logistics Fleet Tracking App", "BlueWave Logistics", "Mobile App Development",
         "2026-04-20", "18000", "2026-10-15", "bluewavelogistics.com"),
        ("BlueWave Data Backup Solution", "BlueWave Logistics", "Data Backup & Recovery",
         "2026-08-05", "3300", "2026-09-21", "bluewavelogistics.com"),
        ("BlueWave IT Support Retainer", "BlueWave Logistics", "IT Support & Maintenance",
         "2026-01-01", "800", "2026-09-30", "bluewavelogistics.com"),
        ("Silverline Retail E-commerce Platform", "Silverline Retail Co.", "Website Development",
         "2026-03-01", "15000", "2026-09-23", "silverlineretail.com"),
        ("Silverline Retail Cybersecurity Audit", "Silverline Retail Co.", "Cybersecurity Audit",
         "2026-08-25", "4200", "2026-10-12", "silverlineretail.com"),
        ("Silverline Retail Network Setup", "Silverline Retail Co.", "Network Infrastructure Setup",
         "2026-07-10", "6100", "2026-11-05", "silverlineretail.com"),
    ]
    project_ids = []
    for pname, cust, ptype, start, cost, invoice, dom in projects:
        rid = record(projects_cat, {
            k_pname: pname, k_pcust: cust_id[cust], k_ptype: type_id[ptype],
            k_pstart: start, k_pcost: cost, k_pinvoice: invoice,
            k_pdomain: domain_id[dom], k_phosting: hosting_id[cust], k_pdocs: "",
        })
        project_ids.append(rid)

    # Tag everything so it's all findable/removable as one group, and so the
    # Tags page has something to show on a fresh install.
    db.execute("INSERT INTO tags(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (TAG_NAME,))
    tag_id = db.execute("SELECT id FROM tags WHERE name = ?", (TAG_NAME,)).fetchone()[0]
    for rid in record_ids:
        _tag_record(db, tag_id, rid)

    return record_ids


def is_untouched_install(db: sqlite3.Connection) -> bool:
    """True only when there are no categories yet -- the exact moment demo
    data should be loaded (right after the very first admin account is made)."""
    return db.execute("SELECT 1 FROM categories LIMIT 1").fetchone() is None
