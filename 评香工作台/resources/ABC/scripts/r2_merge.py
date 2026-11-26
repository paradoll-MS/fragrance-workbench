# -*- coding: utf-8 -*-
"""r2_merge.py (fix v3) — 合并第二轮历史工单补标结果:
- C 品类校验:中文品类→CAT ID 统一,仅合法叶子写入
- kind 阻断:reference_only/logistics_only/modification_base/ambiguous/rejected 组不继承组标签
- category_candidates:仅推荐类 kind(实际使用依据)纳入,保留历史候选身份
- 主视图同步:history 标签并入 fragrance.jsonl 的 ABC 字段,与 fragrance_tags.jsonl 一致
- 保留冲突编码行(行级重写)
"""
import json, os, re, collections, datetime

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "output")
DOCS = os.path.join(WS, "docs")
R2 = os.path.join(WS, "_work", "r2")
WORK = os.path.join(WS, "_work")

# ---------------- tag dictionaries ----------------
CAT_NAME = {}
CAT_BY_NAME = {}
with open(os.path.join(WORK, "categories.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            CAT_NAME[p[0]] = p[1]
            CAT_BY_NAME[p[1]] = p[0]

def norm_cat(c):
    if not c:
        return None
    c = str(c).strip()
    if c in CAT_NAME:
        return c
    if c in CAT_BY_NAME:
        return CAT_BY_NAME[c]
    return None

def load_tags(fname, label_col):
    ids = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0]:
                ids[p[0]] = p
    return ids

A_DICT = load_tags("tags_A.txt", 2)
B_DICT = load_tags("tags_B.txt", 2)
C_DICT = load_tags("tags_C.txt", 5)   # [0]=id [1]=品类中文 [2]=维度 [3]=父ID [4]=标签 [5]=节点类型 [6]=路径
# C leaf check + CAT ID
C_CAT_ID = {}      # C id -> CAT id
C_IS_LEAF = {}     # C id -> bool
C_LABEL = {}       # C id -> 标签
C_PATH = {}        # C id -> 完整路径
for cid, p in C_DICT.items():
    C_CAT_ID[cid] = norm_cat(p[1])
    C_IS_LEAF[cid] = (p[5] == "叶子")
    C_LABEL[cid] = p[4]
    C_PATH[cid] = p[6]
C_CN = collections.defaultdict(list)
for cid, p in C_DICT.items():
    C_CN[(p[4], p[5])].append(cid)
A_CN = collections.defaultdict(list)
for cid, p in A_DICT.items():
    A_CN[(p[2], p[1])].append(cid)
B_CN = collections.defaultdict(list)
for cid, p in B_DICT.items():
    B_CN[(p[2], p[1])].append(cid)

def map_tag_id(val, level, cat=None):
    if not val:
        return None
    v = str(val).strip()
    if v in A_DICT or v in B_DICT or v in C_DICT:
        return v
    head = v.split(":")[0].strip()
    if head in A_DICT or head in B_DICT or head in C_DICT:
        return head
    # Chinese label -> ID
    if level == "C":
        for key, lst in C_CN.items():
            if key[0] == v:
                for cid in lst:
                    if C_IS_LEAF[cid] and (cat is None or C_CAT_ID[cid] == cat):
                        return cid
                return lst[0]
        return None
    for d, lv in ((A_CN, level), (B_CN, level)):
        for (lab, lv2), lst in d.items():
            if lab == v and (lv2 == lv or lv2 == level or level == "B" and lv2 == "B"):
                return lst[0]
    # any-level fallback
    for (lab, _), lst in A_CN.items():
        if lab == v:
            return lst[0]
    for (lab, _), lst in B_CN.items():
        if lab == v:
            return lst[0]
    return None

def map_list(vals, level, cat=None):
    out, unmapped = [], []
    for v in vals or []:
        if isinstance(v, dict):
            v = v.get("id") or v.get("tag_id") or v.get("label") or ""
        tid = map_tag_id(v, level, cat)
        if tid:
            out.append(tid)
        else:
            unmapped.append(str(v))
    return out, unmapped

# ---------------- load tasks & results ----------------
with open(os.path.join(R2, "full_tasks.json"), encoding="utf-8") as f:
    tasks = {t["task_id"]: t for t in json.load(f)["tasks"]}
with open(os.path.join(R2, "full_contexts.jsonl"), encoding="utf-8") as f:
    ctx_by_tid = {json.loads(l)["task_id"]: json.loads(l) for l in f if l.strip()}

results = {}
for fn in os.listdir(os.path.join(R2, "results")):
    if fn.endswith(".json"):
        tid = fn[:-5]
        try:
            results[tid] = json.load(open(os.path.join(R2, "results", fn), encoding="utf-8"))
        except json.JSONDecodeError:
            pass
print("results loaded:", len(results), "/", len(tasks))

lib = {}
with open(os.path.join(OUT, "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        lib[r["fragrance_id"]] = r
code_by_sid = {}
for tid, t in tasks.items():
    for i, s in enumerate(t.get("samples", []), 1):
        code_by_sid[(tid, i)] = s["code"]
    for i, m in enumerate(t.get("mentions", []), len(t.get("samples", [])) + 1):
        code_by_sid[(tid, i)] = m["code"] if isinstance(m, dict) else m

# counterevidence block
counter_block = set()
with open(os.path.join(OUT, "history_counterevidence.jsonl"), encoding="utf-8") as f:
    for line in f:
        e = json.loads(line)
        if e.get("fragrance_id") and e.get("tag_id"):
            counter_block.add((e["fragrance_id"], e["tag_id"]))

# kinds that must NOT inherit group (client-goal) tags
NON_INHERIT_KINDS = {"reference_only", "logistics_only", "modification_base",
                     "rejected", "ambiguous", "unrelated", "logistics"}
# kinds with actual usage basis -> eligible for searchable category candidates
RECOMMEND_KINDS = {"recommended", "selected", "direct_evaluation", "near_match"}

now = datetime.datetime.now().strftime("%Y-%m-%d")
work_contexts, relations, cat_evidence, tag_evidence, counterevidence = [], [], [], [], []
review_rows, gap_rows, errors = [], [], []
tag_seq = 0

def add_evidence(sr_kind, fragrance_id, cat, tag_id, tid, gid, n_refs, s_refs, kind):
    global tag_seq
    if (fragrance_id, tag_id) in counter_block:
        return
    tag_seq += 1
    tag_evidence.append({
        "fragrance_id": fragrance_id, "tag_id": tag_id,
        "category_id": cat, "source": "history", "status": "trial",
        "work_order_id": tid, "direction": gid, "kind": kind,
        "note_ids": n_refs or [], "sample_ids": s_refs or [],
        "evidence_ref": f"r2:{tid}:{gid}:{sr_kind}", "date": now, "seq": tag_seq,
    })

for tid, rec in results.items():
    t = tasks.get(tid)
    if not t:
        continue
    wo_number = t.get("wo_number", "")
    old_cat = t.get("old_category", "")
    title = t.get("title", "")
    project = t.get("project_name", "")
    in_lib_codes = {s["code"] for s in t.get("samples", []) if s["code"] in lib}
    ctx = ctx_by_tid.get(tid, {})
    work_contexts.append({
        "task_id": tid, "work_order_number": wo_number, "project": project,
        "title": title, "old_category": old_cat,
        "directions": [g.get("direction", "") for g in rec.get("groups", [])],
        "categories": sorted({c for g in rec.get("groups", []) for c in (g.get("cat") or [])}),
        "query_abc": [g.get("query") or {} for g in rec.get("groups", [])],
        "notes": [n.get("text", "") for n in ctx.get("notes", [])],
        "has_result": True,
    })
    # groups
    for g in rec.get("groups", []):
        gid = g.get("g") or f"d{len(work_contexts[-1]['directions'])}"
        raw_cats = g.get("cat") or []
        cat = [c for c in (norm_cat(x) for x in raw_cats) if c]
        kind = g.get("kind", "recommended")
        n_refs = [n for n in (g.get("n") or [])]
        s_refs = [s for s in (g.get("samples") or []) if s in code_by_sid]
        inherit = kind not in NON_INHERIT_KINDS
        tags = g.get("tags") if not g.get("tags_same_as_query") else g.get("query") or {}
        tags = tags or {}
        target_sids = [s for s in s_refs if code_by_sid.get((tid, s)) in in_lib_codes]
        if inherit:
            for lvl in ("A1", "A2", "A3", "B"):
                tids, un = map_list(tags.get(lvl), lvl)
                for u in un:
                    gap_rows.append({"task_id": tid, "wo_number": wo_number, "level": lvl,
                                     "text": f"组{gid} {lvl} 标签无法映射: {u}"})
                for tag_id in tids:
                    for s in target_sids:
                        add_evidence("group", code_by_sid[(tid, s)], None, tag_id, tid, gid, n_refs, [s], kind)
            for cid in (tags.get("C") or []):
                mapped = map_tag_id(cid, "C", (cat[0] if cat else None))
                if not mapped:
                    mapped = map_tag_id(cid, "C")
                if not mapped:
                    gap_rows.append({"task_id": tid, "wo_number": wo_number, "level": "C",
                                     "text": f"组{gid} C 无法映射: {cid}"})
                    continue
                if not C_IS_LEAF.get(mapped, False):
                    errors.append({"task_id": tid, "wo_number": wo_number,
                                   "text": f"组{gid} C {mapped}({C_LABEL.get(mapped,'')}) 是闸门非叶子,拒绝"})
                    continue
                ccat = C_CAT_ID.get(mapped)
                if cat and ccat not in cat:
                    errors.append({"task_id": tid, "wo_number": wo_number,
                                   "text": f"组{gid} C {mapped}({C_LABEL.get(mapped,'')}, {CAT_NAME.get(ccat,'')}) 不属于组品类 {[CAT_NAME.get(c,c) for c in cat]}"})
                    continue
                for s in target_sids:
                    add_evidence("group", code_by_sid[(tid, s)], ccat, mapped, tid, gid, n_refs, [s], kind)
        # relations (all kinds recorded, no tags)
        for s in s_refs:
            code = code_by_sid.get((tid, s))
            if code and code in in_lib_codes:
                relations.append({"fragrance_id": code, "work_order_id": tid, "wo_number": wo_number,
                                  "direction": gid, "sample_id": s, "kind": kind, "note_ids": n_refs})
        # category evidence only for recommend kinds
        if kind in RECOMMEND_KINDS:
            for c in cat:
                for s in target_sids:
                    code = code_by_sid[(tid, s)]
                    cat_evidence.append({"fragrance_id": code, "category_id": c,
                                         "work_order_id": tid, "direction": gid,
                                         "kind": kind, "note_ids": n_refs, "sample_ids": [s]})
    # individual (per-fragrance actual descriptions are allowed for all kinds)
    for ind in rec.get("individual", []):
        s = ind.get("s")
        code = code_by_sid.get((tid, s))
        if not code or code not in in_lib_codes:
            continue
        kind = ind.get("kind", "direct_evaluation")
        n_refs = [n for n in (ind.get("n") or [])]
        gid = ind.get("g") or "ind"
        cat = [c for c in (norm_cat(x) for x in (ind.get("cat") or [])) if c]
        tags = ind.get("tags") or {}
        for lvl in ("A1", "A2", "A3", "B"):
            tids, un = map_list(tags.get(lvl), lvl)
            for u in un:
                gap_rows.append({"task_id": tid, "wo_number": wo_number, "level": lvl,
                                 "text": f"样品{s} {lvl} 标签无法映射: {u}"})
            for tag_id in tids:
                add_evidence("ind", code, None, tag_id, tid, gid, n_refs, [s], kind)
        for cid in (tags.get("C") or []):
            mapped = map_tag_id(cid, "C", (cat[0] if cat else None))
            if not mapped:
                mapped = map_tag_id(cid, "C")
            if not mapped:
                gap_rows.append({"task_id": tid, "wo_number": wo_number, "level": "C",
                                 "text": f"样品{s} C 无法映射: {cid}"})
                continue
            if not C_IS_LEAF.get(mapped, False):
                errors.append({"task_id": tid, "wo_number": wo_number,
                               "text": f"样品{s} C {mapped}({C_LABEL.get(mapped,'')}) 是闸门非叶子,拒绝"})
                continue
            ccat = C_CAT_ID.get(mapped)
            if cat and ccat not in cat:
                errors.append({"task_id": tid, "wo_number": wo_number,
                               "text": f"样品{s} C {mapped}({C_LABEL.get(mapped,'')}, {CAT_NAME.get(ccat,'')}) 不属于 {[CAT_NAME.get(c,c) for c in cat]}"})
                continue
            add_evidence("ind", code, ccat, mapped, tid, gid, n_refs, [s], kind)
        if kind in RECOMMEND_KINDS:
            for c in cat:
                cat_evidence.append({"fragrance_id": code, "category_id": c,
                                     "work_order_id": tid, "direction": gid,
                                     "kind": kind, "note_ids": n_refs, "sample_ids": [s]})
        relations.append({"fragrance_id": code, "work_order_id": tid, "wo_number": wo_number,
                          "direction": gid, "sample_id": s, "kind": kind, "note_ids": n_refs})
    # counter
    for c in rec.get("counter", []):
        s = c.get("s")
        code = code_by_sid.get((tid, s))
        tag = c.get("tag") or ""
        tag_id = map_tag_id(tag, "") if tag else None
        counterevidence.append({
            "fragrance_id": code, "work_order_id": tid, "wo_number": wo_number,
            "sample_id": s, "tag_id": tag_id, "tag_label": tag,
            "text": c.get("text", ""), "note_ids": [n for n in (c.get("n") or [])],
        })
    for gp in rec.get("gaps", []):
        gap_rows.append({"task_id": tid, "wo_number": wo_number, "cat": gp.get("cat", ""),
                         "text": gp.get("text", "")})

def dedupe(rows, keys):
    seen, out = set(), []
    for r in rows:
        k = tuple(r.get(x) for x in keys)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out

tag_evidence = dedupe(tag_evidence, ["fragrance_id", "tag_id", "category_id", "work_order_id"])
cat_evidence = dedupe(cat_evidence, ["fragrance_id", "category_id", "work_order_id"])
relations = dedupe(relations, ["fragrance_id", "work_order_id", "direction"])
counterevidence = dedupe(counterevidence, ["fragrance_id", "sample_id", "text"])
gap_rows = dedupe(gap_rows, ["task_id", "text"])
errors = dedupe(errors, ["task_id", "text"])

for name, data in [("work_contexts.jsonl", work_contexts), ("history_relations.jsonl", relations),
                   ("history_category_evidence.jsonl", cat_evidence),
                   ("history_tag_evidence.jsonl", tag_evidence),
                   ("history_counterevidence.jsonl", counterevidence)]:
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(name, "->", len(data))

# ---------------- merge into main view ----------------
added_by_level = collections.Counter()
cat_cand_add = 0
frag_rows = []
frag_map = {}
with open(os.path.join(OUT, "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        frag_rows.append(r)
        frag_map.setdefault(r["fragrance_id"], r)
ev_by = collections.defaultdict(list)
for e in tag_evidence:
    ev_by[e["fragrance_id"]].append(e)
cat_evidence_by_code = collections.defaultdict(set)
for ce in cat_evidence:
    if ce.get("category_id"):
        cat_evidence_by_code[ce["fragrance_id"]].add(ce["category_id"])

existing = collections.defaultdict(set)
with open(os.path.join(OUT, "fragrance_tags.jsonl"), encoding="utf-8") as f:
    for line in f:
        t = json.loads(line)
        if t.get("tag_id") and t.get("fragrance_id"):
            existing[(t["fragrance_id"], t["tag_id"], t.get("category_id") or "")].add(t.get("inference_type", "r1"))
new_rows = 0
with open(os.path.join(OUT, "fragrance_tags.jsonl"), "a", encoding="utf-8") as ftf:
    for code, evs in ev_by.items():
        r = frag_map.get(code)
        if not r:
            continue
        sr = r.get("source_row", 0)
        for e in evs:
            tag_id, cat, lvl, tname = e["tag_id"], e.get("category_id"), "", ""
            if tag_id in A_DICT:
                lvl, tname = A_DICT[tag_id][1], A_DICT[tag_id][2]
            elif tag_id in B_DICT:
                lvl, tname = "B", B_DICT[tag_id][2]
            elif tag_id in C_DICT:
                lvl, tname = "C", C_DICT[tag_id][4]
            else:
                continue
            key = (code, tag_id, cat or "")
            if key in existing:
                continue
            rec = {"fragrance_id": code, "category_id": cat, "tag_id": tag_id,
                   "tag_level": lvl, "tag_name": tname,
                   "inference_type": "history", "confidence": None, "status": "trial",
                   "source_row": sr,
                   "evidence": [{"work_order_id": e["work_order_id"], "direction": e["direction"],
                                 "kind": e["kind"], "note_ids": e["note_ids"], "sample_ids": e["sample_ids"],
                                 "source_text": f"工单{e['work_order_id']} {e['direction']}",
                                 "confidence": None, "date": now}]}
            ftf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added_by_level[lvl] += 1
            existing[key].add("history")
            new_rows += 1
    # category candidates: recommend-kind only
    for code, cev in cat_evidence_by_code.items():
        for r in frag_rows:
            if r["fragrance_id"] != code:
                continue
            cc = set(r.get("category_candidates") or [])
            cc.update(cev)
            if len(cc) != len(set(r.get("category_candidates") or [])):
                r["category_candidates"] = sorted(cc)
                cat_cand_add += 1
    # sync history tags into main-view ABC fields (dedupe with existing)
    def sync_tags(r):
        evs = ev_by.get(r["fragrance_id"], [])
        by_level = {"A1": set(r.get("tags_A1") or []), "A2": set(r.get("tags_A2") or []),
                    "A3": set(r.get("tags_A3") or []), "B": set(r.get("tags_B") or [])}
        c_by_cat = collections.defaultdict(set)
        for ck, cids in (r.get("tags_C_by_category") or {}).items():
            c_by_cat[ck].update(cids)
        for e in evs:
            tag_id = e["tag_id"]
            if tag_id in A_DICT:
                lvl = A_DICT[tag_id][1]
                if lvl in by_level:
                    by_level[lvl].add(tag_id)
            elif tag_id in B_DICT:
                by_level["B"].add(tag_id)
            elif tag_id in C_DICT:
                ccat = e.get("category_id") or C_CAT_ID.get(tag_id)
                if ccat:
                    c_by_cat[ccat].add(tag_id)
        r["tags_A1"] = sorted(by_level["A1"]); r["tags_A2"] = sorted(by_level["A2"])
        r["tags_A3"] = sorted(by_level["A3"]); r["tags_B"] = sorted(by_level["B"])
        r["tags_C_by_category"] = {k: sorted(v) for k, v in c_by_cat.items()}
    for r in frag_rows:
        sync_tags(r)
    with open(os.path.join(OUT, "fragrance.jsonl.tmp"), "w", encoding="utf-8") as tmp:
        for r in frag_rows:
            tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("tags added:", new_rows, "by level:", dict(added_by_level),
          "| rows w/ new candidates:", cat_cand_add)

os.replace(os.path.join(OUT, "fragrance.jsonl.tmp"), os.path.join(OUT, "fragrance.jsonl"))
print("merged fragrance.jsonl:", len(frag_rows), "rows")

# ---------------- review queue ----------------
rev = os.path.join(DOCS, "review_queue.xlsx")
import openpyxl
wb = openpyxl.load_workbook(rev)
ws = wb["复核清单"]
n0 = ws.max_row
for g in gap_rows:
    ws.append(["r2", g["task_id"], g["wo_number"], "字典缺口/标签无法映射", g["text"], "", ""])
for e in errors:
    ws.append(["r2", e["task_id"], e["wo_number"], "校验错误", e["text"], "", ""])
wb.save(rev)
print("review_queue appended:", ws.max_row - n0, "(gaps", len(gap_rows), "| errors", len(errors), ")")

# ---------------- manifest ----------------
mpath = os.path.join(OUT, "batch_manifest.json")
m = json.load(open(mpath, encoding="utf-8"))
m["round2"] = {
    "tasks_total": len(tasks), "results": len(results),
    "with_samples": sum(1 for t in tasks.values() if t.get("has_lib_sample")),
    "reused": sum(1 for t in tasks.values() if t.get("reused")),
    "tag_evidence": len(tag_evidence), "category_evidence": len(cat_evidence),
    "relations": len(relations), "counterevidence": len(counterevidence),
    "gaps": len(gap_rows), "errors": len(errors),
    "tags_added": new_rows, "tags_added_by_level": dict(added_by_level),
    "candidate_rows": cat_cand_add,
}
with open(mpath, "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False, indent=2)
print("manifest updated")
