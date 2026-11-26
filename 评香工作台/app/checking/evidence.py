"""F18 match stored evidence against requirements. Pure: returns rows to apply."""

from datetime import date

from ..domain.normalize import clean


def _usable(evidence, today):
    if evidence.get("review_status") not in (None, "", "accepted"):
        return False
    valid_until = clean(evidence.get("valid_until"))
    if not valid_until:
        return True
    try:
        return date.fromisoformat(valid_until[:10]) >= today
    except ValueError:
        return True


def match(requirements, evidences, today=None):
    """Return {requirement_id: {status, evidence_id, note}} for every requirement."""
    today = today or date.today()
    updates = {}
    usable = [item for item in evidences if _usable(item, today)]
    for requirement in requirements:
        metric_id = requirement["metric_id"]
        subitem = requirement.get("subitem") or ""
        conditions_key = requirement.get("conditions_key") or ""
        same = [item for item in usable
                if item["metric_id"] == metric_id and (item.get("subitem") or "") == subitem]
        exact = [item for item in same if (item.get("conditions_key") or "") == conditions_key]
        candidates = exact or ([item for item in same if not conditions_key] if not conditions_key else [])
        if not candidates:
            note = "条件不匹配，需按当前条件重测" if same else ""
            updates[requirement["id"]] = {"status": "unverified", "evidence_id": None, "note": note}
            continue
        newest = sorted(candidates, key=lambda item: (item.get("tested_at") or "", item["id"]))[-1]
        verdicts = {item["verdict"] for item in candidates}
        if "failed" in verdicts and "passed" in verdicts:
            updates[requirement["id"]] = {"status": "needs_review", "evidence_id": newest["id"],
                                          "note": "通过与不符合的证据同时在册，需人工核对"}
        elif newest["verdict"] == "failed":
            updates[requirement["id"]] = {"status": "failed", "evidence_id": newest["id"],
                                          "note": clean(newest.get("measured")) or "部门回不符合"}
        else:
            updates[requirement["id"]] = {"status": "passed", "evidence_id": newest["id"], "note": ""}
    return updates


def receipt_evidence(receipt, task, requirement):
    """Turn one department receipt into an evidence row (dict)."""
    from ..store.db import dumps

    verdict = "passed" if receipt.get("passed") else "failed"
    return {
        "fragrance_id": task["spec"].get("fragrance_id", ""),
        "formula_version": task["spec"].get("formula_version", ""),
        "metric_id": requirement["metric_id"],
        "subitem": requirement.get("subitem") or "",
        "conditions_key": requirement.get("conditions_key") or "",
        "conditions": dumps(requirement.get("conditions") or {}),
        "verdict": verdict,
        "measured": clean(receipt.get("measured"), 500),
        "unit": clean(receipt.get("unit"), 40),
        "method": clean(receipt.get("method"), 200),
        "document": clean(receipt.get("document"), 300),
        "tested_at": clean(receipt.get("tested_at"), 40),
        "valid_until": clean(receipt.get("valid_until"), 40),
        "task_id": task["id"],
        "approved_by": clean(receipt.get("approved_by"), 80),
        "review_status": "accepted",
    }
