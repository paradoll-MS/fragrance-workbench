import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app import config
from app.api.http import Handler
from app.workflow.service import Workbench

DB = config.DATA / "test-http.sqlite3"


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if DB.exists():
            DB.unlink()
        Handler.workbench = Workbench(database=DB)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if DB.exists():
            DB.unlink()

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
                return response.status, (json.loads(payload) if "json" in content_type else payload), content_type
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8")), error.headers.get("Content-Type", "")

    def test_health(self):
        status, data, _ = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["service"], config.SERVICE)
        self.assertEqual(data["version"], config.VERSION)
        self.assertTrue(data["rules"])

    def test_bootstrap_has_vocabulary(self):
        status, data, _ = self.call("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        for key in ("entries", "strategies", "stages", "departments", "endpoints", "issue_codes",
                    "review_categories", "terms", "categories", "project_kinds"):
            self.assertTrue(data.get(key), key)
        self.assertIn("hair_rinse_off", [item["id"] for item in data["review_categories"]])

    def test_static_and_traversal(self):
        status, body, content_type = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("评香工作台".encode("utf-8"), body)
        status, _, _ = self.call("GET", "/style.css")
        self.assertEqual(status, 200)
        status, _, _ = self.call("GET", "/../app/config.py")
        self.assertEqual(status, 404)

    def test_project_lifecycle_api(self):
        status, created, _ = self.call("POST", "/api/projects", {"name": "接口项目", "kind": "customer"})
        self.assertEqual(status, 200)
        project_id = created["project_id"]

        status, listing, _ = self.call("GET", "/api/projects")
        self.assertEqual(status, 200)
        self.assertIn(project_id, [item["id"] for item in listing["projects"]])

        status, view, _ = self.call("GET", f"/api/projects/{project_id}")
        self.assertEqual(status, 200)
        self.assertEqual(view["project"]["name"], "接口项目")

        status, draft, _ = self.call("POST", f"/api/projects/{project_id}/draft", {"directions": [
            {"title": "洗发水方向", "entry": "recommend_simple",
             "conditions": {"markets": ["中国"], "substrate": "洗发水"}}]})
        self.assertEqual(status, 200)
        status, confirmed, _ = self.call("POST", f"/api/projects/{project_id}/draft/{draft['draft_id']}/confirm",
                                         {"edits": draft["draft"]})
        self.assertEqual(status, 200)
        goal = confirmed["committed"][0]["goal_id"]

        status, planned, _ = self.call("POST", f"/api/projects/{project_id}/goals/{goal}/plan",
                                       {"strategy": "select", "payload": {"asset_key": "1040"}})
        self.assertEqual(status, 200)
        self.assertTrue(planned["created"])
        status, view, _ = self.call("GET", f"/api/projects/{project_id}")
        slot = view["subprojects"][0]["rounds"][0]["goals"][0]["slots"][0]
        self.assertEqual(slot["fragrance_id"], "1040")
        self.assertTrue(any(item["action"] == "build_checks" for item in slot["actions"]))

    def test_search_api(self):
        status, data, _ = self.call("POST", "/api/search", {"query": {"text": "白茶 200 以内 洗发水"}})
        self.assertEqual(status, 200)
        self.assertTrue(data["results"])
        self.assertTrue(all(float(card["price"]) <= 200 for card in data["results"] if card["price"]))
        self.assertEqual(data["query"]["categories"], ["CAT_03"])

    def test_search_requires_a_subject(self):
        status, data, _ = self.call("POST", "/api/search", {"query": {"text": ""}})
        self.assertEqual(status, 400)
        self.assertIn("请输入", data["error"])

    def test_edit_asset_requires_existing_fragrance(self):
        status, data, _ = self.call("POST", "/api/asset", {"asset_key": "NOPE", "tags": []})
        self.assertEqual(status, 400)
        self.assertIn("香精不存在", data["error"])

    def test_exact_search_api(self):
        status, data, _ = self.call("POST", "/api/search", {"query": {"text": "香奈儿 COCO Mademoiselle EDP"}})
        self.assertEqual(status, 200)
        self.assertIn("results", data)

    def test_bad_requests(self):
        status, data, _ = self.call("POST", "/api/projects", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("JSON", data["error"])
        status, data, _ = self.call("POST", "/api/projects", {"name": ""})
        self.assertEqual(status, 400)
        self.assertIn("项目名称", data["error"])
        status, data, _ = self.call("GET", "/api/nothing")
        self.assertEqual(status, 404)

    def test_platform_and_receipt(self):
        status, data, _ = self.call("GET", "/api/platform")
        self.assertEqual(status, 200)
        self.assertIn("tasks", data)
        status, data, _ = self.call("POST", "/api/platform/default", {"department": "quality", "result": True})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"], 1)
        self.call("POST", "/api/platform/default", {"department": "quality", "result": ""})

    def test_add_direction_to_existing_project(self):
        status, created, _ = self.call("POST", "/api/projects", {"name": "追加方向项目"})
        project_id = created["project_id"]
        status, draft, _ = self.call("POST", f"/api/projects/{project_id}/draft", {"directions": [
            {"title": "第一个方向", "entry": "recommend_simple", "conditions": {"markets": ["中国"]}}]})
        self.call("POST", f"/api/projects/{project_id}/draft/{draft['draft_id']}/confirm",
                  {"edits": draft["draft"]})
        status, second, _ = self.call("POST", f"/api/projects/{project_id}/draft", {"directions": [
            {"title": "第二个方向", "entry": "with_sample", "conditions": {"markets": ["中国"]}}]})
        status, confirmed, _ = self.call("POST", f"/api/projects/{project_id}/draft/{second['draft_id']}/confirm",
                                         {"edits": second["draft"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(confirmed["committed"]), 1)
        status, view, _ = self.call("GET", f"/api/projects/{project_id}")
        self.assertEqual(len(view["subprojects"]), 2)
        self.assertEqual(view["subprojects"][1]["requirement_type"], "with_sample")

    def test_platform_receipt_uses_spec(self):
        status, created, _ = self.call("POST", "/api/projects", {"name": "回执项目"})
        project_id = created["project_id"]
        draft = self.call("POST", f"/api/projects/{project_id}/draft", {"directions": [
            {"title": "回执方向", "entry": "recommend_simple", "conditions": {"markets": ["中国"]}}]})[1]
        goal = self.call("POST", f"/api/projects/{project_id}/draft/{draft['draft_id']}/confirm",
                         {"edits": draft["draft"]})[1]["committed"][0]["goal_id"]
        slot = self.call("POST", f"/api/projects/{project_id}/goals/{goal}/plan",
                         {"strategy": "select", "payload": {"asset_key": "1040"}})[1]["slot_id"]
        self.call("POST", f"/api/projects/{project_id}/slots/{slot}/advance",
                  {"action": "build_checks", "payload": {"review_category": "hair_rinse_off"}})
        self.call("POST", f"/api/projects/{project_id}/slots/{slot}/advance",
                  {"action": "dispatch_checks", "payload": {}})
        status, data, _ = self.call("GET", "/api/platform")
        check_tasks = [item for item in data["tasks"] if item["type"] == "check"]
        self.assertTrue(check_tasks)
        self.assertTrue(check_tasks[0]["spec"]["requirement_ids"])
        self.call("POST", "/api/platform/receipt", {"task_id": check_tasks[0]["id"], "passed": True, "payload": {}})
        status, view, _ = self.call("GET", f"/api/projects/{project_id}")
        counts = view["subprojects"][0]["rounds"][0]["goals"][0]["slots"][0]["checks"]["counts"]
        self.assertTrue(counts.get("passed"))


if __name__ == "__main__":
    unittest.main()
