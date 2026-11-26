# -*- coding: utf-8 -*-
"""r2_etl_full.py — 从完整香精工单 SQLite(任务文档 canonical schema)构建 §2.1 任务上下文。
输出 _work/r2/full_tasks.json + full_contexts.jsonl;旧 945 任务(tasks.json)合并标注 reused。
"""
import json, os, re, sqlite3, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "output")
R2 = os.path.join(WS, "_work", "r2")
WORK = os.path.join(WS, "_work")
DB = r"C:\Users\26519\Desktop\交付总控\标签和静态数据\05_清洗过的项目工单数据\香精工单.sqlite3"

lib = {}
with open(os.path.join(OUT, "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        lib.setdefault(r["fragrance_id"], r)

def load_ids(fname, labcol=2):
    ids = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0]:
                ids[p[0]] = p[labcol] if len(p) > labcol else p[1]
    return ids
A_LABEL = load_ids("tags_A.txt"); B_LABEL = load_ids("tags_B.txt"); C_LABEL = load_ids("tags_C.txt", 6)
C_PATH = load_ids("tags_C.txt", 6)
CAT_NAME = {}
with open(os.path.join(WORK, "categories.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            CAT_NAME[p[0]] = p[1]

def prior_compact(code):
    r = lib.get(code)
    if not r:
        return None
    return {
        "categories": [CAT_NAME.get(c, c) for c in r["category_ids"]],
        "A1": [A_LABEL.get(t, t) for t in r["tags_A1"]],
        "A2": [A_LABEL.get(t, t) for t in r["tags_A2"]],
        "A3": [A_LABEL.get(t, t) for t in r["tags_A3"]],
        "B": [B_LABEL.get(t, t) for t in r["tags_B"]],
        "C": {CAT_NAME.get(ck, ck): [C_PATH.get(t, t) for t in cids]
              for ck, cids in r["tags_C_by_category"].items()},
    }

con = sqlite3.connect(DB)
cur = con.cursor()
# formula_refs
cur.execute("SELECT id, code, name, is_central FROM formula_refs")
fr = {r[0]: {"code": r[1], "name": r[2], "central": r[3]} for r in cur.fetchall()}
# work_orders
cur.execute("SELECT id, number, project_id, title, category, category_group FROM work_orders")
wo = {r[0]: {"number": r[1], "project_id": r[2], "title": r[3], "category": r[4],
             "category_group": r[5]} for r in cur.fetchall()}
# projects
cur.execute("SELECT id, number, name FROM projects")
proj = {r[0]: {"number": r[1], "name": r[2]} for r in cur.fetchall()}
# sample_occurrences
cur.execute("""SELECT id, work_order_id, formula_id, internal_name, external_code,
               external_name, weight_text, unit_price_text FROM sample_occurrences""")
samples_by_wo = collections.defaultdict(list)
for r in cur.fetchall():
    if r[1] and r[2] in fr:
        samples_by_wo[r[1]].append({
            "sid": r[0], "code": fr[r[2]]["code"], "central": fr[r[2]]["central"],
            "name": r[3] or "", "external_name": r[5] or "",
        })
# notes + note_links
cur.execute("SELECT id, project_id, role, text FROM notes")
notes = {r[0]: {"project_id": r[1], "role": r[2], "text": r[3] or ""} for r in cur.fetchall()}
cur.execute("SELECT note_id, work_order_id, sample_id FROM note_links")
nl = []
for r in cur.fetchall():
    if r[1]:
        nl.append({"note_id": r[0], "wo": r[1], "sample_id": r[2]})
nl_by_wo = collections.defaultdict(list)
for x in nl:
    nl_by_wo[x["wo"]].append(x)
# formula_mentions
cur.execute("SELECT note_id, formula_id, matched_code FROM formula_mentions")
mentions = collections.defaultdict(list)   # wo -> [code...]
mention_note = collections.defaultdict(list)  # wo -> [note_id...]
for r in cur.fetchall():
    nid, fref, code = r
    if fref not in fr:
        continue
    code = fr[fref]["code"] or code
    # find work orders linked to this note
    wos_for_note = {x["wo"] for x in nl if x["note_id"] == nid}
    for w in wos_for_note:
        mentions[w].append(code)
        mention_note[w].append(nid)

# build tasks: any WO with central sample or central mention
done_ids = set()
with open(os.path.join(R2, "tasks.json"), encoding="utf-8") as f:
    for t in json.load(f)["tasks"]:
        done_ids.add(t["task_id"])

tasks = []
for wid, w in sorted(wo.items()):
    samples = []
    for s in samples_by_wo.get(wid, []):
        samples.append({
            "sid": s["sid"], "code": s["code"],
            "name": s["name"] or s["external_name"],
            "customer_name": s["external_name"] or s["name"],
            "central": s["central"], "in_library": s["code"] in lib,
        })
    # notes for this WO (via note_links), ordered by role priority
    role_prio = {"work_requirement": 0, "project_brief": 0, "additional_requirements": 1,
                 "F_PROJDESIRE": 1, "evaluation": 2, "feedback": 2, "supplementary_fields": 3,
                 "sampling": 4}
    note_rows = []
    for x in nl_by_wo.get(wid, []):
        n = notes.get(x["note_id"])
        if not n or not n["text"].strip():
            continue
        smp = []
        if x["sample_id"]:
            for i, s in enumerate(samples, 1):
                if str(s["sid"]) == str(x["sample_id"]):
                    smp.append(i)
        note_rows.append({"n": len(note_rows) + 1, "kind": n["role"], "text": n["text"],
                          "samples": smp, "prio": role_prio.get(n["role"], 5)})
    note_rows.sort(key=lambda r: r["prio"])
    for i, nr in enumerate(note_rows, 1):
        nr["n"] = i
    # central mention codes not already in samples
    sample_codes = {s["code"] for s in samples}
    ment = [c for c in mentions.get(wid, []) if c in lib and c not in sample_codes]
    has_central_sample = any(s["central"] and s["code"] in lib for s in samples)
    if not has_central_sample and not ment:
        continue
    proj_name = proj.get(w["project_id"], {}).get("name", "")
    title = w["title"] if w["title"] and w["title"] != "-" else (proj_name or w["number"])
    tasks.append({
        "task_id": wid, "wo_number": w["number"], "old_category": w["category"] or "",
        "title": title, "project_name": proj_name, "notes": note_rows,
        "samples": samples, "mentions": sorted(ment),
        "has_lib_sample": has_central_sample, "reused": wid in done_ids,
    })

with_samples = [t for t in tasks if t["has_lib_sample"]]
mention_only = [t for t in tasks if not t["has_lib_sample"] and t["mentions"]]
print("总任务:", len(tasks), "| 有用样:", len(with_samples), "| 仅提及:", len(mention_only))
print("复用(已处理):", sum(1 for t in tasks if t["reused"]), "| 新增待跑:", sum(1 for t in tasks if not t["reused"]))

def compact(t):
    samples = []
    for i, s in enumerate(t["samples"], 1):
        entry = {"s": i, "code": s["code"], "in_library": s["code"] in lib}
        if s["name"]:
            entry["name"] = s["name"]
        if s["customer_name"] and s["customer_name"] != s["name"]:
            entry["customer_name"] = s["customer_name"]
        p = prior_compact(s["code"]) if s["code"] in lib else None
        if p:
            entry["prior"] = p
        samples.append(entry)
    notes = [{"n": nr["n"], "kind": nr["kind"], "text": nr["text"], "samples": nr["samples"]}
             for nr in t["notes"]]
    out = {"task_id": t["task_id"]}
    if t["old_category"]:
        out["old_category"] = t["old_category"]
    if t["title"]:
        out["title"] = t["title"]
    if t["project_name"]:
        out["project_context"] = t["project_name"]
    if notes:
        out["notes"] = notes
    if samples:
        out["samples"] = samples
    if t["mentions"]:
        out["mentions"] = [{"s": len(samples) + i, "code": c, "n": 1}
                           for i, c in enumerate(t["mentions"], 1)]
    return out

with open(os.path.join(R2, "full_tasks.json"), "w", encoding="utf-8") as f:
    json.dump({"tasks": tasks, "task_count": len(tasks),
               "with_samples": len(with_samples), "mention_only": len(mention_only),
               "reused": sum(1 for t in tasks if t["reused"]),
               "new": sum(1 for t in tasks if not t["reused"])}, f, ensure_ascii=False, indent=2)
with open(os.path.join(R2, "full_contexts.jsonl"), "w", encoding="utf-8") as f:
    for t in tasks:
        f.write(json.dumps(compact(t), ensure_ascii=False) + "\n")
print("wrote full_tasks.json + full_contexts.jsonl")
