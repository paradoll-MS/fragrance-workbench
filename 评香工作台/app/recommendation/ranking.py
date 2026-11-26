"""Pure ranking: normalise a query, filter candidates, score A/B/C and sort."""

import re
from collections import defaultdict
from decimal import Decimal

from ..domain.normalize import price_value as comparable_price

LEVELS = ("A1", "A2", "A3", "B", "C")
ROLES = ("preference", "required", "avoid")
LOWER_PRIORITY = {"mild": 0, "normal": 1, "strong": 2}

# 口语到应用品类的映射，只用于从自由文字里猜品类。
CATEGORY_WORDS = {
    "个人香氛": ("香水", "香氛", "淡香精", "古龙", "身体香氛", "perfume", "parfum", "cologne"),
    "身体洗护": ("沐浴", "沐浴露", "洗手液", "身体乳", "润肤", "浴盐", "body wash", "shower"),
    "头发洗护": ("洗发", "洗发水", "洗发露", "护发素", "发膜", "护发", "头皮", "shampoo", "conditioner"),
    "面部洗护": ("洗面", "洁面", "面霜", "护肤", "精华", "面膜", "facial", "face care"),
    "口腔护理（含唇部）": ("牙膏", "漱口", "口腔", "唇膏", "口红", "toothpaste", "lip balm"),
    "空间香氛": ("扩香", "香薰", "蜡烛", "空气清新", "线香", "藤条", "diffuser", "candle"),
    "织物护理": ("洗衣", "洗衣液", "柔顺", "留香珠", "织物", "洗涤", "laundry", "fabric"),
    "硬面清洁": ("清洁剂", "厨房", "卫浴", "硬表面", "cleaner"),
    "空清消杀": ("消毒", "杀菌", "除菌", "disinfect"),
    "婴童护理": ("婴童", "婴儿", "宝宝", "儿童", "baby"),
    "宠物护理": ("宠物", "猫砂", "狗", "pet"),
    "工业遮味": ("工业", "遮味", "异味", "malodor"),
}
PRICE_TEXT = (
    ("max", re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以内|以下|封顶|上限|不超过)")),
    ("min", re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以上|起|不低于)")),
    ("range", re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*[-~—至到]\s*(\d+(?:\.\d+)?)")),
    ("target", re.compile(r"(?:参考|目标|理想价)\s*(\d+(?:\.\d+)?)")),
)


def parse_text(text, catalog, config):
    """Free text to a query dict without a model: tags, categories, price, mode."""
    raw = str(text or "").strip()
    query = {"mode": "recommend_simple", "categories": [], "groups": [], "text": raw[:300]}
    if not raw:
        return query
    lowered = raw.casefold()

    hits = []
    for label, words in CATEGORY_WORDS.items():
        for word in words:
            if word.casefold() in lowered:
                hits.append((len(word), label))
                break
    chosen = [label for _, label in sorted(hits, reverse=True)[:3]]
    query["categories"] = [key for key, label in catalog.categories.items() if label in chosen]

    for name, pattern in PRICE_TEXT:
        found = pattern.search(raw)
        if not found:
            continue
        if name == "range":
            low, high = sorted((found.group(1), found.group(2)), key=lambda value: float(value))
            query["min_price"], query["max_price"] = low, high
        elif name == "max":
            query["max_price"] = found.group(1)
        elif name == "min":
            query["min_price"] = found.group(1)
        else:
            query["target_price"] = found.group(1)
        break

    working, matched = raw, []
    for tag_id, term in sorted(catalog.terms.items(), key=lambda item: -len(item[1]["name"])):
        name = term["name"]
        if len(name) < 2 or name not in working:
            continue
        if term["level"] == "C" and term.get("category") not in query["categories"]:
            continue
        matched.append(tag_id)
        working = working.replace(name, "□")
    query["groups"] = [{"role": "preference", "op": "ANY", "tags": [tag]} for tag in matched[:8]]

    for product in catalog.products.values():
        names = [product.get("product_name", "")] + list(product.get("aliases", []))
        if any(len(item) >= 3 and item.casefold() in lowered for item in names if item):
            query["exact"] = True
            query["product_id"] = product["product_id"]
            break
    else:
        if any(brand.get("canonical_name", "") in raw or brand.get("international_name", "").casefold() in lowered
               for brand in catalog.brands.values() if brand.get("international_name") or brand.get("canonical_name")):
            query["mode"] = "recommend_brand"
    for edition in ("EDP", "EDT", "Parfum", "Elixir"):
        if edition.casefold() in lowered:
            query["edition"] = edition
            break
    if any(word in raw for word in ("仿", "同款", "复刻", "一样", "对标", "参照样")):
        query["mode"] = "with_sample"
    return query


def normalize_query(raw, terms, categories, config):
    if not isinstance(raw, dict):
        raise ValueError("查询应为一个对象")
    q = dict(raw)
    q["mode"] = q.get("mode") or "recommend_simple"
    if q["mode"] not in config["modes"]:
        raise ValueError("请选择选香模式")
    q["categories"] = list(dict.fromkeys(q.get("categories", [])))
    if invalid := set(q["categories"]) - set(categories):
        raise ValueError("未知应用品类 " + ", ".join(sorted(invalid)))
    q["sort"] = q.get("sort") or "match"
    for field in ("min_price", "max_price", "target_price"):
        value = q.get(field)
        if value not in (None, "") and comparable_price(value) is None:
            raise ValueError("价格必须是正数，单位为元/公斤")
        q[field] = str(comparable_price(value)) if comparable_price(value) is not None else None
    if q["min_price"] and q["max_price"] and Decimal(q["min_price"]) > Decimal(q["max_price"]):
        raise ValueError("价格下限不能高于上限")

    groups, positive, negative, seen = [], set(), set(), set()
    for group in q.get("groups", []):
        role = group.get("role", "preference")
        op = group.get("op", "ANY").upper()
        strength = group.get("strength", "normal")
        if role not in ROLES or op not in ("ALL", "ANY") or strength not in LOWER_PRIORITY:
            raise ValueError("不支持的需求标签分组")
        ids = sorted(set(group.get("tags", [])))
        if not ids:
            continue
        for tag in ids:
            if tag not in terms or not terms[tag].get("selectable", True):
                raise ValueError("未知标签或 C 标签未选到叶子 " + tag)
            if terms[tag]["level"] == "C" and terms[tag]["category"] not in q["categories"]:
                raise ValueError("C 标签需使用所属应用品类")
        key = (role, op if len(ids) > 1 else "ANY", tuple(ids), strength if role == "avoid" else "")
        if key in seen:
            continue
        seen.add(key)
        (negative if role == "avoid" else positive).update(ids)
        groups.append({"role": role, "op": op, "tags": ids, "strength": strength,
                       "source": str(group.get("source", ""))[:500]})
    if overlap := positive & negative:
        labels = "、".join(terms[tag]["name"] for tag in sorted(overlap))
        raise ValueError("请确认同时出现在正向和负向的标签 " + labels)
    q["groups"] = groups
    return q


def category_branches(query, terms):
    branches = {}
    for category in query["categories"] or [None]:
        groups = []
        for group in query["groups"]:
            tags = [tag for tag in group["tags"]
                    if terms[tag]["level"] != "C" or terms[tag]["category"] == category]
            if tags:
                groups.append({**group, "tags": tags})
        locked = {tag for group in groups if group["role"] == "required" for tag in group["tags"]}
        avoid = {tag for group in groups if group["role"] == "avoid" for tag in group["tags"]}
        preference = [{**group, "tags": [tag for tag in group["tags"] if tag not in locked]}
                      for group in groups if group["role"] == "preference"]
        branches[category] = (groups, [group for group in preference if group["tags"]], avoid)
    return branches


def score_branch(category, tags, groups, terms, edges, config, mode):
    _, preferences, avoid = groups
    weights = config["modes"][mode]
    direct_terms = {tag for group in preferences for tag in group["tags"] if tag in tags}
    retained_ab = {tag for tag in tags - direct_terms - avoid if terms[tag]["level"] != "C"}
    fragrance_c = {tag for tag in tags if terms[tag]["level"] == "C"}
    support = defaultdict(list)
    for c_tag in sorted(fragrance_c - avoid):
        for ab in edges.get(c_tag, set()):
            support[ab].append(c_tag)

    hit_details, group_values, main_note_gaps = {}, defaultdict(list), []
    for group in preferences:
        matches = []
        for tag in group["tags"]:
            if tag not in hit_details:
                info = terms[tag]
                value, kind, via = 0.0, "unmatched", []
                if tag in direct_terms:
                    value, kind = 1.0, "direct"
                elif info["level"] == "C":
                    via = sorted(edges.get(tag, set()) & retained_ab)
                    value = weights["beta"] * min(len(via) / config["saturation_count"], 1)
                    kind = "query_c" if via else "unmatched"
                elif support.get(tag) and weights["alpha"]:
                    value, kind, via = weights["alpha"], "fragrance_c", support[tag]
                hit_details[tag] = {"id": tag, "name": info["name"], "level": info["level"],
                                    "match": value, "kind": kind, "via": via}
            matches.append(hit_details[tag])

        levels = {match["level"] for match in matches}
        bucket = next(iter(levels)) if len(levels) == 1 else "mixed:" + "+".join(sorted(levels))
        weight = max(weights[level] for level in levels)
        if not weight:
            continue
        if group["op"] == "ALL":
            value = sum(match["match"] for match in matches) / len(matches)
            direct = sum(match["kind"] == "direct" for match in matches) / len(matches)
            contributors = [(match, weight * match["match"] / len(matches)) for match in matches]
            main_note_gaps.extend(match for match in matches
                                  if match["kind"] != "direct" and match["level"] in LEVELS[:3])
        else:
            winner = min(matches, key=lambda match: (-match["match"], match["id"]))
            value, direct = winner["match"], float(winner["kind"] == "direct")
            contributors = [(winner, weight * winner["match"])]
            if winner["kind"] != "direct" and all(match["level"] in LEVELS[:3] for match in matches):
                main_note_gaps.append(winner)
        group_values[bucket].append((weight, value, direct, contributors))

    level_scores, contribution = {}, defaultdict(float)
    total_weight = positive_value = direct_value = 0.0
    for level, values in group_values.items():
        weight = values[0][0]
        count = len(values)
        average = sum(item[1] for item in values) / count
        level_scores[level] = round(average, 4)
        positive_value += weight * average
        direct_value += weight * sum(item[2] for item in values) / count
        total_weight += weight
        for _, _, _, contributors in values:
            for match, credit in contributors:
                contribution[match["id"]] += credit / count

    negative = {}
    for group in groups[0]:
        if group["role"] != "avoid":
            continue
        matches = set(group["tags"]) & tags
        if group["op"] == "ALL" and len(matches) != len(group["tags"]):
            continue
        for tag in matches:
            penalty = config["negative_penalties"][group["strength"]]
            negative[tag] = max(negative.get(tag, 0), penalty)
    penalty = min(config["negative_cap"], sum(negative.values()))
    positive = 100 * positive_value / total_weight if total_weight else None
    score = max(0, positive - penalty) if positive is not None else None
    for hit in hit_details.values():
        hit["contribution"] = round(100 * contribution[hit["id"]] / total_weight, 2) if total_weight else 0
    order = sorted(hit_details.values(), key=lambda hit: (-hit["contribution"], hit["id"]))
    have_levels = {terms[tag]["level"] for tag in tags}
    return {
        "category": category,
        "score": round(score, 2) if score is not None else None,
        "positive_score": round(positive, 2) if positive is not None else None,
        "direct_score": round(100 * direct_value / total_weight, 2) if total_weight else 0,
        "level_scores": level_scores,
        "penalty": penalty,
        "negative_hits": [{"id": tag, "name": terms[tag]["name"], "deduction": negative[tag]}
                          for tag in sorted(negative, key=lambda tag: (-negative[tag], tag))],
        "direct_hits": [hit for hit in order if hit["kind"] == "direct"],
        "cross_hits": [hit for hit in order if hit["kind"] in ("fragrance_c", "query_c")],
        "unmatched": [hit for hit in order if not hit["match"]],
        "main_note_gaps": list(dict.fromkeys(hit["name"] for hit in main_note_gaps)),
        "missing_levels": sorted({hit["level"] for hit in order if hit["level"] not in have_levels}),
    }


def evaluate_constraints(row, query, branch, groups, tags):
    blocked, price_issues = [], []
    if branch is not None:
        allowed = row["categories"] if query.get("confirmed_only") else row["searchable_categories"]
        if branch not in allowed:
            blocked.append("应用品类")
    price = row["price"]
    if price is None and (query["min_price"] or query["max_price"] or query["target_price"]):
        price_issues.append("价格待查")
    if price is not None:
        if query["min_price"] and price < Decimal(query["min_price"]):
            price_issues.append("低于价格下限")
        if query["max_price"] and price > Decimal(query["max_price"]):
            price_issues.append("超价")
        if not (query["min_price"] or query["max_price"]) and query["target_price"]:
            if price > Decimal(query["target_price"]):
                price_issues.append("超参考价")
    if price_issues and (query["min_price"] or query["max_price"]):
        blocked.append("价格")
    if query.get("only_new") and not row["is_new"]:
        blocked.append("新品")
    if query.get("only_hot") and not row["is_hot"]:
        blocked.append("爆品")
    if query.get("big_brand") not in (None, "", "all"):
        states = {"confirmed", "manual"}
        if query["big_brand"] == "include_suggested":
            states.add("suggested")
        if not any(item["status"] in states for item in row["products"]):
            blocked.append("大牌仿香")
    if query.get("brand_ids") and not any(
        item.get("brand_id") in query["brand_ids"] and item["status"] != "unverified"
        for item in row["products"]
    ):
        blocked.append("品牌")
    if query.get("product_ids") and not any(item["product_id"] in query["product_ids"]
                                            and item["status"] != "unverified" for item in row["products"]):
        blocked.append("产品目录")
    for group in groups[0]:
        if group["role"] != "required":
            continue
        matched = set(group["tags"]) & tags
        if not matched or (group["op"] == "ALL" and len(matched) != len(group["tags"])):
            blocked.append("硬性标签")
            break
    if row["fragrance_id"] in query.get("rejected_codes", []):
        blocked.append("已排除")
    return blocked, price_issues


def card_message(detail, price_issues, blocked, terms):
    risks = list(price_issues)
    if "硬性标签" in blocked:
        risks.append("硬性香气标签缺项")
    if detail["negative_hits"]:
        risks.append("命中排斥项 " + "、".join(item["name"] for item in detail["negative_hits"][:2]))
    if detail["main_note_gaps"]:
        risks.append("主韵待闻 " + detail["main_note_gaps"][0])
    if "应用品类" in blocked:
        risks.append("应用品类需核对")
    hits = [hit for hit in detail["direct_hits"] + detail["cross_hits"] if hit["contribution"] > 0]
    best = min(hits, key=lambda hit: (-hit["contribution"], hit["kind"] != "direct", hit["id"])) if hits else None
    reason = None
    if best:
        reason = ("直接命中 " if best["kind"] == "direct" else "关联支持 ") + terms[best["id"]]["name"]
    return risks[:3], reason


def rank(query, rows, terms, categories, edges, config):
    query = normalize_query(query, terms, categories, config)
    branches = category_branches(query, terms)
    results, alternatives = [], []
    diagnostics = defaultdict(int)
    for row in rows:
        if row["conflict"]:
            diagnostics["编码待核对"] += 1
            continue
        accepted, excluded, one_away = [], [], set()
        for category, groups in branches.items():
            tags = row["ab"] | row["c"].get(category, set())
            blocked, price_issues = evaluate_constraints(row, query, category, groups, tags)
            if len(blocked) == 1:
                one_away.add(blocked[0])
            if blocked and (len(blocked) > 1 or blocked[0] == "已排除"):
                continue
            detail = score_branch(category, tags, groups, terms, edges, config, query["mode"])
            detail["category_evidence"] = ("confirmed" if category in row["categories"] else
                                           "historical" if category in row["searchable_categories"] else None)
            detail["blocked"] = blocked
            detail["risks"], detail["reason"] = card_message(detail, price_issues, blocked, terms)
            if not detail["reason"] and not blocked:
                hard_hits = [tag for group in groups[0] if group["role"] == "required"
                             for tag in group["tags"] if tag in tags]
                if hard_hits:
                    detail["reason"] = "满足硬性要求 " + terms[hard_hits[0]]["name"]
            (excluded if blocked else accepted).append(detail)

        pool = accepted or excluded
        if not accepted:
            for constraint in one_away:
                diagnostics[constraint] += 1
        if not pool:
            continue
        pool.sort(key=lambda detail: (detail["score"] is None, -(detail["score"] or 0), -detail["direct_score"],
                                      detail["penalty"], detail["category"] or ""))
        card = {**row["card"], **pool[0], "branches": pool}
        (results if accepted else alternatives).append(card)

    def rank_key(card):
        default = (card["score"] is None, -(card["score"] or 0), -card["direct_score"],
                   card["penalty"], card["key"])
        price = comparable_price(card["price"])
        match query["sort"]:
            case "price_asc":
                return price is None, price or 0, default
            case "price_desc":
                return price is None, -(price or 0), default
            case "price_target":
                target = comparable_price(query["target_price"])
                return price is None or target is None, abs(price - target) if price and target else 0, default
            case "new":
                return not card["is_new"], default
            case "hot":
                return not card["is_hot"], default
            case _:
                return default

    results.sort(key=rank_key)
    priority = {"价格": 0, "应用品类": 1, "硬性标签": 2}
    alternatives.sort(key=lambda card: (priority.get(card["blocked"][0], 3), rank_key(card)))
    return {"query": query, "results": results, "alternatives": alternatives,
            "diagnostics": dict(diagnostics), "scoring_version": config["version"]}
