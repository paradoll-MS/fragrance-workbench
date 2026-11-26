"""Table definitions. Every business field that gates a decision lives in a column."""

SCHEMA_VERSION = 1

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 项目：一次客户委托、一次内部升级或一次主动开发
CREATE TABLE IF NOT EXISTS project(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'customer',
  name TEXT NOT NULL,
  customer TEXT NOT NULL DEFAULT '',
  code TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);

-- 资料原件与按格式读出的段
CREATE TABLE IF NOT EXISTS source(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES project(id),
  name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  raw BLOB NOT NULL,
  extracted TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TEXT NOT NULL,
  UNIQUE(project_id, name, sha256)
);

-- 一次拆解提案：模型原始输出，待人工确认
CREATE TABLE IF NOT EXISTS parse_draft(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES project(id),
  source_ids TEXT NOT NULL DEFAULT '[]',
  result TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  seconds REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL
);

-- 子项：一个独立交付目标。开发子项通过 parent 回到父目标位
CREATE TABLE IF NOT EXISTS subproject(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES project(id),
  requirement_type TEXT NOT NULL,
  final_endpoint TEXT NOT NULL DEFAULT 'shipment',
  parent_id INTEGER REFERENCES subproject(id),
  parent_slot_id INTEGER,
  inherit_id INTEGER REFERENCES subproject(id),
  source_round_id INTEGER,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- 轮次：同一子项的一次推荐
CREATE TABLE IF NOT EXISTS round(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subproject_id INTEGER NOT NULL REFERENCES subproject(id),
  no INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'initial',
  previous_round_id INTEGER,
  brief TEXT NOT NULL DEFAULT '{}',
  query_id INTEGER,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  UNIQUE(subproject_id, no)
);

-- 目标：一种实际交付的香精（或一条明确的复寄）
CREATE TABLE IF NOT EXISTS goal(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subproject_id INTEGER NOT NULL REFERENCES subproject(id),
  round_id INTEGER NOT NULL REFERENCES round(id),
  label TEXT NOT NULL,
  is_required INTEGER NOT NULL DEFAULT 0,
  endpoint TEXT NOT NULL DEFAULT 'shipment',
  requested_count INTEGER,
  fields TEXT NOT NULL DEFAULT '{}',
  provenance TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

-- 目标位：一个目标的一次执行方案
CREATE TABLE IF NOT EXISTS slot(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL REFERENCES round(id),
  goal_id INTEGER NOT NULL REFERENCES goal(id),
  strategy TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'planned',
  revision INTEGER NOT NULL DEFAULT 1,
  fragrance_id TEXT NOT NULL DEFAULT '',
  formula_version TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

-- 检查集：一款香精一个版本在一个用途范围下的一次要求快照
CREATE TABLE IF NOT EXISTS check_set(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL REFERENCES slot(id),
  fragrance_id TEXT NOT NULL,
  formula_version TEXT NOT NULL DEFAULT '',
  scope TEXT NOT NULL,
  review_category TEXT NOT NULL DEFAULT '',
  markets TEXT NOT NULL DEFAULT '[]',
  context TEXT NOT NULL DEFAULT '{}',
  coverage TEXT NOT NULL DEFAULT '[]',
  rules_version TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- 要求：默认、条件或客户提出的一条可核销要求
CREATE TABLE IF NOT EXISTS requirement(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_set_id INTEGER NOT NULL REFERENCES check_set(id),
  metric_id TEXT NOT NULL,
  subitem TEXT NOT NULL DEFAULT '',
  department TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'default',
  source_key TEXT NOT NULL DEFAULT 'default',
  origin_text TEXT NOT NULL DEFAULT '',
  mandatory INTEGER NOT NULL DEFAULT 1,
  deferral TEXT NOT NULL DEFAULT 'allowed',
  criteria TEXT NOT NULL DEFAULT '',
  conditions TEXT NOT NULL DEFAULT '{}',
  conditions_key TEXT NOT NULL DEFAULT '',
  due_stage TEXT NOT NULL DEFAULT 'before_release',
  status TEXT NOT NULL DEFAULT 'unverified',
  evidence_id INTEGER,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(check_set_id, metric_id, subitem, source_key)
);

-- 证据：部门回执沉淀，按香精与版本复用
CREATE TABLE IF NOT EXISTS evidence(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fragrance_id TEXT NOT NULL,
  formula_version TEXT NOT NULL DEFAULT '',
  metric_id TEXT NOT NULL,
  subitem TEXT NOT NULL DEFAULT '',
  conditions_key TEXT NOT NULL DEFAULT '',
  conditions TEXT NOT NULL DEFAULT '{}',
  verdict TEXT NOT NULL,
  measured TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL DEFAULT '',
  document TEXT NOT NULL DEFAULT '',
  tested_at TEXT NOT NULL DEFAULT '',
  valid_until TEXT NOT NULL DEFAULT '',
  task_id INTEGER,
  approved_by TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT 'accepted',
  created_at TEXT NOT NULL
);

-- 放行决定
CREATE TABLE IF NOT EXISTS release_decision(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_set_id INTEGER NOT NULL REFERENCES check_set(id),
  slot_id INTEGER NOT NULL REFERENCES slot(id),
  action TEXT NOT NULL,
  verdict TEXT NOT NULL,
  blockers TEXT NOT NULL DEFAULT '[]',
  deferred TEXT NOT NULL DEFAULT '[]',
  reason TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- 开发任务：仿香、创香、改香，挂在目标位下，完成后回父目标位
CREATE TABLE IF NOT EXISTS job(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subproject_id INTEGER NOT NULL REFERENCES subproject(id),
  slot_id INTEGER NOT NULL REFERENCES slot(id),
  dev_type TEXT NOT NULL,
  brief TEXT NOT NULL DEFAULT '{}',
  reference TEXT NOT NULL DEFAULT '{}',
  gc_report TEXT NOT NULL DEFAULT '',
  current_iteration INTEGER NOT NULL DEFAULT 1,
  approved_trial_id INTEGER,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trial(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  iteration INTEGER NOT NULL,
  trial_fragrance_id TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  sample_id TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(job_id, iteration)
);

CREATE TABLE IF NOT EXISTS evaluation(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trial_id INTEGER NOT NULL REFERENCES trial(id),
  verdict TEXT NOT NULL,
  comments TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse_record(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL REFERENCES slot(id),
  task_id INTEGER,
  fragrance_id TEXT NOT NULL,
  formula_version TEXT NOT NULL DEFAULT '',
  approved_by TEXT NOT NULL DEFAULT '',
  check_set_id INTEGER,
  release_decision_id INTEGER,
  created_at TEXT NOT NULL
);

-- 寄样行：以实际寄出记录为准
CREATE TABLE IF NOT EXISTS shipment(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL REFERENCES slot(id),
  goal_id INTEGER NOT NULL REFERENCES goal(id),
  task_id INTEGER,
  kind TEXT NOT NULL,
  fragrance_id TEXT NOT NULL,
  formula_version TEXT NOT NULL DEFAULT '',
  sample_id TEXT NOT NULL DEFAULT '',
  sample_form TEXT NOT NULL DEFAULT '',
  quantity TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  tracking TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'applied',
  shipped_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 部门任务：中台适配层唯一写入的业务单据
CREATE TABLE IF NOT EXISTS task(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES project(id),
  subproject_id INTEGER,
  round_id INTEGER,
  slot_id INTEGER,
  department TEXT NOT NULL,
  task_type TEXT NOT NULL,
  spec TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  attempt INTEGER NOT NULL DEFAULT 1,
  external_id TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 等待与阻断：业务阻断用 Issue 表达，不用异常
CREATE TABLE IF NOT EXISTS issue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type TEXT NOT NULL,
  scope_id INTEGER NOT NULL,
  code TEXT NOT NULL,
  node TEXT NOT NULL DEFAULT '',
  missing TEXT NOT NULL DEFAULT '[]',
  waiting TEXT NOT NULL DEFAULT '[]',
  next_action TEXT NOT NULL DEFAULT '',
  resume_events TEXT NOT NULL DEFAULT '[]',
  owner TEXT NOT NULL DEFAULT '',
  due_at TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL DEFAULT '',
  UNIQUE(scope_type, scope_id, code)
);

CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  command TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 0,
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- 人工改动与中台数据
CREATE TABLE IF NOT EXISTS asset_edit(
  asset_key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quote(
  code TEXT PRIMARY KEY,
  price TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_default(
  department TEXT PRIMARY KEY,
  result INTEGER NOT NULL
);

-- 选香快照
CREATE TABLE IF NOT EXISTS search_run(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES project(id),
  fingerprint TEXT NOT NULL,
  input TEXT NOT NULL,
  preview TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_subproject_project ON subproject(project_id);
CREATE INDEX IF NOT EXISTS idx_round_subproject ON round(subproject_id);
CREATE INDEX IF NOT EXISTS idx_goal_round ON goal(round_id);
CREATE INDEX IF NOT EXISTS idx_slot_goal ON slot(goal_id);
CREATE INDEX IF NOT EXISTS idx_check_set_slot ON check_set(slot_id, scope, revision);
CREATE INDEX IF NOT EXISTS idx_requirement_set ON requirement(check_set_id, status);
CREATE INDEX IF NOT EXISTS idx_evidence_match ON evidence(fragrance_id, metric_id, subitem, conditions_key);
CREATE INDEX IF NOT EXISTS idx_issue_scope ON issue(scope_type, scope_id, state);
CREATE INDEX IF NOT EXISTS idx_task_slot ON task(slot_id, status);
CREATE INDEX IF NOT EXISTS idx_shipment_slot ON shipment(slot_id, kind);
"""
