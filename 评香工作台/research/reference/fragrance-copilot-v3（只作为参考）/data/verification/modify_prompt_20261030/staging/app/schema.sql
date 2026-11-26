
PRAGMA foreign_keys=ON;
CREATE TABLE library_items(
 code TEXT PRIMARY KEY, name TEXT, new_class TEXT, co_classes_json TEXT,
 central INTEGER, price REAL, price_text TEXT, grade TEXT, family TEXT,
 subfamily TEXT, notes TEXT, perfumer TEXT, usage_count INTEGER,
 is_hot INTEGER, is_new INTEGER, central_hot INTEGER, central_new INTEGER,
 is_brand_dupe INTEGER, is_brand_reference INTEGER, primary_brand TEXT,
 brand_tags_json TEXT, brand_labels_json TEXT, c_ids_json TEXT,
 a1_ids_json TEXT, a2_ids_json TEXT, a3_ids_json TEXT
);
CREATE TABLE library_tags(
 code TEXT NOT NULL, domain TEXT NOT NULL, tag_id TEXT NOT NULL,
 layer TEXT, label TEXT, path TEXT, scope TEXT, context_class TEXT,
 c_new_class TEXT, c_dimension TEXT,
 PRIMARY KEY(code, domain, tag_id, scope, context_class)
);
CREATE INDEX idx_lt_code ON library_tags(code);
CREATE INDEX idx_lt_c ON library_tags(domain, tag_id, scope);
CREATE TABLE c_nodes(
 id TEXT PRIMARY KEY, new_class TEXT, dimension TEXT, parent_id TEXT,
 label TEXT, path TEXT, description TEXT
);
CREATE TABLE terms(
 id TEXT PRIMARY KEY, domain TEXT, layer TEXT, label TEXT,
 definition TEXT, parent_id TEXT
);
CREATE TABLE term_aliases(
 alias TEXT PRIMARY KEY, term_id TEXT, scope TEXT
);
CREATE TABLE c_ab(
 c_id TEXT NOT NULL, term_id TEXT NOT NULL, domain TEXT, label TEXT, layer TEXT,
 PRIMARY KEY(c_id, term_id)
);
CREATE INDEX idx_cab_c ON c_ab(c_id);
CREATE TABLE formula_product_labels(
 code TEXT NOT NULL, brand TEXT NOT NULL, product TEXT NOT NULL,
 relation TEXT, source TEXT, PRIMARY KEY(code, brand, product, relation, source)
);
CREATE INDEX idx_fpl_brand ON formula_product_labels(brand, product);
CREATE INDEX idx_fpl_code ON formula_product_labels(code);
CREATE TABLE category_map(
 k_code TEXT PRIMARY KEY, level1 TEXT, level2 TEXT, level3 TEXT,
 norm_class TEXT, new_class TEXT, aliases_json TEXT, identity_json TEXT,
 norm_status TEXT, new_status TEXT
);
CREATE TABLE projects(
 id TEXT PRIMARY KEY, name TEXT, customer TEXT, brand TEXT, sales TEXT,
 evaluator TEXT, grade TEXT, status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE artifacts(
 id TEXT PRIMARY KEY, project_id TEXT, filename TEXT, stored_name TEXT,
 mime TEXT, text TEXT, text_meta_json TEXT, source_type TEXT, role TEXT,
 note TEXT, status TEXT, created_at TEXT
);
CREATE TABLE briefs(
 id TEXT PRIMARY KEY, project_id TEXT, subproject_id TEXT, data_json TEXT,
 narrative TEXT, status TEXT, version INTEGER, created_at TEXT, updated_at TEXT
);
CREATE TABLE subprojects(
 id TEXT PRIMARY KEY, project_id TEXT, title TEXT, task_type TEXT, status TEXT,
 category_l1 TEXT, category_l2 TEXT, category_l3 TEXT, norm_class TEXT,
 new_class TEXT, target_c TEXT, a1_json TEXT, a2_json TEXT, a3_json TEXT,
 brand_filter TEXT, target_products_json TEXT, price_target REAL,
 price_elasticity REAL, endpoint TEXT, brief_id TEXT, parent_subproject_id TEXT,
 created_at TEXT, updated_at TEXT
);
CREATE TABLE external_samples(
 id TEXT PRIMARY KEY, project_id TEXT, subproject_id TEXT, received_at TEXT,
 received_by TEXT, source TEXT, brand TEXT, product TEXT, version TEXT,
 description TEXT, analysis_status TEXT, analysis_result TEXT,
 matched_formula_ids_json TEXT, result TEXT, notes TEXT
);
CREATE TABLE department_tasks(
 id TEXT PRIMARY KEY, subproject_id TEXT, type TEXT, title TEXT, detail TEXT,
 owner TEXT, department TEXT, due TEXT, status TEXT, depends_on_json TEXT,
 payload_json TEXT, result TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE recommendations(
 id TEXT PRIMARY KEY, subproject_id TEXT, filters_json TEXT, algorithm TEXT,
 created_at TEXT
);
CREATE TABLE recommendation_items(
 id TEXT PRIMARY KEY, recommendation_id TEXT, code TEXT, rank INTEGER,
 ab_score INTEGER, ab_hits_json TEXT, price_gap REAL, reason TEXT,
 decision TEXT, note TEXT
);
CREATE TABLE decisions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT, entity_id TEXT, field TEXT,
 old_value TEXT, new_value TEXT, actor TEXT, reason TEXT, created_at TEXT
);
CREATE TABLE stories(
 id TEXT PRIMARY KEY, project_id TEXT, sections_json TEXT, search_text TEXT,
 updated_at TEXT
);
