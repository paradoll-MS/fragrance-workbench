import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.store.db import rows
from app.workflow.service import Workbench


def open_tasks():
    with wb.store.connect() as db:
        return rows(db, "SELECT * FROM task WHERE status IN ('sent','queued')")


def drain():
    for task in open_tasks():
        wb.apply_receipt(task["id"], True, {})


DB = config.DATA / "debug-reuse.sqlite3"
if DB.exists():
    DB.unlink()
wb = Workbench(database=DB)
project = wb.create_project("调试", "customer", "x")
wb.add_source(project, "需求.txt", text="洗发水白茶木质 300 以内 中国")
draft_id, _ = wb.manual_draft(project, [{"title": "竞品复刻", "entry": "with_sample",
                                         "conditions": {"markets": ["中国"], "substrate": "洗发水",
                                                        "sample_reference": "S-77"}}])
goal = wb.confirm_draft(project, draft_id)["directions"][0]["goal_id"]
plan = wb.plan(project, goal, "duplicate", {"sample_reference": "S-77"})
parent, child = plan["slot_id"], plan["child_slot_id"]
drain()
drain()
wb.advance(project, child, "accept_trial", {"note": "ok"})
print("child build", wb.advance(project, child, "build_checks", {"review_category": "hair_rinse_off"})["notice"])
wb.advance(project, child, "dispatch_checks", {})
drain()
wb.advance(project, child, "release_warehouse", {})
wb.advance(project, child, "dispatch_warehouse", {})
drain()
wb.advance(project, child, "accept_warehouse", {"fragrance_id": "DIY-01", "formula_version": "V1"})
print("parent build", wb.advance(project, parent, "build_checks", {"review_category": "hair_rinse_off"})["notice"])
with wb.store.connect() as db:
    print("goals", rows(db, "SELECT id, substr(fields,1,160) AS fields FROM goal"))
    print("evidences", rows(db, "SELECT metric_id, subitem, conditions_key, fragrance_id FROM evidence LIMIT 3"))
    print("parent req", rows(db, "SELECT metric_id, subitem, conditions_key FROM requirement "
                                 "WHERE check_set_id=(SELECT MAX(id) FROM check_set) LIMIT 3"))
