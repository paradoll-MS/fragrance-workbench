from app import config
from app.workflow.service import Workbench

db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
asset_key = next(iter(wb.catalog.raw))
plan = wb.plan(1, 1, "select", {"asset_key": asset_key})
wb.advance(1, plan["slot_id"], "build_checks", {}, None)
with wb.store.connect() as conn:
    slot = conn.execute("SELECT * FROM slot WHERE id=?", (plan["slot_id"],)).fetchone()
print("stage", slot["stage"], "checks", slot["check_set_id"])
reqs = conn.execute("SELECT metric_id, subitem, source, origin_text, mandatory FROM requirement WHERE check_set_id=? ORDER BY id", (slot["check_set_id"],)).fetchall()
for r in reqs:
    if r["source"] == "customer" or r["metric_id"] in ("R_MARKET", "R_ALLERGEN", "Q_STABILITY"):
        print(r["metric_id"], "|", r["subitem"], "|", r["origin_text"][:80])
print("total", len(reqs))
