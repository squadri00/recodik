-- MyVault schema v1
-- Applied once on a fresh database. Versioned via meta.value where key='schema_version'.

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
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_fields_category ON fields(category_id, sort_order);
CREATE INDEX idx_records_category ON records(category_id, updated_at);

-- Global full-text search. Content is rebuilt from records.data + categories.name
-- on every record insert/update/delete (see myvault/search.py).
CREATE VIRTUAL TABLE records_fts USING fts5(
  record_id UNINDEXED,
  category_id UNINDEXED,
  category_name,
  content,
  tokenize = 'porter'
);
