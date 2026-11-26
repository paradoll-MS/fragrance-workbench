import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.store.db import rows
from app.workflow.service import Workbench

DB = config.DATA / "debug2.sqlite3"
if DB.exists():
    DB.unlink()
wb = Workbench(database=DB)
pid = wb.create_project("调试2", "customer")
wb.add_source(pid, "a.txt", text="洗发水 白茶 300 以内")
draft_id, _ = wb.manual_draft(pid, [{"title": "洗发水", "entry": "recommend_simple",
                                     "conditions": {"markets": ["中国"], "substrate": "洗发水"}}])
goal = wb.confirm_draft(pid, draft_id)["directions"][0]["goal_id"]
slot = wb.plan(pid, goal, "select", {"asset_key": "1040"})["slot_id"]
wb.advance(pid, slot, "build_checks", {"review_category": "hair_rinse_off"})
wb.advance(pid, slot, "dispatch_checks", {})


def tasks(kind):
    with wb.store.connect() as db:
        return rows(db, "SELECT * FROM task WHERE task_type=? AND status='sent'", (kind,))


for task in tasks("check"):
    wb.apply_receipt(task["id"], True, {})
print(wb.advance(pid, slot, "release_formal", {})["notice"])
print(wb.advance(pid, slot, "prepare_sample", {"form": "10 ml", "quantity": "10", "unit": "ml"})["notice"])
print(wb.advance(pid, slot, "dispatch_shipment", {})["notice"])
for task in tasks("shipment"):
    wb.apply_receipt(task["id"], True, {"tracking": "SF1"})
with wb.store.connect() as db:
    print("project", rows(db, "SELECT id,status FROM project"))
    print("subproject", rows(db, "SELECT id,status,final_endpoint FROM subproject"))
    print("goal", rows(db, "SELECT id,status FROM goal"))
    print("slot", rows(db, "SELECT id,stage FROM slot"))
    print("shipment", rows(db, "SELECT id,kind FROM shipment"))
    print("issue", rows(db, "SELECT id,code,state,scope_id FROM issue"))
