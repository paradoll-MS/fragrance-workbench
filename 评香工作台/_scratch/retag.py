import json, sqlite3, urllib.request
conn = sqlite3.connect("data/workbench.sqlite3"); conn.row_factory = sqlite3.Row
for gid in (9, 10, 11):
    row = conn.execute("SELECT fields FROM goal WHERE id=?", (gid,)).fetchone()
    if not row: continue
    fields = json.loads(row["fields"]); fields.pop("targeting", None)
    conn.execute("UPDATE goal SET fields=? WHERE id=?", (json.dumps(fields, ensure_ascii=False), gid))
conn.commit(); conn.close()

def post(path, body):
    req = urllib.request.Request("http://127.0.0.1:18762"+path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode())
for gid in (9, 10):
    found = post("/api/search", {"goal_id": gid})
    print(gid, found["total"], [(g["role"], g["tags"]) for g in found["query"]["groups"]])
