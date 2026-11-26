PRAGMA foreign_keys = ON;

CREATE TABLE imports (
  id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, source_root TEXT NOT NULL
);
CREATE TABLE source_files (
  id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id),
  path TEXT NOT NULL, sha256 TEXT NOT NULL, source_kind TEXT NOT NULL, exported_at TEXT
);
CREATE TABLE source_records (
  id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES source_files(id),
  source_table TEXT NOT NULL, source_key TEXT NOT NULL, locator TEXT NOT NULL,
  raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT, department TEXT,
  UNIQUE(file_id, source_table, source_key)
);
CREATE TABLE customers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE projects (
  id TEXT PRIMARY KEY, number TEXT, name TEXT NOT NULL,
  customer_id TEXT REFERENCES customers(id), sales_names TEXT, evaluator_names TEXT,
  target_price_text TEXT, source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE work_orders (
  id TEXT PRIMARY KEY, number TEXT, project_id TEXT REFERENCES projects(id), title TEXT,
  category TEXT, category_group TEXT, target_price_text TEXT, reported_stage TEXT,
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE formula_refs (
  id TEXT PRIMARY KEY, code TEXT UNIQUE, name TEXT, is_central INTEGER NOT NULL DEFAULT 0 CHECK(is_central IN (0,1))
);
CREATE TABLE catalog_entries (
  id TEXT PRIMARY KEY, formula_id TEXT NOT NULL REFERENCES formula_refs(id), name TEXT,
  category1 TEXT, category2 TEXT, category3 TEXT, family TEXT, subfamily TEXT,
  note_text TEXT, keywords TEXT, perfumer TEXT, grade TEXT, origin TEXT,
  price_text TEXT, price_value REAL, source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE sample_occurrences (
  id TEXT PRIMARY KEY, work_order_id TEXT NOT NULL REFERENCES work_orders(id),
  formula_id TEXT REFERENCES formula_refs(id), internal_name TEXT, external_code TEXT, external_name TEXT,
  weight_text TEXT, weight_g REAL, dosage_text TEXT,
  unit_price_text TEXT, unit_price REAL, sample_amount_text TEXT, sample_amount REAL,
  reported_ship_date TEXT, delivery_note TEXT,
  storage_location TEXT, stock_qty_text TEXT, stock_qty REAL, perfumer_qty_text TEXT, perfumer_qty REAL,
  data_state TEXT NOT NULL DEFAULT 'current' CHECK(data_state IN ('current','not_in_latest_export')),
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE attributes (
  id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  field TEXT NOT NULL, label TEXT NOT NULL, value TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE aliases (
  id INTEGER PRIMARY KEY, formula_id TEXT NOT NULL REFERENCES formula_refs(id),
  name TEXT NOT NULL, alias_kind TEXT NOT NULL,
  project_id TEXT REFERENCES projects(id), sample_id TEXT REFERENCES sample_occurrences(id),
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE notes (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), role TEXT NOT NULL,
  text TEXT NOT NULL, is_shared INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE note_links (
  note_id TEXT NOT NULL REFERENCES notes(id), source_id TEXT NOT NULL REFERENCES source_records(id),
  source_field TEXT NOT NULL, work_order_id TEXT REFERENCES work_orders(id),
  sample_id TEXT REFERENCES sample_occurrences(id),
  UNIQUE(note_id,source_id,source_field)
);
CREATE TABLE attachments (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
  work_order_id TEXT REFERENCES work_orders(id), name TEXT, remote_file_id TEXT,
  source_id TEXT NOT NULL REFERENCES source_records(id), source_field TEXT NOT NULL, metadata_json TEXT NOT NULL
);
CREATE TABLE shipment_mentions (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
  work_order_id TEXT NOT NULL REFERENCES work_orders(id), sample_id TEXT REFERENCES sample_occurrences(id),
  reported_date TEXT, tracking_text TEXT, tracking_number TEXT, handoff_mode TEXT,
  origin_text TEXT, recipient TEXT, receiving_info TEXT,
  source_id TEXT NOT NULL REFERENCES source_records(id), date_basis TEXT NOT NULL
);
CREATE TABLE physical_samples (
  id TEXT PRIMARY KEY, formula_id TEXT REFERENCES formula_refs(id), record_kind TEXT NOT NULL,
  location TEXT, quantity_text TEXT, recorded_date TEXT, name TEXT,
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE events (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), work_order_id TEXT REFERENCES work_orders(id),
  sample_id TEXT REFERENCES sample_occurrences(id), event_type TEXT NOT NULL,
  event_time TEXT NOT NULL, time_basis TEXT NOT NULL, actor TEXT, description TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source_records(id)
);
CREATE TABLE directions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), name TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source_records(id), evidence TEXT NOT NULL,
  UNIQUE(project_id,name)
);
CREATE TABLE direction_links (
  direction_id TEXT NOT NULL REFERENCES directions(id), sample_id TEXT REFERENCES sample_occurrences(id),
  note_id TEXT REFERENCES notes(id), evidence TEXT NOT NULL,
  CHECK((sample_id IS NOT NULL) != (note_id IS NOT NULL))
);
CREATE TABLE formula_mentions (
  note_id TEXT NOT NULL REFERENCES notes(id), formula_id TEXT NOT NULL REFERENCES formula_refs(id),
  matched_code TEXT NOT NULL, relation_kind TEXT NOT NULL DEFAULT 'text_mention',
  PRIMARY KEY(note_id,formula_id)
);
CREATE TABLE record_links (
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source_records(id), PRIMARY KEY(entity_type,entity_id,source_id)
);
CREATE TABLE search_documents (
  id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  project_id TEXT REFERENCES projects(id), title TEXT NOT NULL, body TEXT NOT NULL
);
CREATE VIRTUAL TABLE search_fts USING fts5(title,body,content='search_documents',content_rowid='id',tokenize='trigram');
CREATE TABLE field_decisions (
  source_table TEXT NOT NULL, field TEXT NOT NULL, label TEXT,
  disposition TEXT NOT NULL, destination TEXT NOT NULL, reason TEXT NOT NULL,
  populated INTEGER NOT NULL, total INTEGER NOT NULL, PRIMARY KEY(source_table,field)
);

CREATE INDEX idx_projects_number ON projects(number);
CREATE INDEX idx_projects_customer ON projects(customer_id);
CREATE INDEX idx_work_project ON work_orders(project_id);
CREATE INDEX idx_work_number ON work_orders(number);
CREATE INDEX idx_samples_work ON sample_occurrences(work_order_id);
CREATE INDEX idx_samples_formula ON sample_occurrences(formula_id);
CREATE INDEX idx_samples_external ON sample_occurrences(external_code);
CREATE INDEX idx_alias_name ON aliases(name);
CREATE INDEX idx_alias_formula ON aliases(formula_id);
CREATE INDEX idx_notes_project ON notes(project_id);
CREATE INDEX idx_note_links_note ON note_links(note_id);
CREATE INDEX idx_events_project_time ON events(project_id,event_time);
CREATE INDEX idx_attrs_entity ON attributes(entity_type,entity_id);
CREATE INDEX idx_ship_work ON shipment_mentions(work_order_id);
CREATE INDEX idx_ship_tracking ON shipment_mentions(tracking_number);
CREATE INDEX idx_physical_formula ON physical_samples(formula_id);

CREATE VIEW v_project_overview AS
SELECT p.*, c.name AS customer_name, s.created_at, s.created_by, s.updated_at, s.updated_by,
  (SELECT count(*) FROM work_orders w WHERE w.project_id=p.id) AS work_order_count,
  (SELECT count(*) FROM sample_occurrences d JOIN work_orders w ON w.id=d.work_order_id WHERE w.project_id=p.id) AS sample_count
FROM projects p LEFT JOIN customers c ON c.id=p.customer_id JOIN source_records s ON s.id=p.source_id;

CREATE VIEW v_sample_trace AS
SELECT d.*, f.code AS internal_code, f.is_central, w.number AS work_order_number,
  w.project_id, p.number AS project_number, p.name AS project_name,
  c.name AS customer_name, s.created_at, s.created_by, s.updated_at, s.updated_by
FROM sample_occurrences d LEFT JOIN formula_refs f ON f.id=d.formula_id
JOIN work_orders w ON w.id=d.work_order_id LEFT JOIN projects p ON p.id=w.project_id
LEFT JOIN customers c ON c.id=p.customer_id JOIN source_records s ON s.id=d.source_id;

CREATE VIEW v_catalog AS
SELECT f.id AS formula_id, f.code, f.name, count(*) AS catalog_record_count,
  group_concat(DISTINCT e.name) AS catalog_names,
  group_concat(DISTINCT e.category1) AS category1,
  group_concat(DISTINCT e.category2) AS category2,
  group_concat(DISTINCT e.category3) AS category3,
  group_concat(DISTINCT e.family) AS family,
  group_concat(DISTINCT e.perfumer) AS perfumers
FROM formula_refs f JOIN catalog_entries e ON e.formula_id=f.id GROUP BY f.id;

CREATE VIEW v_note_context AS
SELECT n.*, max(s.updated_at) AS source_last_saved_at,
  count(*) AS source_record_count,
  group_concat(DISTINCT l.work_order_id) AS work_order_ids,
  group_concat(DISTINCT l.sample_id) AS sample_ids
FROM notes n JOIN note_links l ON l.note_id=n.id JOIN source_records s ON s.id=l.source_id GROUP BY n.id;

CREATE VIEW v_shipment_groups AS
SELECT project_id,tracking_number,count(*) AS mention_count,
  group_concat(DISTINCT work_order_id) AS work_order_ids,
  group_concat(DISTINCT reported_date) AS reported_dates,
  count(DISTINCT sample_id) AS sample_count
FROM shipment_mentions WHERE tracking_number IS NOT NULL GROUP BY project_id,tracking_number;
