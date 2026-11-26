"""Brief objects: what the customer asked for, kept whole, split per direction.

The parse model fills this shape. Nothing here calls a model or touches the store.
A direction inherits the project-level conditions and only overrides what it says.
"""

import re

from .normalize import as_list, clean, normalize_markets, number

KINDS = ("scent", "regulatory", "stability", "performance", "commercial", "other")

REGULATORY = re.compile(
    r"IFRA|REACH|法规|合规|禁用|限用|禁止|不得|不含|无\s*\d+\s*个?过敏原|过敏原|闪点|CMR|SVHC|"
    r"防腐剂|防晒|着色剂|CAS|MSDS|SDS|COA|认证|申报|进出口|REACH|加州|欧盟|EPA")
STABILITY = re.compile(r"稳定|表稳|变色|相容|兼容|析出|浑浊|沉淀|光照|高温|低温|冻融|保质期|货架")
PERFORMANCE = re.compile(r"留香|持香|强度|扩散|爆发|层次|表现力|肤感|干爽|清洁|残留|去味|除味")
COMMERCIAL = re.compile(r"价格|价位|单价|成本|报价|数量|款数|交期|送样|截止|起订|年量|订单")

GLOBAL_TEXT = (
    "customer", "brand", "application_name", "application_id", "substrate", "form", "end_product",
    "dosage_text", "target_audience", "age_band", "gender", "sample_due", "launch_date",
    "deadline_text", "delivery_note", "flash_point", "stability_note", "price_text", "price_rule",
    "quantity_text", "project_code", "brief_goal",
)
GLOBAL_LIST = (
    "markets", "regulatory", "prohibitions", "certifications", "allergen_scope", "requirements",
    "open_questions",
)

DIRECTION_TEXT = (
    "title", "scent_text", "scent_notes", "category", "substrate", "application_name",
    "end_product", "dosage_text", "target_audience", "age_band", "gender", "sample_reference",
    "edition", "product", "brand", "application_id", "review_category_id",
)
DIRECTION_LIST = (
    "scent_families", "exclusions", "feelings", "scenes", "requirements", "markets", "references",
)


def classify(text):
    text = str(text or "")
    if STABILITY.search(text):
        return "stability"
    if REGULATORY.search(text):
        return "regulatory"
    if PERFORMANCE.search(text):
        return "performance"
    if COMMERCIAL.search(text):
        return "commercial"
    if re.search(r"香|味|韵|调|花|木|果|绿|甜|酸|苦|奶|辛|麝|龙涎|柑橘|茶", text):
        return "scent"
    return "other"


def metric_for(kind):
    return {"stability": "Q_STABILITY"}.get(kind, "R_EXTRA")


def _unwrap(value, depth=0):
    """Some models stringify a dict field; unwrap it instead of storing the repr."""
    if depth > 3 or not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return value
    try:
        import ast

        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return value
    return _unwrap(parsed, depth + 1) if isinstance(parsed, dict) else value


def requirement(item):
    """One customer requirement: text plus what kind of check it asks for."""
    item = _unwrap(item)
    if isinstance(item, dict):
        text = clean(_unwrap(item.get("text")), 600)
        kind = item.get("kind") if item.get("kind") in KINDS else classify(text)
        mandatory = bool(item.get("mandatory", True))
        metric = clean(item.get("metric_id"), 40) or metric_for(kind)
    else:
        text, kind, mandatory = clean(item, 600), classify(item), True
        metric = metric_for(kind)
    return {"text": text, "kind": kind, "mandatory": mandatory, "metric_id": metric}


def _listed(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value] if value not in (None, "") else []


def requirements(values, inherited=None):
    items = []
    for value in _listed(inherited) + _listed(values):
        item = requirement(value)
        if item["text"]:
            items.append(item)
    unique, seen = [], set()
    for item in items:
        if item["text"] in seen:
            continue
        seen.add(item["text"])
        unique.append(item)
    return unique


def normalize_shared(raw):
    shared = {}
    if not isinstance(raw, dict):
        return shared
    for key in GLOBAL_TEXT:
        value = clean(raw.get(key), 800)
        if value:
            shared[key] = value
    for key in GLOBAL_LIST:
        if key == "requirements":
            items = requirements(raw.get(key))
            if items:
                shared[key] = items
        elif key == "markets":
            values = normalize_markets(raw.get(key))
            if values:
                shared[key] = values
        else:
            values = [clean(item, 600) for item in as_list(raw.get(key)) if clean(item, 600)]
            if values:
                shared[key] = values
    if raw.get("stability_required") is not None:
        shared["stability_required"] = bool(raw.get("stability_required"))
    elif shared.get("stability_note"):
        note = shared["stability_note"]
        if re.search(r"否|不做|不需要|无需|免做", note):
            shared["stability_required"] = False
        elif re.search(r"是|需要|要求做|必须做", note):
            shared["stability_required"] = True
    if raw.get("allergen_free") is not None:
        shared["allergen_free"] = bool(raw.get("allergen_free"))
    return shared


def normalize_direction(raw):
    brief = {"kind": "direction"}
    if not isinstance(raw, dict):
        return brief
    for key in DIRECTION_TEXT:
        value = clean(raw.get(key), 1200)
        if value:
            brief[key] = value
    for key in DIRECTION_LIST:
        if key == "requirements":
            items = requirements(raw.get(key))
            if items:
                brief[key] = items
        elif key == "markets":
            values = normalize_markets(raw.get(key))
            if values:
                brief[key] = values
        elif key == "references":
            refs = []
            for item in as_list(raw.get(key))[:12]:
                if isinstance(item, dict):
                    refs.append({key: clean(item.get(key), 200) for key in
                                 ("name", "brand", "type", "intent", "note")})
                elif clean(item):
                    refs.append({"name": clean(item, 200)})
            if refs:
                brief[key] = refs
        else:
            values = [clean(item, 200) for item in as_list(raw.get(key)) if clean(item, 200)]
            if values:
                brief[key] = values
    if not brief.get("scent_text") and brief.get("scent_notes"):
        brief["scent_text"] = brief["scent_notes"]
    return brief


def from_conditions(conditions):
    """Manual drafts carry conditions only; keep them as a one-direction brief."""
    brief = {"kind": "direction"}
    mapping = {"scent": "scent_text", "substrate": "substrate", "end_product": "end_product",
               "dose_text": "dosage_text", "sample_reference": "sample_reference",
               "edition": "edition", "product": "product", "brand": "brand"}
    for source, target in mapping.items():
        if conditions.get(source):
            brief[target] = clean(conditions[source], 1200)
    if conditions.get("avoid"):
        brief["exclusions"] = [clean(item, 200) for item in as_list(conditions["avoid"]) if clean(item)]
    if conditions.get("requirements"):
        brief["requirements"] = requirements(conditions["requirements"])
    return brief


def conditions_from(brief, shared=None):
    """Compatibility view: the flat conditions the workflow and old pages use."""
    shared = shared or {}
    conditions = {}
    if brief.get("scent_text"):
        conditions["scent"] = brief["scent_text"]
    if brief.get("exclusions"):
        conditions["avoid"] = brief["exclusions"]
    for key in ("substrate", "end_product", "dosage_text", "sample_reference", "edition",
                "product", "brand", "application_id", "review_category_id"):
        if brief.get(key):
            conditions[key] = brief[key]
    for key in ("markets", "price_text", "price_rule", "price_min", "price_max", "price_min",
                "price_target", "quantity_text", "deadline_text", "sample_form", "count_min",
                "count_max", "special_claim", "composition_text"):
        value = brief.get(key) if brief.get(key) not in (None, "", []) else shared.get(key)
        if value not in (None, "", []):
            conditions[key] = value
    if brief.get("requirements") or shared.get("requirements"):
        conditions["requirements"] = requirements(brief.get("requirements"), shared.get("requirements"))
    if brief.get("target_audience") or shared.get("target_audience"):
        conditions["target_audience"] = brief.get("target_audience") or shared.get("target_audience")
    return conditions


def mode_for(entry):
    if entry == "recommend_brand":
        return "recommend_brand"
    if entry == "with_sample":
        return "with_sample"
    return "recommend_simple"


def merge(shared, direction, application_id="", review_category_id="", mode=""):
    """Goal fields: project conditions, direction overrides, filed as one brief."""
    shared = shared or {}
    direction = direction or {}
    fields = {}
    if mode:
        fields["mode"] = mode
    for key in ("markets", "substrate", "end_product", "dosage_text", "deadline_text",
                "sample_form", "price_text", "price_rule", "price_min", "price_max",
                "price_target", "quantity_text", "target_audience", "age_band", "gender",
                "application_name", "customer", "brand"):
        value = direction.get(key) if direction.get(key) not in (None, "", []) else shared.get(key)
        if value not in (None, "", []):
            fields[key] = value
    fields["application_id"] = direction.get("application_id") or application_id or ""
    fields["review_category_id"] = direction.get("review_category_id") or review_category_id or ""
    for key in ("scent_text", "scent_notes"):
        if direction.get(key):
            fields[key] = direction[key]
    for key in ("scent_families", "exclusions", "feelings", "scenes", "references"):
        if direction.get(key):
            fields[key] = direction[key]
    inherited = list(shared.get("requirements") or [])
    for text in shared.get("regulatory") or []:
        inherited.append({"text": text, "kind": "regulatory"})
    for text in shared.get("prohibitions") or []:
        inherited.append({"text": "禁用：" + text, "kind": "regulatory"})
    for text in shared.get("certifications") or []:
        inherited.append({"text": "文件：" + text, "kind": "regulatory"})
    for text in shared.get("allergen_scope") or []:
        inherited.append({"text": "过敏原：" + text, "kind": "regulatory"})
    if shared.get("flash_point"):
        inherited.append({"text": "闪点：" + str(shared["flash_point"]), "kind": "regulatory"})
    if shared.get("stability_required") is not None:
        kind = "stability" if shared["stability_required"] else "other"
        inherited.append({"text": shared.get("stability_note") or "客户要求稳定性考察",
                          "kind": kind, "mandatory": bool(shared["stability_required"])})
    elif shared.get("stability_note"):
        inherited.append({"text": shared["stability_note"], "kind": "other"})
    fields["requirements"] = requirements(direction.get("requirements"), inherited)
    for key in ("regulatory", "prohibitions", "certifications", "allergen_scope"):
        if shared.get(key):
            fields[key] = shared[key]
    if shared.get("stability_required") is not None:
        fields["stability_required"] = shared["stability_required"]
    if shared.get("stability_note"):
        fields["stability_note"] = shared["stability_note"]
    if shared.get("flash_point"):
        fields["flash_point"] = shared["flash_point"]
    fields["brief"] = {"shared": shared, "direction": direction}
    if not fields.get("scent") and fields.get("scent_text"):
        fields["scent"] = fields["scent_text"]
    return fields


def missing(fields):
    """Fields worth showing as blank; never a reason to block."""
    checks = {
        "application_id": "应用品类", "markets": "市场", "target_audience": "人群",
        "scent_text": "香气要求", "dose_text": "添加量", "price_text": "价格",
    }
    return [label for key, label in checks.items() if not fields.get(key)]
