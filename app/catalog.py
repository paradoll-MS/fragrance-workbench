import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from .paths import APP_ROOT as ROOT, resource_path
from .recommendation import comparable_price


ABC = resource_path("ABC")
CONFIG = json.loads((ROOT / "scoring.json").read_text(encoding="utf-8"))


def read_jsonl(path):
    if path.exists():
        with path.open(encoding="utf-8-sig") as source:
            return [json.loads(line) for line in source if line.strip()]
    return []


def canon(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())


class Catalog:
    def __init__(self, abc=ABC):
        self.data_path = abc / "output"
        self.terms = {}
        self.aliases = defaultdict(set)
        self.edges = {}
        book_path = abc / "品类与ABC标签体系_V2.xlsx"
        book = load_workbook(book_path, read_only=True, data_only=True)
        try:
            self.categories = {key: name for key, name, *_ in
                               list(book["应用品类"].values)[1:] if key and name}
            codes = {label: key for key, label in self.categories.items()}
            for tab in ("A标签", "B标签"):
                for key, level, name, *_ in list(book[tab].values)[1:]:
                    if key and name:
                        self.terms[key] = {"id": key, "level": level if tab == "A标签" else "B", "name": name}
                        self.aliases[canon(name)].add(key)
            for key, category, _, parent, name, kind, path, *_ in list(book["C标签树"].values)[1:]:
                if key and category in codes and name:
                    self.terms[key] = {"id": key, "level": "C", "name": name, "category": codes[category],
                                       "path": path, "parent": parent, "selectable": kind == "叶子"}
            for alias, key, *_ in list(book["AB别名"].values)[1:]:
                if alias and key in self.terms:
                    self.aliases[canon(alias)].add(key)
            for row in list(book["C到AB关联映射"].values)[1:]:
                if row[0] not in self.terms:
                    continue
                self.edges[row[0]] = {tag.strip() for i in (4, 6, 8, 10)
                                      for tag in re.split(r"[;；]", str(row[i] or ""))
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
        self.brands = {b["brand_id"]: b for b in read_jsonl(self.data_path / "brand.jsonl")}
        self.products = {p["product_id"]: p for p in read_jsonl(self.data_path / "product.jsonl")}

    def products_by_code(self):
        products = defaultdict(dict)
        has_curated_suggestions = (self.data_path / "suggested_dupe_tags.jsonl").is_file()
        for filename in ("fragrance_product.jsonl", "suggested_dupe_tags.jsonl", "confirmed_product_relations.jsonl"):
            for row in read_jsonl(self.data_path / filename):
                pid = row.get("product_id")
                code = row.get("fragrance_id")
                if pid not in self.products or code not in self.raw:
                    continue
                source_row = row.get("source_row")
                source = self.raw[code]
                if source_row is not None and source_row not in (source.get("source_rows") or [source.get("source_row")]):
                    continue
                status = "unverified"
                if filename == "suggested_dupe_tags.jsonl" or (
                    not has_curated_suggestions and row.get("relation_status") == "strong_candidate"
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
        return products

    def asset_rows(self, changes, quotes, product_labels=None):
        if product_labels is None:
            product_labels = self.products_by_code()
        for key, row in self.raw.items():
            overlay = changes.get(key, {})
            name = overlay.get("name", row["fragrance_name"])
            category_ids = overlay.get("categories", row["category_ids"])
            categories = set(category_ids) & set(self.categories)
            historic = (set(row.get("category_candidates") or []) & set(self.categories))
            historic -= set(row.get("category_ids", [])) - categories
            if "tags" in overlay:
                tag_ids = overlay["tags"]
            else:
                tag_ids = [t for k in ("A1", "A2", "A3", "B") for t in row.get("tags_" + k, [])]
                tag_ids += [t for tags in row["tags_C_by_category"].values() for t in tags]
            ab = set()
            c = defaultdict(set)
            for tag in tag_ids:
                info = self.terms.get(tag)
                if not info or not info.get("selectable", True):
                    continue
                if info["level"] != "C":
                    ab.add(tag)
                elif info["category"] in categories | historic:
                    c[info["category"]].add(tag)
            base_products = list(product_labels[key].values())
            if "product_ids" in overlay:
                visible = set(overlay["product_ids"])
                products = [p for p in base_products if p["product_id"] in visible]
                for pid in visible - {p["product_id"] for p in products}:
                    item = self.products[pid]
                    products.append({"product_id": pid, "name": item["product_name"], "brand_id": item["brand_id"],
                                     "edition": None, "status": "manual"})
            else:
                products = base_products
            live = quotes.get(row["fragrance_id"])
            raw_price = live if live is not None else row.get("system_quote")
            price = comparable_price(raw_price)
            card = {"key": key, "fragrance_id": row["fragrance_id"], "name": name,
                    "price": str(price) if price is not None else None,
                    "raw_price": raw_price, "price_source": "mock" if live is not None else "catalog",
                    "categories": sorted(categories), "historical_categories": sorted(historic - categories),
                    "tags": sorted(ab | set().union(*c.values())),
                    "products": products, "is_new": bool(row["is_new"]), "is_hot": bool(row["is_hot"]),
                    "manual": bool(overlay)}
            yield {"conflict": bool(row.get("conflict")), "categories": categories,
                   "searchable_categories": categories | historic, "ab": ab, "c": c, "products": products,
                   "exact_products": base_products,
                   "fragrance_id": row["fragrance_id"], "price": price, "is_new": card["is_new"],
                   "is_hot": card["is_hot"], "card": card}

