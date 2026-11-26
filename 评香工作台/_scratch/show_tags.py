import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:18762/api/projects/5", timeout=30) as r:
    data = json.loads(r.read().decode())
for goal in data["subprojects"][0]["rounds"][0]["goals"][:2]:
    t = goal["fields"].get("targeting", {})
    print(goal["id"], t.get("method"), "unmapped", t.get("unmapped"))
