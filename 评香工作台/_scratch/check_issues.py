import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def slot_of(project_id):
    _, view = call("GET", f"/api/projects/{project_id}")
    return [slot for sub in view["subprojects"] for round_item in sub["rounds"]
            for goal in round_item["goals"] for slot in goal["slots"]][0]


project = call("POST", "/api/projects", {"name": "问题恢复检查"})[1]["project_id"]
call("POST", f"/api/projects/{project}/sources", {"name": "需求.txt", "text": "洗发水 白茶 300 以内 中国"})
draft = call("POST", f"/api/projects/{project}/draft", {"directions": [{
    "title": "白茶洗发水", "entry": "recommend_simple",
    "conditions": {"markets": ["中国"], "substrate": "洗发水", "price_text": "300 以内"}}]})[1]
goal = call("POST", f"/api/projects/{project}/draft/{draft['draft_id']}/confirm", {})[1]["committed"][0]["goal_id"]
plan = call("POST", f"/api/projects/{project}/goals/{goal}/plan",
            {"strategy": "select", "payload": {"asset_key": "1040"}})[1]
slot = plan["slot_id"]

status, blocked = call("POST", f"/api/projects/{project}/slots/{slot}/advance", {"action": "release_formal"})
print("blocked", status, blocked.get("blocked"), [item["code"] for item in blocked.get("issues", [])])
view = slot_of(project)
print("view issues", [item["code"] for item in view["issues"]])
print("view actions", [(item["action"], item["enabled"]) for item in view["actions"] if not item["enabled"]])

status, built = call("POST", f"/api/projects/{project}/slots/{slot}/advance",
                     {"action": "build_checks", "payload": {"review_category": "hair_rinse_off"}})
print("build", status, built.get("notice"))
print("view issues after build", [item["code"] for item in slot_of(project)["issues"]])

status, wrong = call("POST", f"/api/projects/{project}/slots/{slot}/advance", {"action": "dispatch_shipment"})
print("wrong stage", status, wrong.get("error"))
