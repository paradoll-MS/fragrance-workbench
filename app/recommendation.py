from collections import defaultdict
from decimal import Decimal, InvalidOperation


LEVELS = ("A1", "A2", "A3", "B", "C")
ROLES = ("preference", "required", "avoid")
LOWER_PRIORITY = {"mild": 0, "normal": 1, "strong": 2}


def comparable_price(value):
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    return price if price.is_finite() and price > 0 else None


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
    if q["min_price"] and q["max_price"]:
        if Decimal(q["min_price"]) > Decimal(q["max_price"]):
            raise ValueError("价格下限不能高于上限")

    groups = []
    positive = set()
    negative = set()
    seen = set()
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
        labels = "、".join(terms[t]["name"] for t in sorted(overlap))
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
        locked = {tag for g in groups if g["role"] == "required" for tag in g["tags"]}
        avoid = {tag for g in groups if g["role"] == "avoid" for tag in g["tags"]}
        preference = [{**g, "tags": [t for t in g["tags"] if t not in locked]}
                      for g in groups if g["role"] == "preference"]
        branches[category] = (groups, [g for g in preference if g["tags"]], avoid)
    return branches


def score_branch(category, tags, groups, terms, edges, config, mode):
    _, preferences, avoid = groups
    weights = config["modes"][mode]
    direct_terms = {tag for g in preferences for tag in g["tags"] if tag in tags}
    retained_ab = {t for t in tags - direct_terms - avoid if terms[t]["level"] != "C"}
    fragrance_c = {t for t in tags if terms[t]["level"] == "C"}
    support = defaultdict(list)
    for c_tag in sorted(fragrance_c - avoid):
        for ab in edges.get(c_tag, set()):
            support[ab].append(c_tag)

    hit_details = {}
    group_values = defaultdict(list)
    main_note_gaps = []
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

        levels = {m["level"] for m in matches}
        bucket = next(iter(levels)) if len(levels) == 1 else "mixed:" + "+".join(sorted(levels))
        weight = max(weights[level] for level in levels)
        if not weight:
            continue
        if group["op"] == "ALL":
            value = sum(m["match"] for m in matches) / len(matches)
            direct = sum(m["kind"] == "direct" for m in matches) / len(matches)
            contributors = [(m, weight * m["match"] / len(matches)) for m in matches]
            main_note_gaps.extend(m for m in matches if m["kind"] != "direct" and m["level"] in LEVELS[:3])
        else:
            winner = min(matches, key=lambda m: (-m["match"], m["id"]))
            value, direct = winner["match"], float(winner["kind"] == "direct")
            contributors = [(winner, weight * winner["match"])]
            if winner["kind"] != "direct" and all(m["level"] in LEVELS[:3] for m in matches):
                main_note_gaps.append(winner)
        group_values[bucket].append((weight, value, direct, contributors))

    level_scores = {}
    contribution = defaultdict(float)
    total_weight = positive_value = direct_value = 0.0
    for level, values in group_values.items():
        weight = values[0][0]
        n = len(values)
        average = sum(row[1] for row in values) / n
        level_scores[level] = round(average, 4)
        positive_value += weight * average
        direct_value += weight * sum(row[2] for row in values) / n
        total_weight += weight
        for _, _, _, contributors in values:
            for match, credit in contributors:
                contribution[match["id"]] += credit / n

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
    explanation_order = sorted(hit_details.values(), key=lambda h: (-h["contribution"], h["id"]))
    have_levels = {terms[t]["level"] for t in tags}
    return {
        "category": category,
        "score": round(score, 2) if score is not None else None,
        "positive_score": round(positive, 2) if positive is not None else None,
        "direct_score": round(100 * direct_value / total_weight, 2) if total_weight else 0,
        "level_scores": level_scores,
        "penalty": penalty,
        "negative_hits": [{"id": t, "name": terms[t]["name"], "deduction": negative[t]}
                          for t in sorted(negative, key=lambda t: (-negative[t], t))],
        "direct_hits": [h for h in explanation_order if h["kind"] == "direct"],
        "cross_hits": [h for h in explanation_order if h["kind"] in ("fragrance_c", "query_c")],
        "unmatched": [h for h in explanation_order if not h["match"]],
        "main_note_gaps": list(dict.fromkeys(h["name"] for h in main_note_gaps)),
        "missing_levels": sorted({h["level"] for h in explanation_order if h["level"] not in have_levels}),
    }


def evaluate_constraints(row, query, branch, groups, tags):
    blocked = []
    if branch is not None:
        allowed = row["categories"] if query.get("confirmed_only") else row["searchable_categories"]
        if branch not in allowed:
            blocked.append("应用品类")
    price = row["price"]
    price_issues = []
    if price is None and (query["min_price"] or query["max_price"] or query["target_price"]):
        price_issues.append("价格待查")
    if price is not None:
        if query["min_price"] and price < Decimal(query["min_price"]):
            price_issues.append("低于价格下限")
        if query["max_price"] and price > Decimal(query["max_price"]):
            price_issues.append("超价")
        if not (query["min_price"] or query["max_price"]):
            if query["target_price"] and price > Decimal(query["target_price"]):
                price_issues.append("超参考价")
    if price_issues and (query["min_price"] or query["max_price"]):
        blocked.append("价格")
    if query.get("only_new") and not row["is_new"]:
        blocked.append("新品")
    if query.get("only_hot") and not row["is_hot"]:
        blocked.append("爆品")
    if query.get("big_brand") != "all" and query.get("big_brand"):
        states = {"confirmed", "manual"}
        if query["big_brand"] == "include_suggested":
            states.add("suggested")
        if not any(p["status"] in states for p in row["products"]):
            blocked.append("大牌仿香")
    if query.get("brand_ids") and not any(
        p.get("brand_id") in query["brand_ids"] and p["status"] != "unverified"
        for p in row["products"]
    ):
        blocked.append("品牌")
    if query.get("product_ids") and not any(p["product_id"] in query["product_ids"]
                                           and p["status"] != "unverified" for p in row["products"]):
        blocked.append("产品目录")
    for g in groups[0]:
        if g["role"] == "required":
            matched = set(g["tags"]) & tags
            if not matched or (g["op"] == "ALL" and len(matched) != len(g["tags"])):
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
        risks.append("命中排斥项 " + "、".join(t["name"] for t in detail["negative_hits"][:2]))
    if detail["main_note_gaps"]:
        risks.append("主韵待闻 " + detail["main_note_gaps"][0])
    if "应用品类" in blocked:
        risks.append("应用品类需核对")
    hits = [h for h in detail["direct_hits"] + detail["cross_hits"] if h["contribution"] > 0]
    best = min(hits, key=lambda h: (-h["contribution"], h["kind"] != "direct", h["id"])) if hits else None
    reason = None
    if best:
        reason = ("直接命中 " if best["kind"] == "direct" else "关联支持 ") + terms[best["id"]]["name"]
    return risks[:3], reason


def rank(query, rows, terms, categories, edges, config):
    query = normalize_query(query, terms, categories, config)
    branches = category_branches(query, terms)
    results = []
    alternatives = []
    diagnostics = defaultdict(int)
    for row in rows:
        if row["conflict"]:
            diagnostics["编码待核对"] += 1
            continue
        accepted = []
        excluded = []
        one_away = set()
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
                hard_hits = [t for group in groups[0] if group["role"] == "required"
                             for t in group["tags"] if t in tags]
                if hard_hits:
                    detail["reason"] = "满足硬性要求 " + terms[hard_hits[0]]["name"]
            (excluded if blocked else accepted).append(detail)

        pool = accepted or excluded
        if not accepted:
            for constraint in one_away:
                diagnostics[constraint] += 1
        if not pool:
            continue
        pool.sort(key=lambda d: (d["score"] is None, -(d["score"] or 0), -d["direct_score"],
                                 d["penalty"], d["category"] or ""))
        card = {**row["card"], **pool[0], "branches": pool}
        if accepted:
            results.append(card)
        else:
            alternatives.append(card)

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
