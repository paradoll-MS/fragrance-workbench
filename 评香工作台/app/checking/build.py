"""F17 build the requirement set for one fragrance version and one scope."""

from ..assets.rules import group_by_department
from ..domain.models import CheckContext


def build(rules, context: CheckContext):
    """Pure: requirements + coverage for a slot's fragrance version."""
    requirements, coverage = rules.build(context)
    if not requirements:
        coverage.append({"code": "no_requirements",
                         "text": "未生成任何要求，请确认审查品类与客户要求"})
    return requirements, coverage, group_by_department(requirements)


def scope_for(endpoint, stage_action):
    if stage_action in ("warehouse",):
        return "warehouse"
    if endpoint == "warehouse":
        return "warehouse"
    return "shipment"


def context_from(goal_fields, review_category, markets, fragrance_id, formula_version, scope):
    return CheckContext(
        fragrance_id=fragrance_id,
        formula_version=formula_version,
        scope=scope,
        review_category=review_category or "",
        markets=tuple(markets or ()),
        substrate=str(goal_fields.get("substrate") or ""),
        dose_text=str(goal_fields.get("dose_text") or ""),
        end_product=str(goal_fields.get("end_product") or ""),
        customer_requirements=tuple(goal_fields.get("requirements") or ()),
    )
