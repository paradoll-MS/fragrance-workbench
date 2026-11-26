import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:18762"


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


print("rename", call("PATCH", "/api/projects/1", {"name": "示例 · 洗发水白茶木质（已改名）", "customer": "示例客户"}))
print("asset", call("POST", "/api/asset", {"asset_key": "1040", "add_tags": ["白茶"], "note": "人工确认"}))
print("target", call("POST", "/api/target", {"text": "白茶木质，清爽"}))
print("search empty", call("POST", "/api/search", {"query": {"text": ""}}))
print("plan bad strategy", call("POST", "/api/projects/1/goals/1/plan", {"strategy": "create", "payload": {}}))
print("health", call("GET", "/api/health"))
