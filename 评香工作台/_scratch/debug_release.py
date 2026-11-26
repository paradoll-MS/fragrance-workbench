import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.store.db import rows
from app.workflow.service import Workbench

DB = config.DATA / "debug.sqlite3"
if DB.exists():
    DB.unlink()
wb = Workbench(database=DB)
pid = wb.create_project("调试", "customer")
wb.add_source(pid, "a.txt", text="洗发水 白茶 300 以内")
draft_id, _ = wb.manual_draft(pid, [{"title": "洗发水", "entry": "recommend_simple",
                                     "conditions": {"markets": ["中国"], "substrate": "洗发水"}}])
goal = wb.confirm_draft(pid, draft_id)["directions"][0]["goal_id"]
slot = wb.plan(pid, goal, "select", {"asset_key": "1040"})["slot_id"]
print(wb.advance(pid, slot, "build_checks", {"review_category": "hair_rinse_off"})["notice"])
print(wb.advance(pid, slot, "dispatch_checks", {})["notice"])

with wb.store.connect() as db:
    print("before receipts", [(r["department"], r["status"]) for r in
                               rows(db, "SELECT * FROM requirement ORDER BY id")])
    tasks = rows(db, "SELECT * FROM task WHERE task_type='check'")
for task in tasks:
    if task["department"] == "compliance":
        wb.apply_receipt(task["id"], False, {"note": "缺证书"})
with wb.store.connect() as db:
    print("after fail", [(r["department"], r["status"], r["note"]) for r in
                         rows(db, "SELECT * FROM requirement ORDER BY id")])
out = wb.advance(pid, slot, "release_formal", {})
print("release", out.get("blocked"), out.get("notice"), out.get("issues"))
with wb.store.connect() as db:
    print("releases", [(r["action"], r["verdict"]) for r in rows(db, "SELECT * FROM release_decision")])
    print("project", rows(db, "SELECT id,status FROM project"))
    print("subproject", rows(db, "SELECT id,status FROM subproject"))
    print("goal", rows(db, "SELECT id,status FROM goal"))
    print("slot", rows(db, "SELECT id,stage FROM slot"))
