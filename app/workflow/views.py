"""Read models: everything the browser displays comes from here."""

from ..domain import enums
from ..store.db import loads, row, rows
from . import gates, issues


def bootstrap(workbench):
    rules = workbench.rules
    return {
        "service": "fragrance-workbench",
        "entries": [{"value": key, "label": enums.ENTRY_LABELS[key],
                     "strategies": list(enums.ENTRY_STRATEGIES[key])} for key in enums.ENTRY_STRATEGIES],
        "strategies": [{"value": key, "label": label} for key, label in enums.STRATEGY_LABELS.items()],
        "stages": [{"value": key, "label": label} for key, label in enums.STAGE_LABELS.items()],
        "departments": [{"value": key, "label": label} for key, label in enums.DEPARTMENT_LABELS.items()],
        "endpoints": [{"value": key, "label": label} for key, label in enums.ENDPOINT_LABELS.items()],
        "issue_codes": enums.ISSUE_CODES,
        "review_categories": [{"id": item["id"], "name": item["name"]} for item in rules.category_options()],
        "rules_version": rules.version,
        "scoring_version": workbench.config.get("version", "abc-0.1"),
        "terms": {key: {"name": value["name"], "level": value["level"]}
                  for key, value in workbench.catalog.terms.items()},
        "categories": dict(workbench.catalog.categories),
        "project_kinds": [{"value": key, "label": label} for key, label in enums.PROJECT_KINDS.items()],
        "limits": {"max_text": 6000, "max_upload_mb": 30},
    }


def project_list(workbench):
    items = []
    with workbench.store.connect() as db:
        projects = rows(db, "SELECT * FROM project ORDER BY updated_at DESC, id DESC")
    for project in projects:
        items.append({**dict(project), **one_counts(project["id"], workbench)})
    return {"projects": items}


def one_counts(project_id, workbench):
    with workbench.store.connect() as db:
        subprojects = rows(db, "SELECT id, status, final_endpoint FROM subproject WHERE project_id=?", (project_id,))
        slots = rows(db, "SELECT l.stage FROM slot l JOIN goal g ON g.id=l.goal_id "
                         "JOIN subproject s ON s.id=g.subproject_id WHERE s.project_id=?", (project_id,))
        open_issues = rows(db, "SELECT i.id, i.code, i.scope_type, i.scope_id FROM issue i WHERE i.state='open' "
                               "AND ((i.scope_type='project' AND i.scope_id=?) OR (i.scope_type='slot' AND i.scope_id IN "
                               "(SELECT l.id FROM slot l JOIN goal g ON g.id=l.goal_id JOIN subproject s ON s.id=g.subproject_id "
                               "WHERE s.project_id=?)))", (project_id, project_id))
    return {"subproject_count": len(subprojects),
            "subproject_done": sum(1 for item in subprojects if item["status"] == "completed"),
            "slot_count": len(slots),
            "slot_done": sum(1 for item in slots if item["stage"] == "complete"),
            "issue_count": len(open_issues),
            "issues": [{"code": item["code"], "label": enums.ISSUE_CODES.get(item["code"], item["code"]),
                        "scope": item["scope_type"], "scope_id": item["scope_id"]} for item in open_issues[:8]]}


def project_view(workbench, project_id):
    with workbench.store.connect() as db:
        return _project_view(workbench, db, project_id)


def _project_view(workbench, db, project_id):
    project = row(db, "SELECT * FROM project WHERE id=?", (project_id,))
    if not project:
        raise ValueError("项目不存在")
    view = {"project": dict(project), "progress": one_counts(project_id, workbench), "subprojects": []}
    for subproject in rows(db, "SELECT * FROM subproject WHERE project_id=? ORDER BY id", (project_id,)):
        node = {"id": subproject["id"], "title": subproject["title"],
                "requirement_type": subproject["requirement_type"],
                "requirement_label": enums.ENTRY_LABELS.get(subproject["requirement_type"], ""),
                "final_endpoint": subproject["final_endpoint"],
                "final_endpoint_label": enums.ENDPOINT_LABELS.get(subproject["final_endpoint"], ""),
                "status": subproject["status"], "parent_id": subproject["parent_id"],
                "is_development": subproject["final_endpoint"] == "warehouse_return",
                "rounds": []}
        for round_row in rows(db, "SELECT * FROM round WHERE subproject_id=? ORDER BY no", (subproject["id"],)):
            brief = loads(round_row["brief"], {})
            round_node = {"id": round_row["id"], "no": round_row["no"], "kind": round_row["kind"],
                          "kind_label": enums.ROUND_LABELS.get(round_row["kind"], round_row["kind"]),
                          "status": round_row["status"], "summary": brief.get("summary", ""),
                          "goals": []}
            for goal in rows(db, "SELECT * FROM goal WHERE round_id=? ORDER BY id", (round_row["id"],)):
                round_node["goals"].append(goal_view(workbench, db, goal))
            node["rounds"].append(round_node)
        view["subprojects"].append(node)
    return view


def goal_view(workbench, db, goal):
    fields = loads(goal["fields"], {})
    provenance = loads(goal["provenance"], {})
    subproject = row(db, "SELECT * FROM subproject WHERE id=?", (goal["subproject_id"],))
    entry = subproject["requirement_type"] if subproject else ""
    return {
        "id": goal["id"], "label": goal["label"], "status": goal["status"],
        "endpoint": goal["endpoint"], "endpoint_label": enums.ENDPOINT_LABELS.get(goal["endpoint"], ""),
        "requested_count": goal["requested_count"], "fields": fields,
        "provenance": provenance,
        "entry": entry, "entry_label": enums.ENTRY_LABELS.get(entry, ""),
        "strategies": [{"value": key, "label": enums.STRATEGY_LABELS[key],
                        "allowed": key in enums.ENTRY_STRATEGIES.get(entry, ("select",))}
                       for key in ("select", "duplicate", "create", "modify", "resend")],
        "slots": [slot_view(workbench, db, slot) for slot in
                  rows(db, "SELECT * FROM slot WHERE goal_id=? ORDER BY id", (goal["id"],))],
    }


def slot_view(workbench, db, slot):
    payload = loads(slot["payload"], {})
    job = row(db, "SELECT * FROM job WHERE slot_id=? ORDER BY id DESC LIMIT 1", (slot["id"],))
    child = row(db, "SELECT id, status FROM subproject WHERE parent_slot_id=? ORDER BY id DESC LIMIT 1",
                (slot["id"],))
    developing = bool(child and child["status"] == "active")
    job_node = None
    if job:
        trial = row(db, "SELECT * FROM trial WHERE job_id=? ORDER BY iteration DESC LIMIT 1", (job["id"],))
        job_node = {"id": job["id"], "dev_type": job["dev_type"],
                    "dev_type_label": enums.STRATEGY_LABELS.get(job["dev_type"], ""),
                    "gc_report": job["gc_report"], "iteration": job["current_iteration"],
                    "reference": loads(job["reference"], {}),
                    "brief": loads(job["brief"], {}),
                    "approved_trial_id": job["approved_trial_id"],
                    "trial": {"id": trial["id"], "iteration": trial["iteration"],
                              "fragrance_id": trial["trial_fragrance_id"],
                              "formula_version": trial["formula_version"],
                              "notes": trial["notes"]} if trial else None}
    return {
        "id": slot["id"], "strategy": slot["strategy"],
        "strategy_label": enums.STRATEGY_LABELS.get(slot["strategy"], slot["strategy"]),
        "stage": slot["stage"], "stage_label": enums.STAGE_LABELS.get(slot["stage"], slot["stage"]),
        "fragrance_id": slot["fragrance_id"], "formula_version": slot["formula_version"],
        "revision": slot["revision"], "paused": bool(payload.get("paused")),
        "pause_reason": payload.get("pause_reason", ""),
        "payload": {key: value for key, value in payload.items()
                    if key in ("sample_id", "sample_form", "quantity", "unit", "shipment_kind",
                               "returned_from", "note", "base_version", "sample_reference")},
        "child_subproject_id": child["id"] if developing else None,
        "actions": [] if developing else gates.available(db, slot),
        "issues": [issues.as_dict(item) for item in issues.open_for(db, "slot", slot["id"])],
        "job": job_node,
        "checks": check_view(workbench, db, slot),
        "tasks": [{"id": task["id"], "type": task["task_type"],
                   "type_label": enums.TASK_TYPE_LABELS.get(task["task_type"], task["task_type"]),
                   "department": task["department"],
                   "department_label": enums.DEPARTMENT_LABELS.get(task["department"], task["department"]),
                   "status": task["status"], "external_id": task["external_id"],
                   "created_at": task["created_at"]}
                  for task in rows(db, "SELECT * FROM task WHERE slot_id=? ORDER BY id", (slot["id"],))],
        "shipments": [{"id": item["id"], "kind": item["kind"],
                       "kind_label": enums.SHIPMENT_LABELS.get(item["kind"], item["kind"]),
                       "fragrance_id": item["fragrance_id"], "formula_version": item["formula_version"],
                       "sample_form": item["sample_form"], "quantity": item["quantity"], "unit": item["unit"],
                       "tracking": item["tracking"], "shipped_at": item["shipped_at"]}
                      for item in rows(db, "SELECT * FROM shipment WHERE slot_id=? ORDER BY id", (slot["id"],))],
        "warehouse": warehouse_view(db, slot),
    }


def check_view(workbench, db, slot):
    check_set = row(db, "SELECT * FROM check_set WHERE slot_id=? ORDER BY revision DESC, id DESC LIMIT 1",
                    (slot["id"],))
    if not check_set:
        return None
    requirements = rows(db, "SELECT * FROM requirement WHERE check_set_id=? ORDER BY department, id",
                        (check_set["id"],))
    releases = rows(db, "SELECT * FROM release_decision WHERE slot_id=? ORDER BY id", (slot["id"],))
    counts = {}
    for requirement in requirements:
        counts[requirement["status"]] = counts.get(requirement["status"], 0) + 1
    by_department = {}
    for requirement in requirements:
        by_department.setdefault(requirement["department"], []).append(requirement)
    return {
        "id": check_set["id"], "revision": check_set["revision"], "scope": check_set["scope"],
        "scope_label": "入库" if check_set["scope"] == "warehouse" else "客户交付",
        "review_category": check_set["review_category"], "markets": loads(check_set["markets"], []),
        "rules_version": check_set["rules_version"], "total": len(requirements),
        "counts": counts, "coverage": loads(check_set["coverage"], []),
        "departments": [{"department": key,
                         "label": enums.DEPARTMENT_LABELS.get(key, key),
                         "requirements": [{"id": item["id"], "metric_id": item["metric_id"],
                                           "metric_name": workbench.rules.metrics.get(item["metric_id"], {}).get(
                                               "name", item["metric_id"]),
                                           "subitem": item["subitem"], "status": item["status"],
                                           "source": item["source"], "deferral": item["deferral"],
                                           "mandatory": bool(item["mandatory"]),
                                           "criteria": item["criteria"], "note": item["note"],
                                           "conditions": loads(item["conditions"], {})}
                                          for item in by_department.get(key, [])]}
                        for key in ("compliance", "quality", "application") if by_department.get(key)],
        "releases": [{"id": item["id"], "action": item["action"],
                      "action_label": enums.RELEASE_LABELS.get(item["action"], item["action"]),
                      "verdict": item["verdict"], "reason": item["reason"],
                      "deferred": loads(item["deferred"], []), "created_at": item["created_at"]}
                     for item in releases],
    }


def warehouse_view(db, slot):
    record = row(db, "SELECT * FROM warehouse_record WHERE slot_id=? ORDER BY id DESC LIMIT 1", (slot["id"],))
    if not record:
        return None
    return {"id": record["id"], "fragrance_id": record["fragrance_id"],
            "formula_version": record["formula_version"], "approved_by": record["approved_by"],
            "created_at": record["created_at"]}


def platform_view(workbench):
    with workbench.store.connect() as db:
        return _platform_view(workbench, db)


def _platform_view(workbench, db):
    tasks = rows(db, "SELECT * FROM task WHERE status IN ('queued','sent') ORDER BY id")
    return {
        "tasks": [{"id": task["id"], "type": task["task_type"],
                   "type_label": enums.TASK_TYPE_LABELS.get(task["task_type"], task["task_type"]),
                   "department": task["department"],
                   "department_label": enums.DEPARTMENT_LABELS.get(task["department"], task["department"]),
                   "status": task["status"], "external_id": task["external_id"],
                   "project_id": task["project_id"], "created_at": task["created_at"],
                   "spec": loads(task["spec"], {})} for task in tasks],
        "defaults": workbench.platform.default_result(db, None),
        "departments": [{"value": key, "label": label} for key, label in enums.DEPARTMENT_LABELS.items()],
        "quotes": workbench.platform.quotes(db),
        "receipts": [{"task_id": task["id"], "department": task["department"],
                      "created_at": task["updated_at"]}
                     for task in rows(db, "SELECT * FROM task WHERE status IN ('done','failed') ORDER BY id DESC LIMIT 20")],
    }
