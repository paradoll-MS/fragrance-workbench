import json, urllib.request
base = "http://127.0.0.1:18762"
def get(path):
    with urllib.request.urlopen(base+path, timeout=30) as r:
        return json.loads(r.read().decode())
projects = get("/api/projects")
print("projects", [(p["id"], p["name"]) for p in projects["projects"]])
data = get("/api/projects/5")
goal = data["subprojects"][0]["rounds"][0]["goals"][0]
print("goal", goal["label"], "scent", goal["fields"].get("scent_text"), "mode", goal["fields"].get("mode"), "tags", [i["name"] for i in goal["fields"]["targeting"]["items"]])
