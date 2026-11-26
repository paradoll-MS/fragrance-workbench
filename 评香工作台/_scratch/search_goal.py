import json, urllib.request
BASE = "http://127.0.0.1:18762"
def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode("utf-8"))
found = call("POST", "/api/search", {"goal_id": 9})
print("total", found["total"], "groups", [(g["role"], g["tags"]) for g in found["query"]["groups"]])
print("top", [(item["name"], item.get("score")) for item in found["results"][:3]])
goal = call("GET", "/api/projects/5")["subprojects"][0]["rounds"][0]["goals"][0]
t = goal["fields"].get("targeting", {})
print("method", t.get("method"), "items", [(i["name"], i["basis"]) for i in t.get("items", [])], "unmapped", t.get("unmapped"))
