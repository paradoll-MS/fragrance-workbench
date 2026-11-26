"""Command layer: the only place that writes business state."""

import json
import re
from datetime import date
from decimal import Decimal

from .. import config
from ..adapters.mock_platform import MockPlatform
from ..recommendation import ranking
from ..assets.catalog import Catalog
from ..assets.rules import ReviewRules
from ..checking import evidence as evidence_rules
from ..checking import release as release_rules
from ..checking.build import build as build_requirements
from ..checking.build import context_from
from ..domain import brief as brief_model
from ..domain import enums
from ..domain.models import IssueSpec, StepBlocked, digest
from ..domain.normalize import canon, clean, normalize_direction, number
from ..intelligence import parse as parse_model
from ..intelligence import targeting
from ..intelligence.extract import extract
from ..store.db import Store, dumps, insert, loads, now, one, row, rows, update
from . import gates, issues, planning, routing


class Workbench:
    def __init__(self, database=None, catalog=None, rules=None, platform=None, scoring=None):
        self.store = Store(database or config.DATABASE)
        self.catalog = catalog or Catalog()
        self.rules = rules or ReviewRules()
        self.platform = platform or MockPlatform()
        self.config = scoring or config.scoring()

    # ---------------------------------------------------------------- projects
    def create_project(self, name, kind="customer", customer="", code=""):
        name = clean(name, 120)
        if not name:
            raise ValueError("请填写项目名称")
        if kind not in enums.PROJECT_KINDS:
            kind = "customer"
        with self.store.transaction() as db:
            project_id = insert(db, "project", kind=kind, name=name, customer=clean(customer, 120),
                                code=clean(code, 60), status="active", updated_at=now())
            Store.audit(db, "create_project", "project", project_id, "create",
                        {"name": name, "kind": kind})
        return project_id

    def rename_project(self, project_id, name, customer=""):
        with self.store.transaction() as db:
            project = self._require(db, "project", project_id)
            update(db, "project", project_id, name=clean(name, 120) or project["name"],
                   customer=clean(customer, 120), revision=project["revision"] + 1, updated_at=now())
            Store.audit(db, "rename_project", "project", project_id, "update", {"name": name})

    # ----------------------------------------------------------------- sources
    def add_source(self, project_id, name, text=None, raw=None, vision=False):
        with self.store.transaction() as db:
            self._require(db, "project", project_id)
            if text:
                raw = str(text).encode("utf-8")
                name = name or "本轮文字.txt"
            if not raw:
                raise ValueError("请先选择文件或输入文字")
            import hashlib

            digest = hashlib.sha256(raw).hexdigest()
            existing = row(db, "SELECT * FROM source WHERE project_id=? AND name=? AND sha256=?",
                           (project_id, name, digest))
            if existing:
                return existing["id"]
            reader = None
            if vision:
                from ..intelligence.client import chat

                def reader(url):
                    return chat(config.VISION_MODEL, [{"role": "user", "content": [
                        {"type": "text", "text": "逐块转写画面可辨识的业务文字，保留数字、否定、顺序与标题；"
                                                 "丢弃电话、地址和私聊身份信息。若与业务无关，概括其内容类型即可。"},
                        {"type": "image_url", "image_url": {"url": url}}]}], 2400, timeout=90)

            extracted = extract(name, raw, vision=reader)
            source_id = insert(db, "source", project_id=project_id, name=name, sha256=digest, raw=raw,
                               extracted=dumps(extracted), status=extracted["status"])
            Store.audit(db, "add_source", "source", source_id, "create",
                        {"name": name, "segments": len(extracted["segments"])})
            return source_id

    def source_segments(self, db, project_id, source_ids=None):
        query = "SELECT * FROM source WHERE project_id=?"
        params = [project_id]
        if source_ids:
            query += " AND id IN (" + ",".join("?" for _ in source_ids) + ")"
            params.extend(source_ids)
        segments, warnings = [], []
        for item in db.execute(query + " ORDER BY id", params):
            extracted = loads(item["extracted"], {})
            for index, segment in enumerate(extracted.get("segments", []), 1):
                segments.append({"id": f"{item['id']}:{index}", "source": item["name"],
                                 "locator": segment["locator"], "kind": segment.get("kind", "verbatim"),
                                 "text": segment["text"]})
            warnings.extend(extracted.get("warnings", []))
        return segments, warnings

    # -------------------------------------------------------------- draft flow
    def analyze(self, project_id, source_ids=None, model=None):
        with self.store.transaction() as db:
            project = self._require(db, "project", project_id)
            segments, warnings = self.source_segments(db, project_id, source_ids)
            if not segments:
                raise ValueError("所选资料还没有可读文字，可补录文字后重试")
            context = self._recent_context(db, project_id)
            result, meta = parse_model.propose(
                segments, context, self.catalog.categories,
                [{"id": item["id"], "name": item["name"]} for item in self.rules.category_options()],
                model=model)
            result["source_warnings"] = warnings
            draft_id = insert(db, "parse_draft", project_id=project_id,
                              source_ids=dumps(source_ids or []), result=dumps(result),
                              model=meta["model"], seconds=meta["seconds"], status="draft")
            Store.audit(db, "analyze", "parse_draft", draft_id, "propose",
                        {"directions": len(result["directions"]), "model": meta["model"]})
            return draft_id, result, meta

    def manual_draft(self, project_id, directions):
        """Create a draft by hand; same shape as model output."""
        with self.store.transaction() as db:
            self._require(db, "project", project_id)
            shaped = []
            for item in directions:
                direction, issues_found = normalize_direction(
                    item, [], self.catalog.categories,
                    [option["id"] for option in self.rules.category_options()], enums.ENTRY_LABELS)
                if direction:
                    shaped.append(direction)
            if not shaped:
                raise ValueError("请至少填写一个方向标题")
            result = {"project_name": "", "summary": "手填需求", "shared": {}, "directions": shaped,
                      "open_questions": [], "dropped": [], "source_warnings": []}
            draft_id = insert(db, "parse_draft", project_id=project_id, source_ids="[]",
                              result=dumps(result), model="手填", seconds=0, status="draft")
            return draft_id, result

    def confirm_draft(self, project_id, draft_id, edits=None, kind="customer"):
        with self.store.transaction() as db:
            project = self._require(db, "project", project_id)
            draft = self._require(db, "parse_draft", draft_id)
            if draft["status"] == "confirmed":
                return loads(draft["result"]).get("committed", {})
            result = edits or loads(draft["result"], {})
            directions = [item for item in result.get("directions", []) if item.get("title")]
            if not directions:
                raise ValueError("草案里没有可执行方向，先补充或手填")
            shared = result.get("shared") or {}
            if shared.get("customer") and not project["customer"]:
                update(db, "project", project_id, customer=clean(shared["customer"], 120))
            committed = []
            for direction in directions:
                committed.append(self._commit_direction(db, project, direction, shared, kind))
            result["committed"] = {"directions": committed}
            update(db, "parse_draft", draft_id, result=dumps(result), status="confirmed")
            self.recompute(db, project_id)
            Store.audit(db, "confirm_draft", "parse_draft", draft_id, "confirm",
                        {"directions": len(committed)})
            return result["committed"]

    def _commit_direction(self, db, project, direction, shared, kind):
        entry = direction.get("entry") if direction.get("entry") in enums.ENTRY_STRATEGIES else "recommend_simple"
        route = routing.route(entry, project["kind"])
        subproject_id = insert(db, "subproject", project_id=project["id"], requirement_type=entry,
                               final_endpoint=route["endpoint"], title=direction["title"],
                               status="active")
        conditions = dict(direction.get("conditions") or {})
        direction_brief = direction.get("brief") or brief_model.from_conditions(conditions)
        fields = brief_model.merge(shared or {}, direction_brief,
                                   application_id=conditions.get("application_id", ""),
                                   review_category_id=conditions.get("review_category_id", ""),
                                   mode=brief_model.mode_for(entry))
        for key in ("markets", "deadline_text", "sample_form", "dose_text"):
            if key not in fields and conditions.get(key):
                fields[key] = conditions[key]
        round_brief = {"summary": (shared.get("brief_goal") or ""), "shared": shared or {},
                       "direction": direction_brief, "open_questions": [], "round": 1}
        round_id = insert(db, "round", subproject_id=subproject_id, no=1, kind="initial",
                          brief=dumps(round_brief), status="active")
        goal_id = insert(db, "goal", subproject_id=subproject_id, round_id=round_id,
                         label=direction["title"], is_required=0,
                         endpoint="shipment" if route["endpoint"] == "shipment" else route["endpoint"],
                         requested_count=number(fields.get("count_max") or fields.get("count_min")),
                         fields=dumps(fields),
                         provenance=dumps({key: "source" for key in fields if key != "brief"}))
        return {"subproject_id": subproject_id, "round_id": round_id, "goal_id": goal_id,
                "title": direction["title"], "entry": entry, "entry_label": route["label"],
                "strategies": route["strategies"], "endpoint": route["endpoint"],
                "issues": route["issues"]}

    def add_direction(self, project_id, direction):
        """Add one more direction to an existing project as a new subproject and round."""
        draft_id, result = self.manual_draft(project_id, [direction])
        return self.confirm_draft(project_id, draft_id)

    # ------------------------------------------------------------------ planning
    def plan(self, project_id, goal_id, strategy, payload=None):
        payload = dict(payload or {})
        with self.store.transaction() as db:
            project = self._require(db, "project", project_id)
            goal = self._require(db, "goal", goal_id)
            subproject = self._require(db, "subproject", goal["subproject_id"])
            if subproject["project_id"] != project_id:
                raise ValueError("目标不属于该项目")
            entry = subproject["requirement_type"]
            if not planning.strategy_allowed(entry, strategy):
                raise ValueError("该方向不能执行" + enums.STRATEGY_LABELS.get(strategy, strategy))
            fields = loads(goal["fields"], {})
            payload.setdefault("endpoint", goal["endpoint"])
            payload["requirement_type"] = entry
            if strategy == "select":
                asset_key = payload.get("asset_key", "")
                asset = self.catalog.raw.get(asset_key)
                if not asset:
                    raise ValueError("请选择库内香精")
                payload["fragrance_id"] = asset["fragrance_id"]
                payload["asset_key"] = asset_key
                payload["formula_version"] = payload.get("formula_version") or f"CATALOG-{asset['fragrance_id']}"
                existing = row(db, "SELECT * FROM slot WHERE goal_id=? AND strategy='select' AND "
                                   "fragrance_id=? ORDER BY id LIMIT 1",
                               (goal_id, asset["fragrance_id"]))
                if existing:
                    return {"slot_id": existing["id"], "created": False}
                slot_id = planning.create_slot(db, goal["round_id"], goal_id, "select", payload,
                                               stage="checking", fragrance_id=asset["fragrance_id"],
                                               formula_version=payload["formula_version"])
            elif strategy == "resend":
                parent = self._last_sent(db, subproject["id"])
                if not parent:
                    raise ValueError("没有可复寄的实发记录")
                payload.update(fragrance_id=parent["fragrance_id"], formula_version=parent["formula_version"])
                slot_id = planning.create_slot(db, goal["round_id"], goal_id, "resend", payload,
                                               stage="checking", fragrance_id=parent["fragrance_id"],
                                               formula_version=parent["formula_version"])
            elif strategy in ("duplicate", "create", "modify"):
                spawned = planning.spawn_development(db, project, subproject, goal, strategy, payload)
                child = row(db, "SELECT * FROM slot WHERE id=?", (spawned["child_slot"],))
                if strategy == "duplicate":
                    self._dispatch(db, project, subproject, child, "analysis", "analysis",
                                   {"fragrance_id": "", "formula_version": "",
                                    "sample_reference": payload.get("sample_reference", "")})
                else:
                    self._dispatch(db, project, subproject, child, "perfumery", "perfumery",
                                   {"fragrance_id": payload.get("fragrance_id", ""),
                                    "formula_version": payload.get("base_version", ""),
                                    "changes": fields.get("changes", ""),
                                    "retained": fields.get("retained", "")})
                Store.audit(db, "plan", "slot", spawned["parent_slot"], "develop",
                            {"strategy": strategy, "child": spawned["child_subproject"]})
                return {"slot_id": spawned["parent_slot"], "child_slot_id": spawned["child_slot"],
                        "child_subproject_id": spawned["child_subproject"], "created": True}
            else:
                raise ValueError("未知方案")
            update(db, "goal", goal_id, status="active")
            Store.audit(db, "plan", "slot", slot_id, "create", {"strategy": strategy, "goal": goal_id})
            return {"slot_id": slot_id, "created": True}

    def reroute(self, project_id, goal_id, entry):
        with self.store.transaction() as db:
            goal = self._require(db, "goal", goal_id)
            subproject = self._require(db, "subproject", goal["subproject_id"])
            if subproject["project_id"] != project_id:
                raise ValueError("目标不属于该项目")
            if row(db, "SELECT id FROM slot WHERE goal_id=?", (goal_id,)):
                raise ValueError("已有执行方案，不能改型")
            new_entry = routing.reroute(subproject["requirement_type"], entry)
            route = routing.route(new_entry, "customer")
            update(db, "subproject", subproject["id"], requirement_type=new_entry,
                   title=subproject["title"], revision=subproject["revision"] + 1)
            Store.audit(db, "reroute", "subproject", subproject["id"], "update",
                        {"from": subproject["requirement_type"], "to": new_entry})
            return {"goal_id": goal_id, "entry": new_entry, "strategies": route["strategies"]}

    def _last_sent(self, db, subproject_id):
        found = row(db, "SELECT s.* FROM shipment s JOIN slot l ON l.id=s.slot_id JOIN goal g ON g.id=l.goal_id "
                        "WHERE g.subproject_id=? AND s.kind IN ('formal','initial') ORDER BY s.id DESC LIMIT 1",
                    (subproject_id,))
        return found

    # ------------------------------------------------------------------ advance
    def advance(self, project_id, slot_id, action, payload=None, revision=None):
        payload = dict(payload or {})
        with self.store.transaction() as db:
            project = self._require(db, "project", project_id)
            slot = self._require(db, "slot", slot_id)
            goal = self._require(db, "goal", slot["goal_id"])
            subproject = self._require(db, "subproject", goal["subproject_id"])
            if subproject["project_id"] != project_id:
                raise ValueError("目标位不属于该项目")
            if revision is not None and int(revision) != slot["revision"]:
                raise ValueError("状态已更新，请刷新后重试")
            if action == "pause":
                planning.pause(db, slot, payload.get("note", ""))
                issues.open_issue(db, "slot", slot_id, "blocked", ("已暂存",), next_action="恢复后继续",
                                  node="pause")
                Store.audit(db, "pause", "slot", slot_id, "pause", payload)
                return self._advance_result(db, slot_id, "已暂存")
            if action == "resume":
                planning.resume(db, slot)
                issues.resolve_issue(db, "slot", slot_id, "blocked")
                return self._advance_result(db, slot_id, "已恢复")
            allowed = {name for name, _label in gates.ACTIONS.get(slot["stage"], [])}
            if action not in allowed:
                raise ValueError("当前阶段不能执行该动作：" + gates.stage_label(slot["stage"]))

            state = gates.facts(db, slot)
            blocking = gates.issues(state, action)
            if blocking:
                issues.sync(db, "slot", slot_id, blocking, node=action)
                return {"slot_id": slot_id, "revision": slot["revision"], "stage": slot["stage"],
                        "blocked": True, "issues": [item.as_dict() for item in blocking]}
            handler = getattr(self, "_do_" + action, None)
            if handler is None:
                raise ValueError("不支持的动作 " + action)
            try:
                notice = handler(db, project, subproject, goal, slot, state, payload)
            except StepBlocked as stop:
                issues.sync(db, "slot", slot_id, [stop.spec], node=action)
                return {"slot_id": slot_id, "revision": slot["revision"], "stage": slot["stage"],
                        "blocked": True, "issues": [stop.spec.as_dict()]}
            fresh = row(db, "SELECT stage FROM slot WHERE id=?", (slot_id,))
            stage = fresh["stage"] if fresh["stage"] != slot["stage"] else gates.next_stage(slot, action)
            update(db, "slot", slot_id, revision=slot["revision"] + 1, **({"stage": stage} if stage != slot["stage"] else {}))
            self.recompute(db, project_id)
            self._revalidate(db, slot_id)
            Store.audit(db, action, "slot", slot_id, "advance", payload, revision=slot["revision"] + 1)
            return self._advance_result(db, slot_id, notice or "")

    def _revalidate(self, db, slot_id):
        slot = row(db, "SELECT * FROM slot WHERE id=?", (slot_id,))
        if not slot:
            return []
        return issues.revalidate(db, "slot", slot_id, gates.blocking(db, slot))

    def _advance_result(self, db, slot_id, notice):
        updated = row(db, "SELECT * FROM slot WHERE id=?", (slot_id,))
        return {"slot_id": slot_id, "revision": updated["revision"], "stage": updated["stage"],
                "blocked": False, "notice": notice,
                "actions": gates.available(db, updated),
                "issues": [issues.as_dict(item) for item in issues.open_for(db, "slot", slot_id)]}

    def _do_pick(self, db, project, subproject, goal, slot, state, payload):
        if not slot["fragrance_id"]:
            raise ValueError("请先选定香精")
        update(db, "subproject", subproject["id"], status="active")
        return f"已选定 {slot['fragrance_id']}"

    def _do_build_checks(self, db, project, subproject, goal, slot, state, payload):
        scope = self._scope(slot, subproject, goal)
        fields = loads(goal["fields"], {})
        markets = payload.get("markets") or fields.get("markets") or []
        category = payload.get("review_category") or fields.get("review_category_id") or ""
        if not category:
            category = self.rules.infer_category(" ".join(filter(None, [
                str(fields.get("substrate", "")), str(fields.get("end_product", ""))])))
        context = context_from(fields, category, markets, slot["fragrance_id"], slot["formula_version"], scope)
        drafts, coverage, grouped = build_requirements(self.rules, context)
        latest = row(db, "SELECT * FROM check_set WHERE slot_id=? ORDER BY revision DESC LIMIT 1", (slot["id"],))
        revision = (latest["revision"] + 1) if latest else 1
        check_set_id = insert(db, "check_set", slot_id=slot["id"], fragrance_id=slot["fragrance_id"],
                              formula_version=slot["formula_version"], scope=scope,
                              review_category=category, markets=dumps(markets), context=dumps(fields),
                              coverage=dumps(coverage), rules_version=self.rules.version, revision=revision)
        for draft in drafts:
            insert(db, "requirement", check_set_id=check_set_id, metric_id=draft.metric_id,
                   subitem=draft.subitem, department=draft.department, source=draft.source,
                   source_key=draft.source_key, origin_text=draft.origin_text,
                   mandatory=1 if draft.mandatory else 0, deferral=draft.deferral,
                   criteria=draft.criteria, conditions=dumps(draft.conditions),
                   conditions_key=draft.conditions_key, due_stage=draft.due_stage,
                   status="unverified")
        self._rematch(db, check_set_id)
        counted = one(db, "SELECT COUNT(*) FROM requirement WHERE check_set_id=?", (check_set_id,), 0)
        reused = one(db, "SELECT COUNT(*) FROM requirement WHERE check_set_id=? AND status!='unverified'",
                     (check_set_id,), 0)
        return (f"生成 {counted} 条检查要求" +
                (f"，其中 {reused} 条有既有证据可直接核销" if reused else ""))

    def _do_dispatch_checks(self, db, project, subproject, goal, slot, state, payload):
        check_set = state["check_set"]
        if not check_set:
            raise ValueError("先生成检查清单")
        requirements = rows(db, "SELECT * FROM requirement WHERE check_set_id=? AND status='unverified'",
                            (check_set["id"],))
        if not requirements:
            return "没有待派发的要求，现有证据已覆盖"
        grouped = {}
        for requirement in requirements:
            grouped.setdefault(requirement["department"], []).append(requirement)
        for department, items in grouped.items():
            spec = {"fragrance_id": slot["fragrance_id"], "formula_version": slot["formula_version"],
                    "scope": check_set["scope"], "review_category": check_set["review_category"],
                    "markets": loads(check_set["markets"], []),
                    "requirement_ids": [item["id"] for item in items],
                    "requirements": [{"id": item["id"], "metric_id": item["metric_id"],
                                      "metric_name": self.rules.metrics.get(item["metric_id"], {}).get("name", ""),
                                      "subitem": item["subitem"], "criteria": item["criteria"],
                                      "conditions": loads(item["conditions"], {})} for item in items]}
            self._dispatch(db, project, subproject, slot, "check", department, spec)
            db.execute("UPDATE requirement SET status='pending' WHERE id IN (" +
                       ",".join("?" for _ in items) + ")", [item["id"] for item in items])
        return f"已向 {len(grouped)} 个部门派发 {len(requirements)} 条要求"

    def _do_release_warehouse(self, db, project, subproject, goal, slot, state, payload):
        return self._decide(db, slot, state, "warehouse", payload)

    def _do_release_initial(self, db, project, subproject, goal, slot, state, payload):
        return self._decide(db, slot, state, "initial", payload)

    def _do_release_formal(self, db, project, subproject, goal, slot, state, payload):
        return self._decide(db, slot, state, "formal", payload)

    def _decide(self, db, slot, state, action, payload):
        check_set = state["check_set"]
        requirements = state["requirements"]
        verdict = release_rules.decide(action, requirements)
        deferred = [{"requirement_id": item["requirement_id"], "metric": item["metric"]}
                    for item in verdict.deferred]
        if action == "initial" and verdict.passed and deferred and not clean(payload.get("note")):
            raise ValueError("暂缓需要填写说明与承诺补齐时间")
        decision_id = insert(db, "release_decision", check_set_id=check_set["id"], slot_id=slot["id"],
                             action=action, verdict="passed" if verdict.passed else "blocked",
                             blockers=dumps([{k: v for k, v in item.items() if k != "why"} for item in verdict.blockers]),
                             deferred=dumps(deferred), reason=clean(payload.get("note"), 300),
                             actor=clean(payload.get("actor", "评香"), 60),
                             fingerprint=canon(str(check_set["id"]) + action))
        if not verdict.passed:
            raise StepBlocked(IssueSpec("check_failed",
                                        missing=tuple(item["metric"] for item in verdict.blockers[:6]),
                                        next_action=verdict.reason))
        booked = loads(row(db, "SELECT payload FROM slot WHERE id=?", (slot["id"],))["payload"], {})
        booked["release_" + action] = decision_id
        booked["shipment_kind"] = "formal" if action == "formal" else booked.get("shipment_kind", "initial")
        if action == "initial":
            booked["shipment_kind"] = "initial"
        update(db, "slot", slot["id"], payload=dumps(booked))
        return f"{enums.RELEASE_LABELS[action]}通过" + (f"，暂缓 {len(deferred)} 项" if deferred else "")

    def _do_dispatch_warehouse(self, db, project, subproject, goal, slot, state, payload):
        spec = {"fragrance_id": slot["fragrance_id"], "formula_version": slot["formula_version"],
                "check_set_id": state["check_set"]["id"] if state["check_set"] else None}
        self._dispatch(db, project, subproject, slot, "warehouse", "warehouse", spec)
        return "已派发入库"

    def _do_accept_warehouse(self, db, project, subproject, goal, slot, state, payload):
        task = (state["by_type"].get("warehouse") or [None])[-1]
        fragrance_id = payload.get("fragrance_id") or slot["fragrance_id"]
        version = payload.get("formula_version") or slot["formula_version"]
        record_id = insert(db, "warehouse_record", slot_id=slot["id"], task_id=task["id"] if task else None,
                           fragrance_id=fragrance_id, formula_version=version,
                           approved_by=clean(payload.get("actor", "评香"), 60),
                           check_set_id=state["check_set"]["id"] if state["check_set"] else None,
                           release_decision_id=(state["releases"].get("warehouse") or {}).get("id"))
        if (fragrance_id, version) != (slot["fragrance_id"], slot["formula_version"]):
            db.execute("UPDATE evidence SET fragrance_id=?, formula_version=? "
                       "WHERE fragrance_id=? AND formula_version=?",
                       (fragrance_id, version, slot["fragrance_id"], slot["formula_version"]))
            Store.audit(db, "accept_warehouse", "slot", slot["id"], "rename_fragrance",
                        {"from": slot["fragrance_id"], "to": fragrance_id,
                         "from_version": slot["formula_version"], "to_version": version})
        update(db, "slot", slot["id"], fragrance_id=fragrance_id, formula_version=version)
        if subproject["final_endpoint"] == "warehouse_return" and subproject["parent_slot_id"]:
            parent_slot_id = planning.return_to_parent(db, subproject["id"], fragrance_id, version)
            update(db, "slot", slot["id"], stage="complete")
            return f"已入库 {fragrance_id}，已回到父项目标位 {parent_slot_id}"
        if subproject["final_endpoint"] == "warehouse":
            update(db, "slot", slot["id"], stage="complete")
            return f"已入库 {fragrance_id}，目标完成"
        fresh = row(db, "SELECT * FROM slot WHERE id=?", (slot["id"],))
        self._do_build_checks(db, project, subproject, goal, fresh, gates.facts(db, fresh), {})
        return f"已入库 {fragrance_id}，按客户交付重建二查清单"

    def _do_prepare_sample(self, db, project, subproject, goal, slot, state, payload):
        result = self.platform.reserve(db, slot["fragrance_id"], slot["formula_version"],
                                       clean(payload.get("quantity"), 40), clean(payload.get("unit"), 20))
        if not result["ok"]:
            raise StepBlocked(IssueSpec("stock_short", missing=(result["note"],),
                                        next_action="等库存或改寄样量"))
        booked = loads(row(db, "SELECT payload FROM slot WHERE id=?", (slot["id"],))["payload"], {})
        booked.update(sample_id=result["sample_id"], sample_form=clean(payload.get("form"), 120) or
                      booked.get("sample_form", ""), quantity=clean(payload.get("quantity"), 40),
                      unit=clean(payload.get("unit"), 20))
        update(db, "slot", slot["id"], payload=dumps(booked))
        return f"已预留样品 {result['sample_id']}"

    def _do_dispatch_shipment(self, db, project, subproject, goal, slot, state, payload):
        booked = loads(row(db, "SELECT payload FROM slot WHERE id=?", (slot["id"],))["payload"], {})
        kind = booked.get("shipment_kind") or "formal"
        spec = {"fragrance_id": slot["fragrance_id"], "formula_version": slot["formula_version"],
                "sample_id": booked.get("sample_id", ""), "sample_form": booked.get("sample_form", ""),
                "quantity": booked.get("quantity", ""), "unit": booked.get("unit", ""),
                "kind": kind, "goal_id": goal["id"], "release": booked.get("release_" + kind)}
        self._dispatch(db, project, subproject, slot, "shipment", "shipment", spec)
        return "已派发寄样"

    def _do_record_shipment(self, db, project, subproject, goal, slot, state, payload):
        booked = loads(row(db, "SELECT payload FROM slot WHERE id=?", (slot["id"],))["payload"], {})
        kind = payload.get("kind") or booked.get("shipment_kind") or "formal"
        existing = row(db, "SELECT id FROM shipment WHERE slot_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                       (slot["id"], kind))
        if existing:
            return "这次寄样已经记录过"
        self._record_shipment(db, slot, goal, payload)
        if kind == "formal":
            update(db, "slot", slot["id"], stage="complete")
            return "已记录正式寄样，目标完成"
        update(db, "slot", slot["id"], stage="checking", revision=slot["revision"] + 1)
        return "已记录初寄样，可继续正式寄样"

    def _record_shipment(self, db, slot, goal, payload):
        booked = loads(row(db, "SELECT payload FROM slot WHERE id=?", (slot["id"],))["payload"], {})
        kind = payload.get("kind") or booked.get("shipment_kind") or "formal"
        shipment_id = insert(db, "shipment", slot_id=slot["id"], goal_id=goal["id"],
                             task_id=payload.get("task_id"), kind=kind,
                             fragrance_id=payload.get("fragrance_id") or slot["fragrance_id"],
                             formula_version=payload.get("formula_version") or slot["formula_version"],
                             sample_id=payload.get("sample_id") or booked.get("sample_id", ""),
                             sample_form=payload.get("sample_form") or booked.get("sample_form", ""),
                             quantity=payload.get("quantity") or booked.get("quantity", ""),
                             unit=payload.get("unit") or booked.get("unit", ""),
                             tracking=clean(payload.get("tracking"), 120), status="applied",
                             shipped_at=now())
        booked.pop("sample_id", None)
        booked.pop("release_" + kind, None)
        update(db, "slot", slot["id"], payload=dumps(booked))
        return shipment_id

    # ------------------------------------------------------------------ development
    def _do_confirm_gc(self, db, project, subproject, goal, slot, state, payload):
        job = state["job"]
        report = clean(payload.get("report"), 200) or job["gc_report"]
        update(db, "job", job["id"], gc_report=report)
        if state["trial"]:
            return "GC 已确认；已有试作可直接验收"
        if any(task["status"] in ("sent", "queued") for task in state["by_type"].get("perfumery", [])):
            return "GC 已确认；调香任务已在进行"
        self._dispatch(db, project, subproject, slot, "perfumery", "perfumery",
                       {"fragrance_id": "", "formula_version": "", "gc_report": report,
                        "sample_reference": loads(job["reference"], {}).get("sample_reference", "")})
        return "GC 已确认，已派发调香"

    def _do_accept_trial(self, db, project, subproject, goal, slot, state, payload):
        trial = state["trial"]
        insert(db, "evaluation", trial_id=trial["id"], verdict="passed",
               comments=clean(payload.get("note"), 500), actor=clean(payload.get("actor", "评香"), 60))
        update(db, "job", state["job"]["id"], approved_trial_id=trial["id"], status="approved")
        update(db, "slot", slot["id"], fragrance_id=trial["trial_fragrance_id"],
               formula_version=trial["formula_version"], stage="checking")
        return f"已验收 {trial['trial_fragrance_id']}"

    def _do_reject_trial(self, db, project, subproject, goal, slot, state, payload):
        trial = state["trial"]
        note = clean(payload.get("note"), 500)
        if not note:
            raise ValueError("退回调香需要写清下一次的意见")
        insert(db, "evaluation", trial_id=trial["id"], verdict="rejected", comments=note,
               actor=clean(payload.get("actor", "评香"), 60))
        iteration = state["job"]["current_iteration"] + 1
        update(db, "job", state["job"]["id"], current_iteration=iteration)
        self._dispatch(db, project, subproject, slot, "perfumery", "perfumery",
                       {"fragrance_id": trial["trial_fragrance_id"],
                        "formula_version": trial["formula_version"],
                        "previous_evaluation": note, "iteration": iteration})
        return f"已退回，进入第 {iteration} 次调香"

    # ------------------------------------------------------------------ dispatch
    def _dispatch(self, db, project, subproject, slot, task_type, department, spec):
        task_id = insert(db, "task", project_id=project["id"], subproject_id=subproject["id"],
                         round_id=slot["round_id"], slot_id=slot["id"], department=department,
                         task_type=task_type, spec=dumps(spec), status="queued",
                         updated_at=now())
        task = row(db, "SELECT * FROM task WHERE id=?", (task_id,))
        external = self.platform.dispatch(db, task)
        return task_id, external

    # ------------------------------------------------------------------ receipts
    def apply_receipt(self, task_id, passed, payload=None):
        payload = dict(payload or {})
        with self.store.transaction() as db:
            task = self._require(db, "task", task_id)
            if task["status"] in ("done", "failed", "cancelled"):
                raise ValueError("该回执已处理")
            spec = loads(task["spec"], {})
            event = self.platform.receipt(db, task, passed, payload)
            task = row(db, "SELECT * FROM task WHERE id=?", (task_id,))
            if task["task_type"] == "analysis":
                self._apply_analysis(db, task, spec, passed, payload)
            elif task["task_type"] == "perfumery":
                self._apply_perfumery(db, task, spec, passed, payload)
            elif task["task_type"] == "check":
                self._apply_check(db, task, spec, passed, payload)
            elif task["task_type"] == "warehouse":
                pass
            elif task["task_type"] == "shipment":
                self._apply_shipment(db, task, spec, passed, payload)
            self.recompute(db, task["project_id"])
            if task["slot_id"]:
                self._revalidate(db, task["slot_id"])
            Store.audit(db, "apply_receipt", "task", task_id, "receipt",
                        {"passed": passed, "event": event["event_id"]})
            return event

    def _apply_analysis(self, db, task, spec, passed, payload):
        slot = self._require(db, "slot", task["slot_id"])
        project = self._require(db, "project", task["project_id"])
        subproject = self._require(db, "subproject", task["subproject_id"])
        job = row(db, "SELECT * FROM job WHERE slot_id=? ORDER BY id DESC LIMIT 1", (slot["id"],))
        if not job:
            return
        if passed:
            report = clean(payload.get("document"), 200) or f"DIY-GC-{task['id']}"
            update(db, "job", job["id"], gc_report=report)
            self._dispatch(db, project, subproject, slot, "perfumery", "perfumery",
                           {"gc_report": report,
                            "sample_reference": loads(job["reference"], {}).get("sample_reference", "")})
            issues.resolve_issue(db, "slot", slot["id"], "gc_pending")
        else:
            issues.open_issue(db, "slot", slot["id"], "sample_unavailable", ("分析样不可用",),
                              next_action="换样或补报告")

    def _apply_perfumery(self, db, task, spec, passed, payload):
        slot = self._require(db, "slot", task["slot_id"])
        job = row(db, "SELECT * FROM job WHERE slot_id=? ORDER BY id DESC LIMIT 1", (slot["id"],))
        if not job:
            return
        if not passed:
            issues.open_issue(db, "slot", slot["id"], "trial_pending", ("调香未完成",),
                              next_action="重派或改方")
            return
        code = clean(payload.get("trial_fragrance_id"), 60) or f"DIY-{job['dev_type'].upper()}-{job['current_iteration']:02d}"
        version = clean(payload.get("formula_version"), 60) or f"V{job['current_iteration']}"
        existing = row(db, "SELECT * FROM trial WHERE job_id=? AND iteration=?", (job["id"], job["current_iteration"]))
        if existing:
            update(db, "trial", existing["id"], trial_fragrance_id=code, formula_version=version,
                   notes=clean(payload.get("note"), 500), sample_id=clean(payload.get("sample_id"), 60))
        else:
            insert(db, "trial", job_id=job["id"], iteration=job["current_iteration"],
                   trial_fragrance_id=code, formula_version=version,
                   sample_id=clean(payload.get("sample_id"), 60), notes=clean(payload.get("note"), 500))
        issues.resolve_issue(db, "slot", slot["id"], "trial_pending")

    def _apply_check(self, db, task, spec, passed, payload):
        results = payload.get("results") or []
        by_id = {int(item["requirement_id"]): item for item in results if item.get("requirement_id")}
        ids = spec.get("requirement_ids") or []
        if not ids:
            return
        requirements = rows(db, "SELECT * FROM requirement WHERE id IN (" + ",".join("?" for _ in ids) + ")",
                            ids)
        for requirement in requirements:
            item = by_id.get(requirement["id"], {"passed": passed})
            verdict = "passed" if item.get("passed", passed) else "failed"
            insert(db, "evidence", **evidence_rules.receipt_evidence(
                {"passed": verdict == "passed", "measured": item.get("measured", ""),
                 "unit": item.get("unit", ""), "method": item.get("method", ""),
                 "document": item.get("document", "") or payload.get("document", ""),
                 "tested_at": item.get("tested_at", date.today().isoformat()),
                 "valid_until": item.get("valid_until", ""),
                 "approved_by": payload.get("actor", "mock")},
                {"id": task["id"], "spec": spec}, requirement))
            db.execute("UPDATE requirement SET status=?, note=? WHERE id=?",
                       (verdict, clean(item.get("note"), 300), requirement["id"]))
        check_set_id = one(db, "SELECT check_set_id FROM requirement WHERE id=?", (ids[0],))
        self._rematch(db, check_set_id)

    def _apply_shipment(self, db, task, spec, passed, payload):
        slot = self._require(db, "slot", task["slot_id"])
        goal = self._require(db, "goal", slot["goal_id"])
        if not passed:
            issues.open_issue(db, "slot", slot["id"], "shipment_pending", ("寄样未发出",),
                              next_action="重派寄样")
            return
        kind = payload.get("kind") or spec.get("kind") or "formal"
        shipment_id = self._record_shipment(db, slot, goal, {
            "kind": kind, "task_id": task["id"], "tracking": payload.get("tracking"),
            "sample_id": payload.get("sample_id") or spec.get("sample_id"),
            "quantity": payload.get("quantity") or spec.get("quantity"),
            "unit": payload.get("unit") or spec.get("unit"),
            "sample_form": payload.get("sample_form") or spec.get("sample_form")})
        if kind == "formal":
            update(db, "slot", slot["id"], stage="complete")
        else:
            update(db, "slot", slot["id"], stage="checking", revision=slot["revision"] + 1)

    def _rematch(self, db, check_set_id):
        if not check_set_id:
            return
        check_set = row(db, "SELECT * FROM check_set WHERE id=?", (check_set_id,))
        if not check_set:
            return
        requirements = rows(db, "SELECT * FROM requirement WHERE check_set_id=?", (check_set_id,))
        evidences = rows(db, "SELECT * FROM evidence WHERE fragrance_id=? AND (formula_version=? OR formula_version='')",
                         (check_set["fragrance_id"], check_set["formula_version"]))
        updates = evidence_rules.match(requirements, evidences)
        for requirement in requirements:
            change = updates.get(requirement["id"])
            if not change:
                continue
            if requirement["status"] == "pending" and change["status"] == "unverified":
                continue
            db.execute("UPDATE requirement SET status=?, evidence_id=?, note=? WHERE id=?",
                       (change["status"], change["evidence_id"], change["note"], requirement["id"]))

    # ------------------------------------------------------------------ progress
    def _scope(self, slot, subproject, goal):
        payload = loads(slot["payload"], {})
        if payload.get("endpoint") in ("warehouse", "warehouse_return") or subproject["final_endpoint"] != "shipment":
            return "warehouse"
        return "shipment"

    def recompute(self, db, project_id):
        for subproject in rows(db, "SELECT * FROM subproject WHERE project_id=?", (project_id,)):
            goals = rows(db, "SELECT * FROM goal WHERE subproject_id=?", (subproject["id"],))
            for goal in goals:
                slots = rows(db, "SELECT * FROM slot WHERE goal_id=?", (goal["id"],))
                complete = bool(slots) and all(slot["stage"] == "complete" for slot in slots)
                update(db, "goal", goal["id"], status="complete" if complete else "active")
            for round_row in rows(db, "SELECT * FROM round WHERE subproject_id=?", (subproject["id"],)):
                round_goals = rows(db, "SELECT * FROM goal WHERE round_id=?", (round_row["id"],))
                done = bool(round_goals) and all(goal["status"] == "complete" for goal in round_goals)
                update(db, "round", round_row["id"], status="complete" if done else "active")
            if subproject["status"] == "completed":
                continue
            if subproject["final_endpoint"] == "warehouse_return":
                if any(slot["stage"] == "complete" for slot in
                       rows(db, "SELECT * FROM slot WHERE goal_id IN (SELECT id FROM goal WHERE subproject_id=?)",
                            (subproject["id"],))):
                    update(db, "subproject", subproject["id"], status="completed")
                continue
            states = rows(db, "SELECT status FROM goal WHERE subproject_id=?", (subproject["id"],))
            if states and all(item["status"] == "complete" for item in states):
                update(db, "subproject", subproject["id"], status="completed")
        remaining = one(db, "SELECT COUNT(*) FROM subproject WHERE project_id=? AND status='active'", (project_id,), 0)
        update(db, "project", project_id, status="active" if remaining else "completed")

    # ------------------------------------------------------------------ helpers
    def _require(self, db, table, row_id):
        if row_id in (None, "", 0):
            raise ValueError("缺少对象编号")
        found = row(db, f"SELECT * FROM {table} WHERE id=?", (row_id,))
        if not found:
            raise ValueError("对象不存在或已删除")
        return found

    def _recent_context(self, db, project_id):
        briefs = rows(db, "SELECT r.brief, r.no, s.title FROM round r JOIN subproject s ON s.id=r.subproject_id "
                          "WHERE s.project_id=? ORDER BY r.id DESC LIMIT 6", (project_id,))
        shipments = rows(db, "SELECT sh.fragrance_id, sh.formula_version, sh.kind, g.label FROM shipment sh "
                             "JOIN goal g ON g.id=sh.goal_id JOIN subproject s ON s.id=g.subproject_id "
                             "WHERE s.project_id=? ORDER BY sh.id DESC LIMIT 20", (project_id,))
        return {"rounds": [{"no": item["no"], "title": item["title"], "brief": loads(item["brief"], {})}
                           for item in briefs],
                "shipments": [{"label": item["label"], "fragrance_id": item["fragrance_id"],
                               "formula_version": item["formula_version"], "kind": item["kind"]}
                              for item in shipments]}

    # ------------------------------------------------------------------ search
    def ensure_targeting(self, goal_id):
        """Compute C tags for a goal once, keep the result and its evidence."""
        with self.store.connect() as db:
            goal = row(db, "SELECT * FROM goal WHERE id=?", (goal_id,))
            if not goal:
                raise ValueError("目标不存在")
            subproject = row(db, "SELECT * FROM subproject WHERE id=?", (goal["subproject_id"],))
            fields = loads(goal["fields"], {})
        if (fields.get("targeting") or {}).get("groups"):
            return fields["targeting"]
        mode = fields.get("mode") or brief_model.mode_for(subproject["requirement_type"] if subproject else "")
        result = targeting.tag_direction(fields, mode, self.catalog, self.config)
        with self.store.transaction() as db:
            fresh = loads(row(db, "SELECT fields FROM goal WHERE id=?", (goal_id,))["fields"], {})
            fresh["targeting"] = result
            update(db, "goal", goal_id, fields=dumps(fresh))
            Store.audit(db, "targeting", "goal", goal_id, result.get("method", ""),
                        {"c_ids": result.get("c_ids", []), "unmapped": len(result.get("unmapped", []))})
        return result

    def search(self, query, page=1, project_id=None, limit=30, goal_id=None):
        if not isinstance(query, dict):
            query = {"text": str(query or "")}
        if goal_id:
            with self.store.connect() as db:
                goal = row(db, "SELECT * FROM goal WHERE id=?", (goal_id,))
            if not goal:
                raise ValueError("目标不存在")
            fields = loads(goal["fields"], {})
            mapped = query.get("groups") or (fields.get("targeting") or {}).get("groups")
            if not mapped:
                mapped = self.ensure_targeting(goal_id).get("groups")
            base = {"text": query.get("text") or fields.get("scent_text") or "",
                    "mode": query.get("mode") or "recommend_simple",
                    "categories": [fields["application_id"]] if fields.get("application_id") else [],
                    "groups": mapped or [],
                    "min_price": fields.get("price_min"), "max_price": fields.get("price_max")}
            query = {**base, **{key: value for key, value in query.items() if value not in (None, "", [])}}
        if query.get("text") and not query.get("groups"):
            parsed = ranking.parse_text(query["text"], self.catalog, self.config)
            if query.get("mode"):
                parsed["mode"] = query["mode"]
            if query.get("categories"):
                parsed["categories"] = query["categories"]
            query = parsed
        normalized = ranking.normalize_query(query, self.catalog.terms, self.catalog.categories, self.config)
        if not (normalized.get("groups") or normalized.get("categories") or normalized.get("exact")
                or normalized.get("min_price") or normalized.get("max_price")
                or normalized.get("target_price")):
            raise ValueError("请输入要找的香型、产品或描述；只按价格或品类筛选也可以")
        with self.store.connect() as db:
            edits = {item["asset_key"]: loads(item["payload"], {}) for item in db.execute("SELECT * FROM asset_edit")}
            quotes = self.platform.quotes(db)
        labels = self.catalog.products_by_code()
        result = ranking.rank(normalized, self.catalog.asset_rows(edits, quotes, labels),
                              self.catalog.terms, self.catalog.categories, self.catalog.edges, self.config)
        if normalized.get("exact"):
            rows_all, clues = self._exact(normalized, edits, quotes, labels)
            alternatives = []
        else:
            rows_all, clues, alternatives = result["results"], [], result["alternatives"]
        total = len(rows_all)
        page = max(1, int(page or 1))
        start = (page - 1) * limit
        payload = {
            "query": normalized, "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit),
            "results": rows_all[start:start + limit], "alternatives": alternatives[:12],
            "clues": clues[:12], "diagnostics": result["diagnostics"],
            "scoring_version": result["scoring_version"],
            "unmatched_total": sum(1 for item in rows_all if item.get("score") is None),
            "unmatched_preview": [{"name": item["name"], "fragrance_id": item["fragrance_id"]}
                                  for item in rows_all if item.get("score") is None][:6],
        }
        if project_id:
            with self.store.transaction() as db:
                payload["query_id"] = self._save_query(db, project_id, normalized, payload)
        return payload

    def _save_query(self, db, project_id, normalized, payload):
        fingerprint = digest(json.dumps(normalized, ensure_ascii=False, sort_keys=True))
        existing = row(db, "SELECT id FROM search_run WHERE project_id=? AND fingerprint=?",
                       (project_id, fingerprint))
        if existing:
            return existing["id"]
        preview = {"total": payload["total"],
                   "top": [{"fragrance_id": item["fragrance_id"], "name": item["name"],
                            "score": item.get("score")} for item in payload["results"][:5]]}
        return insert(db, "search_run", project_id=project_id, fingerprint=fingerprint,
                      input=dumps(normalized), preview=dumps(preview))

    def _exact(self, query, edits, quotes, labels):
        state = {"confirmed", "manual"}
        include_suggested = query.get("big_brand") == "include_suggested"
        if include_suggested:
            state.add("suggested")
        rows_all, clues = [], []
        wanted_product = query.get("product_id") or ""
        wanted_edition = query.get("edition") or ""
        for asset in self.catalog.asset_rows(edits, quotes, labels):
            matches = [item for item in asset["exact_products"]
                       if not wanted_product or item["product_id"] == wanted_product]
            if not matches:
                continue
            confirmed = [item for item in matches if item["status"] in state]
            card = {**asset["card"], "branches": [], "score": None, "penalty": 0,
                    "direct_hits": [], "cross_hits": [], "unmatched": [], "negative_hits": [],
                    "risks": [], "reason": "精确命中 " + matches[0]["name"],
                    "products": matches, "blocked": []}
            if not confirmed:
                card["risks"] = ["目录关系只是建议，待确认后再选"]
                clues.append(card)
                continue
            edition_ok = [item for item in confirmed if not wanted_edition
                          or (item["edition"] or "").lower() == wanted_edition.lower()]
            if not edition_ok:
                card["risks"] = ["版本待确认：目录关系未绑定 " + (wanted_edition or "该版本")]
                clues.append(card)
                continue
            if query.get("max_price") and asset["price"] is not None and \
                    asset["price"] > Decimal(query["max_price"]):
                card["risks"] = ["超价"]
                clues.append(card)
                continue
            rows_all.append(card)
        return rows_all, clues

    def edit_asset(self, payload):
        key = clean(payload.get("key") or payload.get("asset_key"), 120)
        if key not in self.catalog.raw:
            raise ValueError("香精不存在：" + (key or "未指定"))
        with self.store.transaction() as db:
            existing = row(db, "SELECT payload FROM asset_edit WHERE asset_key=?", (key,))
            current = loads(existing["payload"], {}) if existing else {}
            tags = payload.get("tags")
            if tags is not None:
                current["tags"] = [tag for tag in tags if tag in self.catalog.terms]
            if payload.get("name"):
                current["name"] = clean(payload["name"], 200)
            if payload.get("product_ids") is not None:
                current["product_ids"] = [pid for pid in payload["product_ids"] if pid in self.catalog.products]
            db.execute("INSERT INTO asset_edit(asset_key,payload,updated_at) VALUES(?,?,?) "
                       "ON CONFLICT(asset_key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                       (key, dumps(current), now()))
            Store.audit(db, "edit_asset", "asset", key, "update", current)
        return current

    def target(self, text, mode, categories, model=None):
        return targeting.map_brief(text, mode, categories, self.catalog, self.config, model=model)
