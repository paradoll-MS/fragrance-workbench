import json
import unittest
from pathlib import Path

from app import config
from app.domain import brief as brief_model
from app.intelligence import parse, targeting
from app.store.db import dumps, insert
from app.workflow.service import Workbench

DB = config.DATA / "test-brief.sqlite3"
SOURCE = (
    "项目名称：贝德美蓝甘菊健发洗发露。产品类型：洗发水。使用人群：儿童。"
    "目标消费者：6-12 岁儿童。建议方向：花香-草本，花香-果香-草本，其他由研发推荐。"
    "蓝甘菊品牌香为主调，具有功效感香氛。无 26 个过敏原。香精添加量：0.4%。"
    "稳定性考察：否，请说明是否有易变色原料。送样数量：每个方向 1-2 款。"
    "所有送样香精必须符合 REACH、IFRA51、《化妆品安全技术规范》2021 版。"
    "闪点高于 61 度。确保推荐的香精不含有邻甲氨基苯甲酸甲酯(DMA)、铃兰醛(LILIAL)。"
    "相关技术文件：IFRA51、82 个过敏原、MSDS、COA。"
)
DIRECTIONS = [
    {"title": "花香-草本", "entry": "recommend_brand",
     "basis": [{"segment_id": "s1", "quote": "花香-草本"}],
     "brief": {"scent_text": "花香-草本，蓝甘菊品牌香为主调，具有功效感香氛",
               "scent_families": ["花香", "草本"], "application_id": "CAT_02",
               "requirements": [{"text": "72H 留香为加分项", "kind": "performance"}]}},
    {"title": "花香-果香-草本", "entry": "recommend_brand",
     "basis": [{"segment_id": "s1", "quote": "花香-果香-草本"}],
     "brief": {"scent_text": "花香-果香-草本，蓝甘菊品牌香为主调",
               "scent_families": ["花香", "果香", "草本"], "application_id": "CAT_02"}},
    {"title": "其他由研发推荐", "entry": "recommend_brand",
     "basis": [{"segment_id": "s1", "quote": "其他由研发推荐"}],
     "brief": {"scent_text": "其他由研发推荐", "application_id": "CAT_02"}},
]
SHARED = {
    "customer": "贝德美", "brand": "贝德美", "markets": ["CN"], "target_audience": "6-12 岁儿童",
    "age_band": "儿童", "substrate": "洗发水", "dosage_text": "0.4%", "application_name": "洗发水",
    "stability_required": False, "stability_note": "稳定性考察：否，请说明是否有易变色原料。",
    "regulatory": ["所有送样香精必须符合 REACH、IFRA51、《化妆品安全技术规范》2021 版",
                   "闪点高于 61 度", "香精配方中不直接添加准用防腐剂、防晒剂及着色剂"],
    "prohibitions": ["邻甲氨基苯甲酸甲酯(DMA)", "铃兰醛(LILIAL)"],
    "certifications": ["IFRA51", "82 个过敏原", "MSDS", "COA"],
    "allergen_scope": ["无 26 个过敏原"], "price_text": "180 元/公斤",
    "quantity_text": "每个方向 1-2 款", "sample_due": "9/17 收到",
}
RAW = {"project_name": "贝德美蓝甘菊", "summary": "儿童洗发水品牌香",
       "shared": SHARED, "directions": DIRECTIONS, "open_questions": []}


class BriefTest(unittest.TestCase):
    def setUp(self):
        if DB.exists():
            DB.unlink()
        self.wb = Workbench(database=DB)

    def tearDown(self):
        if DB.exists():
            DB.unlink()

    def shaped(self):
        return parse.shape(RAW, [{"id": "s1", "locator": "p1", "kind": "text", "text": SOURCE}],
                           self.wb.catalog.categories,
                           [item["id"] for item in self.wb.rules.category_options()])

    def save(self, project, result):
        with self.wb.store.transaction() as db:
            return insert(db, "parse_draft", project_id=project, source_ids="[]",
                          result=dumps(result), model="fixture", seconds=0, status="draft")

    def test_three_directions_survive_with_compliance(self):
        result = self.shaped()
        self.assertEqual(3, len(result["directions"]))
        self.assertEqual(3, len(result["shared"]["regulatory"]))
        self.assertFalse(result["shared"]["stability_required"])
        self.assertIn("易变色", result["shared"]["stability_note"])
        goal_fields = brief_model.merge(result["shared"], result["directions"][0]["brief"],
                                        result["directions"][0]["conditions"].get("application_id"))
        self.assertEqual("6-12 岁儿童", goal_fields["target_audience"])
        self.assertEqual(["CN"], goal_fields["markets"])
        self.assertEqual("花香-草本，蓝甘菊品牌香为主调，具有功效感香氛", goal_fields["scent_text"])
        kinds = {item["kind"] for item in goal_fields["requirements"]}
        self.assertEqual({"regulatory", "performance", "other"}, kinds)
        note = [item for item in goal_fields["requirements"] if "易变色" in item["text"]]
        self.assertEqual("R_EXTRA", note[0]["metric_id"])
        required = dict(result["shared"], stability_required=True, stability_note="需要做稳定性考察")
        strict = brief_model.merge(required, result["directions"][0]["brief"],
                                   result["directions"][0]["conditions"].get("application_id"))
        self.assertIn("Q_STABILITY", {item["metric_id"] for item in strict["requirements"]})

    def test_commit_keeps_every_direction_and_inherits_shared(self):
        project = self.wb.create_project("蓝甘菊", "customer", "贝德美")
        self.wb.add_source(project, "需求.txt", text=SOURCE)
        draft_id = self.save(project, self.shaped())
        committed = self.wb.confirm_draft(project, draft_id)
        self.assertEqual(3, len(committed["directions"]))
        self.assertEqual(3, len({item["subproject_id"] for item in committed["directions"]}))
        for item in committed["directions"]:
            with self.wb.store.connect() as db:
                goal = dict(db.execute("SELECT * FROM goal WHERE id=?", (item["goal_id"],)).fetchone())
            fields = json.loads(goal["fields"])
            self.assertEqual("6-12 岁儿童", fields["target_audience"])
            self.assertEqual("recommend_brand", fields["mode"])
            self.assertEqual(["CN"], fields["markets"])
            self.assertTrue(fields["requirements"])
            self.assertIn("regulatory", {row["kind"] for row in fields["requirements"]})
            self.assertIn("易变色", " ".join(row["text"] for row in fields["requirements"]))

    def test_tagging_returns_grounded_c_tags_and_survives_failure(self):
        result = self.shaped()
        fields = brief_model.merge(result["shared"], result["directions"][0]["brief"],
                                   result["directions"][0]["conditions"].get("application_id"))
        candidates = self.wb.catalog.c_candidates("CAT_02")
        self.assertTrue(candidates)
        chosen = candidates[0]
        basis = "蓝甘菊品牌香为主调"

        def fake(model, messages, limit, timeout=40):
            return {"c_ids": [chosen["c_id"]],
                    "items": [{"c_id": chosen["c_id"], "basis": basis, "confidence": 0.8}],
                    "used_conditions": ["target_audience:6-12 岁儿童"], "unmapped": []}

        original = targeting.json_object
        targeting.json_object = fake
        try:
            tagged = targeting.tag_direction(fields, "recommend_brand", self.wb.catalog, self.wb.config)
        finally:
            targeting.json_object = original
        self.assertEqual([chosen["c_id"]], tagged["c_ids"])
        self.assertEqual("preference", tagged["groups"][0]["role"])
        self.assertEqual(["target_audience:6-12 岁儿童"], tagged["used_conditions"])

        def broken(model, messages, limit, timeout=40):
            raise targeting.ModelError("timeout")

        targeting.json_object = broken
        try:
            fallback = targeting.tag_direction(fields, "recommend_brand", self.wb.catalog, self.wb.config)
        finally:
            targeting.json_object = original
        self.assertTrue(fallback["unmapped"])
        self.assertIn("标签模型不可用", fallback["unmapped"][0])

    def test_search_uses_goal_targeting(self):
        project = self.wb.create_project("蓝甘菊", "customer", "贝德美")
        self.wb.add_source(project, "需求.txt", text=SOURCE)
        draft_id = self.save(project, self.shaped())
        goal_id = self.wb.confirm_draft(project, draft_id)["directions"][0]["goal_id"]
        candidates = self.wb.catalog.c_candidates("CAT_02")
        used = {tag for asset in self.wb.catalog.asset_rows({}, {}, self.wb.catalog.products_by_code())
                for tag in asset["card"]["tags"]}
        chosen = next(item for item in candidates if item["c_id"] in used)

        def fake(model, messages, limit, timeout=40):
            return {"c_ids": [chosen["c_id"]],
                    "items": [{"c_id": chosen["c_id"], "basis": "蓝甘菊品牌香为主调", "confidence": 0.8}],
                    "used_conditions": [], "unmapped": []}

        original = targeting.json_object
        targeting.json_object = fake
        try:
            found = self.wb.search({}, goal_id=goal_id, limit=5)
        finally:
            targeting.json_object = original
        self.assertEqual([chosen["c_id"]], found["query"]["groups"][0]["tags"])
        self.assertIn("CAT_02", found["query"]["categories"])
        self.assertTrue(found["results"])



