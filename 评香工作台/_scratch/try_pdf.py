import json
from app import config
from app.workflow.service import Workbench

db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
if db.exists():
    db.unlink()
wb = Workbench(database=db)
project = wb.create_project("蓝甘菊PDF", "customer", "贝德美")
pdf = config.CASES / "/真实案例/蓝甘菊_儿童健发洗发水香气需求_260904/260904蓝甘菊儿童健发洗发水香气需求.pdf"
source = wb.add_source(project, "蓝甘菊需求.pdf", raw=pdf.read_bytes())
draft_id, result, meta = wb.analyze(project)
print("meta", meta)
print("project", result["project_name"])
print("shared", json.dumps(result["shared"], ensure_ascii=False)[:1800])
print("questions", result["open_questions"])
for d in result["directions"]:
    print("---", d["title"], d["entry"], d["conditions"].get("application_id"))
    print("brief", json.dumps(d["brief"], ensure_ascii=False)[:700])
    print("conditions", json.dumps(d["conditions"], ensure_ascii=False)[:500])
out = config.DATA.parent / "_scratch" / "pdf-case-result.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved", out)



