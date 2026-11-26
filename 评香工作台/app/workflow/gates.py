"""Slot stages, actions and their preconditions. Blocking is data, not exceptions."""

from ..domain import enums
from ..domain.models import IssueSpec

ACTIONS = {
    "planned": [
        ("pick", "选定库香"), ("develop", "启动开发"), ("pause", "暂存"),
    ],
    "developing": [
        ("confirm_gc", "确认 GC 报告"), ("accept_trial", "验收通过"),
        ("reject_trial", "退回调香"), ("pause", "暂存"),
    ],
    "checking": [
        ("build_checks", "生成检查清单"), ("dispatch_checks", "派发检查"),
        ("release_warehouse", "入库放行"), ("dispatch_warehouse", "派发入库"),
        ("accept_warehouse", "确认入库"), ("release_initial", "初寄样放行"),
        ("release_formal", "正式寄样放行"), ("pause", "暂存"),
    ],
    "shipping": [
        ("prepare_sample", "准备样品"), ("dispatch_shipment", "派发寄样"), ("pause", "暂存"),
    ],
    "complete": [],
    "cancelled": [],
}


def facts(db, slot):
    from ..store.db import loads

    slot = dict(slot)
    slot["payload"] = loads(slot.get("payload"), {}) or {}
    slot_id = slot["id"]
    job = db.execute("SELECT * FROM job WHERE slot_id=? ORDER BY id DESC LIMIT 1", (slot_id,)).fetchone()
    trial = None
    if job:
        trial = db.execute("SELECT * FROM trial WHERE job_id=? ORDER BY iteration DESC LIMIT 1",
                           (job["id"],)).fetchone()
    check_set = db.execute(
        "SELECT * FROM check_set WHERE slot_id=? ORDER BY revision DESC, id DESC LIMIT 1",
        (slot_id,)).fetchone()
    requirements = []
    if check_set:
        requirements = db.execute("SELECT * FROM requirement WHERE check_set_id=?", (check_set["id"],)).fetchall()
    releases = {item["action"]: dict(item) for item in db.execute(
        "SELECT * FROM release_decision WHERE slot_id=? ORDER BY id", (slot_id,))}
    tasks = db.execute("SELECT * FROM task WHERE slot_id=? ORDER BY id", (slot_id,)).fetchall()
    by_type = {}
    for task in tasks:
        by_type.setdefault(task["task_type"], []).append(task)
    warehouse = db.execute("SELECT * FROM warehouse_record WHERE slot_id=? ORDER BY id DESC LIMIT 1",
                           (slot_id,)).fetchone()
    shipments = db.execute("SELECT * FROM shipment WHERE slot_id=? ORDER BY id", (slot_id,)).fetchall()
    return {
        "slot": dict(slot), "job": dict(job) if job else None, "trial": dict(trial) if trial else None,
        "check_set": dict(check_set) if check_set else None,
        "requirements": [dict(item) for item in requirements],
        "releases": releases, "tasks": [dict(item) for item in tasks], "by_type": by_type,
        "warehouse": dict(warehouse) if warehouse else None,
        "shipments": [dict(item) for item in shipments],
        "initial_sent": any(item["kind"] == "initial" for item in shipments),
        "formal_sent": any(item["kind"] in ("formal", "resend") for item in shipments),
        "passed_release": {name: item for name, item in releases.items() if item["verdict"] == "passed"},
    }


def _open_release(state, action):
    decision = state["releases"].get(action)
    return decision if decision and decision["verdict"] == "passed" else None


def issues(state, action):
    """Preconditions for one action. Returns IssueSpec tuples."""
    found = []
    slot = state["slot"]
    strategy = slot["strategy"]
    endpoint = slot["payload"].get("endpoint") if isinstance(slot["payload"], dict) else None
    endpoint = endpoint or "shipment"
    job = state["job"]

    def need(condition, code, missing=(), next_action="", waiting=()):
        if not condition:
            found.append(IssueSpec(code, tuple(missing), tuple(waiting), next_action))

    if action == "pick":
        need(strategy in ("select", "resend", "adopt"), "blocked", ("该方案不是选香",),
             "改走开发或结束该目标")
    elif action == "develop":
        need(strategy in ("duplicate", "create", "modify"), "blocked", ("该方案不是开发",), "直接选香")
        if strategy == "modify":
            need(bool(slot["payload"].get("base_version")), "formula_unknown", ("原配方版本",),
                 "填写可用配方版本，或转对香")
        if strategy == "duplicate":
            need(bool(slot["payload"].get("sample_reference")), "sample_unavailable", ("分析样",),
                 "登记分析样后启动仿香")
        need(not job, "blocked", ("开发已启动",), "在开发节点继续")
    elif action == "confirm_gc":
        need(job and job["dev_type"] == "duplicate", "blocked", ("不是仿香",), "直接验收试作")
        need(bool(job and job["gc_report"]), "gc_pending", ("GC 报告",), "等分析回执或补录报告",
             ("analysis",))
    elif action == "accept_trial":
        need(bool(state["trial"]), "trial_pending", ("试作",), "等调香回执", ("perfumery",))
        need(not job or job["dev_type"] != "duplicate" or bool(job["gc_report"]), "gc_pending",
             ("GC 报告",), "先确认分析回执")
        need(not job or not job["approved_trial_id"], "blocked", ("已验收",), "继续检查")
    elif action == "reject_trial":
        need(bool(state["trial"]), "trial_pending", ("试作",), "等调香回执", ("perfumery",))
    elif action == "build_checks":
        need(bool(slot["fragrance_id"]), "reference_unresolved", ("香精编号",), "先选香或完成开发")
    elif action == "dispatch_checks":
        need(bool(state["check_set"]), "check_context_missing", ("检查清单",), "先生成检查清单")
        need(not any(task["status"] == "sent" for task in state["by_type"].get("check", [])),
             "check_pending", ("检查回执",), "等部门回执", ("check",))
    elif action.startswith("release_"):
        target = action.split("_", 1)[1]
        need(bool(state["check_set"]), "check_context_missing", ("检查清单",), "先生成检查清单")
        if target == "warehouse":
            need(endpoint != "shipment", "blocked", ("该目标终点是客户交付",), "走寄样放行")
            need(bool(slot["fragrance_id"]), "reference_unresolved", ("香精编号",), "先确定香精")
        if target in ("initial", "formal"):
            need(endpoint == "shipment", "blocked", ("该目标终点不是客户交付",), "走入库放行")
            need(bool(slot["fragrance_id"]), "reference_unresolved", ("香精编号",), "先确定香精")
        if target == "initial":
            need(slot["payload"].get("requirement_type") != "find_product", "blocked",
                 ("精确找香只开放正式寄样",), "直接正式寄样放行")
            need(not state["formal_sent"], "blocked", ("已正式寄样",), "开复寄轮")
    elif action == "dispatch_warehouse":
        need(bool(_open_release(state, "warehouse")), "check_pending", ("入库放行",), "先完成入库放行")
        need(not state["by_type"].get("warehouse"), "warehouse_pending", ("入库回执",), "等入库回执",
             ("warehouse",))
    elif action == "accept_warehouse":
        task = (state["by_type"].get("warehouse") or [None])[-1]
        need(bool(task and task["status"] == "done"), "warehouse_pending", ("入库回执",), "等入库回执",
             ("warehouse",))
        need(not state["warehouse"], "blocked", ("已确认入库",), "回到父项或继续寄样")
    elif action == "prepare_sample":
        need(bool(state["passed_release"]), "check_pending", ("寄样放行",), "先做寄样放行")
        need(bool(slot["fragrance_id"]), "reference_unresolved", ("香精编号",), "先确定香精")
    elif action == "dispatch_shipment":
        need(bool(slot["payload"].get("sample_id")), "sample_unavailable", ("实物样",), "先准备样品")
        need(not any(task["status"] in ("sent", "queued") for task in state["by_type"].get("shipment", [])),
             "shipment_pending", ("寄样回执",), "等寄样回执", ("shipment",))
    elif action == "record_shipment":
        task = (state["by_type"].get("shipment") or [None])[-1]
        need(bool(task and task["status"] == "done"), "shipment_pending", ("寄样回执",), "等寄样回执",
             ("shipment",))
        kind = state["slot"]["payload"].get("shipment_kind") or "formal"
        need(not any(item["kind"] == kind for item in state["shipments"]), "blocked",
             ("这次寄样已记录",), "继续下一步")
    elif action == "pause":
        need(not state["passed_release"], "blocked", ("已放行，不能暂存",), "继续推进或结束目标")
    return found


def available(db, slot):
    """Return every action for the stage with its blocking issues."""
    state = facts(db, slot)
    items = []
    for action, label in ACTIONS.get(slot["stage"], []):
        found = issues(state, action)
        items.append({"action": action, "label": label,
                      "enabled": not found,
                      "issues": [issue.as_dict() for issue in found]})
    return items


def blocking(db, slot):
    """Every issue the current stage would raise, regardless of which action was tried."""
    state = facts(db, slot)
    found = []
    for action, _label in ACTIONS.get(slot["stage"], []):
        found.extend(issues(state, action))
    return found


TRANSITIONS = {
    "pick": "checking",
    "develop": "developing",
    "confirm_gc": "developing",
    "accept_trial": "checking",
    "release_initial": "shipping",
    "release_formal": "shipping",
}


def next_stage(slot, action):
    return TRANSITIONS.get(action, slot["stage"])


def stage_label(stage):
    return enums.STAGE_LABELS.get(stage, stage)
