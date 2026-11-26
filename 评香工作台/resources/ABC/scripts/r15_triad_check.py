# -*- coding: utf-8 -*-
"""r15_triad_check.py — 三调仅用于 A3/C:核查 fix 批(batch_100+)新增的 A1/A2,
若该标签只出现在三调原文、未出现在主韵/香族/子香族/风格等非三调字段 → 判定为三调驱动,生成移除批。
输出 _work/r15/batch_200_result.jsonl + _work/r15/triad_removals.jsonl(复核清单)。
"""
import json, os, re, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
R15 = os.path.join(WORK, "r15")

# tags_A: id -> [level, label]
A = {}
with open(os.path.join(WORK, "tags_A.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if p[0]:
            A[p[0]] = (p[1], p[2])

# fixed library rows
fixed = {}
with open(os.path.join(WORK, "original_library_fixed.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        fixed[r["source_row"]] = r

# fragrance name by source_row (name-based inference is legitimate evidence)
name_by_sr = {}
with open(os.path.join(WS, "output", "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("source_row") is not None:
            name_by_sr.setdefault(r["source_row"], r.get("fragrance_name", ""))

NON_TRIAD_FIELDS = ["香族", "子香族", "主韵关键词", "风格", "概念/系列", "经典/流行/小众",
                    "情绪感受", "人格特质", "联觉", "联觉-细分", "联觉-词汇",
                    "借鉴品牌", "借鉴产品名称"]

def non_triad_text(fr):
    parts = []
    for k in NON_TRIAD_FIELDS:
        v = fr.get(k)
        if v:
            parts.append(str(v))
    return "\n".join(parts)

def triad_text(fr):
    v = fr.get("三调")
    return str(v) if v else ""

# fix batches (batch_100..152)
fix_files = sorted(f for f in os.listdir(R15) if re.fullmatch(r"batch_1\d\d_result\.jsonl", f) or re.fullmatch(r"batch_15[0-2]_result\.jsonl", f))
print("fix batches:", len(fix_files))

removals = []        # per-row removal records for batch_200
audit = []           # review lines
kept = 0
n_added = 0
for fn in fix_files:
    with open(os.path.join(R15, fn), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            sr = rec.get("source_row")
            if sr is None:
                continue
            fr = fixed.get(sr)
            adds = list(rec.get("tags_A1_add") or []) + list(rec.get("tags_A2_add") or [])
            if not adds:
                continue
            n_added += len(adds)
            nt = non_triad_text(fr) if fr else ""
            nm = name_by_sr.get(sr, "")
            nt = (nt + "\n" + nm) if nm else nt
            tt = triad_text(fr) if fr else ""
            to_remove = []
            for tid in adds:
                if tid not in A:
                    continue
                lvl, label = A[tid]
                if lvl not in ("A1", "A2"):
                    continue
                lab = label
                if not lab:
                    continue
                in_non_triad = lab in nt
                in_triad = lab in tt
                if in_non_triad:
                    kept += 1
                    continue
                if in_triad:
                    # appears only in 三调 -> triad-driven A1/A2 -> remove
                    to_remove.append(tid)
                    audit.append({"source_row": sr, "tag_id": tid, "level": lvl,
                                  "label": lab, "basis": "仅三调原文出现"})
                else:
                    # not found in either -> keep (basis unknown, avoid over-removal)
                    kept += 1
            if to_remove:
                rec2 = {"source_row": sr, "tags_A1_remove": [], "tags_A2_remove": [],
                        "tags_A1_add": [], "tags_A2_add": [], "tags_A3_add": [], "tags_A3_remove": [],
                        "tags_B_add": [], "tags_B_remove": [], "tags_C_add": {}, "tags_C_remove": {},
                        "category_ids": None, "category_candidates": [],
                        "product_candidates_add": [], "product_candidates_remove": [],
                        "dupe_status": None, "notes": "三调驱动A1/A2修订(三调仅用于A3/C)"}
                for tid in to_remove:
                    lvl = A[tid][0]
                    rec2[f"tags_{lvl}_remove"].append(tid)
                removals.append(rec2)

print("fix批 A1/A2 新增标签:", n_added, "| 保留(有主韵/香族/风格依据):", kept,
      "| 移除(仅三调驱动):", sum(len(r[f"tags_{A[t][0]}_remove"]) for r in removals for t in []))
removed_total = sum(len(r["tags_A1_remove"]) + len(r["tags_A2_remove"]) for r in removals)
print("移除标签总数:", removed_total, "| 涉及行:", len(removals))

with open(os.path.join(R15, "batch_200_result.jsonl"), "w", encoding="utf-8") as f:
    for r in removals:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(os.path.join(R15, "triad_removals.jsonl"), "w", encoding="utf-8") as f:
    for a in audit:
        f.write(json.dumps(a, ensure_ascii=False) + "\n")
print("wrote batch_200_result.jsonl (", len(removals), "rows ) + triad_removals.jsonl (", len(audit), ")")

# level breakdown
c = collections.Counter()
for a in audit:
    c[a["level"]] += 1
print("removal by level:", dict(c))
