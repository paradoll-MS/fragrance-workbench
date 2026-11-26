import base64, json, urllib.request

BASE = "http://127.0.0.1:18762"
def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode("utf-8"))

project = call("POST", "/api/projects", {"name": "贝德美蓝甘菊 · 儿童洗发水", "kind": "customer", "customer": "贝德美"})["project_id"]
pdf = config_path = r"C:\Users\26519\Desktop\交付总控\评香工作台\research\cases\真实案例\蓝甘菊_儿童健发洗发水香气需求_260904\260904蓝甘菊儿童健发洗发水香气需求.pdf"
raw = open(pdf, "rb").read()
source = call("POST", f"/api/projects/{project}/sources", {"name": "蓝甘菊需求.pdf", "base64": base64.b64encode(raw).decode()})
print("project", project, "source", source)
analysis = call("POST", f"/api/projects/{project}/analyze", {})
print("draft", analysis["draft_id"], "directions", [item["title"] for item in analysis["draft"]["directions"]])
committed = call("POST", f"/api/projects/{project}/draft/{analysis['draft_id']}/confirm", {"edits": analysis["draft"]})["committed"]
print("goals", [(item["goal_id"], item["title"]) for item in committed])

