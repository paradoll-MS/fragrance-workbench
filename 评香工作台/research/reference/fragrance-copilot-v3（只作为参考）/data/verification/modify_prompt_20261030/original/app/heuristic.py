"""Deterministic brief extraction fallback.

LLM providers can be slow/unavailable. This module extracts the fields that
are literally present in a customer brief so the UI never shows an empty form.
It never invents a price, market or compliance conclusion.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", (s or "").replace("\r", "\n")).strip()


def _after(text: str, labels, max_len=120) -> str:
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*[：:]\s*([^\n]{{1,{max_len}}})", text)
        if m:
            return m.group(1).strip(" ；;，,")
    return ""


def _block(text: str, start_labels, end_labels, max_len=1200) -> str:
    for label in start_labels:
        m = re.search(rf"{re.escape(label)}[^\n]*\n?", text)
        if not m:
            continue
        rest = text[m.end():]
        end = len(rest)
        for e in end_labels:
            mm = re.search(rf"\n\s*{re.escape(e)}\s*[：:]", rest)
            if mm:
                end = min(end, mm.start())
        return rest[:min(end, max_len)].strip()
    return ""


def _uniq(xs):
    out = []
    for x in xs:
        x = x.strip(" -—/、，,；;")
        if x and x not in out:
            out.append(x)
    return out


def brief_from_text(text: str, filename: str, artifact_id: str, project: dict | None = None) -> dict:
    text = _norm(text)
    project = project or {}
    name = _after(text, ["项目名称", "产品名称", "品名"]) or ""
    ptype = _after(text, ["产品类型", "品类", "产品形态"])
    if not name:
        name = project.get("name", "")
    # 案例/表格里未必写“产品类型”；按项目名+正文的明确形态词兜底
    if not ptype:
        hay = (project.get("name", "") + "\n" + text[:4000]).lower()
        for kw, l3 in [("洗发", "洗发水"), ("护发", "护发素"), ("沐浴", "沐浴露"),
                       ("线香", "线香"), ("卫生香", "卫生香"), ("蜡烛", "蜡烛"),
                       ("藤条", "藤条挥发液"), ("无火", "藤条挥发液"), ("扩香", "藤条挥发液"),
                       ("香水", "香水"), ("香膏", "香膏"), ("洗衣", "洗衣液"),
                       ("柔顺", "柔顺剂"), ("洗洁精", "洗洁精")]:
            if kw in hay:
                ptype = l3
                break
    app = _after(text, ["应用", "使用场景"])
    audience = _after(text, ["使用人群", "目标消费者", "目标人群"])
    dosage = _after(text, ["香精添加量", "添加量"])
    qty = _after(text, ["送样数量", "样品数量"])
    deadline = _after(text, ["送样截止日期", "截止日期", "交期"])
    sample_due = _after(text, ["打样日期", "送样日期"])
    price_m = re.search(r"(?:目标价|价格|单价|成本|预算)\s*[：:]?\s*(?:人民币|RMB|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元)?(?:\s*/\s*(kg|公斤|千克|瓶|克))?", text, re.I)
    if not price_m:
        price_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*/\s*(kg|公斤|千克|瓶|克)", text, re.I)
    price = float(price_m.group(1)) if price_m else None
    unit = (price_m.group(2) if price_m and price_m.group(2) else "公斤") if price_m else ""
    if unit in ("kg", "千克"):
        unit = "公斤"
    markets = []
    if re.search(r"中国大陆|中国市场|国内市场|全国", text):
        markets.append("中国大陆")
    for m in re.findall(r"(欧盟|美国|日本|韩国|东南亚|中东|澳洲|加拿大|英国)", text):
        if m not in markets:
            markets.append(m)
    scent_block = _block(text, ["香气需求", "香味需求", "香气方向"], ["产品定位", "样品需求", "香精类型", "配方说明"])
    theme = scent_block
    if not theme:
        theme = _after(text, ["香型", "香气", "香韵"], 200)
    if not theme:
        # 不用项目名冒充香气主题；退化时保留资料首段，至少让人看到真实需求
        theme = re.sub(r"\s+", " ", text[:240]).strip() or project.get("name", "")
    family_text = _after(text, ["建议方向", "香型方向", "香调"], 300)
    # 建议方向是“方向”，先按逗号/分号保留整条；不要按“-”拆，否则三个方向会变成一堆香调
    directions = _uniq(re.split(r"[，,；;、]", family_text)) if family_text else []
    directions = [x for x in directions if len(x) <= 40]
    families = _uniq(re.split(r"[-—/、+＋]", family_text)) if family_text else []
    # 只从香气段补充大类，绝不从全文扫“麝香”（法规禁用物里也有麝香）
    known = ["花香", "果香", "草本", "木质", "木香", "柑橘", "水生", "海洋", "绿叶", "茶香", "东方", "琥珀", "美食", "粉香", "醛香", "皮革", "烟熏"]
    for k in known:
        if k in (scent_block or "") and k not in families:
            families.append(k)
    exclusions = []
    for pat in [r"无\s*26\s*个过敏原", r"不含[^\n。；]{1,80}", r"不添加[^\n。；]{1,80}", r"禁止[^\n。；]{1,80}", r"不得[^\n。；]{1,80}"]:
        for m in re.findall(pat, text):
            exclusions.append(m.strip())
    regulatory = []
    for kw in ["IFRA", "REACH", "化妆品安全技术规范", "MSDS", "COA", "CMR", "SVHC", "防腐剂", "防晒剂", "着色剂"]:
        if kw.lower() in text.lower():
            regulatory.append(kw)
    flash = _after(text, ["闪点"], 50)
    allergen = "无 26 个过敏原" if re.search(r"无\s*26\s*个过敏原", text) else ""
    summary = theme or _after(text, ["项目背景"], 300) or text[:240]
    open_q = []
    if price is None:
        open_q.append({"question": "目标价未在资料中明确；补价后才能按价格弹性硬筛", "impact": "recommendation", "owner": "销售"})
    if not markets:
        open_q.append({"question": "销售地未明确；法规/过敏原默认值无法按地区收窄", "impact": "compliance", "owner": "客户"})
    if not ptype:
        open_q.append({"question": "产品类型/L3 未明确；需先定品类才能映射新类", "impact": "category", "owner": "评香"})
    return {
        "schema_version": "2.0",
        "generation_mode": "heuristic",
        "project": {"name": project.get("name", ""), "customer": project.get("customer", ""),
                    "brand": project.get("brand", ""), "sales": project.get("sales", ""),
                    "evaluator": project.get("evaluator", ""), "grade": project.get("grade", ""),
                    "date": "", "summary": summary[:600]},
        "product": {"name": name, "category_l1": "", "category_l2": "", "category_l3": ptype,
                    "application": app or ptype, "new_class": "", "form": _after(text, ["剂型", "形态"], 80),
                    "usage": audience, "target_audience": audience,
                    "substrate": _after(text, ["基料", "基质"], 100), "dosage": dosage},
        "scent": {"theme": theme[:800], "core_position": "", "directions": directions[:8], "direction_notes": {}, "references": [], "families": families[:12],
                  "top": [], "middle": [], "base": [], "feelings": [], "scenes": [], "exclusions": exclusions[:12],
                  "intensity": _after(text, ["强度"], 40), "longevity": _after(text, ["留香"], 60),
                  "diffusion": _after(text, ["扩散"], 40), "old_formula": ""},
        "commercial": {"target_price": price, "price_band": "", "terminal_price": "",
                       "annual_volume": _after(text, ["年量", "年产量"], 80), "moq": _after(text, ["MOQ", "起订量"], 80),
                       "launch_date": _after(text, ["上市", "入库时间"], 80), "sample_due": sample_due,
                       "markets": markets, "channel": _after(text, ["渠道", "电商"], 100)},
        "compliance": {"markets": markets, "regulatory": regulatory, "allergen": allergen,
                       "halal": "有" if "清真" in text else "", "flash_point": flash,
                       "stability": "否" if re.search(r"稳定性考察[^\n]*否", text) else "",
                       "color": _after(text, ["颜色", "变色"], 80), "substrate_test": ""},
        "deliverables": {"type": "香精样品" if "香精样品" in text else "", "quantity": qty,
                         "recipient": _after(text, ["收件人", "收样人"], 80), "deadline": deadline,
                         "notes": _after(text, ["送样要求", "其他要求"], 200)},
        "evidence": {"source": [{"artifact_id": artifact_id, "locator": filename, "quote": text[:500]}]},
        "confidence": {"overall": 0.55, "note": "规则抽取；需评香核对"},
        "open_questions": open_q,
    }
