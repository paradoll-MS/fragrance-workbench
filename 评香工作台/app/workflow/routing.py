"""F05 routing: which strategies a direction may take."""

from ..domain import enums
from ..domain.models import endpoint_for


def strategies(entry):
    return list(enums.ENTRY_STRATEGIES.get(entry, ("select",)))


def route(entry, project_kind="customer", parent_id=None, has_sample=False, has_base=False):
    """Return requirement_type, allowed strategies, endpoint and the issues worth showing."""
    if entry not in enums.ENTRY_STRATEGIES:
        entry = "recommend_simple"
    allowed = strategies(entry)
    if entry == "with_sample" and not has_sample:
        allowed = [item for item in allowed if item != "duplicate"]
    if entry == "modify" and not has_base:
        allowed = list(allowed)
    issues = []
    if entry == "find_product":
        issues.append({"code": "reference_unresolved", "text": "精确产品需先核对目录身份与版本"})
    if entry == "modify" and not has_base:
        issues.append({"code": "formula_unknown", "text": "改香需确认原配方版本，可先留空"})
    return {"requirement_type": entry, "label": enums.ENTRY_LABELS[entry],
            "strategies": allowed, "endpoint": endpoint_for(project_kind, entry, parent_id),
            "issues": issues}


TRANSITIONS = {("modify", "with_sample"), ("recommend_simple", "recommend_brand"),
               ("with_sample", "recommend_brand"), ("find_product", "with_sample")}


def reroute(current, target):
    if (current, target) not in TRANSITIONS:
        raise ValueError("不支持把 " + enums.ENTRY_LABELS.get(current, current) + " 改为 " +
                         enums.ENTRY_LABELS.get(target, target))
    return target
