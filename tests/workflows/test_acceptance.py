"""Acceptance cases: walk real paths end to end and assert the business outcomes.

These are the cases a reviewer repeats by hand on the running app; keeping them here
means a change that breaks the story fails the suite, not just the unit tests.
"""

import unittest

from app import config
from app.store.db import loads, rows
from app.workflow import views
from app.workflow.service import Workbench

DB = config.DATA / "test-acceptance.sqlite3"


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        if DB.exists():
            DB.unlink()
        self.wb = Workbench(database=DB)
        self.project = self.wb.create_project("验收项目", "customer", "某日化")
        self.wb.add_source(self.project, "需求.txt",
                           text="洗发水，白茶木质，300 以内，中国市场，先寄初样给客户")

    def tearDown(self):
        if DB.exists():
            DB.unlink()

    def direction(self, title, entry, conditions):
        draft_id, _ = self.wb.manual_draft(self.project, [{
            "title": title, "entry": entry, "conditions": conditions}])
        committed = self.wb.confirm_draft(self.project, draft_id)
        return committed["directions"][0]["goal_id"]

    def pending(self, kind):
        with self.wb.store.connect() as db:
            return rows(db, "SELECT * FROM task WHERE task_type=? AND status IN ('sent','queued') ORDER BY id",
                        (kind,))

    def pass_all(self, kind, passed=True):
        for task in self.pending(kind):
            self.wb.apply_receipt(task["id"], passed, {"note": "部门已出结果"})

    def slot_rows(self):
        with self.wb.store.connect() as db:
            return rows(db, "SELECT * FROM slot ORDER BY id")

    def test_recommend_and_ship_to_customer(self):
        """验收参考 5.1／5.10：一条选香路径从资料到客户交付，每步都有对象支撑。"""
        goal = self.direction("洗发水白茶木质", "recommend_simple",
                              {"markets": ["中国"], "substrate": "洗发水", "price_text": "300 以内"})
        plan = self.wb.plan(self.project, goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.assertEqual(self.slot_rows()[0]["stage"], "checking")

        built = self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.assertIn("11 条", built["notice"])
        with self.wb.store.connect() as db:
            check_set = dict(db.execute("SELECT * FROM check_set WHERE slot_id=?", (slot_id,)).fetchone())
            requirements = rows(db, "SELECT * FROM requirement WHERE check_set_id=?", (check_set["id"],))
        self.assertEqual(check_set["review_category"], "hair_rinse_off")
        self.assertTrue(all(item["origin_text"] for item in requirements))
        self.assertTrue(all(item["criteria"] for item in requirements))
        self.assertEqual({item["department"] for item in requirements}, {"compliance", "quality", "application"})

        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        tasks = self.pending("check")
        self.assertEqual(len({task["department"] for task in tasks}), 3)
        for task in tasks:
            spec = loads(task["spec"], {})
            self.assertTrue(spec["requirements"])
            self.assertTrue(all(item["criteria"] for item in spec["requirements"]))

        self.pass_all("check")
        released = self.wb.advance(self.project, slot_id, "release_formal", {"note": "全项通过"})
        self.assertFalse(released["blocked"])
        self.wb.advance(self.project, slot_id, "prepare_sample", {"form": "10 ml", "quantity": "10", "unit": "ml"})
        self.wb.advance(self.project, slot_id, "dispatch_shipment", {})
        self.pass_all("shipment")

        view = views.project_view(self.wb, self.project)
        self.assertEqual(view["project"]["status"], "completed")
        slot = view["subprojects"][0]["rounds"][0]["goals"][0]["slots"][0]
        self.assertEqual(slot["stage"], "complete")
        self.assertEqual(slot["checks"]["counts"]["passed"], slot["checks"]["total"])
        self.assertEqual([item["kind"] for item in slot["shipments"]], ["formal"])
        self.assertEqual([item["action"] for item in slot["checks"]["releases"]], ["formal"])
        self.assertEqual(slot["shipments"][0]["fragrance_id"], "1040")

    def test_duplicate_through_development_to_parent_shipment(self):
        """验收参考 5.7／5.8／6.9：仿香走分析、调香、入库，回父项后二查复用证据。"""
        goal = self.direction("竞品样复刻", "with_sample",
                              {"markets": ["中国"], "substrate": "洗发水", "sample_reference": "S-77"})
        plan = self.wb.plan(self.project, goal, "duplicate", {"sample_reference": "S-77"})
        parent, child = plan["slot_id"], plan["child_slot_id"]

        self.assertEqual([task["task_type"] for task in self.pending("analysis")], ["analysis"])
        self.pass_all("analysis")
        self.assertTrue(self.pending("perfumery"))
        self.pass_all("perfumery")

        confirmed = self.wb.advance(self.project, child, "confirm_gc", {"report": "GC-01"})
        self.assertEqual(confirmed["notice"], "GC 已确认；已有试作可直接验收")
        self.assertEqual(len(self.pending("perfumery")), 0)
        rejected = self.wb.advance(self.project, child, "reject_trial", {"note": "木质偏薄"})
        self.assertFalse(rejected["blocked"])
        self.assertTrue(self.pending("perfumery"))
        self.pass_all("perfumery")
        self.wb.advance(self.project, child, "accept_trial", {"note": "接近客户样"})

        with self.wb.store.connect() as db:
            trials = rows(db, "SELECT * FROM trial ORDER BY id")
            evaluations = rows(db, "SELECT * FROM evaluation ORDER BY id")
        self.assertEqual(len(trials), 2)
        self.assertEqual([item["verdict"] for item in evaluations], ["rejected", "passed"])

        self.wb.advance(self.project, child, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, child, "dispatch_checks", {})
        self.pass_all("check")
        self.wb.advance(self.project, child, "release_warehouse", {})
        self.wb.advance(self.project, child, "dispatch_warehouse", {})
        self.pass_all("warehouse")
        self.wb.advance(self.project, child, "accept_warehouse", {"fragrance_id": "DIY-01", "formula_version": "V1"})

        with self.wb.store.connect() as db:
            parent_slot = dict(db.execute("SELECT * FROM slot WHERE id=?", (parent,)).fetchone())
        self.assertEqual(parent_slot["fragrance_id"], "DIY-01")
        self.assertEqual(parent_slot["stage"], "checking")

        rebuilt = self.wb.advance(self.project, parent, "build_checks", {"review_category": "hair_rinse_off"})
        self.assertIn("既有证据", rebuilt["notice"])
        view = views.project_view(self.wb, self.project)
        parent_view = [slot for sub in view["subprojects"] for round_item in sub["rounds"]
                       for goal_item in round_item["goals"] for slot in goal_item["slots"]
                       if slot["id"] == parent][0]
        self.assertEqual(parent_view["checks"]["counts"].get("passed"), parent_view["checks"]["total"])

        self.wb.advance(self.project, parent, "release_formal", {"note": "复用入库证据"})
        self.wb.advance(self.project, parent, "prepare_sample", {"form": "10 ml", "quantity": "10", "unit": "ml"})
        self.wb.advance(self.project, parent, "dispatch_shipment", {})
        self.pass_all("shipment")

        view = views.project_view(self.wb, self.project)
        self.assertEqual(view["project"]["status"], "completed")
        self.assertEqual(view["progress"]["subproject_done"], 2)
        self.assertEqual(view["progress"]["slot_done"], 2)
        child_view = [slot for sub in view["subprojects"] for round_item in sub["rounds"]
                      for goal_item in round_item["goals"] for slot in goal_item["slots"]
                      if slot["id"] == child][0]
        self.assertEqual(child_view["stage"], "complete")
        self.assertEqual(child_view["warehouse"]["fragrance_id"], "DIY-01")


if __name__ == "__main__":
    unittest.main()
