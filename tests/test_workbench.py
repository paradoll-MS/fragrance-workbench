import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json

from app.catalog import CONFIG
from app.recommendation import category_branches, normalize_query, score_branch, rank
from app.server import Workbench, make_handler
from app.targeting import direct_mapping, verify_proposal


TERMS = {
    "rose": {"name": "玫瑰", "level": "A1"},
    "lemon": {"name": "柠檬", "level": "A1"},
    "sweet": {"name": "甜感", "level": "A2"},
    "wood": {"name": "木质", "level": "A2"},
    "fresh": {"name": "清新", "level": "B"},
    "salon": {"name": "沙龙", "level": "C", "category": "p"},
    "citrus": {"name": "柑橘", "level": "C", "category": "s"},
}
CATEGORIES = {"p": "个人", "s": "空间"}
EDGES = {"salon": {"wood", "rose"}, "citrus": {"lemon", "fresh"}}


def group(*tags, role="preference", op="ANY", strength="normal"):
    return {"tags": list(tags), "role": role, "op": op, "strength": strength}


def detail(tags, groups, mode="recommend_brand", category="p"):
    query = normalize_query({"mode": mode, "groups": groups, "categories": [category]},
                            TERMS, CATEGORIES, CONFIG)
    branches = category_branches(query, TERMS)
    return score_branch(category, set(tags), branches[category], TERMS, EDGES, CONFIG, mode)


def asset(key, *, tags=(), price=None, cats=("p",), known=("p",), c=None):
    from app.recommendation import comparable_price
    return {
        "conflict": False, "categories": set(known), "searchable_categories": set(cats),
        "ab": set(tags), "c": c or {}, "products": [], "price": comparable_price(price),
        "fragrance_id": key, "is_new": False, "is_hot": False,
        "card": {"key": key, "price": price, "is_new": False, "is_hot": False}
    }


class ScoreTests(unittest.TestCase):
    def test_soft_avoid_has_visible_bounded_penalty(self):
        q = [group("wood"), group("sweet", role="avoid", strength="strong")]
        self.assertEqual(detail(["wood"], q)["score"], 100)
        penalty = detail(["wood", "sweet"], q + [group("sweet", role="avoid", strength="mild")])
        self.assertEqual(penalty["score"], 78)
        self.assertEqual(penalty["negative_hits"][0]["name"], "甜感")
        self.assertEqual(detail(["wood", "sweet", "fresh"], q + [group("fresh", role="avoid", strength="strong")])["penalty"], 30)
        self.assertIsNone(detail(["sweet"], [group("sweet", role="avoid")])["score"])

    def test_any_satisfied_does_not_warn_about_other_leg(self):
        g = group("rose", "lemon")
        self.assertEqual(detail(["rose"], [g])["score"], 100)
        self.assertEqual(detail(["rose"], [g])["main_note_gaps"], [])
        expected = detail(["rose"], [dict(g, op="ALL")])
        self.assertEqual(expected["score"], 50)
        self.assertEqual(expected["main_note_gaps"], ["柠檬"])

    def test_bidirectional_mapping_and_no_double_credit(self):
        case = detail(["salon"], [group("wood")])
        self.assertEqual(case["score"], 20)
        self.assertEqual(case["cross_hits"][0]["via"], ["salon"])
        self.assertEqual(detail(["salon", "wood"], [group("wood")])["score"], 100)
        self.assertEqual(detail(["wood", "rose"], [group("salon")])["score"], 50)
        self.assertEqual(detail(["wood"], [group("salon")])["score"], 25)
        self.assertEqual(detail(["wood"], [group("wood"), group("salon")])["score"], 33.33)
        self.assertEqual(detail(["salon"], [group("wood")], "with_sample")["score"], 10)

    def test_active_dimensions_only_and_hard_tags_not_counted(self):
        g = [group("wood"), group("fresh")]
        self.assertEqual(detail(["wood"], g, "recommend_simple")["score"], 62.5)
        self.assertIsNone(detail(["wood"], [group("wood"), group("wood", role="required")])["score"])

    def test_multi_category_filters_independent_and_historical_distinct(self):
        q = {"mode": "recommend_brand", "categories": ["p", "s"],
             "groups": [group("salon", role="required"), group("citrus", role="required"), group("fresh")]}
        rows = [
            asset("s", tags=["fresh"], cats=["s"], known=[], c={"s": {"citrus"}}),
            asset("p", tags=["fresh"], c={"s": {"citrus"}}),
        ]
        result = rank(q, rows, TERMS, CATEGORIES, EDGES, CONFIG)
        self.assertEqual([r["key"] for r in result["results"]], ["s"])
        self.assertEqual(result["results"][0]["category_evidence"], "historical")
        self.assertFalse(rank({**q, "confirmed_only": True}, rows, TERMS, CATEGORIES, EDGES, CONFIG)["results"])

    def test_price_and_hard_tag_diagnostics_are_distinct(self):
        q = {"categories": ["p"], "max_price": 100,
             "groups": [group("rose", role="required"), group("sweet", role="avoid")]}
        rows = [asset("close", tags=["rose", "sweet"], price=100),
                asset("expensive", tags=["rose"], price=101),
                asset("unknown", tags=["rose"], price="90-110"),
                asset("wrong", tags=["wood"], price=95)]
        result = rank(q, rows, TERMS, CATEGORIES, EDGES, CONFIG)
        self.assertEqual([r["key"] for r in result["results"]], ["close"])
        self.assertEqual(result["diagnostics"], {"价格": 2, "硬性标签": 1})
        self.assertIn("命中排斥项 甜感", result["results"][0]["risks"])
        self.assertEqual({r["key"]: r["risks"][0] for r in result["alternatives"]},
                         {"expensive": "超价", "unknown": "价格待查", "wrong": "硬性香气标签缺项"})


class WebsiteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.app = Workbench(Path(cls.directory.name) / "test.sqlite3")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.worker.join()
        cls.server.server_close()
        cls.directory.cleanup()

    def request(self, path, data=None, as_html=False):
        request = Request(f"http://127.0.0.1:{self.server.server_port}" + path,
                          data=json.dumps(data).encode() if data is not None else None)
        with urlopen(request, timeout=10) as response:
            content = response.read().decode()
            return content if as_html else json.loads(content)

    def test_cross_site_round_trip(self):
        self.assertIn("评香工作台", self.request("/", as_html=True))
        self.assertIn("模拟中台", self.request("/mock-platform", as_html=True))
        self.assertGreater(len(self.request("/api/bootstrap")["terms"]), 800)
        project = self.request("/api/projects", {"name": "演示"})
        query = {"categories": ["CAT_07"], "max_price": 90,
                 "groups": [group("A1_c3bf4b4601", role="required")]}
        found = self.request("/api/search", {"query": query, "project_id": project["id"]})
        self.assertEqual(found["total"], 0)
        self.assertGreaterEqual(found["diagnostics"]["价格"], 5)
        self.assertTrue(any("超价" in a["risks"] or "价格待查" in a["risks"] for a in found["alternatives"]))
        self.request("/api/quotes", {"code": "2051", "price": 89})
        after = self.request("/api/search", {"query": query, "project_id": project["id"], "manual": True})
        card = next(c for c in after["results"] if c["key"] == "2051")
        self.assertEqual(card["price_source"], "mock")
        self.assertNotEqual(found["query_id"], after["query_id"])
        q2 = {**query, "groups": query["groups"] + [group("B5_c8073c6276", role="avoid")]}
        refilter = self.request("/api/search", {"query": q2, "project_id": project["id"], "manual": True})
        action = {"project_id": project["id"], "action": "initial_shipment", "query_id": refilter["query_id"],
                  "sample_form": "10 ml", "key": "2051"}
        self.request("/api/decisions", action)
        self.request("/api/decisions", action)
        self.request("/api/assets", {"key": "2051", "tags": [], "product_ids": ["PR_0060"]})
        simulated = self.request("/api/platform")
        self.assertEqual(len(simulated["tasks"]), 1)
        self.assertIn("需求筛选修改", [r["kind"] for r in simulated["feed"]])
        self.assertIn("香精资产修改", [r["kind"] for r in simulated["feed"]])
        self.request("/api/task-result", {"id": simulated["tasks"][0]["id"], "passed": False})
        self.assertEqual(self.request("/api/platform")["tasks"][0]["result"], 0)
        self.request("/api/task-result", {"id": simulated["tasks"][0]["id"], "passed": True})
        self.assertEqual(self.request("/api/platform")["tasks"][0]["result"], 1)
        latest = self.request("/api/search", {"query": {"mode": "find_product", "product_id": "PR_0060"}})
        self.assertFalse(any(row["key"] == "2051" for row in latest["results"]))

    def test_mapping_lookup_and_price_validation(self):
        self.assertEqual(direct_mapping("桂花", self.app.catalog)[0]["tags"], ["A1_c3bf4b4601"])
        self.assertIsNone(direct_mapping("桂花，不要太甜", self.app.catalog))
        with self.assertRaises(HTTPError) as error:
            self.request("/api/search", {"query": {"min_price": 100, "max_price": 90}})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_generic_intensity_and_accord_are_not_overinterpreted(self):
        quote = "闻起来偏木质，别太浓。"
        checked, issue = verify_proposal({"source": "别太浓", "role": "avoid", "tags": ["B3_e826d4f21c"]},
                                          quote, self.app.catalog, "with_sample")
        self.assertIsNone(checked)
        self.assertIn("强度要求待闻", issue)
        checked, issue = verify_proposal({"source": "偏木质", "role": "required",
                                          "tags": ["A2_4d8dcb29ec", "A3_23ddc3a344"]},
                                         quote, self.app.catalog, "with_sample")
        self.assertIsNone(issue)
        self.assertEqual(checked["role"], "preference")
        self.assertEqual(checked["tags"], ["A2_4d8dcb29ec"])

    def test_catalog_sandbox_and_dictionary_are_live(self):
        starter = {"term": "电光樱桃", "query": {"groups": [group("A2_c6c54a254f")]}}
        result = self.request("/api/sandbox-search", starter)
        self.assertTrue(any(card["fragrance_id"] == "LYP879BLY" and card["score"] == 100
                            for card in result["results"]))
        changed = self.request("/api/sandbox-search", {**starter, "weights": {"A2": 0}})
        self.assertIsNone(changed["results"][0]["score"])
        self.assertEqual(len(self.request("/api/dictionaries")["review_categories"]), 18)

    def test_default_department_result_is_isolated_to_new_tasks(self):
        self.request("/api/mock-default", {"department": "analysis", "result": False})
        project = self.request("/api/projects", {"name": "分析测试"})
        self.request("/api/decisions", {"project_id": project["id"], "action": "duplicate",
                                        "note": "合成任务"})
        tasks = [r for r in self.request("/api/platform")["tasks"] if r["project_id"] == project["id"]]
        self.assertEqual(tasks[0]["result"], 0)
        self.request("/api/mock-default", {"department": "analysis", "result": None})
        self.request("/api/decisions", {"project_id": project["id"], "action": "duplicate",
                                        "note": "另一条合成任务"})
        tasks = [r for r in self.request("/api/platform")["tasks"] if r["project_id"] == project["id"]]
        self.assertEqual([r["result"] for r in tasks], [None, 0])

    def test_confirmed_product_with_unverified_version(self):
        q = {"mode": "find_product", "product_id": "PR_0082"}
        general = self.request("/api/search", {"query": q})
        self.assertIn("JKP864AJK", {row["key"] for row in general["results"]})
        specific = self.request("/api/search", {"query": {**q, "edition": "EDP"}})
        self.assertEqual(specific["total"], 0)
        self.assertIn("JKP864AJK", {row["key"] for row in specific["clues"]})


if __name__ == "__main__":
    unittest.main()
