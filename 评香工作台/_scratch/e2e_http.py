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
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            if "json" in response.headers.get("Content-Type", ""):
                return json.loads(payload)
            return payload
    except urllib.error.HTTPError as error:
        print("HTTP", error.code, error.read().decode("utf-8")[:400])
        raise


def tasks(kind, department=None):
    data = call("GET", "/api/platform")
    return [item for item in data["tasks"] if item["type"] == kind
            and (department is None or item["department"] == department)]


def receipt(kind, passed=True, payload=None, department=None):
    for task in tasks(kind, department):
        call("POST", "/api/platform/receipt", {"task_id": task["id"], "passed": passed,
                                               "payload": payload or {}})


def advance(project, slot, action, payload=None, revision=None):
    body = {"action": action, "payload": payload or {}}
    if revision is not None:
        body["revision"] = revision
    result = call("POST", f"/api/projects/{project}/slots/{slot}/advance", body)
    if result.get("blocked"):
        print("BLOCKED", action, [item["label"] for item in result["issues"]])
    return result


def slot_of(project, goal):
    view = call("GET", f"/api/projects/{project}")
    for sub in view["subprojects"]:
        for round_item in sub["rounds"]:
            for item in round_item["goals"]:
                if item["id"] == goal:
                    return item["slots"][0]
    raise SystemExit("slot not found")


project = call("POST", "/api/projects", {"name": "示例 · 洗发水白茶木质", "kind": "customer",
                                         "customer": "示例客户", "code": "DEMO-01"})["project_id"]
print("project", project)

source = call("POST", f"/api/projects/{project}/sources", {"name": "客户需求.txt", "text": (
    "客户要一款洗发水用的白茶木质香精，中国市场，价格 300 元/公斤以内。"
    "另外有一个竞品样，希望照着复刻一款接近的。"
    "首轮先各寄 10 ml 样品。")})
print("source", source)

draft = call("POST", f"/api/projects/{project}/draft", {"directions": [
    {"title": "洗发水白茶木质", "entry": "recommend_simple",
     "conditions": {"markets": ["中国"], "substrate": "洗发水", "price_text": "300 以内",
                    "sample_form": "10 ml"}},
    {"title": "竞品样复刻", "entry": "with_sample",
     "conditions": {"markets": ["中国"], "substrate": "洗发水", "sample_reference": "客户样 A"}},
]})
committed = call("POST", f"/api/projects/{project}/draft/{draft['draft_id']}/confirm",
                 {"edits": draft["draft"]})["committed"]
print("directions", [(item["goal_id"], item["entry"]) for item in committed])

goal_a, goal_b = committed[0]["goal_id"], committed[1]["goal_id"]

# 方向一：直接选香 → 初寄 → 正式寄样
plan_a = call("POST", f"/api/projects/{project}/goals/{goal_a}/plan",
              {"strategy": "select", "payload": {"asset_key": "1040"}})
slot_a = plan_a["slot_id"]
print("slot A", slot_a)
print(advance(project, slot_a, "build_checks", {"review_category": "hair_rinse_off", "markets": ["CN"]})["notice"])
print(advance(project, slot_a, "dispatch_checks")["notice"])
receipt("check")
print(advance(project, slot_a, "release_initial", {"note": "先寄样，细项后补"})["notice"])
print(advance(project, slot_a, "prepare_sample", {"form": "10 ml 喷雾样", "quantity": "10", "unit": "ml"})["notice"])
print(advance(project, slot_a, "dispatch_shipment")["notice"])
receipt("shipment", payload={"tracking": "SF-INITIAL"})
print("after initial", slot_of(project, goal_a)["stage"])

# 方向一：二查后正式寄样
print(advance(project, slot_a, "build_checks", {"review_category": "hair_rinse_off", "markets": ["CN"]})["notice"])
print(advance(project, slot_a, "dispatch_checks")["notice"])
print(advance(project, slot_a, "release_formal", {"note": "二查通过"})["notice"])
print(advance(project, slot_a, "prepare_sample", {"form": "10 ml 喷雾样", "quantity": "10", "unit": "ml"})["notice"])
print(advance(project, slot_a, "dispatch_shipment")["notice"])
receipt("shipment", payload={"tracking": "SF-FORMAL-A"})

# 方向二：对香 → 开发子项 → 入库 → 回到父项
plan_b = call("POST", f"/api/projects/{project}/goals/{goal_b}/plan",
              {"strategy": "duplicate", "payload": {"sample_reference": "客户样 A"}})
child = plan_b["child_slot_id"]
print("child slot", child)
receipt("analysis", payload={"document": "GC-2026-01"})
receipt("perfumery", payload={"trial_fragrance_id": "DIY-2601", "formula_version": "V1", "note": "初步接近"})
print(advance(project, child, "accept_trial", {"note": "方向对，进入检查"})["notice"])
print(advance(project, child, "build_checks", {"review_category": "hair_rinse_off", "markets": ["CN"]})["notice"])
print(advance(project, child, "dispatch_checks")["notice"])
receipt("check")
print(advance(project, child, "release_warehouse", {"note": "入库"})["notice"])
print(advance(project, child, "dispatch_warehouse")["notice"])
receipt("warehouse")
print(advance(project, child, "accept_warehouse", {"fragrance_id": "DIY-2601", "formula_version": "V1"})["notice"])

# 父项二查 → 正式寄样
parent_b = plan_b["slot_id"]
print("parent slot", parent_b)
print(advance(project, parent_b, "build_checks", {"review_category": "hair_rinse_off", "markets": ["CN"]})["notice"])
print(advance(project, parent_b, "dispatch_checks")["notice"])
receipt("check")
print(advance(project, parent_b, "release_formal", {"note": "二查通过"})["notice"])
print(advance(project, parent_b, "prepare_sample", {"form": "10 ml 喷雾样", "quantity": "10", "unit": "ml"})["notice"])
print(advance(project, parent_b, "dispatch_shipment")["notice"])
receipt("shipment", payload={"tracking": "SF-FORMAL"})

view = call("GET", f"/api/projects/{project}")
print("project status", view["project"]["status"], view["progress"])
for sub in view["subprojects"]:
    print("sub", sub["id"], sub["title"], sub["status"], "dev=" + str(sub["is_development"]))
    for round_item in sub["rounds"]:
        for goal in round_item["goals"]:
            for slot in goal["slots"]:
                print("  slot", slot["id"], slot["strategy"], slot["stage"], slot["fragrance_id"],
                      "checks", (slot["checks"] or {}).get("total"),
                      "actions", [item["action"] for item in slot["actions"] if item["enabled"]])

pages = ["/", "/index.html", "/project.html?id=%d" % project, "/select.html", "/mock.html",
         "/style.css", "/common.js", "/project.js"]
for page in pages:
    request = urllib.request.Request(BASE + page)
    with urllib.request.urlopen(request, timeout=10) as response:
        print("page", page, response.status, response.headers.get("Content-Type"))
