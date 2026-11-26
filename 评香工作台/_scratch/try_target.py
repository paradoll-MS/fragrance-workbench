import json
from app import config
from app.workflow.service import Workbench

db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
with wb.store.connect() as conn:
    draft = conn.execute("SELECT * FROM parse_draft ORDER BY id DESC LIMIT 1").fetchone()
committed = wb.confirm_draft(1, draft["id"])
print("directions", [(d["title"], d["goal_id"]) for d in committed["directions"]])
goal = committed["directions"][0]["goal_id"]
with wb.store.connect() as conn:
    goal_row = conn.execute("SELECT * FROM goal WHERE id=?", (goal,)).fetchone()
fields = json.loads(goal_row["fields"])
print("application", fields.get("application_id"), "candidates", len(wb.catalog.c_candidates(fields.get("application_id") or "")))
print("targeting...")
res = wb.ensure_targeting(goal)
print("method", res["method"])
print("c_ids", res["c_ids"])
for item in res["items"]:
    print(" -", item["path"], "|", item["basis"])
print("used", res["used_conditions"])
print("unmapped", res["unmapped"])
print("groups", [(g["role"], g["tags"]) for g in res["groups"]])
