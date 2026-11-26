"""Persist project directions, rounds and simulated execution."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import PureWindowsPath
import re

from .catalog import canon
from .intelligence import ENTRIES, FOLLOWUPS, STRATEGIES, propose, read_vision
from .sources import MAX_UPLOAD, decode_upload, extract_source


SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_sources(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 name TEXT NOT NULL, digest TEXT NOT NULL, raw BLOB NOT NULL, extracted TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id,name,digest)
);
CREATE TABLE IF NOT EXISTS flow_drafts(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 source_ids TEXT NOT NULL, result TEXT NOT NULL, model TEXT, elapsed REAL, status TEXT NOT NULL DEFAULT 'draft',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS flow_rounds(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 draft_id INTEGER UNIQUE REFERENCES flow_drafts(id), number INTEGER NOT NULL, shared TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id,number)
);
CREATE TABLE IF NOT EXISTS flow_goals(
 id INTEGER PRIMARY KEY, round_id INTEGER NOT NULL REFERENCES flow_rounds(id), spec TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flow_slots(
 id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES flow_goals(id), strategy TEXT NOT NULL,
 state TEXT NOT NULL, context TEXT NOT NULL, stage_revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS flow_task_refs(
 task_id INTEGER PRIMARY KEY REFERENCES tasks(id), slot_id INTEGER NOT NULL REFERENCES flow_slots(id),
 stage TEXT NOT NULL, revision INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS flow_shipments(
 id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES flow_slots(id), task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
 kind TEXT NOT NULL, details TEXT NOT NULL, shipped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS flow_task_slot ON flow_task_refs(slot_id,revision,stage);
"""
STEPS = {
    "analysis": ("analysis",), "perfumery": ("perfumery",),
    "warehouse_review": ("compliance", "quality", "application"), "warehouse": ("warehouse",),
    "sample": ("sample",), "shipment_review": ("compliance", "quality", "application"), "shipment": ("shipment",)
}
DEPT = {"analysis": "分析", "perfumery": "调香", "compliance": "合规", "quality": "质量",
        "application": "应用", "warehouse": "入库", "sample": "备样", "shipment": "寄样"}
TEXT_FIELDS = (
    "scent", "avoid", "product", "brand", "edition", "substrate", "dose_text", "quantity_text", "sample_form",
    "price_text", "deadline_text", "base_code", "sample_reference", "changes", "retained", "fulfillment", "price_rule",
    "launch_tier", "delivery_scope", "composition_text"
)
NUMBER_FIELDS = ("count_min", "count_max", "price_min", "price_max", "price_target")
SAMPLE_AMOUNT = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|毫升|g|克)(?![a-z])", re.I)


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_fields(dict_row, *fields):
    item = dict(dict_row)
    for key in fields:
        item[key] = json.loads(item[key])
    return item


def require(connection, sql, params, message):
    row = connection.execute(sql, params).fetchone()
    if not row:
        raise ValueError(message)
    return row


def clean_text(value):
    if isinstance(value, str):
        return value.strip()[:6000]
    if isinstance(value, list):
        return "；".join(str(x) for x in value)[:6000]
    return str(value).strip() if value is not None else ""


def clean_number(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and 0 < number <= 100000000:
            return float(number)
    except InvalidOperation:
        pass
    return None


def anchored_deadline(value, segments):
    if not value or not segments:
        return True
    normalized = re.sub(r"\s+", "", str(value))
    has_delivery = re.compile(r"定香|定稿|交期|寄出|交[付样]|截止|最晚|收[到样]|寄样|送达|完成|之前|前$")
    short = re.search(r"\d{1,2}月(?:\d{1,2}日?|底|初|中旬)|\d{1,2}/\d{1,2}|下周[一二三四五六日天]", normalized)
    phrase = short.group() if short else normalized
    for segment in segments:
        for line in segment["text"].splitlines():
            compact = re.sub(r"\s+", "", line)
            if (phrase in compact and has_delivery.search(compact)) or (normalized in compact and has_delivery.search(normalized)):
                return True
    return False


class Workflow:
    def __init__(self, store, catalog, review_rules):
        self.store = store
        self.catalog = catalog
        self.review_rules = review_rules
        with store.connect() as db:
            db.executescript(SCHEMA)

    def source(self, data):
        project = int(data["project_id"])
        with self.store.connect() as db:
            require(db, "SELECT id FROM projects WHERE id=?", (project,), "项目不存在")
        if "text" in data:
            name = PureWindowsPath(str(data.get("name") or "需求文字.txt")).name
            if not name.lower().endswith(".txt"):
                name += ".txt"
            raw = str(data["text"]).encode("utf-8")
            if not raw.strip() or len(raw) > MAX_UPLOAD:
                raise ValueError("请输入不超过 30 MB 的文字资料")
        else:
            name = PureWindowsPath(str(data.get("name") or "未知资料")).name
            raw = decode_upload(data)
        digest = hashlib.sha256(raw).hexdigest()
        try:
            extracted = extract_source(name, raw, read_vision if data.get("vision") is True else None)
        except Exception as exc:
            extracted = {"segments": [], "status": "needs_text",
                         "warnings": [f"原件已保存，读取失败（{type(exc).__name__}），可补录文字"]}
        with self.store.connect() as db:
            db.execute("""INSERT INTO flow_sources(project_id,name,digest,raw,extracted) VALUES(?,?,?,?,?)
                          ON CONFLICT(project_id,name,digest) DO UPDATE SET extracted=excluded.extracted
                          WHERE length(flow_sources.extracted) < length(excluded.extracted)""",
                       (project, name, digest, raw, encode(extracted)))
            saved = require(db, "SELECT id,name,digest,extracted FROM flow_sources WHERE project_id=? AND name=? AND digest=?",
                            (project, name, digest), "无法读取资料")
            return json_fields(saved, "extracted")

    @staticmethod
    def _goals(db, project):
        return db.execute("""
          SELECT g.id,g.round_id,g.spec,r.number FROM flow_goals g JOIN flow_rounds r ON r.id=g.round_id
          WHERE r.project_id=? ORDER BY r.number,g.id""", (project,)).fetchall()

    @staticmethod
    def _ships(db, project):
        return db.execute("""
          SELECT h.*,s.goal_id FROM flow_shipments h JOIN flow_slots s ON s.id=h.slot_id
          JOIN flow_goals g ON g.id=s.goal_id JOIN flow_rounds r ON r.id=g.round_id
          WHERE r.project_id=? ORDER BY h.id DESC""", (project,)).fetchall()

    def analyze(self, data):
        project = int(data["project_id"])
        with self.store.connect() as db:
            row = require(db, "SELECT * FROM projects WHERE id=?", (project,), "项目不存在")
            selected = set(int(i) for i in data.get("source_ids", []))
            sources = [s for s in db.execute("SELECT id,name,extracted FROM flow_sources WHERE project_id=? ORDER BY id",
                                             (project,)) if s["id"] in selected]
            goals = [json_fields(g, "spec") for g in self._goals(db, project)]
            shipments = [json_fields(h, "details") for h in self._ships(db, project)]
        segments = []
        for source in sources:
            for index, segment in enumerate(json.loads(source["extracted"])["segments"], 1):
                segments.append({**segment, "id": f'{source["id"]}.{index}',
                                 "locator": source["name"] + " / " + segment["locator"]})
        if not segments and row["brief"] and not goals and not selected:
            saved = self.source({"project_id": project, "name": "项目录入原文.txt", "text": row["brief"]})
            source_id = saved["id"]
            selected = {source_id}
            segments = [{**s, "id": f"{source_id}.{n}", "locator": "项目录入原文 / " + s["locator"]}
                        for n, s in enumerate(saved["extracted"]["segments"], 1)]
        categories = {k: v["name"] for k, v in self.review_rules["review_category_defaults"].items()}
        raw, meta = propose(segments, {"project_name": row["name"], "goals": goals[-25:],
                                       "shipments": shipments[:25]}, self.catalog.categories, categories)
        if not isinstance(raw, dict) or not isinstance(raw.get("directions"), list):
            raise ValueError("需求草案结构有误，可重试或手填")
        result = self.validate_draft(raw, segments, goals, shipments)
        with self.store.connect() as db:
            saved = db.execute("INSERT INTO flow_drafts(project_id,source_ids,result,model,elapsed) VALUES(?,?,?,?,?)",
                               (project, encode(sorted(selected)), encode(result), meta["model"], meta["seconds"]))
            return {"id": saved.lastrowid, "result": result, **meta}

    def resolve_product(self, brand, name):
        product_query, brand_query = canon(name), canon(brand)
        if not product_query:
            return None
        is_tf = brand_query == "tf" or any(v in brand_query for v in ("汤姆福特", "tomford"))
        explicit_tf = any(product_query.startswith(v) for v in ("tf", "汤姆福特", "tomford"))
        if ("白麝香" in product_query or "whitesuede" in product_query) and (is_tf or explicit_tf):
            return "PR_0060" if "PR_0060" in self.catalog.products else None
        found = []
        for pid, item in self.catalog.products.items():
            directory_brand = self.catalog.brands.get(item["brand_id"], {})
            brand_names = [item.get("brand_name"), directory_brand.get("canonical_name"),
                           directory_brand.get("international_name"), *directory_brand.get("aliases", [])]
            if brand_query and brand_query not in {canon(v) for v in brand_names}:
                continue
            variants = {canon(v) for v in [item["product_name"], *item.get("aliases", [])]}
            if product_query in variants or (brand_query and product_query.isdigit() and
                                             any(re.search(rf"(?<!\d){re.escape(product_query)}(?!\d)", v)
                                                 for v in variants)):
                found.append(pid)
        return found[0] if len(found) == 1 else None

    def _expand_numbered_series(self, items, segments):
        result = []
        source_text = "\n".join(s["text"] for s in segments)
        affirmed = re.search(r"(?:尤其|其中|特别|优先)(.{1,32}?)(?:必须有|必须包含|必须提供|都要)", source_text)
        numbers = list(dict.fromkeys(re.findall(r"\d{1,3}", affirmed.group(1)))) if affirmed else []
        if "全系列" not in source_text or not numbers:
            return items
        for item in items:
            if not isinstance(item, dict) or "全系列" not in clean_text(item.get("title")):
                result.append(item)
                continue
            fields = item.get("conditions") or {}
            brand = clean_text(fields.get("brand"))
            if not brand:
                for b in self.catalog.brands.values():
                    alias = next((x for x in (b.get("international_name"), b.get("canonical_name"))
                                  if x and canon(x) in canon(source_text)), None)
                    if alias:
                        brand = alias
                        break
            identities = [(number, self.resolve_product(brand, number)) for number in numbers]
            if not brand or any(pid is None for _, pid in identities):
                result.append(item)
                continue
            base = {**fields, "brand": brand}
            existing_ids = {self.resolve_product((x.get("conditions") or {}).get("brand"),
                                                 (x.get("conditions") or {}).get("product"))
                            for x in items if isinstance(x, dict) and x.get("entry") == "find_product"}
            for number, pid in identities:
                if pid in existing_ids:
                    continue
                product = self.catalog.products[pid]["product_name"]
                result.append({**item, "title": brand + " " + product, "entry": "find_product",
                               "conditions": {**base, "product": product, "count_min": 1, "count_max": 1}})
            result.append({**item, "title": brand + " 其余系列推荐", "entry": "recommend_simple",
                           "conditions": {**base, "product": None, "edition": None,
                                          "count_min": None, "count_max": None}})
        return result

    def validate_draft(self, raw, segments, previous_goals, shipments):
        by_id = {r["id"]: r for r in segments}
        existing = {r["id"]: r for r in previous_goals}
        sent = {r["id"]: r for r in shipments}
        issues = [clean_text(s) for s in (raw.get("open_questions") or []) if s][:20]
        output = {key: clean_text(raw.get(key)) for key in ("project_name", "summary")}
        shared = dict(raw["shared"]) if isinstance(raw.get("shared"), dict) else {}
        if not anchored_deadline(shared.get("deadline_text"), segments):
            shared["deadline_text"] = None
            issues.append("资料中未找到与交付事项关联的总体交期，已留空")
        output["shared"] = shared
        output["directions"] = []
        for item in self._expand_numbered_series(raw.get("directions", []), segments)[:40]:
            if not isinstance(item, dict) or not clean_text(item.get("title")):
                continue
            title = clean_text(item["title"])
            entry = item.get("entry")
            if entry not in ENTRIES:
                issues.append(title + " 的入口需确认")
                entry = "recommend_simple"
            intent = item.get("intent") or "new"
            intent = intent if intent in FOLLOWUPS else "new"
            prior = clean_number(item.get("previous_goal_id"))
            previous_id = int(prior) if prior and prior == int(prior) and int(prior) in existing else None
            shipment = clean_number(item.get("source_shipment_id"))
            shipment_id = int(shipment) if shipment and shipment == int(shipment) and int(shipment) in sent else None
            if shipment_id:
                basis_goal = sent[shipment_id]["goal_id"]
                if previous_id and previous_id != basis_goal:
                    issues.append(title + " 的原方向与寄样记录不一致")
                    shipment_id = None
                else:
                    previous_id = basis_goal
            conditions = item.get("conditions") or {}
            if not isinstance(conditions, dict):
                conditions = {}
            if entry in ("recommend_simple", "recommend_brand"):
                product_id = (self.resolve_product(conditions.get("brand"), conditions.get("product")) or
                              self.resolve_product(conditions.get("brand"), title))
                if product_id == "PR_0060" and segments:
                    selected_refs = [by_id[str(ref["segment_id"])]["text"] for ref in item.get("basis", [])
                                     if isinstance(ref, dict) and str(ref.get("segment_id")) in by_id]
                    evidence = selected_refs or ([r["text"] for r in segments] if len(raw["directions"]) == 1 else [])
                    phrase = r"(?:TF|汤姆\s*[·・]?\s*福特|Tom\s*Ford)\s*的?\s*(?:白麝香|White\s*Suede)"
                    for snippet in evidence:
                        for found in re.finditer(phrase, snippet, re.I):
                            window = snippet[max(0, found.start() - 20):found.end() + 10]
                            if re.search(r"推荐|指定|必须|包含|想要|需要", window) and not re.search(r"类似|风格|参考|借鉴", window):
                                entry = "find_product"
                                issues.append("已按原文将 TF 白麝香作为指定产品")
                                break
            cleaned = {key: clean_text(conditions.get(key)) for key in TEXT_FIELDS if conditions.get(key)}
            cleaned.update({key: value for key in NUMBER_FIELDS if (value := clean_number(conditions.get(key)))})
            for key in ("markets", "requirements"):
                if isinstance(conditions.get(key), list):
                    cleaned[key] = [clean_text(x) for x in conditions[key] if x][:40]
            if conditions.get("application_id") in self.catalog.categories:
                cleaned["application_id"] = conditions["application_id"]
            if conditions.get("review_category_id") in self.review_rules["review_category_defaults"]:
                cleaned["review_category_id"] = conditions["review_category_id"]
            if not anchored_deadline(cleaned.get("deadline_text"), segments):
                cleaned.pop("deadline_text")
                issues.append(title + " 的交期需核对原文")
            if entry not in ("modify", "resend"):
                cleaned.pop("base_code", None)
            if previous_id:
                past = existing[previous_id]["spec"].get("conditions", {})
                preserved = ("application_id", "review_category_id", "substrate", "markets", "dose_text",
                             "sample_form", "requirements", "price_rule", "price_min", "price_max", "price_target",
                             "price_text", "retained")
                cleaned = {**{k: past[k] for k in preserved if k in past}, **cleaned}
            if shipment_id:
                cleaned.setdefault("base_code", sent[shipment_id]["details"].get("fragrance_code"))
                cleaned["base_version"] = sent[shipment_id]["details"].get("formula_version")
            elif (entry == "modify" and not cleaned.get("base_code")) or entry == "resend":
                issues.append(title + " 需要确认实际原样")
            for key in ("dose_text", "sample_form", "deadline_text", "markets"):
                if shared.get(key) and not cleaned.get(key):
                    cleaned[key] = shared[key]
            dose = clean_text(cleaned.get("dose_text"))
            if dose and (re.search(r"主水果|年轻放大器|空气感|前调|中调|后调|各占", dose) or dose.count("%") > 1):
                cleaned.setdefault("composition_text", dose)
                cleaned.pop("dose_text")
            if cleaned.get("sample_form") in {"香水", "香精", "精油"} and segments:
                material = cleaned["sample_form"]
                if not any(re.search(r"寄.{0,20}" + material + r"|" + material + r".{0,20}样品", s["text"])
                           for s in segments):
                    cleaned.pop("sample_form")
            delivery_note = clean_text(shared.get("delivery_note"))
            if dosage := re.search(r"(\d+(?:\.\d+)?\s*[%％])\s*加香", delivery_note):
                cleaned.setdefault("dose_text", dosage.group(1))
                if "小样" in delivery_note:
                    cleaned.setdefault("sample_form", "加香小样")
            current_dose = clean_text(cleaned.get("dose_text"))
            if "加香" in current_dose and (number := re.search(r"\d+(?:\.\d+)?\s*[%％]", current_dose)):
                cleaned["dose_text"] = number.group()
            form = clean_text(cleaned.get("sample_form"))
            if amount := SAMPLE_AMOUNT.search(form):
                cleaned.setdefault("quantity_text", amount.group())
                cleaned["sample_form"] = (form[:amount.start()] + form[amount.end():]).strip(" ：:，,")
            if entry == "find_product":
                resolved = (self.resolve_product(cleaned.get("brand"), cleaned.get("product")) or
                            self.resolve_product(cleaned.get("brand"), title))
                if not resolved and cleaned.get("brand"):
                    prefix = canon(cleaned["brand"])
                    number = re.match(re.escape(prefix) + r"(\d{1,3})(?!\d)", canon(title))
                    if number:
                        resolved = self.resolve_product(cleaned["brand"], number.group(1))
                if resolved:
                    cleaned["catalog_product_id"] = resolved
                    cleaned["product"] = self.catalog.products[resolved]["product_name"]
                else:
                    issues.append(title + " 的精确产品尚未与目录唯一关联")
            elif "系列" in title and cleaned.get("brand"):
                match = [k for k, v in self.catalog.brands.items() if canon(cleaned["brand"]) in
                         {canon(alias) for alias in [v["canonical_name"], v["international_name"], *v.get("aliases", [])]}]
                if len(match) == 1:
                    cleaned["catalog_brand_id"] = match[0]
            cleaned["fulfillment"] = "warehouse" if entry == "invent" or cleaned.get("fulfillment") == "warehouse" else "ship"
            checked = []
            for ref in (item.get("basis") or [])[:16]:
                if not isinstance(ref, dict):
                    continue
                quote = clean_text(ref.get("quote"))
                source_id = str(ref.get("segment_id", ""))
                norm = lambda text: re.sub(r"\s+", "", text)
                if quote and (s := by_id.get(source_id)) and norm(quote) in norm(s["text"]):
                    checked.append({"segment_id": source_id, "quote": quote, "locator": s["locator"]})
            if segments and not checked:
                issues.append(title + " 的原文引用需人工核对")
            output["directions"].append({"title": title, "entry": entry, "intent": intent,
                                         "previous_goal_id": previous_id, "source_shipment_id": shipment_id,
                                         "basis": checked, "conditions": cleaned,
                                         "strategies": list(STRATEGIES[entry])})
        output["open_questions"] = list(dict.fromkeys(issues))
        return output

    def confirm(self, data):
        project = int(data["project_id"])
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "SELECT id FROM projects WHERE id=?", (project,), "项目不存在")
            draft_id = data.get("draft_id")
            stored = None
            if draft_id:
                stored = require(db, "SELECT * FROM flow_drafts WHERE id=? AND project_id=?", (draft_id, project),
                                 "草案不属于这个项目")
                if stored["status"] == "confirmed":
                    row = require(db, "SELECT id,number FROM flow_rounds WHERE draft_id=?", (draft_id,), "轮次不存在")
                    return dict(row)
            raw = data.get("result") or (json.loads(stored["result"]) if stored else {})
            if not isinstance(raw.get("directions"), list):
                raise ValueError("请填写需确认的方向")
            go = [json_fields(r, "spec") for r in self._goals(db, project)]
            sh = [json_fields(r, "details") for r in self._ships(db, project)]
            result = self.validate_draft(raw, [], go, sh)
            if not result["directions"]:
                raise ValueError("至少保留一个有名称的方向")
            inputs = [d for d in raw["directions"] if isinstance(d, dict) and clean_text(d.get("title"))]
            for original, spec in zip(inputs, result["directions"], strict=False):
                saved_basis = original.get("basis", [])
                spec["basis"] = [r for r in saved_basis if isinstance(r, dict) and r.get("quote")][:16]
            number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM flow_rounds WHERE project_id=?", (project,)).fetchone()[0]
            round_id = db.execute("INSERT INTO flow_rounds(project_id,draft_id,number,shared) VALUES(?,?,?,?)",
                                  (project, draft_id, number, encode(
                                      {"summary": result["summary"], "fields": result["shared"],
                                       "open_questions": result["open_questions"]}))).lastrowid
            for goal in result["directions"]:
                db.execute("INSERT INTO flow_goals(round_id,spec) VALUES(?,?)", (round_id, encode(goal)))
            if stored:
                db.execute("UPDATE flow_drafts SET status='confirmed' WHERE id=?", (draft_id,))
            self.store.record(db, "确认需求轮次", {"project_id": project, "round_id": round_id, "number": number})
            return {"id": round_id, "number": number}

    def _goal(self, db, project, goal_id):
        row = require(db, """SELECT g.id,g.spec,r.number,r.shared FROM flow_goals g JOIN flow_rounds r ON r.id=g.round_id
                WHERE g.id=? AND r.project_id=?""", (goal_id, project), "需求方向不属于项目")
        return json_fields(row, "spec", "shared")

    def _slot(self, db, project, slot_id):
        row = require(db, """SELECT s.* FROM flow_slots s JOIN flow_goals g ON g.id=s.goal_id
           JOIN flow_rounds r ON r.id=g.round_id WHERE s.id=? AND r.project_id=?""",
                      (slot_id, project), "方案不属于项目")
        return json_fields(row, "context")

    def reroute(self, data):
        project, goal_id = int(data["project_id"]), int(data["goal_id"])
        requested = data["entry"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            goal = self._goal(db, project, goal_id)
            spec = goal["spec"]
            previous = spec["entry"]
            if (previous, requested) not in {("modify", "with_sample"), ("recommend_simple", "recommend_brand")}:
                raise ValueError("请在需求草案里确认其他入口")
            if db.execute("SELECT 1 FROM flow_slots WHERE goal_id=?", (goal_id,)).fetchone():
                raise ValueError("此方向已有执行记录，请在新轮次另建方向")
            spec.update(entry=requested, strategies=list(STRATEGIES[requested]))
            db.execute("UPDATE flow_goals SET spec=? WHERE id=?", (encode(spec), goal_id))
            self.store.record(db, "修改需求入口", {"project_id": project, "goal_id": goal_id,
                                                 "from": previous, "to": requested})
            return spec

    @staticmethod
    def _tasks(db, slot):
        return [dict(r) for r in db.execute("""
          SELECT t.id,t.department,t.result,t.result_note,x.stage,x.consumed FROM tasks t
          JOIN flow_task_refs x ON x.task_id=t.id
          WHERE x.slot_id=? AND x.revision=? AND x.stage=? ORDER BY t.id""",
          (slot["id"], slot["stage_revision"], slot["state"]))]

    def _dispatch(self, db, project, slot, goal, skip=()):
        state, context = slot["state"], slot["context"]
        fields = goal["spec"]["conditions"]
        rule = self.review_rules["review_category_defaults"].get(fields.get("review_category_id"), {})
        defaults = {r["department"]: r["result"] for r in db.execute("SELECT * FROM mock_defaults")}
        for department in STEPS[state]:
            if department in skip:
                continue
            metrics = [k for k in rule.get("defaults", []) if
                       self.review_rules["metric_dictionary"].get(k["metric_id"], {}).get("department") == department]
            spec = {"workflow": True, "slot_id": slot["id"], "goal": goal["spec"]["title"], "round": goal["number"],
                    "strategy": slot["strategy"], "stage": state, "brief": fields, "shared": goal["shared"]["fields"],
                    "note": context.get("note", ""), "assay": metrics,
                    "sample_form": context.get("sample_form") or fields.get("sample_form"), "execution": context}
            value = defaults.get(department)
            task_id = db.execute("INSERT INTO tasks(project_id,department,title,spec,result) VALUES(?,?,?,?,?)",
                                 (project, department, f"{goal['spec']['title']} · {DEPT[department]}", encode(spec),
                                  value)).lastrowid
            db.execute("INSERT INTO flow_task_refs(task_id,slot_id,stage,revision) VALUES(?,?,?,?)",
                       (task_id, slot["id"], state, slot["stage_revision"]))
            if value is not None:
                self.store.record(db, "模拟部门回执", {"task_id": task_id, "passed": bool(value), "automatic": True})

    def plan(self, data):
        project, goal_id = int(data["project_id"]), int(data["goal_id"])
        strategy = data["strategy"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            goal = self._goal(db, project, goal_id)
            spec = goal["spec"]
            if strategy not in spec["strategies"]:
                raise ValueError("此方向不支持该方案")
            fields = spec["conditions"]
            key = data.get("asset_key")
            asset = self.catalog.raw.get(key)
            if key and (not asset or asset.get("conflict")):
                raise ValueError("请确认原香编号")
            query_id = data.get("query_id")
            if query_id:
                require(db, "SELECT id FROM query_runs WHERE id=? AND project_id=?", (query_id, project),
                        "选香快照不属于项目")
            context = {"note": clean_text(data.get("note")), "iteration": 1,
                       "sample_reference": clean_text(data.get("sample_reference") or fields.get("sample_reference")),
                       "asset_key": key, "base_code": clean_text(data.get("base_code") or fields.get("base_code")),
                       "base_version": clean_text(data.get("base_version") or fields.get("base_version")),
                       "query_id": query_id, "synthetic": True}
            state = {"duplicate": "analysis", "modify": "perfumery", "create": "perfumery",
                     "select": "chosen", "resend": "chosen"}[strategy]
            if strategy == "select":
                if not asset:
                    raise ValueError("请先选择库香")
                if spec["entry"] == "find_product":
                    relation = self.catalog.products_by_code().get(asset["fragrance_id"], {}).values()
                    if not any(r["product_id"] == fields.get("catalog_product_id") and r["status"] == "confirmed"
                               and (not fields.get("edition") or canon(r.get("edition")) == canon(fields["edition"]))
                               for r in relation):
                        raise ValueError("该香精与目标产品没有经确认的对应关系")
                if spec["entry"] == "with_sample" and not context["sample_reference"]:
                    raise ValueError("请确认用于对香的实物样")
                context.update(fragrance_code=asset["fragrance_id"],
                               formula_version=f"MOCK-CATALOG-{asset['fragrance_id']}")
                for row in db.execute("SELECT id,strategy,state,context,stage_revision FROM flow_slots WHERE goal_id=?", (goal_id,)):
                    existing = json_fields(row, "context")
                    if existing["context"].get("fragrance_code") == asset["fragrance_id"]:
                        return existing
            if strategy == "modify":
                context["base_code"] = asset["fragrance_id"] if asset else context["base_code"]
                if not context["base_code"] or not context["base_version"]:
                    raise ValueError("请确认被改香精及可调用配方版本")
                if not (fields.get("changes") or context["note"]):
                    raise ValueError("请填写改动要求")
            if strategy == "duplicate" and not context["sample_reference"]:
                raise ValueError("请先登记可用于分析的样品或参照")
            if strategy == "create" and not (fields.get("scent") or context["note"]):
                raise ValueError("请填写创香方向")
            if strategy == "resend":
                shipment = require(db, """SELECT h.details FROM flow_shipments h JOIN flow_slots s ON s.id=h.slot_id
                    JOIN flow_goals g ON g.id=s.goal_id JOIN flow_rounds r ON r.id=g.round_id
                    WHERE h.id=? AND r.project_id=?""", (spec.get("source_shipment_id"), project),
                                   "请先明确原来实际寄出的样品")
                prior = json.loads(shipment["details"])
                context.update(fragrance_code=prior["fragrance_code"], formula_version=prior["formula_version"],
                               source_shipment_id=spec["source_shipment_id"])
            saved = db.execute("INSERT INTO flow_slots(goal_id,strategy,state,context) VALUES(?,?,?,?)",
                               (goal_id, strategy, state, encode(context))).lastrowid
            slot = {"id": saved, "strategy": strategy, "state": state, "context": context, "stage_revision": 1}
            if state in STEPS:
                self._dispatch(db, project, slot, goal)
            self.store.record(db, "确认处理方案", {"project_id": project, "goal_id": goal_id,
                                                 "slot_id": saved, "strategy": strategy})
            return slot

    def actions(self, slot, tasks, fulfillment):
        state, context = slot["state"], slot["context"]
        if state == "complete":
            return []
        if context.get("paused"):
            return ["resume"]
        if state == "chosen":
            if fulfillment == "warehouse":
                return ["warehouse_existing"] if slot["strategy"] == "select" else []
            if not context.get("sample_id"):
                return ["prepare_sample"]
            available = [] if context.get("initial_sent") or slot["strategy"] == "resend" else ["initial_shipment"]
            return available + (["formal_shipment"] if context.get("ship_checked") else ["shipment_checks"])
        responses = [item["result"] for item in tasks]
        if any(r == 0 for r in responses):
            return ["retry"]
        if not responses or any(r is None for r in responses):
            return []
        return {"analysis": ["confirm_analysis"], "perfumery": ["accept_trial", "reject_trial"],
                "warehouse_review": ["send_warehouse"], "warehouse": ["record_warehouse"],
                "sample": ["record_sample"], "shipment_review": ["record_shipment_checks"],
                "shipment": ["record_shipment"]}.get(state, [])

    def advance(self, data):
        project, slot_id = int(data["project_id"]), int(data["slot_id"])
        action = data["action"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            slot = self._slot(db, project, slot_id)
            if int(data.get("revision", slot["stage_revision"])) != slot["stage_revision"]:
                raise ValueError("方案已更新，请刷新")
            goal = self._goal(db, project, slot["goal_id"])
            fields = goal["spec"]["conditions"]
            tasks = self._tasks(db, slot)
            context, state = slot["context"], slot["state"]
            if (action == "pause" and state != "complete" and not context.get("paused")
                    or action == "resume" and context.get("paused")):
                if action == "pause":
                    context["paused"] = True
                    context["pause_reason"] = clean_text(data.get("note"))
                else:
                    context.pop("paused", None)
                db.execute("UPDATE flow_slots SET context=? WHERE id=?", (encode(context), slot_id))
                self.store.record(db, "方案暂存" if action == "pause" else "恢复方案",
                                  {"project_id": project, "slot_id": slot_id, "stage": state})
                return slot
            if action not in self.actions(slot, tasks, fields["fulfillment"]):
                raise ValueError("该步骤的条件尚未满足")
            note = clean_text(data.get("note"))
            if action == "retry":
                context["note"] = note or context["note"]
                next_state = state
            elif action == "confirm_analysis":
                context["analysis_report"] = f"MOCK-GC-{tasks[0]['id']}"
                next_state = "perfumery"
            elif action == "reject_trial":
                if not note:
                    raise ValueError("请填写评香退回意见")
                context["iteration"] += 1
                context["note"] = note
                next_state = "perfumery"
            elif action == "accept_trial":
                context.update(trial_code=f"MOCK-TRIAL-{tasks[0]['id']}",
                               formula_version=f"MOCK-V-{slot_id}-{context['iteration']}", evaluation_note=note)
                next_state = "warehouse_review"
            elif action == "warehouse_existing":
                next_state = "warehouse_review"
            elif action == "send_warehouse":
                next_state = "warehouse"
            elif action == "record_warehouse":
                context.update(warehouse_id=f"MOCK-WH-{tasks[0]['id']}",
                               fragrance_code=context.get("fragrance_code") or f"MOCK-F-{slot_id}")
                next_state = "complete" if fields["fulfillment"] == "warehouse" else "chosen"
            elif action == "prepare_sample":
                sample_form = clean_text(data.get("sample_form") or fields.get("sample_form"))
                quantity = clean_text(data.get("quantity") or fields.get("quantity_text"))
                if not sample_form or not quantity:
                    raise ValueError("请填写样品形态和数量")
                context.update(sample_form=sample_form, quantity=quantity)
                next_state = "sample"
            elif action == "record_sample":
                context["sample_id"] = f"MOCK-S-{tasks[0]['id']}"
                next_state = "chosen"
            elif action == "shipment_checks":
                next_state = "shipment_review"
            elif action == "record_shipment_checks":
                context["ship_checked"] = True
                next_state = "chosen"
            elif action in ("initial_shipment", "formal_shipment"):
                context["shipment_kind"] = "initial" if action == "initial_shipment" else (
                    "resend" if slot["strategy"] == "resend" else "formal")
                next_state = "shipment"
            else:
                h = {k: context[k] for k in ("sample_id", "fragrance_code", "formula_version", "sample_form", "quantity")}
                h.update(tracking=f"MOCK-TRACK-{tasks[0]['id']}", simulated=True)
                db.execute("INSERT INTO flow_shipments(slot_id,task_id,kind,details) VALUES(?,?,?,?)",
                           (slot_id, tasks[0]["id"], context["shipment_kind"], encode(h)))
                next_state = "complete"
                if context["shipment_kind"] == "initial":
                    context["initial_sent"] = True
                    context.pop("sample_id")
                    next_state = "chosen"
            reused = [t for t in tasks if action == "retry" and t["result"] == 1]
            if tasks:
                db.executemany("UPDATE flow_task_refs SET consumed=1 WHERE task_id=?",
                               [(t["id"],) for t in tasks if t not in reused])
            slot.update(state=next_state, context=context, stage_revision=slot["stage_revision"] + 1)
            for task in reused:
                db.execute("UPDATE flow_task_refs SET revision=? WHERE task_id=?",
                           (slot["stage_revision"], task["id"]))
            db.execute("UPDATE flow_slots SET state=?,context=?,stage_revision=? WHERE id=?",
                       (slot["state"], encode(context), slot["stage_revision"], slot_id))
            if next_state in STEPS:
                self._dispatch(db, project, slot, goal, {t["department"] for t in reused})
            self.store.record(db, "项目节点推进", {"project_id": project, "slot_id": slot_id, "action": action,
                                                 "state": next_state})
            return slot

    def snapshot(self, data):
        project = int(data["project_id"])
        with self.store.connect() as db:
            item = require(db, "SELECT * FROM projects WHERE id=?", (project,), "项目不存在")
            records = [json_fields(r, "extracted") for r in db.execute(
                "SELECT id,name,digest,extracted,created_at FROM flow_sources WHERE project_id=? ORDER BY id", (project,))]
            drafts = [json_fields(r, "source_ids", "result") for r in db.execute(
                "SELECT * FROM flow_drafts WHERE project_id=? ORDER BY id DESC LIMIT 10", (project,))]
            rounds = [json_fields(r, "shared") for r in db.execute(
                "SELECT * FROM flow_rounds WHERE project_id=? ORDER BY number DESC", (project,))]
            for branch in rounds:
                goals = [json_fields(g, "spec") for g in db.execute(
                    "SELECT * FROM flow_goals WHERE round_id=? ORDER BY id", (branch["id"],))]
                for goal in goals:
                    slots = [json_fields(s, "context") for s in db.execute(
                        "SELECT * FROM flow_slots WHERE goal_id=? ORDER BY id", (goal["id"],))]
                    for slot in slots:
                        slot["tasks"] = self._tasks(db, slot)
                        slot["actions"] = self.actions(slot, slot["tasks"], goal["spec"]["conditions"]["fulfillment"])
                        if slot["state"] != "complete" and not slot["context"].get("paused"):
                            slot["actions"].append("pause")
                    quantity = int(goal["spec"]["conditions"].get("count_min") or 1)
                    goal.update(slots=slots, complete=sum(s["state"] == "complete" for s in slots) >= quantity)
                completed = sum(s["state"] == "complete" for g in goals for s in g["slots"])
                total_min = clean_number(branch["shared"]["fields"].get("total_min"))
                branch.update(goals=goals, completed_choices=completed,
                              complete=bool(goals) and all(g["complete"] for g in goals)
                              and (not total_min or completed >= total_min))
            shipments = [json_fields(h, "details") for h in self._ships(db, project)]
            return {"project": dict(item), "sources": records, "drafts": drafts, "rounds": rounds,
                    "shipments": shipments, "entries": ENTRIES,
                    "complete": bool(rounds) and all(r["complete"] for r in rounds)}
