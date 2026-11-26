import unittest

from app.domain import enums
from app.domain.normalize import canon, clean, normalize_conditions, normalize_direction, number, price_value
from app.domain.models import endpoint_for


class NormalizeTest(unittest.TestCase):
    def test_canon_ignores_case_and_spaces(self):
        self.assertEqual(canon(" COCO  小姐 "), "coco小姐")

    def test_number_rejects_prose(self):
        self.assertIsNone(number("约三五款"))
        self.assertEqual(number("5"), 5)
        self.assertEqual(number("12"), 12)

    def test_price_keeps_decimal(self):
        self.assertEqual(str(price_value("180.5")), "180.5")
        self.assertIsNone(price_value("面议"))

    def test_price_rule_recognised(self):
        conditions, questions = normalize_conditions(
            {"price_text": "300 以内", "count_min": 2, "count_max": 3, "markets": ["中国"]},
            ["CAT_01"], ["hair_rinse_off"])
        self.assertEqual(conditions.get("price_max"), "300")
        self.assertEqual(conditions.get("count_min"), 2)
        self.assertEqual(questions, [])

    def test_unknown_category_dropped_with_question(self):
        conditions, questions = normalize_conditions({"review_category_id": "不存在"}, ["CAT_01"], ["hair_rinse_off"])
        self.assertNotIn("review_category_id", conditions)
        self.assertTrue(any("审查品类" in item for item in questions))

    def test_direction_requires_title(self):
        direction, questions = normalize_direction({"title": "  "}, [], ["CAT_01"], [], enums.ENTRY_LABELS)
        self.assertIsNone(direction)
        self.assertEqual(questions, [])

    def test_basis_must_be_verbatim(self):
        segments = [{"id": "1:1", "locator": "第 1 段", "text": "客户要白茶木质，300 以内"}]
        direction, questions = normalize_direction({
            "title": "白茶木质", "entry": "recommend_simple",
            "basis": [{"segment_id": "1:1", "quote": "白茶木质，300 以内"}],
        }, segments, ["CAT_01"], [], enums.ENTRY_LABELS)
        self.assertEqual(len(direction["basis"]), 1)
        self.assertEqual(questions, [])

        direction, questions = normalize_direction({
            "title": "白茶木质", "entry": "recommend_simple",
            "basis": [{"segment_id": "1:1", "quote": "完全不相干的话"}],
        }, segments, ["CAT_01"], [], enums.ENTRY_LABELS)
        self.assertEqual(direction["basis"], [])
        self.assertTrue(questions)

    def test_clean_trims_and_limits(self):
        self.assertEqual(clean("  a  ", 3), "a")
        self.assertEqual(len(clean("x" * 50, 10)), 10)


class RoutingTest(unittest.TestCase):
    def test_entry_strategies(self):
        self.assertIn("duplicate", enums.ENTRY_STRATEGIES["with_sample"])
        self.assertNotIn("create", enums.ENTRY_STRATEGIES["find_product"])

    def test_endpoint_by_kind(self):
        self.assertEqual(endpoint_for("customer", "recommend_simple"), "shipment")
        self.assertEqual(endpoint_for("invent", "invent"), "warehouse")
        self.assertEqual(endpoint_for("customer", "with_sample", parent_id=7), "warehouse_return")


if __name__ == "__main__":
    unittest.main()


