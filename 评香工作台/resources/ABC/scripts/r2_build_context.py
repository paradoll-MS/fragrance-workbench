# -*- coding: utf-8 -*-
"""Round 2 ETL step 2: build per-work-order context JSONs (§2.1 compact format),
canonical tables (work_orders/samples/notes/mentions), library prior tags,
and the task manifest. Outputs _work/r2/contexts.jsonl + tasks.json."""
import json, os, re, sqlite3, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "output")
R2 = os.path.join(WS, "_work", "r2")
DB = os.path.join(R2, "香精工单.sqlite3")

# ---------- library + tags ----------
lib = {}          # code -> {name, categories, tags...}
lib_name = {}
with open(os.path.join(OUT, "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        c = r["fragrance_id"]
        lib[c] = r
        lib_name.setdefault(r["fragrance_name"], c)

# tag labels
def load_ids(fname):
    ids = {}
    with open(os.path.join(WS, "_work", fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0]:
                ids[p[0]] = p[2] if len(p) > 2 else p[1]
    return ids
A_LABEL = load_ids("tags_A.txt")
B_LABEL = load_ids("tags_B.txt")
C_LABEL = load_ids("tags_C.txt")   # id -> 标签 (path)
C_PATH = {}
with open(os.path.join(WS, "_work", "tags_C.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 7 and p[0]:
            C_PATH[p[0]] = p[6]
CAT_NAME = {}
with open(os.path.join(WS, "_work", "categories.txt"), encoding="utf-8") as f:
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

# ---------- sqlite ----------
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("PRAGMA table_info(`w_bo_gd_20250707155940`)")
wo_cols = [c[1] for c in cur.fetchall()]
cur.execute("SELECT * FROM `w_bo_gd_20250707155940`")
wo_rows = {r[0]: dict(zip(wo_cols, r)) for r in cur.fetchall()}
cur.execute("PRAGMA table_info(`w_wo_sample_details`)")
sd_cols = [c[1] for c in cur.fetchall()]
cur.execute("SELECT * FROM `w_wo_sample_details`")
sd_rows = [dict(zip(sd_cols, r)) for r in cur.fetchall()]

def clean_analysis(t):
    # F_WO_ANALYSIS is often JSON attachment metadata; keep only readable non-JSON text
    if not t:
        return ""
    t = t.strip()
    if t.startswith("[{") or t.startswith("{"):
        try:
            d = json.loads(t)
            if isinstance(d, list):
                return ""
        except json.JSONDecodeError:
            pass
    return t

def body_notes(w):
    parts = []
    for col in ["F_AROMA_AND_CHARM_V1", "F_WO_EVALUATION_REMARK", "F_WO_FLAVOR_REMARK", "F_WO_CONTRAST"]:
        v = w.get(col) or ""
        v = clean_analysis(v)
        if v and v not in ("-",):
            parts.append(v)
    ana = clean_analysis(w.get("F_WO_ANALYSIS") or "")
    if ana:
        parts.append(ana)
    return parts

def title_of(w):
    t = (w.get("F_WO_TITLE") or "").strip()
    if t and t != "-":
        return t
    p = (w.get("F_WO_PROJNAME_NAME") or "").strip()
    if p:
        return p
    b = body_notes(w)
    return (b[0][:60] if b else w.get("F_WO_NUMBER", ""))

# ---------- build tasks ----------
CODE_PAT = re.compile(r"\b(?:\d{4,5}[A-Z]{0,2}|[A-Z]{2,3}\d{3,5}[A-Z]{0,3})\b")
tasks = []
seen_codes = set()

detail_by_wo = collections.defaultdict(list)
for d in sd_rows:
    if d.get("REF_ID_"):
        detail_by_wo[d["REF_ID_"]].append(d)

for wid, w in sorted(wo_rows.items()):
    samples = []
    for d in detail_by_wo.get(wid, []):
        code = (d.get("F_SAMPLE_INNER_NUMBER_NAME") or "").strip()
        if not code:
            continue
        samples.append({
            "sid": d.get("ID_"), "code": code,
            "name": (d.get("F_SAMPLE_INNER_NAME") or "").strip(),
            "customer_name": (d.get("F_SAMPLE_NAME") or "").strip(),
            "feedback": (d.get("F_SAMPLE_FEEDBACK") or "").strip(),
            "flavor_eval": (d.get("F_SAMPLE_FLAVOR_NAME") or "").strip(),
            "quote": (d.get("F_SAMPLE_QUOTE") or "").strip(),
        })
    notes = body_notes(w)
    body = "\n".join(notes)
    mentions = {m for m in CODE_PAT.findall(body) if m in lib and m not in
                {s["code"] for s in samples}}
    if not samples and not mentions:
        continue
    has_lib_sample = any(s["code"] in lib for s in samples)
    if not has_lib_sample and not mentions:
        continue  # only non-library samples: no library increment possible
    tasks.append({
        "task_id": wid,
        "wo_number": w.get("F_WO_NUMBER") or "",
        "old_category": w.get("F_WO_SUB_CATEGORY_NAME") or "",
        "title": title_of(w),
        "project_name": w.get("F_WO_PROJNAME_NAME") or "",
        "notes": notes,
        "samples": samples,
        "mentions": sorted(mentions),
        "has_lib_sample": has_lib_sample,
    })
    for s in samples:
        if s["code"] in lib:
            seen_codes.add(s["code"])
    seen_codes |= mentions

with_samples = [t for t in tasks if t["has_lib_sample"]]
mention_only = [t for t in tasks if not t["has_lib_sample"] and t["mentions"]]
print("总任务:", len(tasks), "| 有用样:", len(with_samples), "| 仅提及:", len(mention_only))
print("覆盖在库款:", len(seen_codes))

with open(os.path.join(R2, "tasks.json"), "w", encoding="utf-8") as f:
    json.dump({"tasks": tasks, "task_count": len(tasks),
               "with_samples": len(with_samples), "mention_only": len(mention_only),
               "library_codes_covered": len(seen_codes)}, f, ensure_ascii=False, indent=2)

# ---------- per-task compact context (§2.1) ----------
def compact(t):
    samples = []
    for i, s in enumerate(t["samples"], 1):
        entry = {"s": i, "code": s["code"], "in_library": s["code"] in lib}
        if s["name"]:
            entry["name"] = s["name"]
        if s["customer_name"]:
            entry["customer_name"] = s["customer_name"]
        if s["feedback"]:
            entry["feedback"] = s["feedback"]
        if s["flavor_eval"] and s["flavor_eval"] != "未评估":
            entry["flavor_eval"] = s["flavor_eval"]
        p = prior_compact(s["code"]) if entry["in_library"] else None
        if p:
            entry["prior"] = p
        samples.append(entry)
    notes = [{"n": i, "kind": "work_requirement", "text": n,
              "samples": [j for j, s in enumerate(t["samples"], 1)
                          if any(k in n for k in [s["code"], s["name"], s["customer_name"]] if k)]}
             for i, n in enumerate(t["notes"], 1)]
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

with open(os.path.join(R2, "contexts.jsonl"), "w", encoding="utf-8") as f:
    for t in tasks:
        f.write(json.dumps(compact(t), ensure_ascii=False) + "\n")
print("wrote contexts.jsonl:", len(tasks))

# sample output
with open(os.path.join(R2, "contexts.jsonl"), encoding="utf-8") as f:
    first = json.loads(f.readline())
print("sample context keys:", list(first.keys()))
