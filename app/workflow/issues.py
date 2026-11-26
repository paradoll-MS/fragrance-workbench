"""WorkflowIssue: the only way a blocked step is represented."""

from ..domain.enums import ISSUE_CODES, RESUME_EVENTS
from ..store.db import dumps, loads, now, rows


def open_issue(db, scope_type, scope_id, code, missing=(), waiting=(), next_action="", node=""):
    db.execute(
        "INSERT INTO issue(scope_type,scope_id,code,node,missing,waiting,next_action,resume_events,"
        "state,created_at) VALUES(?,?,?,?,?,?,?,?,'open',?) "
        "ON CONFLICT(scope_type,scope_id,code) DO UPDATE SET "
        "missing=excluded.missing, waiting=excluded.waiting, next_action=excluded.next_action, "
        "node=excluded.node, state='open', resolved_at=''",
        (scope_type, scope_id, code, node, dumps(list(missing)), dumps(list(waiting)),
         next_action, dumps([RESUME_EVENTS.get(code, "manual_resolve")]), now()),
    )


def resolve_issue(db, scope_type, scope_id, code):
    db.execute("UPDATE issue SET state='resolved', resolved_at=? "
               "WHERE scope_type=? AND scope_id=? AND code=? AND state='open'",
               (now(), scope_type, scope_id, code))


def resolve_all(db, scope_type, scope_id, keep=()):
    for item in open_for(db, scope_type, scope_id):
        if item["code"] not in keep:
            resolve_issue(db, scope_type, scope_id, item["code"])


def open_for(db, scope_type, scope_id):
    items = rows(db, "SELECT * FROM issue WHERE scope_type=? AND scope_id=? AND state='open' ORDER BY id",
                 (scope_type, scope_id))
    for item in items:
        item["missing"] = loads(item["missing"], [])
        item["waiting"] = loads(item["waiting"], [])
        item["resume_events"] = loads(item["resume_events"], [])
        item["label"] = ISSUE_CODES.get(item["code"], item["code"])
    return items


def sync(db, scope_type, scope_id, specs, node=""):
    """Create issues for the given specs and close the ones no longer asserted."""
    keep = set()
    for spec in specs:
        keep.add(spec.code)
        open_issue(db, scope_type, scope_id, spec.code, spec.missing, spec.waiting, spec.next_action, node)
    resolve_all(db, scope_type, scope_id, keep)
    return keep


def revalidate(db, scope_type, scope_id, specs):
    """Recovery: close issues whose cause is gone, leave the rest untouched."""
    current = {spec.code for spec in specs}
    resolved = []
    for item in open_for(db, scope_type, scope_id):
        if item["code"] not in current:
            resolve_issue(db, scope_type, scope_id, item["code"])
            resolved.append(item["code"])
    return resolved


def as_dict(item):
    return {"code": item["code"], "label": item.get("label", item["code"]),
            "missing": item.get("missing", []), "waiting": item.get("waiting", []),
            "next_action": item.get("next_action", ""), "resume_event": (item.get("resume_events") or [""])[0],
            "node": item.get("node", ""), "created_at": item.get("created_at", "")}
