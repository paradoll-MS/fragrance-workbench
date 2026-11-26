from __future__ import annotations

import json
import sqlite3
import time
import uuid
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "app.sqlite3"
UPLOADS = DATA / "uploads"
EXPORTS = DATA / "exports"
CONFIG_PATH = DATA / "config.json"
_LOCK = threading.RLock()
_READY = set()


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    with _LOCK:
        if str(DB_PATH) not in _READY:
            con.execute('PRAGMA journal_mode=WAL')
            if not con.execute("select 1 from sqlite_master where name='projects'").fetchone():
                con.executescript((ROOT / 'app/schema.sql').read_text(encoding='utf-8'))
            _migrate_v3(con)
            con.commit()
            _READY.add(str(DB_PATH))
    con.execute("""CREATE TABLE IF NOT EXISTS llm_calls(
        id TEXT PRIMARY KEY, project_id TEXT, node TEXT, provider TEXT, model TEXT,
        prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
        cost REAL, elapsed REAL, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS terms(
        id TEXT PRIMARY KEY, domain TEXT, layer TEXT, label TEXT,
        definition TEXT, parent_id TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS term_aliases(
        alias TEXT PRIMARY KEY, term_id TEXT, scope TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS endpoint_checks(
        subproject_id TEXT NOT NULL, section TEXT NOT NULL, code TEXT NOT NULL,
        label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        source TEXT NOT NULL DEFAULT 'default', detail TEXT,
        note TEXT, updated_at TEXT, PRIMARY KEY(subproject_id, code))""")
    for col, ddl in (("source", "TEXT NOT NULL DEFAULT 'default'"), ("detail", "TEXT")):
        try:
            con.execute(f"ALTER TABLE endpoint_checks ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    # additive migration for modify base
    try:
        con.execute("ALTER TABLE subprojects ADD COLUMN base_formula_code TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE subprojects ADD COLUMN direction TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE recommendation_items ADD COLUMN c_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE recommendation_items ADD COLUMN c_score INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE subprojects ADD COLUMN target_cs_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE artifacts ADD COLUMN parse_error TEXT")
    except sqlite3.OperationalError:
        pass
    for col, ddl in (("c_weight", "REAL DEFAULT 3"), ("ab_weight", "REAL DEFAULT 1"),
                     ("category_source", "TEXT DEFAULT 'rule'"), ("category_confidence", "REAL DEFAULT 1"),
                     ("category_candidates_json", "TEXT"), ("c_basis_json", "TEXT"),
                     ("a1_hard", "INTEGER DEFAULT 1")):
        try:
            con.execute(f"ALTER TABLE subprojects ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    return con


def _migrate_v3(con):
    con.execute('''CREATE TABLE IF NOT EXISTS identity_aliases(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('brand','product')),
        brand TEXT NOT NULL, product TEXT NOT NULL DEFAULT '', alias TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'user_confirmed', created_at TEXT NOT NULL,
        UNIQUE(kind,brand,product,alias))''')
    con.execute('''CREATE TABLE IF NOT EXISTS llm_calls(
        id TEXT PRIMARY KEY, project_id TEXT, node TEXT, provider TEXT, model TEXT,
        prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
        cost REAL, elapsed REAL, created_at TEXT)''')
    additions = {
        'llm_calls': {'details_json': "TEXT DEFAULT '{}'"},
        'projects': {'customer_info_json': "TEXT DEFAULT '{}'", 'coordination_json': "TEXT DEFAULT '{}'"},
        'subprojects': {
            'customer_requirements_json': "TEXT DEFAULT '[]'",
            'planning_json': "TEXT DEFAULT '{}'", 'base_sample_reference': 'TEXT',
            'b_json': "TEXT DEFAULT '[]'", 'hard_filters_json': 'TEXT',
            'brand_requirements_json': "TEXT DEFAULT '[]'", 'wants_hot': 'INTEGER DEFAULT 0',
            'wants_new': 'INTEGER DEFAULT 0', 'abc_basis_json': "TEXT DEFAULT '{}'",
            'source_refs_json': "TEXT DEFAULT '[]'", 'understanding_key': 'TEXT',
            'selected_codes_json': "TEXT DEFAULT '[]'", 'workflow_stage': "TEXT DEFAULT 'draft'",
            'type_history_json': "TEXT DEFAULT '[]'", 'context_json': "TEXT DEFAULT '{}'",
        },
        'artifacts': {'annotation_json': "TEXT DEFAULT '{}'", 'updated_at': 'TEXT'},
        'recommendation_items': {'snapshot_json': 'TEXT'},
    }
    for table, cols in additions.items():
        existing = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        for col, ddl in cols.items():
            if col not in existing:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    con.executescript('''
        CREATE TABLE IF NOT EXISTS app_migrations(key TEXT PRIMARY KEY, applied_at TEXT);
        CREATE TABLE IF NOT EXISTS generation_runs(
          id TEXT PRIMARY KEY, project_id TEXT, status TEXT, stage TEXT, fingerprint TEXT,
          input_json TEXT, output_json TEXT, error TEXT, created_at TEXT, updated_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS generation_one_active ON generation_runs(project_id)
          WHERE status IN ('queued','running');
        CREATE TABLE IF NOT EXISTS brief_history(
          id TEXT PRIMARY KEY, brief_id TEXT, project_id TEXT, subproject_id TEXT,
          version INTEGER, data_json TEXT, actor TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS task_files(
          id TEXT PRIMARY KEY, task_id TEXT, filename TEXT, stored_name TEXT, mime TEXT, created_at TEXT);
    ''')
    if not one(con, "select key from app_migrations where key='v3_import'"):
        # V2 created all department templates on GET. Unstarted empty templates are not dispatched work.
        con.execute("""update department_tasks set status='cancelled',result='v2 未派发模板归档；v3 按实际流程重建'
                       where status='todo' and coalesce(payload_json,'') in ('','{}')
                       and coalesce(depends_on_json,'') in ('','[]') and coalesce(result,'')=''""")
        con.execute("insert into app_migrations values('v3_import',?)", (now(),))


def save_brief(con, project_id, value, subproject_id=None, actor='llm'):
    from .model import brief
    value = brief(value)
    old = one(con, "select * from briefs where project_id=? and coalesce(subproject_id,'')=? order by version desc limit 1",
              (project_id, subproject_id or ''))
    bid = old['id'] if old else uid('b_')
    version = old['version'] + 1 if old else 1
    if old:
        con.execute('update briefs set data_json=?,version=?,status=?,updated_at=? where id=?',
                    (js(value), version, 'edited' if actor == 'evaluator' else 'draft', now(), bid))
    else:
        con.execute('insert into briefs(id,project_id,subproject_id,data_json,status,version,created_at,updated_at) values(?,?,?,?,?,?,?,?)',
                    (bid, project_id, subproject_id, js(value), 'draft', version, now(), now()))
    con.execute('insert into brief_history values(?,?,?,?,?,?,?,?)',
                (uid('bh_'), bid, project_id, subproject_id, version, js(value), actor, now()))
    return bid


def rows(con, sql, params=()):
    return [dict(x) for x in con.execute(sql, params).fetchall()]


def one(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def js(v):
    return json.dumps(v, ensure_ascii=False)


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def audit(con, entity, entity_id, field, old, new, actor="evaluator", reason=""):
    con.execute(
        "insert into decisions(entity,entity_id,field,old_value,new_value,actor,reason,created_at) values(?,?,?,?,?,?,?,?)",
        (entity, entity_id, field, js(old), js(new), actor, reason, now()),
    )
