import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.store.db import loads
from app.workflow import views
from app.workflow.service import Workbench

DB = config.DATA / "smoke.sqlite3"
if DB.exists():
    DB.unlink()
wb = Workbench(database=DB)
PID = wb.create_project("测试项目", "customer", "某日化", "T-001")

wb.add_source(PID, "需求.txt", text="给洗发水推荐两款白茶木质，300 以内，中国市场，10 ml 样品")
draft_id, result = wb.manual_draft(PID, [{
    "title": "洗发水白茶木质", "entry": "recommend_simple",
    "conditions": {"markets": ["中国"], "substrate": "洗发水", "price_text": "300 以内",
                   "sample_form": "10 ml"},
}])
print("draft", result["directions"][0]["title"], result["directions"][0]["conditions"])
committed = wb.confirm_draft(PID, draft_id)
goal_id = committed["directions"][0]["goal_id"]
print("goal", goal_id, committed["directions"][0]["entry"], committed["directions"][0]["endpoint"])

plan = wb.plan(PID, goal_id, "select", {"asset_key": "1040"})
print("plan", plan)
slot_id = plan["slot_id"]

out = wb.advance(PID, slot_id, "build_checks", {})
print("build", out.get("notice"), out.get("issues"))
out = wb.advance(PID, slot_id, "dispatch_checks", {})
print("dispatch", out.get("notice"), out.get("blocked"), [i.get("label") for i in out.get("issues", [])])

tasks = None
with wb.store.connect() as db:
    from app.store.db import rows
    task_rows = rows(db, "SELECT * FROM task WHERE project_id=? AND status='sent'", (PID,))
print("tasks", [(t["id"], t["task_type"], t["department"]) for t in task_rows])
for task in task_rows:
    wb.apply_receipt(task["id"], True, {"note": "模拟通过"})
    print("receipt", task["id"], task["department"])

out = wb.advance(PID, slot_id, "release_formal", {"note": "全项通过"})
print("release", out.get("notice"), out.get("blocked"), out.get("issues"))

out = wb.advance(PID, slot_id, "prepare_sample", {"form": "10 ml 喷雾样", "quantity": "10", "unit": "ml"})
print("sample", out.get("notice"), out.get("blocked"))
out = wb.advance(PID, slot_id, "dispatch_shipment", {})
print("ship dispatch", out.get("notice"), out.get("blocked"), out.get("issues"))
with wb.store.connect() as db:
    ship_tasks = rows(db, "SELECT * FROM task WHERE project_id=? AND task_type='shipment' AND status='sent'", (PID,))
for task in ship_tasks:
    wb.apply_receipt(task["id"], True, {"tracking": "SF123"})

view = views.project_view(wb, PID)
print("project", view["project"]["status"], view["progress"])
for sub in view["subprojects"]:
    for round_item in sub["rounds"]:
        for goal in round_item["goals"]:
            for slot in goal["slots"]:
                print("slot", slot["id"], slot["strategy"], slot["stage"], slot["fragrance_id"], len(slot["tasks"]), len(slot["shipments"]))

print("\n=== 对香 → 开发子项 → 回到父项 ===")
draft2_id, _ = wb.manual_draft(PID, [{
    "title": "客户对标样复刻", "entry": "with_sample",
    "conditions": {"markets": ["中国"], "sample_reference": "S-77", "substrate": "洗发水"},
}])
committed2 = wb.confirm_draft(PID, draft2_id)
goal2 = committed2["directions"][0]["goal_id"]
plan2 = wb.plan(PID, goal2, "duplicate", {"sample_reference": "S-77"})
parent_slot, child_slot = plan2["slot_id"], plan2["child_slot_id"]
print("plan2", plan2)


def pending(kind):
    with wb.store.connect() as db:
        return rows(db, "SELECT * FROM task WHERE task_type=? AND status='sent' ORDER BY id", (kind,))


for task in pending("analysis"):
    wb.apply_receipt(task["id"], True, {"document": "GC-9"})
print("after analysis", [(t["task_type"], t["department"]) for t in pending("perfumery")])
for task in pending("perfumery"):
    wb.apply_receipt(task["id"], True, {"trial_fragrance_id": "DIY-01", "formula_version": "V1"})
out = wb.advance(PID, child_slot, "accept_trial", {"note": "可以"})
print("accept trial", out.get("notice"), out.get("blocked"), out.get("issues"))
out = wb.advance(PID, child_slot, "build_checks", {"review_category": "hair_rinse_off", "markets": ["中国"]})
print("child build", out.get("notice"), out.get("blocked"), [i["label"] for i in out.get("issues", [])])
out = wb.advance(PID, child_slot, "dispatch_checks", {})
print("child dispatch", out.get("notice"))
for task in pending("check"):
    wb.apply_receipt(task["id"], True, {})
out = wb.advance(PID, child_slot, "release_warehouse", {"note": "入库"})
print("warehouse release", out.get("notice"), out.get("blocked"), out.get("issues"))
out = wb.advance(PID, child_slot, "dispatch_warehouse", {})
print("warehouse dispatch", out.get("notice"))
for task in pending("warehouse"):
    wb.apply_receipt(task["id"], True, {})
out = wb.advance(PID, child_slot, "accept_warehouse", {"fragrance_id": "DIY-01", "formula_version": "V1"})
print("warehouse accept", out.get("notice"), out.get("blocked"), out.get("issues"))

view = views.project_view(wb, PID)
for sub in view["subprojects"]:
    print("sub", sub["id"], sub["title"], sub["status"], sub["is_development"])
    for round_item in sub["rounds"]:
        for goal in round_item["goals"]:
            for slot in goal["slots"]:
                print("  slot", slot["id"], slot["strategy"], slot["stage"], slot["fragrance_id"],
                      slot["formula_version"], "checks", (slot["checks"] or {}).get("total"))

