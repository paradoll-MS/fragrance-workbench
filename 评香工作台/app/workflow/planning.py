"""F10/F12 planning: create target slots, spawn development subprojects, return results."""

import json

from ..domain import enums
from ..domain.models import endpoint_for
from ..store.db import dumps, insert, loads, now, row, update


def strategy_allowed(entry, strategy):
    return strategy in enums.ENTRY_STRATEGIES.get(entry, ("select",))


def create_slot(db, round_id, goal_id, strategy, payload=None, stage="planned", fragrance_id="",
                formula_version=""):
    return insert(db, "slot", round_id=round_id, goal_id=goal_id, strategy=strategy, stage=stage,
                  fragrance_id=fragrance_id, formula_version=formula_version,
                  payload=dumps(payload or {}))


def spawn_development(db, project, subproject, goal, strategy, payload):
    """Create the derived development subproject, its round, goal, slot and job."""
    parent_slot = create_slot(db, goal["round_id"], goal["id"], strategy,
                              payload={**payload, "endpoint": subproject["final_endpoint"],
                                       "parent": True},
                              stage="developing", fragrance_id=payload.get("fragrance_id", ""))
    child_id = insert(db, "subproject", project_id=project["id"], requirement_type="develop",
                      final_endpoint="warehouse_return", parent_id=subproject["id"],
                      parent_slot_id=parent_slot, title=goal["label"],
                      status="active")
    child_round = insert(db, "round", subproject_id=child_id, no=1, kind="initial",
                         brief=dumps({"summary": f"开发：{goal['label']}", "fields": loads(goal["fields"], {})}))
    child_goal = insert(db, "goal", subproject_id=child_id, round_id=child_round, label=goal["label"],
                        is_required=0, endpoint="warehouse",
                        fields=goal["fields"], provenance=goal["provenance"])
    child_slot = create_slot(db, child_round, child_goal, strategy,
                             payload={**payload, "endpoint": "warehouse_return", "parent_slot": parent_slot},
                             stage="developing")
    job = insert(db, "job", subproject_id=child_id, slot_id=child_slot, dev_type=strategy,
                 brief=dumps({"label": goal["label"], "fields": loads(goal["fields"], {}),
                              "note": payload.get("note", "")}),
                 reference=dumps({key: payload.get(key) for key in
                                  ("asset_key", "fragrance_id", "formula_version", "sample_reference",
                                   "base_code", "base_version") if payload.get(key)}),
                 status="active")
    return {"parent_slot": parent_slot, "child_subproject": child_id, "child_round": child_round,
            "child_goal": child_goal, "child_slot": child_slot, "job": job}


def return_to_parent(db, child_subproject_id, fragrance_id, formula_version):
    child = row(db, "SELECT * FROM subproject WHERE id=?", (child_subproject_id,))
    if not child or not child["parent_slot_id"]:
        return None
    update(db, "subproject", child["id"], status="completed")
    parent_slot = row(db, "SELECT * FROM slot WHERE id=?", (child["parent_slot_id"],))
    payload = loads(parent_slot["payload"], {})
    payload.pop("paused", None)
    payload.pop("parent", None)
    payload["returned_from"] = child["id"]
    update(db, "slot", parent_slot["id"], fragrance_id=fragrance_id, formula_version=formula_version,
           stage="checking", payload=dumps(payload), revision=parent_slot["revision"] + 1)
    return parent_slot["id"]


def snapshot_goal(db, goal):
    return {"id": goal["id"], "label": goal["label"], "round_id": goal["round_id"],
            "subproject_id": goal["subproject_id"], "endpoint": goal["endpoint"],
            "is_required": bool(goal["is_required"]), "fields": loads(goal["fields"], {})}


def pause(db, slot, reason=""):
    payload = loads(slot["payload"], {})
    payload["paused"] = True
    payload["pause_reason"] = str(reason)[:300]
    update(db, "slot", slot["id"], payload=dumps(payload), revision=slot["revision"] + 1)


def resume(db, slot):
    payload = loads(slot["payload"], {})
    payload.pop("paused", None)
    payload.pop("pause_reason", None)
    update(db, "slot", slot["id"], payload=dumps(payload), revision=slot["revision"] + 1)


def default_endpoint(project, entry, parent_id=None):
    return endpoint_for(project["kind"], entry, parent_id)
