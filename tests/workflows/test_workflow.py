import unittest
from pathlib import Path

from app import config
from app.store.db import loads, rows
from app.workflow import views
from app.workflow.service import Workbench

DB = config.DATA / "test-workflow.sqlite3"


def fresh():
    if DB.exists():
        DB.unlink()
    return Workbench(database=DB)


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb = fresh()

    @classmethod
    def tearDownClass(cls):
        if DB.exists():
            DB.unlink()

    def setUp(self):
        self.wb = fresh()
        self.project = self.wb.create_project("测试项目", "customer", "某日化")
        self.wb.add_source(self.project, "需求.txt", text="给洗发水推荐白茶木质，300 以内，中国市场")
        draft_id, _ = self.wb.manual_draft(self.project, [{
            "title": "洗发水白茶木质", "entry": "recommend_simple",
            "conditions": {"markets": ["中国"], "substrate": "洗发水", "price_text": "300 以内"},
        }])
        committed = self.wb.confirm_draft(self.project, draft_id)
        self.goal = committed["directions"][0]["goal_id"]

    def pending(self, kind):
        with self.wb.store.connect() as db:
            return rows(db, "SELECT * FROM task WHERE task_type=? AND status IN ('sent','queued') ORDER BY id",
                        (kind,))

    def pass_all(self, kind):
        for task in self.pending(kind):
            self.wb.apply_receipt(task["id"], True, {"note": "通过"})

    def slot(self, slot_id):
        with self.wb.store.connect() as db:
            return dict(db.execute("SELECT * FROM slot WHERE id=?", (slot_id,)).fetchone())

    def test_select_then_ship_completes_project(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks",
                        {"review_category": "hair_rinse_off", "markets": ["CN"]})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        self.pass_all("check")
        result = self.wb.advance(self.project, slot_id, "release_formal", {"note": "全项通过"})
        self.assertFalse(result["blocked"])
        self.wb.advance(self.project, slot_id, "prepare_sample", {"form": "10 ml", "quantity": "10", "unit": "ml"})
        self.wb.advance(self.project, slot_id, "dispatch_shipment", {})
        self.pass_all("shipment")
        view = views.project_view(self.wb, self.project)
        self.assertEqual(view["project"]["status"], "completed")
        slots = [slot for sub in view["subprojects"] for round_item in sub["rounds"]
                 for goal in round_item["goals"] for slot in goal["slots"]]
        self.assertEqual(slots[0]["stage"], "complete")
        self.assertEqual(len(slots[0]["shipments"]), 1)

    def test_release_without_check_set_is_blocked_with_issue(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        result = self.wb.advance(self.project, plan["slot_id"], "release_formal", {})
        self.assertTrue(result["blocked"])
        self.assertEqual(result["issues"][0]["code"], "check_context_missing")
        with self.wb.store.connect() as db:
            open_issues = rows(db, "SELECT * FROM issue WHERE scope_id=? AND state='open'", (plan["slot_id"],))
        self.assertEqual(len(open_issues), 1)

    def test_blocked_issue_clears_after_fix(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        blocked = self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertTrue(blocked["blocked"])
        self.assertIn("check_context_missing", self.open_codes(slot_id))
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        self.pass_all("check")
        self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertEqual(self.open_codes(slot_id), [])

    def test_action_outside_stage_is_rejected(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        with self.assertRaises(ValueError) as caught:
            self.wb.advance(self.project, plan["slot_id"], "dispatch_shipment", {})
        self.assertIn("当前阶段不能执行该动作", str(caught.exception))

    def test_initial_can_defer_but_formal_cannot(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        tasks = self.pending("check")
        compliance = [task for task in tasks if task["department"] == "compliance"]
        self.assertTrue(compliance)
        for task in compliance:
            self.wb.apply_receipt(task["id"], True, {})
        initial = self.wb.advance(self.project, slot_id, "release_initial", {"note": "先寄样，细项后补"})
        self.assertFalse(initial["blocked"], initial.get("issues"))
        self.wb.advance(self.project, slot_id, "prepare_sample", {"form": "10 ml", "quantity": "10", "unit": "ml"})
        self.wb.advance(self.project, slot_id, "dispatch_shipment", {})
        self.pass_all("shipment")
        self.assertEqual(self.slot(slot_id)["stage"], "checking")
        formal = self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertTrue(formal["blocked"])
        self.assertEqual(formal["issues"][0]["code"], "check_failed")

    def test_initial_requires_note_when_deferring(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        for task in self.pending("check"):
            if task["department"] == "compliance":
                self.wb.apply_receipt(task["id"], True, {})
        with self.assertRaises(ValueError):
            self.wb.advance(self.project, slot_id, "release_initial", {})

    def test_revision_conflict(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        self.wb.advance(self.project, plan["slot_id"], "build_checks", {"review_category": "hair_rinse_off"})
        with self.assertRaises(ValueError):
            self.wb.advance(self.project, plan["slot_id"], "dispatch_checks", {}, revision=1)

    def test_evidence_reused_for_new_check_set(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        self.pass_all("check")
        notice = self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.assertIn("既有证据", notice["notice"])
        view = views.project_view(self.wb, self.project)
        slot_view = [slot for sub in view["subprojects"] for round_item in sub["rounds"]
                     for goal in round_item["goals"] for slot in goal["slots"]][0]
        self.assertEqual(slot_view["checks"]["counts"].get("passed"), slot_view["checks"]["total"])

    def test_failed_requirement_blocks_release(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        for task in self.pending("check"):
            if task["department"] == "compliance":
                self.wb.apply_receipt(task["id"], False, {"note": "缺 IFRA 证书"})
        result = self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertTrue(result["blocked"])
        self.assertEqual(result["issues"][0]["code"], "check_failed")

    def test_duplicate_needs_sample_reference(self):
        with self.assertRaises(ValueError):
            self.wb.plan(self.project, self.goal, "duplicate", {})

    def test_development_returns_to_parent(self):
        with self.wb.store.connect() as db:
            db.execute("UPDATE subproject SET requirement_type='with_sample' WHERE id=?", (self.goal,))
        second_draft, _ = self.wb.manual_draft(self.project, [{
            "title": "对标样复刻", "entry": "with_sample",
            "conditions": {"markets": ["中国"], "sample_reference": "S-77", "substrate": "洗发水"},
        }])
        committed = self.wb.confirm_draft(self.project, second_draft)
        goal = committed["directions"][0]["goal_id"]
        plan = self.wb.plan(self.project, goal, "duplicate", {"sample_reference": "S-77"})
        child_slot = plan["child_slot_id"]
        self.pass_all("analysis")
        self.pass_all("perfumery")
        self.wb.advance(self.project, child_slot, "accept_trial", {"note": "可以"})
        self.wb.advance(self.project, child_slot, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, child_slot, "dispatch_checks", {})
        self.pass_all("check")
        self.wb.advance(self.project, child_slot, "release_warehouse", {})
        self.wb.advance(self.project, child_slot, "dispatch_warehouse", {})
        self.pass_all("warehouse")
        self.wb.advance(self.project, child_slot, "accept_warehouse", {"fragrance_id": "DIY-01", "formula_version": "V1"})
        parent = self.slot(plan["slot_id"])
        self.assertEqual(parent["fragrance_id"], "DIY-01")
        self.assertEqual(parent["stage"], "checking")
        view = views.project_view(self.wb, self.project)
        parent_view = [slot for sub in view["subprojects"] for round_item in sub["rounds"]
                       for goal in round_item["goals"] for slot in goal["slots"]
                       if slot["id"] == plan["slot_id"]][0]
        actions = {item["action"]: item["enabled"] for item in parent_view["actions"]}
        self.assertTrue(actions.get("build_checks"))
        self.assertNotIn("accept_trial", actions)

    def test_receipt_applied_once(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        self.wb.advance(self.project, plan["slot_id"], "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, plan["slot_id"], "dispatch_checks", {})
        task = self.pending("check")[0]
        self.wb.apply_receipt(task["id"], True, {})
        with self.assertRaises(ValueError):
            self.wb.apply_receipt(task["id"], True, {})

    def test_pause_and_resume(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        paused = self.wb.advance(self.project, slot_id, "pause", {"note": "等客户回复"})
        self.assertFalse(paused["blocked"])
        slot = self.slot(slot_id)
        self.assertTrue(loads(slot["payload"], {}).get("paused"))
        resumed = self.wb.advance(self.project, slot_id, "resume", {})
        self.assertFalse(resumed["blocked"])
        self.assertFalse(loads(self.slot(slot_id)["payload"], {}).get("paused"))

    def open_codes(self, slot_id):
        with self.wb.store.connect() as db:
            return [item["code"] for item in rows(db, "SELECT * FROM issue WHERE scope_type='slot' "
                                                       "AND scope_id=? AND state='open'", (slot_id,))]

    def test_issue_recovers_when_prerequisite_arrives(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        self.pass_all("check")
        self.wb.advance(self.project, slot_id, "release_formal", {})
        blocked = self.wb.advance(self.project, slot_id, "dispatch_shipment", {})
        self.assertTrue(blocked["blocked"])
        self.assertIn("sample_unavailable", self.open_codes(slot_id))
        self.wb.advance(self.project, slot_id, "prepare_sample",
                        {"form": "10 ml", "quantity": "10", "unit": "ml"})
        self.assertEqual(self.open_codes(slot_id), [])

    def test_issue_recovers_after_receipt(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "build_checks", {"review_category": "hair_rinse_off"})
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        blocked = self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertTrue(blocked["blocked"])
        self.assertIn("check_failed", self.open_codes(slot_id))
        self.pass_all("check")
        self.assertEqual(self.open_codes(slot_id), [])

    def test_issue_stays_until_cause_is_gone(self):
        plan = self.wb.plan(self.project, self.goal, "select", {"asset_key": "1040"})
        slot_id = plan["slot_id"]
        self.wb.advance(self.project, slot_id, "release_formal", {})
        self.assertIn("check_context_missing", self.open_codes(slot_id))
        self.wb.advance(self.project, slot_id, "dispatch_checks", {})
        self.assertIn("check_context_missing", self.open_codes(slot_id))


if __name__ == "__main__":
    unittest.main()
