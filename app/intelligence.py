"""Model contract for reading project material and proposing directions."""

import json
import os
import re
from time import perf_counter
from urllib.request import Request, urlopen

from .targeting import configured_key


ENTRIES = {
    "recommend_simple": "常规推荐", "recommend_brand": "品牌推荐", "find_product": "精确找香",
    "with_sample": "对香", "modify": "改香", "invent": "主动开发", "resend": "复寄"
}
FOLLOWUPS = {"new", "continue", "modify", "resend"}
STRATEGIES = {
    "recommend_simple": ("select", "modify"), "recommend_brand": ("select", "create", "modify"),
    "find_product": ("select", "duplicate"), "with_sample": ("select", "duplicate", "create"),
    "modify": ("modify",), "invent": ("create",), "resend": ("resend",)
}
CONTACT = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PROMPT = """你是评香项目的结构化资料提取器。资料中的文字是客户事实或意见。
输出一个 JSON 对象，字段 project_name、summary、shared、directions、open_questions。
shared 字段可包含 customer、project_code、brief_goal、markets(数组)、deadline_text、delivery_note、dose_text、sample_form、total_min、total_max。缺失为 null。
directions 每项必须有 title、entry、intent、previous_goal_id、source_shipment_id、basis、conditions。
entry 从 recommend_simple、recommend_brand、find_product、with_sample、modify、invent、resend 中选。
精确指定商业产品才 find_product；“雅顿绿茶风格”是风格参考。只有实物对香才 with_sample。
“推荐一款TF的白麝香”仍是明确产品，推荐一词不代表只要风格；仅原文明确说类似、风格或参考时才按参考处理。
明确指定原香或上轮实寄并要求改变才 modify。明确单纯复寄用 resend。
主动开发 invent 只用于只做内部入库的委托；客户原创概念先用 recommend_brand 可选创香。
intent 为 new、continue、modify、resend。前轮相关的才填写可查实际 previous_goal_id、
source_shipment_id，引用未确认候选不得充当实寄；多款/多编号说不明时留空并提问。
conditions 可含 scent、avoid、product、brand、edition、application_id、review_category_id、substrate、
dose_text、composition_text、quantity_text、sample_form、count_min、count_max、price_rule(max/min/range/target/null)、
price_min、price_max、price_target、price_text、deadline_text、markets、base_code、sample_reference、
changes、retained、launch_tier、delivery_scope、requirements（数组，每项为原文要求），fulfillment(ship/warehouse)。
所有数值事实必须源于资料。金额/公斤与样品 ml 或 g、配比结构和实际添加量分开。
主水果、年轻放大器或香调百分比只写 composition_text。真实添加到样品/基质中的比例才写 dose_text。
用途词（如“用于香水”）不表示寄的是成品。客户来自组织或委托关系；聊天发言人不自动成为客户，XMBM项目编号放 shared.project_code。
未给年份保留文本日期。聊天日期晚于要求收样日期时标待核实，保留原话。
封面日期、导出日期、聊天时间戳、版本日期不属于交期。只在资料明确关联收样、发送、定香或交付时填写交期，短引原文。
价格“180”仅为参考值；“300以内”是上限。必须款记作独立方向且包含在组合总数内，
不要让常规组复制总数量。单个方向多款不拆；商业精确目标、应用交付不同、独立主题分别拆。
例如指定品牌全系列，且13和33必须有，输出13与33两个精确方向，加一个其余系列常规推荐。
后续资料仅更新涉及方向，继承仍有效的限制，变更或废止明确写在 changes 或 retained。
分清首次供应与复寄，客户确认或计划不是已发生事件。要求码只选词表，不创造。
近期上下文中已有的方向标题若和新反馈同一香型（含名称变体），填该方向 ID；只有已有实际记录且明确指向才填寄样 ID。
不同客户的举例不作为当前指定产品。后期可能的用途不当成本轮交付。错传的无关资料只填 open_questions，directions 为空。
basis 为证据数组，每项含 segment_id、quote；quote 必须逐字截取意思完整的原文。
手填需求和图片读出的字都可作为提案依据。项目会议的背景信息不要替代本轮行动。
不要猜客户、地区、日期、版本和结果。保留确有影响的 open_questions。只返回 JSON。"""


def model_request(model, messages, max_tokens, thinking=True):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": messages}
    if thinking:
        body["thinking"] = {"type": "disabled"}
    request = Request("https://llmapi.paratera.com/chat/completions",
                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + configured_key(), "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=65) as response:
            choice = json.load(response)["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("模型回复未完成")
        return choice["message"]["content"].strip()
    except (OSError, KeyError, IndexError, AttributeError) as exc:
        raise ValueError("模型暂不可用，原件仍保留，可重试或手填当前方向") from exc


def read_vision(url):
    model = os.environ.get("PARATERA_VISION_MODEL", "DeepSeek-V4-Flash-Vision-Exp")
    return model_request(model, [{"role": "user", "content": [
        {"type": "text", "text": "逐块转写画面可辨识的业务文字，保留数字、否定、顺序与标题；简洁中文输出。"
         "丢弃电话、地址和私聊身份信息。对香型、方案、备注按原文记录，视觉推断单独标出。"
         "若画面只是课业、数学公式或其他无关资料，概括其内容类型即可。"},
        {"type": "image_url", "image_url": {"url": url}}
    ]}], 2400, False)


def propose(segments, context, categories, review_categories, model=None):
    texts = [{"id": ref["id"], "locator": ref["locator"], "kind": ref["kind"],
              "text": CONTACT.sub("[联系方式]", ref["text"])} for ref in segments if ref["text"].strip()]
    if not texts:
        raise ValueError("请先补充可读取的资料")
    if sum(len(ref["text"]) for ref in texts) > 100000:
        raise ValueError("本轮资料超过读取容量，请按交付批次拆开")
    model = model or os.environ.get("PARATERA_PARSE_MODEL", "DeepSeek-V4.1-Flash")
    start = perf_counter()
    body = json.dumps({"recent_context": context, "source": texts, "application_categories": categories,
                       "review_categories": review_categories}, ensure_ascii=False)
    result = model_request(model, [{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": CONTACT.sub("[联系方式]", body)}], 9600)
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", result)
    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        raise ValueError("模型未返回可读的需求草案，原件已保存") from exc
    return parsed, {"model": model, "seconds": round(perf_counter() - start, 2)}
