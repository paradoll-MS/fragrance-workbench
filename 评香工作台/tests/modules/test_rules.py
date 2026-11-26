import unittest

from app.assets.rules import ReviewRules, group_by_department
from app.domain.models import CheckContext


def context(**overrides):
    base = dict(fragrance_id="1040", formula_version="CATALOG-1040", scope="shipment",
                review_category="hair_rinse_off", markets=("CN",), substrate="洗发水",
                dose_text="", end_product="", customer_requirements=())
    base.update(overrides)
    return CheckContext(**base)


class RulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = ReviewRules()

    def test_category_generates_metrics(self):
        requirements, coverage = self.rules.build(context())
        metric_ids = {item.metric_id for item in requirements}
        self.assertIn("R_IFRA", metric_ids)
        self.assertIn("R_MARKET", metric_ids)
        self.assertGreaterEqual(len(requirements), 8)
        self.assertTrue(any(item["code"] == "review_category" for item in coverage))

    def test_no_category_keeps_generic_only(self):
        requirements, coverage = self.rules.build(context(review_category=""))
        metric_ids = {item.metric_id for item in requirements}
        self.assertIn("R_IFRA", metric_ids)
        self.assertNotIn("P1", metric_ids)
        self.assertTrue(any(item["code"] == "review_category_missing" for item in coverage))

    def test_market_becomes_blocked_requirement(self):
        requirements, _ = self.rules.build(context())
        market = [item for item in requirements if item.metric_id == "R_MARKET"][0]
        self.assertEqual(market.deferral, "blocked")
        self.assertIn("中国大陆", market.subitem)
        self.assertEqual(market.conditions.get("market"), "CN")

    def test_missing_market_is_reported_not_blocked(self):
        requirements, coverage = self.rules.build(context(markets=()))
        self.assertFalse([item for item in requirements if item.metric_id == "R_MARKET"])
        self.assertTrue(any(item["code"] == "market_missing" for item in coverage))

    def test_unknown_market_reported(self):
        _, coverage = self.rules.build(context(markets=("XX",)))
        self.assertTrue(any(item["code"] == "market_unknown" for item in coverage))

    def test_customer_requirement_kept_verbatim(self):
        requirements, _ = self.rules.build(context(customer_requirements=({"text": "不得含麝香"},)))
        extra = [item for item in requirements if item.metric_id == "R_EXTRA"]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0].source, "customer")
        self.assertEqual(extra[0].origin_text, "不得含麝香")
        self.assertEqual(extra[0].deferral, "blocked")

    def test_conditional_needs_trigger(self):
        requirements, _ = self.rules.build(context())
        self.assertFalse([item for item in requirements if item.metric_id == "Q_FLASH"])
        requirements, _ = self.rules.build(context(customer_requirements=({"text": "需要液体运输闪点报告"},)))
        self.assertTrue([item for item in requirements if item.metric_id == "Q_FLASH"])

    def test_conditions_fingerprint_differs_by_market(self):
        china, _ = self.rules.build(context(markets=("CN",)))
        japan, _ = self.rules.build(context(markets=("US",)))
        china_market = [item for item in china if item.metric_id == "R_MARKET"][0]
        japan_market = [item for item in japan if item.metric_id == "R_MARKET"][0]
        self.assertNotEqual(china_market.conditions_key, japan_market.conditions_key)

    def test_group_by_department(self):
        requirements, _ = self.rules.build(context())
        groups = group_by_department(requirements)
        self.assertTrue(all(key in ("compliance", "quality", "application") for key in groups))
        self.assertEqual(sum(len(items) for items in groups.values()), len(requirements))

    def test_infer_category_from_substrate(self):
        self.assertEqual(self.rules.infer_category("洗发水"), "hair_rinse_off")
        self.assertEqual(self.rules.infer_category(""), "")

    def test_metric_dictionary_is_complete(self):
        for metric_id, item in self.rules.metrics.items():
            self.assertIn(item["department"], ("compliance", "quality", "application"), metric_id)


if __name__ == "__main__":
    unittest.main()

