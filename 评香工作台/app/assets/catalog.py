"""Read-only ABC assets: categories, tag dictionary, fragrances, brands, products, relations."""

import hashlib
import json
import re
from collections import defaultdict

from openpyxl import load_workbook

from .. import config
from ..domain.normalize import canon, price_value


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


class Catalog:
    def __init__(self, abc=None):
        self.root = abc or config.ABC_ROOT
        self.data_path = self.root / "output"
        self.terms = {}
        self.aliases = defaultdict(set)
        self.edges = {}
        book_path = self.root / "品类与ABC标签体系_V2.xlsx"
        book = load_workbook(book_path, read_only=True, data_only=True)
        try:
            self.categories = {key: name for key, name, *_ in list(book["应用品类"].values)[1:] if key and name}
            codes = {label: key for key, label in self.categories.items()}
            for tab in ("A标签", "B标签"):
                for key, level, name, *_ in list(book[tab].values)[1:]:
                    if key and name:
                        self.terms[key] = {"id": key, "level": level if tab == "A标签" else "B", "name": name}
                        self.aliases[canon(name)].add(key)
            for key, category, dimension, parent, name, kind, path, *_ in list(book["C标签树"].values)[1:]:
                if key and category in codes and name:
                    self.terms[key] = {"id": key, "level": "C", "name": name, "category": codes[category],
                                       "path": path, "parent": parent, "node_type": kind,
                                       "dimension": str(dimension or ""),
                                       "selectable": kind == "叶子"}
            self.llm_rules = []
            if "LLM判断规则" in book.sheetnames:
                for row in list(book["LLM判断规则"].values)[1:]:
                    if row and len(row) > 1 and str(row[1] or "").strip():
                        self.llm_rules.append(str(row[1]).strip())
            self.c_guidance = {}
            if "C左侧判定补充" in book.sheetnames:
                for row in list(book["C左侧判定补充"].values)[1:]:
                    if row and row[0] in self.terms:
                        self.c_guidance[row[0]] = {"path": str(row[2] or ""),
                                                   "type": str(row[3] or ""),
                                                   "text": str(row[4] or "")}
            for alias, key, *_ in list(book["AB别名"].values)[1:]:
                if alias and key in self.terms:
                    self.aliases[canon(alias)].add(key)
            for row in list(book["C到AB关联映射"].values)[1:]:
                if row[0] not in self.terms:
                    continue
                self.edges[row[0]] = {tag.strip() for index in (4, 6, 8, 10)
                                      for tag in re.split(r"[;；]", str(row[index] or ""))
                                      if tag.strip() in self.terms}
        finally:
            book.close()
        self.dictionary_version = hashlib.sha256(book_path.read_bytes()).hexdigest()[:12]
        catalog_file = self.data_path / "fragrance.jsonl"
        self.version = hashlib.sha256(catalog_file.read_bytes()).hexdigest()[:12]
        self.raw = {}
        for row in read_jsonl(catalog_file):
            key = row["fragrance_id"]
            if row.get("conflict"):
                key += "#" + str(row["source_row"])
            if key in self.raw:
                raise ValueError("重复的目录资产 " + key)
            self.raw[key] = row
        self.brands = {item["brand_id"]: item for item in read_jsonl(self.data_path / "brand.jsonl")}
        self.products = {item["product_id"]: item for item in read_jsonl(self.data_path / "product.jsonl")}
        self._product_index = None

    def c_candidates(self, category_id):
        """Leaf C nodes of one application category, each with its left-side guidance."""
        items = []
        for key, term in self.terms.items():
            if term.get("level") != "C" or not term.get("selectable"):
                continue
            if category_id and term.get("category") != category_id:
                continue
            guidance = self.c_guidance.get(key, {})
            items.append({"c_id": key, "name": term["name"], "path": term.get("path", term["name"]),
                          "dimension": term.get("dimension", ""), "guidance": guidance.get("text", ""),
                          "ab_terms": sorted(self.terms[tag]["name"] for tag in self.edges.get(key, set())
                                             if tag in self.terms)})
        return items

    def products_by_code(self):
        if self._product_index is not None:
            return self._product_index
        products = defaultdict(dict)
        curated = (self.data_path / "suggested_dupe_tags.jsonl").is_file()
        for filename in ("fragrance_product.jsonl", "suggested_dupe_tags.jsonl", "confirmed_product_relations.jsonl"):
            for row in read_jsonl(self.data_path / filename):
                pid, code = row.get("product_id"), row.get("fragrance_id")
                if pid not in self.products or code not in self.raw:
                    continue
                source = self.raw[code]
                source_row = row.get("source_row")
                if source_row is not None and source_row not in (source.get("source_rows") or [source.get("source_row")]):
                    continue
                status = "unverified"
                if filename == "suggested_dupe_tags.jsonl" or (
                    not curated and row.get("relation_status") == "strong_candidate"
                ):
                    status = "suggested"
                if filename == "confirmed_product_relations.jsonl" and row.get("relation_status") == "confirmed":
                    status = "confirmed"
                item = self.products[pid]
                key = (pid, row.get("edition"))
                name = row.get("product_name") if filename == "suggested_dupe_tags.jsonl" else item["product_name"]
                existing = products[code].get(key)
                if existing and existing["status"] == "suggested" and status == "unverified":
                    continue
                products[code][key] = {"product_id": pid, "name": name or item["product_name"],
                                       "brand_id": item["brand_id"], "edition": row.get("edition"),
                                       "status": status}
        self._product_index = products
        return products

    def asset_rows(self, asset_edits, quotes, product_labels=None):
        if product_labels is None:
            product_labels = self.products_by_code()
        for key, row in self.raw.items():
            overlay = asset_edits.get(key, {})
            name = overlay.get("name", row["fragrance_name"])
            category_ids = overlay.get("categories", row["category_ids"])
            categories = set(category_ids) & set(self.categories)
            historic = set(row.get("category_candidates") or []) & set(self.categories)
            historic -= set(row.get("category_ids", [])) - categories
            if "tags" in overlay:
                tag_ids = overlay["tags"]
            else:
                tag_ids = [tag for level in ("A1", "A2", "A3", "B") for tag in row.get("tags_" + level, [])]
                tag_ids += [tag for tags in row["tags_C_by_category"].values() for tag in tags]
            ab, grouped = set(), defaultdict(set)
            for tag in tag_ids:
                info = self.terms.get(tag)
                if not info or not info.get("selectable", True):
                    continue
                if info["level"] != "C":
                    ab.add(tag)
                elif info["category"] in categories | historic:
                    grouped[info["category"]].add(tag)
            base_products = list(product_labels[key].values())
            if "product_ids" in overlay:
                visible = set(overlay["product_ids"])
                products = [item for item in base_products if item["product_id"] in visible]
                for pid in visible - {item["product_id"] for item in products}:
                    item = self.products[pid]
                    products.append({"product_id": pid, "name": item["product_name"], "brand_id": item["brand_id"],
                                     "edition": None, "status": "manual"})
            else:
                products = base_products
            live = quotes.get(row["fragrance_id"])
            raw_price = live if live is not None else row.get("system_quote")
            price = price_value(raw_price)
            card = {"key": key, "fragrance_id": row["fragrance_id"], "name": name,
                    "price": str(price) if price is not None else None,
                    "raw_price": raw_price, "price_source": "mock" if live is not None else "catalog",
                    "categories": sorted(categories), "historical_categories": sorted(historic - categories),
                    "tags": sorted(ab | set().union(*grouped.values()) if grouped else ab),
                    "products": products, "is_new": bool(row["is_new"]), "is_hot": bool(row["is_hot"]),
                    "manual": bool(overlay)}
            yield {"conflict": bool(row.get("conflict")), "categories": categories,
                   "searchable_categories": categories | historic, "ab": ab, "c": grouped,
                   "products": products, "exact_products": base_products,
                   "fragrance_id": row["fragrance_id"], "price": price, "is_new": card["is_new"],
                   "is_hot": card["is_hot"], "card": card}
