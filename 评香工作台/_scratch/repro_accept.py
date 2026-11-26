import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.store.db import loads, rows
from app.workflow import views
from app.workflow.service import Workbench

DB = config.DATA / "debug-accept.sqlite3"
if DB.exists():
    DB.unlink()
wb = Workbench(database=DB)
project = wb.create_project("验收", "customer", "x")
wb.add_source(project, "需求.txt", text="洗发水 白茶木质 300 以内 中国 先寄初样")
draft_id, _ = wb.manual_draft(project, [{"title": "竞品样复刻", "entry": "with_sample",
                                         "conditions": {"markets": ["中国"], "substrate": "洗发水",
                                                        "sample_reference": "S-77"}}])
goal = wb.confirm_draft(project, draft_id)["directions"][0]["goal_id"]
plan = wb.plan(project, goal, "duplicate", {"sample_reference": "S-77"})
parent, child = plan["slot_id"], plan["child_slot_id"]


def tasks():
    with wb.store.connect() as db:
        return rows(db, "SELECT * FROM task WHERE status IN ('sent','queued') ORDER BY id")


def pass_all(kind):
    for task in tasks():
        if task["task_type"] == kind:
            wb.apply_receipt(task["id"], True, {"note": "ok"})


pass_all("analysis")
pass_all("perfumery")
print("confirm_gc", wb.advance(project, child, "confirm_gc", {"report": "GC-01"})["notice"])
print("reject", wb.advance(project, child, "reject_trial", {"note": "偏薄"})["notice"])
pass_all("perfumery")
print("accept", wb.advance(project, child, "accept_trial", {"note": "ok"})["notice"])
print("child build", wb.advance(project, child, "build_checks", {"review_category": "hair_rinse_off"})["notice"])
wb.advance(project, child, "dispatch_checks", {})
pass_all("check")
wb.advance(project, child, "release_warehouse", {})
wb.advance(project, child, "dispatch_warehouse", {})
pass_all("warehouse")
wb.advance(project, child, "accept_warehouse", {"fragrance_id": "DIY-01", "formula_version": "V1"})
with wb.store.connect() as db:
    print("child slot", rows(db, "SELECT id,fragrance_id,formula_version,stage FROM slot WHERE id=?", (child,)))
    print("evidence ids", rows(db, "SELECT DISTINCT fragrance_id, formula_version FROM evidence"))
    print("evidence keys", rows(db, "SELECT metric_id, conditions_key FROM evidence LIMIT 3"))
notice = wb.advance(project, parent, "build_checks", {"review_category": "hair_rinse_off"})["notice"]
print("parent build", notice)
with wb.store.connect() as db:
    print("parent req", rows(db, "SELECT metric_id, conditions_key, status FROM requirement "
                                 "WHERE check_set_id=(SELECT MAX(id) FROM check_set) LIMIT 3"))
