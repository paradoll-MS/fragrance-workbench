from app import config
from app.workflow.service import Workbench
db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
with wb.store.connect() as conn:
    reqs = conn.execute("SELECT metric_id, subitem, source, origin_text, mandatory FROM requirement ORDER BY id").fetchall()
    for r in reqs:
        if r["source"] == "customer" or r["metric_id"] in ("R_MARKET", "R_ALLERGEN", "Q_STABILITY"):
            print(r["metric_id"], "|", r["subitem"][:60], "|", (r["origin_text"] or "")[:60], "|", r["mandatory"])
    print("total", len(reqs))
    print("by metric", dict(conn.execute("SELECT metric_id, count(*) FROM requirement GROUP BY metric_id")))
