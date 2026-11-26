import json, urllib.request
base = "http://127.0.0.1:18762"
def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base+path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read().decode())
project = call("POST", "/api/projects", {"name": "模型调用验收", "kind": "customer", "customer": "测试"})["project_id"]
call("POST", f"/api/projects/{project}/sources", {"name": "需求.txt", "text": "客户要求做洗发水香精，方向：花香-草本；其他由研发推荐。人群：6-12 岁儿童。稳定性考察：否。"})
draft = call("POST", f"/api/projects/{project}/analyze", {})
print("project", project, "draft", draft["draft_id"], "directions", [d["title"] for d in draft["draft"]["directions"]])
calls = call("GET", f"/api/projects/{project}/llm-calls")["calls"]
print("calls", [(c["id"], c["purpose"], c["status"], c["model"], c["request_chars"]) for c in calls])
if calls:
    detail = call("GET", f"/api/llm-calls/{calls[0]['id']}")
    print("system head", detail["request"]["messages"][0]["content"][:50])
