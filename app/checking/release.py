"""F20 release decision. Pure: reads requirement statuses, returns a verdict."""

from ..domain.models import Verdict

ADJUDICATED = ("passed", "not_applicable")
OPEN = ("unverified", "pending")


def decide(action, requirements, has_coverage=True):
    """action: warehouse / initial / formal / resend."""
    blockers, deferred = [], []
    if not requirements:
        return Verdict(False, (), (), "没有可核销的要求，先确认审查品类与市场")
    applicable = [item for item in requirements if item.get("status") != "not_applicable"]
    if not applicable:
        return Verdict(False, (), (), "全部要求标为不适用，需确认依据")
    for requirement in applicable:
        status = requirement.get("status")
        label = requirement.get("metric_name") or requirement["metric_id"]
        if requirement.get("subitem"):
            label += "/" + requirement["subitem"]
        item = {"requirement_id": requirement["id"], "metric_id": requirement["metric_id"],
                "metric": label, "status": status, "note": requirement.get("note") or ""}
        if status == "failed":
            blockers.append({**item, "why": "部门回不符合"})
        elif status == "needs_review":
            blockers.append({**item, "why": "证据互相矛盾，待核对"})
        elif status in OPEN:
            if action in ("warehouse", "formal", "resend"):
                blockers.append({**item, "why": "未核销"})
            elif requirement.get("deferral") == "blocked":
                blockers.append({**item, "why": "不可暂缓项未核销"})
            else:
                deferred.append(item)
    if blockers:
        return Verdict(False, tuple(blockers), tuple(deferred), f"{len(blockers)} 项未满足")
    if action == "initial":
        return Verdict(True, (), tuple(deferred), "初寄样放行" if not deferred else f"暂缓 {len(deferred)} 项")
    return Verdict(True, (), (), "全部适用要求通过")


def summarize(requirements):
    counts = {}
    for requirement in requirements:
        counts[requirement.get("status", "unverified")] = counts.get(requirement.get("status", "unverified"), 0) + 1
    return counts
