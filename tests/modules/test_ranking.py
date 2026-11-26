import unittest

from app import config
from app.recommendation import ranking
from app.assets.catalog import Catalog


class TextQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.scoring = config.scoring()

    def parse(self, text):
        return ranking.parse_text(text, self.catalog, self.scoring)

    def test_scent_and_category_and_price(self):
        query = self.parse("白茶木质 300 以内 洗发水")
        self.assertEqual(query["categories"], ["CAT_03"])
        self.assertEqual(query["max_price"], "300")
        self.assertEqual(query["mode"], "recommend_simple")
        names = [self.catalog.terms[group["tags"][0]]["name"] for group in query["groups"]]
        self.assertIn("白茶", names)
        self.assertIn("木质", names)

    def test_c_price_range(self):
        query = self.parse("参考 200 左右")
        self.assertEqual(query["target_price"], "200")

    def test_edition_marks_find_product(self):
        query = self.parse("香奈儿 COCO Mademoiselle EDP")
        self.assertTrue(query.get("exact"))
        self.assertTrue(query.get("product_id"))
        self.assertEqual(query["edition"], "EDP")

    def test_brand_only_query(self):
        query = self.parse("祖玛珑 风格 洗衣液")
        self.assertEqual(query["mode"], "recommend_brand")
        self.assertIn("CAT_07", query["categories"])

    def test_duplicate_words(self):
        query = self.parse("客户同款，仿这个白茶")
        self.assertEqual(query["mode"], "with_sample")

    def test_unknown_text_still_returns_query(self):
        query = self.parse("随便看看")
        self.assertEqual(query["mode"], "recommend_simple")
        self.assertEqual(query["groups"], [])


class RankingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.scoring = config.scoring()
        cls.labels = cls.catalog.products_by_code()

    def run_query(self, text):
        parsed = ranking.parse_text(text, self.catalog, self.scoring)
        query = ranking.normalize_query(parsed, self.catalog.terms, self.catalog.categories, self.scoring)
        rows = list(self.catalog.asset_rows({}, {}, self.labels))
        return query, ranking.rank(query, rows, self.catalog.terms, self.catalog.categories,
                                   self.catalog.edges, self.scoring)

    def test_price_cap_respected(self):
        query, result = self.run_query("白茶 200 以内")
        cap = float(query["max_price"])
        for card in result["results"]:
            if card["price"] is not None:
                self.assertLessEqual(float(card["price"]), cap)

    def test_scores_are_sorted(self):
        _, result = self.run_query("柑橘 洗发水")
        scores = [card["score"] for card in result["results"] if card["score"] is not None]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_exact_hit_for_product(self):
        query, result = self.run_query("香奈儿 COCO Mademoiselle EDP")
        self.assertTrue(query.get("exact"))
        self.assertTrue(query.get("product_id"))
        self.assertEqual(query["mode"], "recommend_simple")

    def test_hard_constraint_goes_to_alternatives(self):
        query = ranking.normalize_query(
            {"mode": "recommend_simple", "categories": ["CAT_03"],
             "groups": [{"role": "required", "op": "ANY", "tags": []}]},
            self.catalog.terms, self.catalog.categories, self.scoring)
        self.assertEqual(query["groups"], [])


if __name__ == "__main__":
    unittest.main()

