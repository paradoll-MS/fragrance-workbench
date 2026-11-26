import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "评香工作台" / "data" / "workspace.sqlite3"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
tabs = [r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")]
for t in tabs:
    n = c.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"{t:20} {n}")

print("\n-- projects --")
for r in c.execute("select id,name,brief from projects"):
    print("PROJ", r["id"], r["name"], "|", (r["brief"] or "")[:70].replace("\n", " "))

print("\n-- rounds --")
for r in c.execute("select id,project_id,number,shared from flow_rounds"):
    print("ROUND", r["id"], "proj", r["project_id"], "no", r["number"], json.loads(r["shared"]).get("summary", "")[:60])

print("\n-- goals --")
for r in c.execute("select id,round_id,spec from flow_goals"):
    s = json.loads(r["spec"])
    print("GOAL", r["id"], "round", r["round_id"], s.get("entry"), "|", s.get("title"), "|", list(s.get("conditions", {}).keys()))

print("\n-- slots --")
for r in c.execute("select id,goal_id,strategy,state,context from flow_slots"):
    ctx = json.loads(r["context"])
    print("SLOT", r["id"], "goal", r["goal_id"], r["strategy"], "state=", r["state"], "ctx:", sorted(ctx))

print("\n-- drafts --")
for r in c.execute("select id,project_id,model,elapsed,status,result from flow_drafts"):
    res = json.loads(r["result"])
    print("DRAFT", r["id"], "proj", r["project_id"], r["model"], r["elapsed"], r["status"],
          "dirs=", [d.get("title") for d in res.get("directions", [])],
          "questions=", len(res.get("open_questions", [])))

print("\n-- sources --")
for r in c.execute("select id,project_id,name,extracted from flow_sources"):
    e = json.loads(r["extracted"])
    print("SRC", r["id"], "proj", r["project_id"], r["name"], e.get("status"), "segs", len(e.get("segments", [])),
          "warn", e.get("warnings"))

print("\n-- feed tail --")
for r in c.execute("select kind,payload from feed order by id desc limit 25"):
    print("FEED", r["kind"], json.loads(r["payload"]))
