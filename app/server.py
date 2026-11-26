import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from .catalog import Catalog, CONFIG, ROOT, canon
from .paths import resource_path
from .recommendation import LEVELS, comparable_price, normalize_query, evaluate_constraints, rank
from .targeting import map_brief
from .workflow import Workflow


WEB = ROOT / "web"
KINDS = {"analysis": "分析", "perfumery": "调香", "compliance": "合规",
         "quality": "质量", "application": "应用", "warehouse": "入库",
         "sample": "备样", "shipment": "寄样"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS asset_edits(asset_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes(code TEXT PRIMARY KEY, price TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mock_defaults(department TEXT PRIMARY KEY, result INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 department TEXT NOT NULL, title TEXT NOT NULL, spec TEXT NOT NULL,
 result INTEGER, result_note TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS decisions(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 fingerprint TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL,
 UNIQUE(project_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS query_runs(
 id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id),
 fingerprint TEXT NOT NULL, input TEXT NOT NULL, preview TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS feed(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(obj):
    return hashlib.sha256(encode(obj).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def state(self, db):
        changes = {r["asset_key"]: json.loads(r["payload"]) for r in db.execute("SELECT * FROM asset_edits")}
        quotes = {r["code"]: r["price"] for r in db.execute("SELECT * FROM quotes")}
        return changes, quotes

    @staticmethod
    def record(db, kind, data):
        db.execute("INSERT INTO feed(kind,payload) VALUES (?,?)", (kind, encode(data)))


class Workbench:
    def __init__(self, db_path):
        self.catalog = Catalog()
        self.store = Store(db_path)
        self.review_rules = json.loads((resource_path("审查") / "香精审查规则_轻量版.json").read_text(encoding="utf-8-sig"))
        self.workflow = Workflow(self.store, self.catalog, self.review_rules)

    def bootstrap(self):
        with self.store.connect() as db:
            projects = [dict(r) for r in db.execute("SELECT * FROM projects ORDER BY id DESC")]
        return {
            "categories": self.catalog.categories,
            "terms": [t for t in self.catalog.terms.values() if t.get("selectable", True)],
            "products": [{"id": p["product_id"], "name": p["product_name"], "brand": p["brand_name"]}
                         for p in self.catalog.products.values()],
            "brands": [{"id": b["brand_id"], "name": b["canonical_name"] or b["international_name"]}
                       for b in self.catalog.brands.values()],
            "projects": projects,
            "scoring_version": CONFIG["version"],
            "catalog_count": len(self.catalog.raw),
            "departments": KINDS,
            "mode_weights": CONFIG["modes"],
        }

    def dictionaries(self):
        review = self.review_rules
        return {
            "review_categories": [{"id": k, **v} for k, v in review["review_category_defaults"].items()],
            "metrics": [{"id": k, **v} for k, v in review["metric_dictionary"].items()],
            "links": [{"id": k, "name": self.catalog.terms[k]["name"], "tags": sorted(tags)}
                      for k, tags in self.catalog.edges.items()],
        }

    def sandbox_search(self, data):
        raw = data.get("query", {})
        mode = raw.get("mode", "recommend_simple")
        if mode not in CONFIG["modes"]:
            raise ValueError("请选择选香模式")
        weights = dict(CONFIG["modes"][mode])
        for key, value in data.get("weights", {}).items():
            if key not in weights:
                raise ValueError("未知的权重字段")
            value = float(value)
            if not math.isfinite(value) or not 0 <= value <= (100 if key in LEVELS else 1):
                raise ValueError("权重须为 0–100，映射系数须为 0–1")
            weights[key] = value
        if not any(weights[key] for key in LEVELS):
            raise ValueError("请保留一个正权重")
        config = {**CONFIG, "version": CONFIG["version"] + "-sandbox",
                  "modes": {**CONFIG["modes"], mode: weights}}
        with self.store.connect() as db:
            changes, quotes = self.store.state(db)
        rows = self.catalog.asset_rows(changes, quotes)
        if text := canon(data.get("term")):
            rows = (row for row in rows if text in canon(row["fragrance_id"]) or text in canon(row["card"]["name"]))
        result = rank(raw, rows, self.catalog.terms, self.catalog.categories, self.catalog.edges, config)
        return {**result, "total": len(result["results"]), "results": result["results"][:40],
                "alternatives": result["alternatives"][:10], "weights": weights}

    def search(self, data):
        query = data.get("query", {})
        with self.store.connect() as db:
            changes, quotes = self.store.state(db)
        product_relations = self.catalog.products_by_code()
        rows = self.catalog.asset_rows(changes, quotes, product_relations)
        if asset_search := canon(query.get("asset_search")):
            rows = (row for row in rows if asset_search in canon(row["fragrance_id"]) or
                    asset_search in canon(row["card"]["name"]))
        if query.get("mode") == "find_product":
            options = normalize_query({**query, "mode": "recommend_simple", "groups": []},
                                      self.catalog.terms, self.catalog.categories, CONFIG)
            product_id = str(query.get("product_id", ""))
            edition = query.get("edition")
            requested_edition = canon(edition)
            if edition and not requested_edition:
                raise ValueError("请输入有效版本，或留空")
            if product_id not in self.catalog.products:
                raise ValueError("请先指定目录产品")
            result = {"exact": True, "results": [], "alternatives": [], "clues": [],
                      "product": self.catalog.products[product_id], "diagnostics": {}}
            for row in rows:
                if row["conflict"]:
                    continue
                matches = [p for p in row["exact_products"] if p["product_id"] == product_id]
                if not matches:
                    continue
                confirmed = any(p["status"] == "confirmed" and (
                    not requested_edition or canon(p["edition"]) == requested_edition
                ) for p in matches)
                card = {**row["card"], "identity": matches, "score": None,
                        "reason": "目录关系已确认" if confirmed else "产品关系待确认", "risks": []}
                if not confirmed:
                    result["clues"].append(card)
                    continue
                constraints = [evaluate_constraints(row, options, cat, ([], [], set()), set())
                               for cat in options["categories"] or [None]]
                blocked, price_issues = min(constraints, key=lambda item: len(item[0]))
                card["risks"] = price_issues + [b for b in blocked if b != "价格"]
                result["alternatives" if blocked else "results"].append(card)
        else:
            result = rank(query, rows, self.catalog.terms, self.catalog.categories, self.catalog.edges, CONFIG)
            if any(card["positive_score"] is not None for card in result["results"]):
                unscored = [card for card in result["results"] if card["positive_score"] == 0]
                result["results"] = [card for card in result["results"] if card["positive_score"] != 0]
                result["unmatched_total"] = len(unscored)
                result["unmatched_preview"] = unscored[:10]
        full_result_count = len(result["results"])
        full_alternatives_count = len(result["alternatives"])
        result["total"] = full_result_count
        result["alternatives_total"] = full_alternatives_count
        limit = 30
        page = max(1, min(500, int(data.get("page", 1))))
        result["results"] = result["results"][(page - 1) * limit:page * limit]
        result["alternatives"] = result["alternatives"][:12]
        selected = data.get("project_id")
        if selected and page == 1:
            basis = {"catalog": self.catalog.version, "dictionary": self.catalog.dictionary_version,
                     "config": CONFIG, "asset_edits": changes, "quotes": quotes,
                     "product_relations": fingerprint({key: list(val.values()) for key, val in product_relations.items()}),
                     "query": result.get("query", query)}
            key = fingerprint(basis)
            with self.store.connect() as db:
                previous = db.execute("SELECT id,input FROM query_runs WHERE project_id=? ORDER BY id DESC LIMIT 1",
                                      (selected,)).fetchone()
                ins = db.execute("INSERT OR IGNORE INTO query_runs(project_id,fingerprint,input,preview) VALUES (?,?,?,?)",
                                 (selected, key, encode(basis), encode(result)))
                current = db.execute("SELECT id FROM query_runs WHERE project_id=? AND fingerprint=?",
                                     (selected, key)).fetchone()
                result["query_id"] = current["id"]
                if ins.rowcount and previous:
                    previous_query = json.loads(previous["input"])["query"]
                    if previous_query != basis["query"] and data.get("manual"):
                        self.store.record(db, "需求筛选修改", {"project_id": selected,
                                                               "from_query_id": previous["id"], "query_id": current["id"],
                                                               "before": previous_query, "after": basis["query"]})
        return result

    def project(self, data):
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("请填写项目名称")
        brief = str(data.get("brief", "")).strip()
        with self.store.connect() as db:
            cursor = db.execute("INSERT INTO projects(name,brief) VALUES (?,?)", (name[:150], brief[:12000]))
            return {"id": cursor.lastrowid, "name": name[:150], "brief": brief[:12000]}

    def edit_asset(self, data):
        key = data["key"]
        if key not in self.catalog.raw or self.catalog.raw[key].get("conflict"):
            raise ValueError("该编号需先处理身份冲突")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changes, quotes = self.store.state(db)
            raw = self.catalog.raw[key]
            before = next(r["card"] for r in self.catalog.asset_rows(changes, quotes) if r["card"]["key"] == key)
            categories = list(dict.fromkeys(data.get("categories", before["categories"])))
            if set(categories) - set(self.catalog.categories):
                raise ValueError("存在未知应用品类")
            tags = sorted(set(data.get("tags", before["tags"])))
            allowed_c = set(categories) | set(raw.get("category_candidates") or [])
            allowed_c -= set(before["categories"]) - set(categories)
            if any(t not in self.catalog.terms or not self.catalog.terms[t].get("selectable", True) for t in tags):
                raise ValueError("请选择有效标签")
            tags = [t for t in tags if self.catalog.terms[t]["level"] != "C" or
                    self.catalog.terms[t]["category"] in allowed_c]
            product_ids = sorted(set(data.get("product_ids", [p["product_id"] for p in before["products"]])))
            if set(product_ids) - set(self.catalog.products):
                raise ValueError("存在未知产品")
            name = str(data.get("name") or before["name"]).strip()
            if not name:
                raise ValueError("请输入香精名称")
            prior = {"name": before["name"], "tags": before["tags"], "categories": before["categories"],
                     "product_ids": sorted({p["product_id"] for p in before["products"]})}
            after = {"name": name, "tags": tags, "categories": sorted(categories), "product_ids": product_ids}
            if prior != after:
                update = {**changes.get(key, {}), **{k: v for k, v in after.items() if v != prior[k]}}
                db.execute("INSERT INTO asset_edits VALUES(?,?) ON CONFLICT(asset_key) DO UPDATE SET payload=excluded.payload",
                           (key, encode(update)))
                delta = {k: {"before": prior[k], "after": v} for k, v in after.items() if v != prior[k]}
                self.store.record(db, "香精资产修改", {"origin": "manual", "key": key, "name": name,
                                                     "changes": delta})
            return after

    def decide(self, data):
        project = int(data["project_id"])
        action = data["action"]
        steps = {
            "select": (),
            "create": ("perfumery",),
            "duplicate": ("analysis",),
            "modify": ("perfumery",),
            "initial_shipment": ("shipment",),
            "formal_shipment": ("shipment",),
            "checks": ("compliance", "quality", "application"),
            "sample": ("sample",),
            "warehouse": ("warehouse",),
        }
        if action not in steps:
            raise ValueError("未知处理动作")
        key = data.get("key")
        if action == "select" and not key:
            raise ValueError("请先选择一款香精")
        if key and (key not in self.catalog.raw or self.catalog.raw[key].get("conflict")):
            raise ValueError("该香精身份需核对")
        sample_form = str(data.get("sample_form") or "").strip()
        if action in {"initial_shipment", "formal_shipment"} and not sample_form:
            raise ValueError("请输入寄样形态及数量")
        info = {"key": key, "name": data.get("name"), "query_id": data.get("query_id"),
                "note": str(data.get("note") or "")[:2000], "sample_form": sample_form,
                "action": action}
        with self.store.connect() as db:
            if info["query_id"] and not db.execute("SELECT 1 FROM query_runs WHERE id=? AND project_id=?",
                                                  (info["query_id"], project)).fetchone():
                raise ValueError("选香快照属于另一个项目")
            cursor = db.execute("INSERT OR IGNORE INTO decisions(project_id,fingerprint,action,detail) VALUES (?,?,?,?)",
                                (project, fingerprint(info), action, encode(info)))
            if cursor.rowcount:
                info["decision_id"] = cursor.lastrowid
                for department in steps[action]:
                    default = db.execute("SELECT result FROM mock_defaults WHERE department=?", (department,)).fetchone()
                    result = default["result"] if default else None
                    task = db.execute("INSERT INTO tasks(project_id,department,title,spec,result) VALUES (?,?,?,?,?)",
                                      (project, department, info["name"] or KINDS[department], encode(info), result))
                    if default:
                        self.store.record(db, "模拟部门回执", {"task_id": task.lastrowid, "passed": bool(result),
                                                              "automatic": True})
                self.store.record(db, "评香决定", {"project_id": project, **info})
            return {"saved": True}

    def platform(self):
        with self.store.connect() as db:
            return {
                "tasks": [{**dict(r), "spec": json.loads(r["spec"])} for r in db.execute(
                    """SELECT t.*, p.name AS project_name, x.consumed FROM tasks t
                       JOIN projects p ON p.id=t.project_id LEFT JOIN flow_task_refs x ON x.task_id=t.id
                       ORDER BY t.id DESC""")],
                "feed": [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute(
                    "SELECT * FROM feed ORDER BY id DESC LIMIT 150")],
                "quotes": self.store.state(db)[1],
                "defaults": {r["department"]: r["result"] for r in db.execute("SELECT * FROM mock_defaults")},
            }

    def task_result(self, data):
        result = data["passed"]
        if not isinstance(result, bool):
            raise ValueError("请选通过或退回")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if data.get("id"):
                tasks = db.execute("""SELECT t.id,t.result,COALESCE(x.consumed,0) AS consumed FROM tasks t
                    LEFT JOIN flow_task_refs x ON x.task_id=t.id WHERE t.id=?""", (int(data["id"]),)).fetchall()
            else:
                tasks = db.execute("""SELECT t.id,t.result,COALESCE(x.consumed,0) AS consumed FROM tasks t
                    LEFT JOIN flow_task_refs x ON x.task_id=t.id WHERE t.result IS NULL AND COALESCE(x.consumed,0)=0""").fetchall()
            for task in tasks:
                if task["result"] == int(result):
                    continue
                if task["consumed"]:
                    raise ValueError("该回执已用于推进项目，请从项目端发起重试")
                db.execute("UPDATE tasks SET result=?, result_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (int(result), str(data.get("note", ""))[:1000], task["id"]))
                self.store.record(db, "模拟部门回执", {"task_id": task["id"], "passed": result})
            return {"updated": len(tasks)}

    def mock_default(self, data):
        department, result = data["department"], data.get("result")
        if department not in KINDS or result is not None and not isinstance(result, bool):
            raise ValueError("请选择部门及回执方式")
        with self.store.connect() as db:
            if result is None:
                db.execute("DELETE FROM mock_defaults WHERE department=?", (department,))
            else:
                db.execute("INSERT INTO mock_defaults VALUES (?,?) ON CONFLICT(department) DO UPDATE SET result=excluded.result",
                           (department, int(result)))
        return {"saved": True}

    def quote(self, data):
        code = str(data["code"]).strip()
        if code not in self.catalog.raw or self.catalog.raw[code].get("conflict"):
            raise ValueError("请填写有效且唯一的香精编号")
        raw = data.get("price")
        with self.store.connect() as db:
            if raw in ("", None):
                db.execute("DELETE FROM quotes WHERE code=?", (code,))
            else:
                price = comparable_price(raw)
                if price is None:
                    raise ValueError("请输入正数报价")
                db.execute("INSERT INTO quotes VALUES(?,?) ON CONFLICT(code) DO UPDATE SET price=excluded.price",
                           (code, str(price)))
            self.store.record(db, "模拟报价更新", {"code": code, "price": raw})
            return {"saved": True}


def make_handler(app):
    get_routes = {
        "/api/health": lambda: {"service": "fragrance-workbench", "ready": True},
        "/api/bootstrap": app.bootstrap, "/api/platform": app.platform, "/api/dictionaries": app.dictionaries,
    }
    post_routes = {
        "/api/search": app.search, "/api/projects": app.project, "/api/assets": app.edit_asset,
        "/api/decisions": app.decide, "/api/task-result": app.task_result, "/api/quotes": app.quote,
        "/api/sandbox-search": app.sandbox_search, "/api/mock-default": app.mock_default,
        "/api/workflow": app.workflow.snapshot, "/api/sources": app.workflow.source,
        "/api/briefs/analyze": app.workflow.analyze, "/api/briefs/confirm": app.workflow.confirm,
        "/api/flow/plan": app.workflow.plan, "/api/flow/advance": app.workflow.advance,
        "/api/flow/reroute": app.workflow.reroute,
        "/api/targeting": lambda data: map_brief(data["text"], data["mode"], data.get("categories", []),
                                                app.catalog, CONFIG),
    }
    static = {
        "/": "index.html", "/mock-platform": "mock.html", "/mock-platform/": "mock.html",
        "/projects": "projects.html", "/projects.js": "projects.js",
        "/workbench.js": "workbench.js", "/mock.js": "mock.js", "/style.css": "style.css",
    }

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, code, content, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def send_json(self, code, value):
            self.send_bytes(code, encode(value).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in get_routes:
                self.send_json(200, get_routes[path]())
            elif path in static:
                file = WEB / static[path]
                content_type = mimetypes.guess_type(file.name)[0] or "text/plain"
                self.send_bytes(200, file.read_bytes(), content_type + "; charset=utf-8")
            else:
                self.send_json(404, {"error": "页面不存在"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in post_routes:
                self.send_json(404, {"error": "接口不存在"})
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                self.send_json(403, {"error": "请从本地工作台操作"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                maximum = 42 * 1024 * 1024 if path == "/api/sources" else 1800000
                if not 0 < length <= maximum:
                    raise ValueError("请求大小无效")
                data = json.loads(self.rfile.read(length))
                self.send_json(200, post_routes[path](data))
            except (ValueError, KeyError, TypeError, AttributeError, sqlite3.IntegrityError) as exc:
                message = str(exc) if isinstance(exc, ValueError) else "请检查输入字段及关联项目"
                self.send_json(400, {"error": message})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18761)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "workspace.sqlite3")
    args = parser.parse_args()
    app = Workbench(args.database)
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app)) as server:
        print(f"评香工作台  http://127.0.0.1:{args.port}/", flush=True)
        print(f"模拟中台    http://127.0.0.1:{args.port}/mock-platform", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
