"""Targeting: one direction brief to C tags, then to A/B via the dictionary's own edges.

The model reads the category's C leaves and the left-side guidance written for them;
it never invents tags. Whatever it cannot ground in the customer's own words goes to
unmapped, and the deterministic path still returns something usable.
"""

import json
import re

from .. import config
from ..domain import brief as brief_model
from ..domain.normalize import canon
from ..recommendation import ranking
from .client import ModelError, json_object

INSTRUCTIONS = """你是香精选香的标签映射助手。输入是一个方向的需求、目标品类、人群、市场和候选 C 标签。
只从候选 C 里选，禁止造 ID，禁止跨品类。
一个方向可以命中多个 C；同一维度选最具体、最有依据的一个，不同维度可以各选一个。
判断必须使用这些条件：目标人群、销售市场、香气原文、香调家族、情绪/场景、客户排除项。
客户说“主打/核心/必须/以…为主调”时该项才设 required，其余都是 preference。
逐字引用客户原文作为 basis；引用必须出现在给定香气文本、家族、人群、情绪场景或客户要求里。没有依据就不要选，宁可少选。
不要选“闸门”节点，只选叶子；不要用父节点充数。
价格、法规、添加量、检测文件不是选 C 的依据，不要因为它们选 C；也不要把它们写进 unmapped。
输出 JSON：{"c_ids":[],"primary_c":"","items":[{"c_id":"","basis":"","confidence":0.0}],"used_conditions":[],"unmapped":[]}
used_conditions 列出实际用到的条件（如 "target_audience:6-12 岁儿童"），没用到不列。
unmapped 只写无法映射到任何 C 的香气/定位/风格表述，每条一句，不要罗列要求清单。只返回 JSON。"""

REQUIRED_WORDS = re.compile(r"主打|核心|必须|主调|以.{0,12}为主|一定要|必须有")
NEGATIVE = re.compile(
    r"不要|不想|不喜欢|不宜|避免|去掉|去除|减弱|降低|减少|排斥|排除|不能|太浓|太甜|太重|太腻|过甜|过浓|过重|杜绝|别太")


def _text(brief, *keys):
    return "；".join(str(brief.get(key) or "").strip() for key in keys if str(brief.get(key) or "").strip())


def _source_text(brief):
    families = "、".join(brief.get("scent_families") or [])
    requirements = "；".join(str(item.get("text")) for item in brief.get("requirements") or []
                             if isinstance(item, dict))
    parts = [_text(brief, "scent_text", "scent_notes", "target_audience"),
             "、".join(brief.get("feelings") or []), "、".join(brief.get("scenes") or []),
             families, requirements]
    return "；".join(part for part in parts if part.strip())


def _quote_ok(quote, source):
    flat = re.sub(r"\s+", "", source)
    parts = [part.strip() for part in re.split(r"[；;，,、]", str(quote or "")) if len(part.strip()) >= 2]
    if not parts:
        return False
    return all(re.sub(r"\s+", "", part) in flat for part in parts)


def _fallback(brief, mode, catalog, scoring_config, reason):
    source = _text(brief, "scent_text", "scent_notes")
    groups = []
    if source:
        try:
            parsed = ranking.parse_text(source, catalog, scoring_config)
            groups = [dict(group) for group in parsed.get("groups", [])]
        except (ValueError, KeyError):
            groups = []
    for family in brief.get("scent_families") or []:
        found = catalog.aliases.get(canon(family), set())
        if len(found) == 1:
            groups.append({"role": "preference", "op": "ANY", "tags": sorted(found),
                           "source": family})
    for item in brief.get("exclusions") or []:
        for part in re.split(r"[、，,；;]", str(item)):
            found = catalog.aliases.get(canon(part), set())
            if len(found) == 1 and NEGATIVE.search(str(item)):
                groups.append({"role": "avoid", "op": "ANY", "tags": sorted(found), "source": item})
    return {"groups": groups, "c_ids": [], "items": [], "used_conditions": [],
            "unmapped": [reason] if reason else [], "method": "字典词面（模型未参与）",
            "dictionary_version": catalog.dictionary_version}


def tag_direction(brief, mode, catalog, scoring_config=None, model=None):
    """brief is the merged goal fields; returns C tag groups plus evidence."""
    scoring_config = scoring_config or config.scoring()
    category = str(brief.get("application_id") or "")
    if category not in catalog.categories:
        return _fallback(brief, mode, catalog, scoring_config, "品类未定，无法按 C 维度判断")
    candidates = catalog.c_candidates(category)
    if not candidates:
        return _fallback(brief, mode, catalog, scoring_config, "该品类没有可用 C 标签")
    source = _source_text(brief)
    if not source.strip():
        return _fallback(brief, mode, catalog, scoring_config, "缺少香气描述")
    payload = {
        "mode": mode,
        "category": catalog.categories[category],
        "target_audience": brief.get("target_audience") or "",
        "markets": brief.get("markets") or [],
        "scent_text": brief.get("scent_text") or "",
        "scent_notes": brief.get("scent_notes") or "",
        "scent_families": brief.get("scent_families") or [],
        "exclusions": brief.get("exclusions") or [],
        "feelings": brief.get("feelings") or [],
        "scenes": brief.get("scenes") or [],
        "requirements": [item.get("text") for item in brief.get("requirements") or []
                         if isinstance(item, dict)],
        "candidates": [{"c_id": item["c_id"], "path": item["path"],
                        "dimension": item["dimension"], "guidance": item["guidance"]}
                       for item in candidates],
        "rules": catalog.llm_rules,
    }
    model = model or config.TARGETING_MODEL
    try:
        raw = json_object(model, [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], 2600, timeout=50)
    except ModelError as error:
        return _fallback(brief, mode, catalog, scoring_config, f"标签模型不可用：{error}")
    if not isinstance(raw, dict) or not isinstance(raw.get("c_ids"), list):
        return _fallback(brief, mode, catalog, scoring_config, "标签模型未返回 C 列表")
    by_id = {item["c_id"]: item for item in candidates}
    items, groups, unmapped = [], [], []
    for entry in (raw.get("items") or [])[:12]:
        if not isinstance(entry, dict):
            continue
        c_id = str(entry.get("c_id") or "")
        if c_id not in by_id:
            unmapped.append("模型给出未知 C：" + c_id)
            continue
        basis = str(entry.get("basis") or "").strip()
        if not _quote_ok(basis, source):
            unmapped.append("需核对依据：" + (basis or by_id[c_id]["path"]))
            continue
        role = "required" if (REQUIRED_WORDS.search(basis) and
                              (by_id[c_id]["name"] in basis or by_id[c_id]["path"].split("/")[-1].strip() in basis)) \
            else "preference"
        if mode == "with_sample":
            role = "preference"
        items.append({"c_id": c_id, "name": by_id[c_id]["name"], "path": by_id[c_id]["path"],
                      "basis": basis, "confidence": entry.get("confidence")})
        groups.append({"role": role, "op": "ANY", "tags": [c_id], "source": basis})
    for c_id in raw.get("c_ids") or []:
        if c_id in by_id and c_id not in {item["c_id"] for item in items}:
            unmapped.append("模型未给出依据：" + by_id[c_id]["path"])
    for item in raw.get("unmapped") or []:
        text = str(item).strip()
        if not text or brief_model.classify(text) in ("regulatory", "stability", "commercial"):
            continue
        if re.search(r"文件|送样|标签|电子文档|COA|MSDS|IFRA|法规|过敏原|闪点|交期|价格|数量|留香|稳定性", text):
            continue
        unmapped.append(text[:120])
    if not groups:
        return _fallback(brief, mode, catalog, scoring_config, "没有可用的 C 依据")
    used = [str(item)[:120] for item in raw.get("used_conditions") or [] if str(item).strip()]
    return {"groups": groups, "c_ids": [item["c_id"] for item in items], "items": items,
            "used_conditions": used[:12], "unmapped": unmapped[:12], "method": model,
            "dictionary_version": catalog.dictionary_version}


def direct_mapping(text, catalog):
    """Return groups when every word is a unique dictionary alias, else None."""
    source = text.strip()
    if "或" in source and re.search(r"以及|和|、|，|,", source):
        return None
    parts = re.split(r"或|以及|和|、|，|,", source)
    ids = set()
    for part in parts:
        matches = catalog.aliases.get(canon(part), set())
        if len(matches) != 1:
            return None
        ids.update(matches)
    if re.search(r"或", source):
        return [{"role": "preference", "op": "ANY", "tags": sorted(ids), "source": source}]
    return [{"role": "preference", "op": "ANY", "tags": [tag], "source": source} for tag in sorted(ids)]


def verify(group, source, catalog, mode):
    quote = str(group.get("source") or "")
    if not quote or quote not in source:
        return None, "需核对来源 " + quote
    if group.get("role") == "avoid":
        if not NEGATIVE.search(quote):
            return None, "需核对负向描述 " + quote
    tags = group.get("tags", [])
    if group.get("role") != "avoid" and "调" not in quote:
        a2 = {canon(catalog.terms[tag]["name"]) for tag in tags if catalog.terms.get(tag, {}).get("level") == "A2"}
        tags = [tag for tag in tags if catalog.terms.get(tag, {}).get("level") != "A3"
                or not (canon(catalog.terms[tag]["name"]).removesuffix("调") in a2)]
    role = "preference" if mode == "with_sample" and group.get("role") == "required" else group.get("role")
    return {**group, "role": role, "tags": tags}, None


def map_brief(text, mode, categories, catalog, scoring_config, model=None):
    source = str(text).strip()
    if not source:
        raise ValueError("请输入香气需求")
    if len(source) > 5500:
        raise ValueError("选香描述太长，请保留当前方向的香气要求")
    if re.search(r"1[3-9]\d{9}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", source):
        raise ValueError("香气描述检测到联系方式，请删除后再映射")
    if groups := direct_mapping(source, catalog):
        return {"groups": groups, "unmapped": [], "method": "字典直配"}
    dictionary = []
    for tag, term in catalog.terms.items():
        if term["level"] == "C" and (term["category"] not in categories or not term["selectable"]):
            continue
        if term["level"] in ranking.LEVELS:
            dictionary.append([tag, term["level"], term.get("path") or term["name"]])
    model = model or config.TARGETING_MODEL
    proposal = json_object(model, [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(
            {"mode": mode, "categories": categories, "dictionary": dictionary, "brief": source},
            ensure_ascii=False)},
    ], 2100, timeout=40)
    if not isinstance(proposal, dict) or not isinstance(proposal.get("groups"), list):
        raise ModelError("模型未返回可用的标签分组，可手选标签")
    verified, unmapped = [], [str(item) for item in (proposal.get("unmapped") or [])][:15]
    for group in proposal["groups"]:
        checked, issue = verify(group, source, catalog, mode)
        if issue:
            unmapped.append(issue)
            continue
        try:
            verified.extend(ranking.normalize_query(
                {"mode": mode, "categories": categories, "groups": [checked]},
                catalog.terms, catalog.categories, scoring_config)["groups"])
        except ValueError:
            unmapped.append("需手工映射 " + str(checked.get("source", ""))[:40])
    return {"groups": verified, "unmapped": unmapped, "method": model}
