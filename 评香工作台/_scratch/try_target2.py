import json
from app import config
from app.store.db import dumps, update
from app.workflow.service import Workbench

db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
with wb.store.transaction() as conn:
    row = conn.execute("SELECT * FROM goal WHERE id=1").fetchone()
    fields = json.loads(row["fields"])
    fields.pop("targeting", None)
    update(conn, "goal", 1, fields=dumps(fields))
res = wb.ensure_targeting(1)
print("method", res["method"])
for item in res["items"]:
    print(" -", item["path"], "|", item["basis"])
print("used", res["used_conditions"])
print("unmapped", res["unmapped"])
print("groups", [(g["role"], g["tags"], g.get("source")) for g in res["groups"]])
