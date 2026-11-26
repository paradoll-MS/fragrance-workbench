"""Generic cleaning of proposed facts. No case-specific patches live here."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

TEXT_FIELDS = (
    "scent", "avoid", "product", "brand", "edition", "substrate", "dose_text", "composition_text",
    "quantity_text", "sample_form", "price_text", "deadline_text", "base_code", "base_version",
    "sample_reference", "changes", "retained", "price_rule", "launch_tier", "delivery_scope",
    "end_product", "special_claim", "similarity_note", "target_audience", "age_band", "gender",
    "application_name", "stability_note", "flash_point",
)
NUMBER_FIELDS = ("count_min", "count_max", "price_min", "price_max", "price_target")
LIST_FIELDS = ("markets", "requirements")
PRICE_RULES = ("max", "min", "range", "target")
SAMPLE_AMOUNT = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|毫升|g|克)(?![a-z])", re.I)


def canon(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())


def clean(value, limit=6000):
    if isinstance(value, (list, tuple)):
        value = "；".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()[:limit]


def price_value(raw):
    try:
        found = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return found if found.is_finite() and found > 0 else None


def number(value):
    try:
        found = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if found.is_finite() and 0 < found <= Decimal("100000000"):
        return float(found)
    return None


def positive(value):
    return number(value)


def price(value):
    return number(value)


def dedupe(items):
    return list(dict.fromkeys(items))


def as_list(value, limit=40):
    if not isinstance(value, (list, tuple)):
        return []
    return [clean(item) for item in value if clean(item)][:limit]


def anchored(value, segments):
    """True when the text appears in the material (whitespace-insensitive)."""
    text = clean(value)
    if not text:
        return False
    flat = re.sub(r"\s+", "", text)
    return any(flat and flat in re.sub(r"\s+", "", seg["text"]) for seg in segments)


def normalize_markets(values):
    """Map common names to the rule file's market codes; keep unknown text as is."""
    from . import enums

    codes, unknown = [], []
    for item in as_list(values):
        key = canon(item)
        code = enums.MARKET_ALIASES.get(key)
        if not code:
            code = item if item in enums.MARKET_LABELS else ""
        if not code:
            for candidate, label in enums.MARKET_LABELS.items():
                if key == canon(label):
                    code = candidate
                    break
        if code and code not in codes:
            codes.append(code)
        elif not code:
            unknown.append(item)
    return codes + unknown


PRICE_MAX = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以内|以下|封顶|上限|不超过)")
PRICE_MIN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以上|起|不低于)")
PRICE_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*[-~—至到]\s*(\d+(?:\.\d+)?)")


def _derive_price_bounds(conditions):
    """Only fills bounds the text states; never guesses a number."""
    text = clean(conditions.get("price_text"))
    if not text or conditions.get("price_max") or conditions.get("price_min"):
        return
    found = PRICE_RANGE.search(text)
    if found:
        low, high = sorted((price_value(found.group(1)), price_value(found.group(2))), key=str)
        if low and high and low < high:
            conditions.update(price_rule="range", price_min=str(low), price_max=str(high))
        return
    found = PRICE_MAX.search(text)
    if found:
        conditions.update(price_rule="max", price_max=found.group(1))
        return
    found = PRICE_MIN.search(text)
    if found:
        conditions.update(price_rule="min", price_min=found.group(1))


def normalize_conditions(raw, categories, review_categories):
    """Turn a proposed conditions object into typed values plus questions."""
    questions = []
    conditions = {}
    if not isinstance(raw, dict):
        return conditions, questions

    for field in TEXT_FIELDS:
        value = clean(raw.get(field))
        if value:
            conditions[field] = value
    for field in NUMBER_FIELDS:
        value = number(raw.get(field))
        if value is not None:
            conditions[field] = value
    for field in LIST_FIELDS:
        values = raw.get(field) if field == "requirements" and isinstance(raw.get(field), list) \
            else as_list(raw.get(field))
        if not values:
            continue
        if field == "requirements":
            from .brief import requirement as to_requirement
            items = [to_requirement(entry) for entry in values if to_requirement(entry)["text"]]
            if items:
                conditions[field] = items
        else:
            conditions[field] = values

    if raw.get("application_id") in categories:
        conditions["application_id"] = raw["application_id"]
    elif raw.get("application_id"):
        questions.append("应用品类不在词表内，已留空")
    if raw.get("review_category_id") in review_categories:
        conditions["review_category_id"] = raw["review_category_id"]
    elif raw.get("review_category_id"):
        questions.append("审查品类不在词表内，已留空")
    if conditions.get("price_rule") not in PRICE_RULES:
        conditions.pop("price_rule", None)
    if conditions.get("markets"):
        conditions["markets"] = normalize_markets(conditions["markets"])
    _derive_price_bounds(conditions)
    fulfillment = raw.get("fulfillment")
    conditions["fulfillment"] = "warehouse" if fulfillment == "warehouse" else "ship"

    low, high = conditions.get("price_min"), conditions.get("price_max")
    if low and high and low > high:
        conditions.pop("price_min")
        conditions.pop("price_max")
        questions.append("价格区间上下限相反，已留空待确认")
    low, high = conditions.get("count_min"), conditions.get("count_max")
    if low and high and low > high:
        conditions.pop("count_min")
        conditions.pop("count_max")
        questions.append("款数上下限相反，已留空待确认")

    dose = clean(conditions.get("dose_text"))
    if dose:
        if dose.count("%") > 1 or re.search(r"前调|中调|后调|各占|主水果|放大器", dose):
            conditions.setdefault("composition_text", dose)
            conditions.pop("dose_text", None)
        else:
            found = re.search(r"\d+(?:\.\d+)?\s*[%％]", dose)
            conditions["dose_text"] = found.group() if found else dose

    sample_form = clean(conditions.get("sample_form"))
    if sample_form:
        amount = SAMPLE_AMOUNT.search(sample_form)
        if amount:
            conditions.setdefault("quantity_text", amount.group())
            conditions["sample_form"] = (sample_form[:amount.start()] + sample_form[amount.end():]).strip(" ：:，,")
    return conditions, questions


def normalize_direction(item, segments, categories, review_categories, entry_labels, shared=None):
    """Validate one proposed direction; returns (direction, questions)."""
    from . import brief as brief_model
    from . import enums

    questions = []
    if not isinstance(item, dict):
        return None, questions
    title = clean(item.get("title"), 300)
    if not title:
        return None, questions
    entry = item.get("entry")
    if entry not in enums.ENTRY_STRATEGIES:
        questions.append(f"{title} 的入口未能判断，暂按常规推荐")
        entry = "recommend_simple"
    intent = item.get("intent") if item.get("intent") in enums.INTENTS else "new"

    brief = brief_model.normalize_direction(item.get("brief") or {})
    if not any(brief.get(key) for key in ("scent_text", "scent_notes", "scent_families", "exclusions",
                                          "substrate", "application_id", "target_audience")):
        brief = brief_model.from_conditions(item.get("conditions") or {})
    raw_conditions = item.get("conditions")
    if not isinstance(raw_conditions, dict):
        raw_conditions = brief_model.conditions_from(brief, shared or {})
    conditions, more = normalize_conditions(raw_conditions, categories, review_categories)
    questions.extend(more)
    if shared:
        for key in ("target_audience", "markets", "substrate", "end_product", "dose_text"):
            if key not in conditions and shared.get(key):
                conditions[key] = shared[key]
    if not conditions.get("requirements") and shared and shared.get("requirements"):
        conditions["requirements"] = shared["requirements"]
    basis = []
    by_text = {seg["id"]: seg for seg in segments if "id" in seg}
    for ref in (item.get("basis") or [])[:16]:
        if not isinstance(ref, dict):
            continue
        quote = clean(ref.get("quote"), 800)
        source = by_text.get(str(ref.get("segment_id")))
        if quote and source and re.sub(r"\s+", "", quote) in re.sub(r"\s+", "", source["text"]):
            basis.append({"segment_id": str(ref["segment_id"]), "quote": quote,
                          "locator": source.get("locator", "")})
    if segments and not basis:
        questions.append(f"{title} 缺少可核对的原文引用")
    deadline = conditions.get("deadline_text")
    if deadline and not anchored(deadline, segments):
        conditions.pop("deadline_text")
        questions.append(f"{title} 的交期未在资料中找到原话，已留空")
    return {
        "title": title,
        "entry": entry,
        "entry_label": entry_labels.get(entry, entry),
        "intent": intent,
        "previous_goal_id": item.get("previous_goal_id"),
        "source_shipment_id": item.get("source_shipment_id"),
        "basis": basis,
        "brief": brief,
        "conditions": conditions,
    }, questions
