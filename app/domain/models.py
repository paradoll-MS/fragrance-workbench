"""Objects passed between layers. Pure data with their own invariants."""

import hashlib
from dataclasses import dataclass, field

from . import enums
from .normalize import canon


@dataclass(frozen=True)
class IssueSpec:
    code: str
    missing: tuple = ()
    waiting: tuple = ()
    next_action: str = ""
    node: str = ""

    def as_dict(self):
        return {
            "code": self.code,
            "label": enums.ISSUE_CODES.get(self.code, self.code),
            "missing": list(self.missing),
            "waiting": list(self.waiting),
            "next_action": self.next_action,
            "resume_event": enums.RESUME_EVENTS.get(self.code, ""),
            "node": self.node,
        }


@dataclass(frozen=True)
class CheckContext:
    """Everything build_checks needs, already resolved by the workflow layer."""

    fragrance_id: str
    formula_version: str
    scope: str
    review_category: str
    markets: tuple = ()
    substrate: str = ""
    dose_text: str = ""
    end_product: str = ""
    customer_requirements: tuple = ()
    known_evidence_conditions: tuple = ()


@dataclass(frozen=True)
class RequirementDraft:
    metric_id: str
    subitem: str
    department: str
    source: str
    source_key: str
    criteria: str
    mandatory: bool
    deferral: str
    due_stage: str
    origin_text: str
    conditions: dict = field(default_factory=dict)

    @property
    def conditions_key(self):
        return conditions_fingerprint(self.conditions)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    blockers: tuple = ()
    deferred: tuple = ()
    reason: str = ""

    def as_dict(self):
        return {"verdict": "passed" if self.passed else "blocked",
                "blockers": list(self.blockers), "deferred": list(self.deferred),
                "reason": self.reason}


class StepBlocked(Exception):
    """A command that the data says cannot run. Carries an IssueSpec, not a stack trace."""

    def __init__(self, spec):
        self.spec = spec
        super().__init__(spec.code)


def conditions_fingerprint(conditions):
    """Stable key for evidence applicability. Only decision-relevant conditions."""
    parts = []
    for key in ("market", "markets", "substrate", "dose", "method", "end_product", "formula_version"):
        value = conditions.get(key)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = "|".join(sorted({canon(item) for item in value if item}))
        else:
            value = canon(value)
        if value:
            parts.append(f"{key}={value}")
    return ";".join(parts)


def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def endpoint_for(project_kind, entry, parent_id=None):
    if parent_id:
        return "warehouse_return"
    if project_kind == "invent" or entry == "invent":
        return "warehouse"
    return "shipment"


def requirement_source(customer_texts):
    return "customer" if customer_texts else "default"
