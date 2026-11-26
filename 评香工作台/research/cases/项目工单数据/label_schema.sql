CREATE TABLE IF NOT EXISTS library_label_runs (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, rule_version TEXT NOT NULL,
  taxonomy_file TEXT NOT NULL, taxonomy_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_taxonomy (
  id TEXT PRIMARY KEY, parent_id TEXT REFERENCES library_taxonomy(id), name TEXT NOT NULL,
  depth INTEGER NOT NULL, new_class TEXT, dimension TEXT, label_path TEXT NOT NULL,
  full_path TEXT NOT NULL, source_node_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_labels (
  formula_id TEXT PRIMARY KEY REFERENCES formula_refs(id),
  new_class_id TEXT REFERENCES library_taxonomy(id), class_basis TEXT NOT NULL,
  evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
  run_id TEXT NOT NULL REFERENCES library_label_runs(id),
  review_status TEXT NOT NULL DEFAULT 'trial' CHECK(review_status IN ('trial','confirmed','edited')),
  review_note TEXT, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS library_dimension_tags (
  formula_id TEXT NOT NULL REFERENCES library_labels(formula_id),
  dimension TEXT NOT NULL CHECK(dimension IN ('核心定位','香气感知与情绪','场景风格适配','常见香型香调')),
  taxonomy_id TEXT NOT NULL REFERENCES library_taxonomy(id), basis TEXT NOT NULL,
  PRIMARY KEY(formula_id,dimension,taxonomy_id)
);
CREATE TABLE IF NOT EXISTS library_review_history (
  id INTEGER PRIMARY KEY, formula_id TEXT NOT NULL, saved_at TEXT NOT NULL,
  old_json TEXT NOT NULL, new_json TEXT NOT NULL, review_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_label_class ON library_labels(new_class_id);
CREATE INDEX IF NOT EXISTS idx_library_tag_dimension ON library_dimension_tags(dimension,taxonomy_id);
CREATE TABLE IF NOT EXISTS library_history_reviews (
  formula_id TEXT NOT NULL REFERENCES library_labels(formula_id), context_key TEXT NOT NULL,
  project_number TEXT, project_name TEXT, work_order_id TEXT, work_order_number TEXT,
  relation_kind TEXT NOT NULL, semantic_kind TEXT NOT NULL, judgment TEXT NOT NULL,
  external_names_json TEXT NOT NULL CHECK(json_valid(external_names_json)),
  note_ids_json TEXT NOT NULL CHECK(json_valid(note_ids_json)),
  run_id TEXT NOT NULL REFERENCES library_label_runs(id),
  PRIMARY KEY(formula_id,context_key)
);
CREATE INDEX IF NOT EXISTS idx_history_project ON library_history_reviews(project_number);
CREATE TRIGGER IF NOT EXISTS library_tag_scope BEFORE INSERT ON library_dimension_tags
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM library_labels l JOIN library_taxonomy cls ON cls.id=l.new_class_id
    JOIN library_taxonomy tag ON tag.id=NEW.taxonomy_id
    WHERE l.formula_id=NEW.formula_id AND tag.new_class=cls.name
      AND tag.dimension=NEW.dimension AND tag.depth>=3
  ) THEN RAISE(ABORT,'标签不属于该新类及维度') END;
END;
CREATE VIEW IF NOT EXISTS v_library_labels AS
SELECT f.id AS formula_id,f.code,f.name,cls.name AS new_class,
  (SELECT group_concat(t.label_path,'；') FROM library_dimension_tags d JOIN library_taxonomy t ON t.id=d.taxonomy_id WHERE d.formula_id=f.id AND d.dimension='核心定位') AS core_position,
  (SELECT group_concat(t.label_path,'；') FROM library_dimension_tags d JOIN library_taxonomy t ON t.id=d.taxonomy_id WHERE d.formula_id=f.id AND d.dimension='香气感知与情绪') AS scent_feeling,
  (SELECT group_concat(t.label_path,'；') FROM library_dimension_tags d JOIN library_taxonomy t ON t.id=d.taxonomy_id WHERE d.formula_id=f.id AND d.dimension='场景风格适配') AS scene_style,
  (SELECT group_concat(t.label_path,'；') FROM library_dimension_tags d JOIN library_taxonomy t ON t.id=d.taxonomy_id WHERE d.formula_id=f.id AND d.dimension='常见香型香调') AS scent_family,
  l.review_status,l.class_basis,l.review_note,l.reviewed_at,l.run_id
FROM formula_refs f LEFT JOIN library_labels l ON l.formula_id=f.id LEFT JOIN library_taxonomy cls ON cls.id=l.new_class_id
WHERE f.is_central=1;
