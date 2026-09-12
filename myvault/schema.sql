-- MyVault schema (current: v5)
-- Applied once on a fresh database. Versioned via meta.value where key='schema_version'.
-- An existing older database is upgraded in place by myvault/db.py's MIGRATIONS instead.

PRAGMA foreign_keys = ON;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT
); -- encryption salt, key verifier, schema version, session secret, install settings

CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'member',   -- 'admin' | 'member'
  created_at    TEXT NOT NULL
);

CREATE TABLE categories (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  icon       TEXT DEFAULT '',
  sort_order INTEGER DEFAULT 0,
  created_by INTEGER,
  created_at TEXT NOT NULL,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE fields (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL,
  label       TEXT NOT NULL,
  field_key   TEXT NOT NULL,          -- stable machine key generated from label; JSON key in records.data
  field_type  TEXT NOT NULL,          -- see field types (v1)
  options     TEXT DEFAULT '[]',      -- JSON array, used by dropdown / multiselect
  required    INTEGER DEFAULT 0,
  sort_order  INTEGER DEFAULT 0,
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
  UNIQUE (category_id, field_key)
);

CREATE TABLE records (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL,
  data        TEXT NOT NULL DEFAULT '{}',  -- JSON keyed by field_key; encrypted values stored as base64 tokens
  created_by  INTEGER,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  deleted_at  TEXT,                        -- v7: set = in the trash; NULL = live
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE files (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id    INTEGER NOT NULL,
  field_key    TEXT NOT NULL,
  filename     TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes   INTEGER NOT NULL,
  data         BLOB NOT NULL,   -- Fernet-encrypted file bytes (v3: the `file` field type)
  uploaded_by  INTEGER,
  uploaded_at  TEXT NOT NULL,
  FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
  FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE alert_dismissals (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id       INTEGER NOT NULL,
  field_key       TEXT NOT NULL,
  dismissed_value TEXT NOT NULL,   -- the date (YYYY-MM-DD) current when dismissed
  dismissed_tier  TEXT NOT NULL,   -- 'upcoming' | 'overdue' -- severity at dismiss time
  dismissed_by    INTEGER,
  dismissed_at    TEXT NOT NULL,
  FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
  FOREIGN KEY (dismissed_by) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE (record_id, field_key)
);

-- v7: append-only audit trail. No foreign keys to categories/records -- an
-- entry must survive the thing it describes being deleted, so identity is
-- denormalized as plain id + name/label columns instead of a live join.
CREATE TABLE audit_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,
  user_id       INTEGER,
  username      TEXT NOT NULL,
  action        TEXT NOT NULL,
  category_id   INTEGER,
  category_name TEXT,
  record_id     INTEGER,
  record_label  TEXT,
  detail        TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- v9: cross-category tags, free-form, independent of category/field structure.
CREATE TABLE tags (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE
);
CREATE TABLE record_tags (
  record_id INTEGER NOT NULL,
  tag_id    INTEGER NOT NULL,
  PRIMARY KEY (record_id, tag_id),
  FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
  FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_fields_category ON fields(category_id, sort_order);
CREATE INDEX idx_records_category ON records(category_id, updated_at);
CREATE INDEX idx_records_deleted ON records(deleted_at);
CREATE INDEX idx_files_record ON files(record_id, field_key);
CREATE INDEX idx_audit_ts ON audit_log(id DESC);
CREATE INDEX idx_record_tags_tag ON record_tags(tag_id);

-- Global full-text search. Content is rebuilt from records.data + categories.name
-- on every record insert/update/delete (see myvault/search.py).
CREATE VIRTUAL TABLE records_fts USING fts5(
  record_id UNINDEXED,
  category_id UNINDEXED,
  category_name,
  content,
  tokenize = 'porter'
);
