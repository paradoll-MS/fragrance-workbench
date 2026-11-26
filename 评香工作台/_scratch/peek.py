import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.workflow.service import Workbench

start = time.time()
db = config.DATA / "smoke.sqlite3"
if db.exists():
    db.unlink()
wb = Workbench(database=db)
print("catalog", len(wb.catalog.raw), "assets", len(wb.catalog.products), "terms", len(wb.catalog.terms),
      "in", round(time.time() - start, 1), "s")
keys = list(wb.catalog.raw)[:3]
for key in keys:
    asset = wb.catalog.raw[key]
    print(key, asset["fragrance_id"], asset.get("name"), asset.get("price"))
print("rules", wb.rules.version, len(wb.rules.metrics), "metrics", len(wb.rules.category_options()), "categories")
