import json
from app import config
from app.store.db import dumps, update
from app.workflow.service import Workbench
from app.intelligence import targeting

db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
with wb.store.transaction() as conn:
    row = conn.execute("SELECT * FROM goal WHERE id=1").fetchone()
    fields = json.loads(row["fields"])
    fields.pop("targeting", None)
    update(conn, "goal", 1, fields=dumps(fields))

orig = targeting.json_object
def spy(*args, **kwargs):
    raw = orig(*args, **kwargs)
    print("RAW", json.dumps(raw, ensure_ascii=False)[:2500])
    return raw
targeting.json_object = spy
res = wb.ensure_targeting(1)
print("method", res["method"])
print("items", res["items"])
print("unmapped", res["unmapped"])
