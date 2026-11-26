import json, sqlite3, urllib.request
base = "http://127.0.0.1:18762"
def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base+path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode())
conn = sqlite3.connect("data/workbench.sqlite3"); conn.row_factory = sqlite3.Row
draft = json.loads(conn.execute("SELECT result FROM parse_draft WHERE id=8").fetchone()["result"])
conn.close()
committed = call("POST", "/api/projects/7/draft/8/confirm", {"edits": draft})["committed"]
goal = committed[0]["goal_id"]
found = call("POST", "/api/search", {"goal_id": goal})
print("goal", goal, "total", found["total"], "groups", len(found["query"]["groups"]))
calls = call("GET", "/api/projects/7/llm-calls")["calls"]
print("calls", [(c["id"], c["purpose"], c["status"], c["model"]) for c in calls])
for c in calls[:2]:
    d = call("GET", f"/api/llm-calls/{c['id']}")
    print(c["purpose"], "system", len(d["request"]["messages"][0]["content"]), "user", len(d["request"]["messages"][1]["content"]), "resp", len(d["response"]))
