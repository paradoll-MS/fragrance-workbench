import json
import os
import re
from urllib.request import Request, urlopen

from .catalog import ROOT, canon
from .recommendation import normalize_query, LEVELS


def direct_mapping(text, catalog):
    source = text.strip()
    if "或" in source and re.search(r"以及|和|、|，|,", source):
        return None
    terms = re.split(r"或|以及|和|、|，|,", source)
    ids = set()
    for t in terms:
        matches = catalog.aliases.get(canon(t), set())
        if len(matches) != 1:
            return None
        ids.update(matches)
    if re.search(r"或", source):
        return [{"role": "preference", "op": "ANY", "tags": sorted(ids), "source": source}]
    return [{"role": "preference", "op": "ANY", "tags": [tag], "source": source} for tag in sorted(ids)]


def configured_key():
    if value := os.environ.get("PARATERA_API_KEY"):
        return value
    local = ROOT.parent / "API密钥配置" / "paratera密钥.txt"
    if local.exists():
        match = re.search(r"\bsk[-_][\w-]{16,}\b", local.read_text(encoding="utf-8-sig"))
        if match:
            return match.group()
    raise ValueError("未配置 Paratera 凭据，可手工选标签")


def verify_proposal(group, source, catalog, mode):
    quote = str(group.get("source") or "")
    if not quote or quote not in source:
        return None, "需核对来源 " + quote
    if group.get("role") == "avoid":
        if not re.search(
            r"不要|不想|不喜欢|不宜|避免|去掉|去除|减弱|降低|减少|排斥|排除|不能|太浓|太甜|太重|太腻|过甜|过浓|过重|杜绝|别太",
            quote,
        ):
            return None, "需核对负向描述 " + quote
        if re.fullmatch(r"\s*(?:别太|不要太|避免过|不要过|过|太)(?:浓郁|浓烈|浓|冲|强)[，。.!！\s]*", quote):
            return None, "强度要求待闻 " + quote
    tags = group.get("tags", [])
    if group.get("role") != "avoid" and "调" not in quote:
        a2 = {canon(catalog.terms[t]["name"]) for t in tags if catalog.terms.get(t, {}).get("level") == "A2"}
        tags = [t for t in tags if catalog.terms.get(t, {}).get("level") != "A3" or
                not (canon(catalog.terms[t]["name"]).removesuffix("调") in a2)]
    role = "preference" if mode == "with_sample" and group.get("role") == "required" else group.get("role")
    return {**group, "role": role, "tags": tags}, None


def map_brief(text, mode, categories, catalog, config):
    source = str(text).strip()
    if not source:
        raise ValueError("请输入香气需求")
    if len(source) > 5500:
        raise ValueError("选香描述太长，请保留当前方向的香气要求")
    if re.search(r"1[3-9]\d{9}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", source):
        raise ValueError("香气描述检测到联系方式，请删除后再映射，也可手工选标签")
    if groups := direct_mapping(source, catalog):
        return {"groups": groups, "unmapped": [], "method": "字典直配"}
    dictionary = []
    for tag, term in catalog.terms.items():
        if term["level"] == "C" and (term["category"] not in categories or not term["selectable"]):
            continue
        if term["level"] in LEVELS:
            dictionary.append([tag, term["level"], term.get("path") or term["name"]])
    instructions = (
        "你将评香需求映射为字典标签。只返回一个JSON对象 groups 和 unmapped。"
        "groups 元素使用 role(preference/required/avoid), op(ANY/ALL), tags(字典ID数组),"
        " strength(mild/normal/strong), source(需求中的逐字短引文)。"
        "仅明确要求某主韵才建议 required。客户明确说不喜欢/不要/太浓太甜时才输出 avoid，"
        "负向作为扣分，禁止把正向词反推成负向。描述太甜、略减某味可用 mild。"
        "任何负向组必须引用带明确负向的原文，多个品类的C分组，不臆造词或编号。"
        "明确要求A或B时保留ANY，不把两个可能性分别要求。单独提原料不等于主韵，with_sample 默认偏好。"
        "泛称木质、花香等映射A2；客户说整体香调或给出结构依据再映射A3。"
        "单独的太浓、太冲是浓淡强度要求，交还 unmapped，别换成厚重感等香气特征。"
        "价格、成分禁用、法规、数量属于其他流程，不转换成香气标签。"
    )
    model = os.environ.get("PARATERA_TARGETING_MODEL", "DeepSeek-V4-Flash-0731")
    payload = {"model": model, "temperature": 0, "thinking": {"type": "disabled"}, "max_tokens": 2100,
               "messages": [{"role": "system", "content": instructions},
                            {"role": "user", "content": json.dumps(
                                {"mode": mode, "categories": categories, "dictionary": dictionary, "brief": source},
                                ensure_ascii=False)}]}
    req = Request("https://llmapi.paratera.com/chat/completions", data=json.dumps(payload).encode("utf-8"),
                  headers={"Authorization": "Bearer " + configured_key(), "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            choice = json.load(response)["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("输出未完成")
        content = choice["message"]["content"].strip()
        content = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", content)
        proposal = json.loads(content)
        verified = []
        unmapped = [str(x) for x in proposal.get("unmapped", [])][:15]
        for group in proposal["groups"]:
            checked, issue = verify_proposal(group, source, catalog, mode)
            if issue:
                unmapped.append(issue)
                continue
            try:
                verified.extend(normalize_query({"mode": mode, "categories": categories, "groups": [checked]},
                                                catalog.terms, catalog.categories, config)["groups"])
            except ValueError:
                unmapped.append("需手工映射 " + checked["source"])
        return {"groups": verified, "unmapped": unmapped, "method": model}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("模型暂未返回可用标签，可重试或直接手工选标签") from exc
