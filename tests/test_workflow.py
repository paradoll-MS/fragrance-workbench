import base64
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from app.server import Workbench
from app.workflow import anchored_deadline


def options(entry, title, conditions=None, intent="new", **lineage):
    return {"title": title, "entry": entry, "intent": intent, "conditions": conditions or {}, **lineage}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = Workbench(Path(folder.name) / "flow.sqlite3")
        self.flow = self.app.workflow
        self.project = self.app.project({"name": "验收项目"})["id"]
        self.base = {"project_id": self.project}

    def goal(self, *directions, shared=None):
        self.flow.confirm({**self.base, "result": {"directions": list(directions), "shared": shared or {}}})
        return self.flow.snapshot(self.base)["rounds"][0]["goals"]

    def current(self, slot):
        current = self.flow.snapshot(self.base)
        return next(s for r in current["rounds"] for g in r["goals"] for s in g["slots"] if s["id"] == slot["id"])

    def step(self, slot, action, **fields):
        return self.flow.advance({**self.base, "slot_id": slot["id"], "revision": slot["stage_revision"],
                                  "action": action, **fields})

    def result(self, slot, passed=True):
        for task in self.current(slot)["tasks"]:
            self.app.task_result({"id": task["id"], "passed": passed})

    def test_extraction_and_draft_gate(self):
        txt = "来源：本地测试\n---原文开始---\n包含一款TF的白麝香，寄18%加香小样\n---原文结束---"
        src = self.flow.source({**self.base, "text": txt})
        self.assertNotIn("来源", src["extracted"]["segments"][0]["text"])
        self.assertIn("3–3", src["extracted"]["segments"][0]["locator"])
        raw = {"shared": {"delivery_note": "仅寄18%加香小样"}, "directions": [
            options("find_product", "TF的白麝香", {"product": "TF的白麝香"}, basis=[
                {"segment_id": f'{src["id"]}.1', "quote": "包含一款TF的白麝香"}])]}
        with patch("app.workflow.propose", return_value=(raw, {"model": "local fixture", "seconds": 0})):
            draft = self.flow.analyze({**self.base, "source_ids": [src["id"]]})
        d = draft["result"]["directions"][0]
        self.assertEqual(d["conditions"]["catalog_product_id"], "PR_0060")
        self.assertEqual(d["conditions"]["dose_text"], "18%")
        self.assertEqual(len(d["basis"]), 1)
        self.assertFalse(self.flow.snapshot(self.base)["rounds"])
        r1 = self.flow.confirm({**self.base, "draft_id": draft["id"]})
        self.assertEqual(r1, self.flow.confirm({**self.base, "draft_id": draft["id"]}))
        self.assertFalse(anchored_deadline("2026年8月29日", [{"text": "文档日期  2026年8月29日"}]))
        self.assertTrue(anchored_deadline("9 月底", [{"text": "最晚在9月底确定定香"}]))

    def test_numbered_series_and_quantity_are_normalized(self):
        input_data = {"shared": {"sample_form": "香精：30ml"}, "directions": [
            options("find_product", "Le Labo 13 精确香型", {"brand": "Le Labo", "product": "香水"}),
            options("find_product", "Le Labo 33 精确香型", {"brand": "Le Labo", "product": "香水"}),
            options("recommend_simple", "Le Labo 其余系列", {"brand": "Le Labo", "dose_text": "主水果75–80%；空气感5–10%"}),
        ]}
        parsed = self.flow.validate_draft(input_data, [], [], [])["directions"]
        self.assertEqual([d["conditions"].get("catalog_product_id") for d in parsed], ["PR_0082", "PR_0081", None])
        self.assertEqual(parsed[2]["conditions"]["catalog_brand_id"], "BR_007")
        self.assertEqual(parsed[0]["conditions"]["quantity_text"], "30ml")
        self.assertNotIn("dose_text", parsed[2]["conditions"])
        self.assertIn("composition_text", parsed[2]["conditions"])

    def test_named_required_product_is_distinct_from_style(self):
        raw = {"directions": [options("recommend_brand", "TF白麝香风格", {"brand": "TF", "product": "白麝香"})]}
        literal = [{"id": "1.1", "locator": "第1行", "text": "请推荐一款TF的白麝香用于香水。"}]
        style = [{"id": "1.1", "locator": "第1行", "text": "请推荐一款TF白麝香风格的香水。"}]
        self.assertEqual(self.flow.validate_draft(raw, literal, [], [])["directions"][0]["entry"], "find_product")
        self.assertEqual(self.flow.validate_draft(raw, style, [], [])["directions"][0]["entry"], "recommend_brand")

    def test_exact_select_to_initial_formal_and_resend(self):
        first = self.goal(options("find_product", "TF白麝香", {
            "brand": "TF", "product": "白麝香", "application_id": "CAT_01", "review_category_id": "fine_fragrance",
            "sample_form": "18%加香小样", "quantity_text": "10 ml", "requirements": ["内部检查"]}))[0]
        with self.assertRaisesRegex(ValueError, "没有经确认"):
            self.flow.plan({**self.base, "goal_id": first["id"], "strategy": "select", "asset_key": "2051"})
        item = self.flow.plan({**self.base, "goal_id": first["id"], "strategy": "select", "asset_key": "JKP1745AJK"})
        self.assertEqual(item["id"], self.flow.plan({**self.base, "goal_id": first["id"], "strategy": "select",
                                                   "asset_key": "JKP1745AJK"})["id"])
        item = self.step(item, "prepare_sample")
        self.assertIn("18%", self.app.platform()["tasks"][0]["spec"]["sample_form"])
        with self.assertRaisesRegex(ValueError, "尚未满足"):
            self.step(item, "record_sample")
        self.result(item)
        item = self.step(item, "record_sample")
        sample_id = item["context"]["sample_id"]
        item = self.step(item, "initial_shipment")
        self.result(item); item = self.step(item, "record_shipment")
        self.assertEqual(item["state"], "chosen")
        self.assertFalse(self.flow.snapshot(self.base)["rounds"][0]["complete"])
        item = self.step(item, "prepare_sample")
        self.result(item); item = self.step(item, "record_sample")
        self.assertNotEqual(sample_id, item["context"]["sample_id"])
        with self.assertRaisesRegex(ValueError, "尚未满足"):
            self.step(item, "formal_shipment")
        item = self.step(item, "shipment_checks")
        platform = self.app.platform()
        check = platform["tasks"][0]["spec"]
        self.assertEqual(check["brief"]["requirements"], ["内部检查"])
        self.assertEqual(check["execution"]["formula_version"], "MOCK-CATALOG-JKP1745AJK")
        self.result(item); item = self.step(item, "record_shipment_checks")
        item = self.step(item, "formal_shipment")
        self.result(item); item = self.step(item, "record_shipment")
        result = self.flow.snapshot(self.base)
        self.assertTrue(result["rounds"][0]["complete"])
        self.assertEqual([r["kind"] for r in result["shipments"]], ["formal", "initial"])
        goal2 = self.goal(options("resend", "复寄白麝香", intent="resend",
                                  source_shipment_id=result["shipments"][0]["id"]))[0]
        self.assertEqual(goal2["spec"]["previous_goal_id"], first["id"])
        resend = self.flow.plan({**self.base, "goal_id": goal2["id"], "strategy": "resend"})
        self.assertEqual(resend["context"]["formula_version"], item["context"]["formula_version"])

    def test_duplicate_rejection_and_terminal_internal_creation(self):
        goals = self.goal(options("with_sample", "实物对香"), options("invent", "内部开发", {"scent": "木质焚香"}))
        with self.assertRaisesRegex(ValueError, "登记"):
            self.flow.plan({**self.base, "goal_id": goals[0]["id"], "strategy": "duplicate"})
        duplicate = self.flow.plan({**self.base, "goal_id": goals[0]["id"], "strategy": "duplicate",
                                    "sample_reference": "实物 A"})
        self.result(duplicate); duplicate = self.step(duplicate, "confirm_analysis")
        self.assertTrue(duplicate["context"]["analysis_report"].startswith("MOCK-GC-"))
        self.result(duplicate)
        trial = self.step(duplicate, "reject_trial", note="减少甜感")
        self.assertEqual(trial["context"]["iteration"], 2)
        created = self.flow.plan({**self.base, "goal_id": goals[1]["id"], "strategy": "create"})
        self.result(created); created = self.step(created, "accept_trial")
        self.result(created, False); created = self.step(created, "retry")
        self.result(created); created = self.step(created, "send_warehouse")
        self.result(created); created = self.step(created, "record_warehouse")
        self.assertEqual(created["state"], "complete")
        self.assertIn("warehouse_id", created["context"])
        self.assertEqual(self.flow.snapshot(self.base)["shipments"], [])

    def test_modify_and_missing_formula_fallback(self):
        goal = self.goal(options("modify", "客户改香", {"base_code": "LYP879BLY", "changes": "减少甜度"}))[0]
        with self.assertRaisesRegex(ValueError, "版本"):
            self.flow.plan({**self.base, "goal_id": goal["id"], "strategy": "modify"})
        changed = self.flow.reroute({**self.base, "goal_id": goal["id"], "entry": "with_sample"})
        self.assertIn("duplicate", changed["strategies"])
        self.assertEqual(changed["conditions"]["changes"], "减少甜度")

    def test_other_project_cannot_supply_a_round_reference(self):
        prior = self.goal(options("recommend_simple", "旧方向"))[0]
        second = self.app.project({"name": "另一项目"})["id"]
        self.flow.confirm({"project_id": second, "result": {"directions":
            [options("modify", "另一个改香", previous_goal_id=prior["id"])]}})
        saved = self.flow.snapshot({"project_id": second})["rounds"][0]["goals"][0]["spec"]
        self.assertIsNone(saved["previous_goal_id"])
        self.assertIsNone(saved["source_shipment_id"])

    def test_source_format_and_duplicate(self):
        import io
        from openpyxl import Workbook
        book = Workbook()
        book.active.title = "线香"
        book.active.append(["方向", "木质"])
        out = io.BytesIO()
        book.save(out)
        b64 = base64.b64encode(out.getvalue()).decode()
        a = self.flow.source({**self.base, "base64": b64, "name": "brief.xlsx"})
        b = self.flow.source({**self.base, "base64": b64, "name": "brief.xlsx"})
        self.assertEqual(a["id"], b["id"])
        self.assertIn("线香", a["extracted"]["segments"][0]["locator"])
        self.assertEqual(a["extracted"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
