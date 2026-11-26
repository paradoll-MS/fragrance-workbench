# -*- coding: utf-8 -*-
"""Round 1.5 fix pass: rebuild LLM batches ONLY for rows whose review fields were corrected
by the direct-XLSX re-read. Batch ids start at batch_100 to avoid clashing with batch_000..048."""
import json, os, re, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
R15 = os.path.join(WORK, "r15")
CTX = os.path.join(R15, "ctx")
BATCH_SIZE = 30

def load_tsv_list(fname, has_header=True):
    out = []
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        if has_header:
            f.readline()
        for line in f:
            out.append(line.rstrip("\n").split("\t"))
    return out

A_rows = [p for p in load_tsv_list("tags_A.txt") if p[0]]
B_rows = [p for p in load_tsv_list("tags_B.txt") if p[0]]
A_LABEL = {p[0]: p[2] for p in A_rows}
B_LABEL = {p[0]: p[2] for p in B_rows}
C_rows = [p for p in load_tsv_list("tags_C.txt") if p[0]]
C_BY_ID = {p[0]: p for p in C_rows}
C_NAME_BY_ID = {p[0]: p[5] for p in C_rows}
cats = {}
with open(os.path.join(WORK, "categories.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            cats[p[0]] = p[1]
CAT_NAME = cats

# corrected fields keyed by source_row
orig_fixed = {}
with open(os.path.join(WORK, "original_library_fixed.jsonl"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rec = json.loads(line)
            orig_fixed[rec["source_row"]] = rec

# old (corrupted) values: TSV + old join_map
old_tsv = []
with open(os.path.join(WORK, "original_library.tsv"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        while len(p) < 30:
            p.append("")
        old_tsv.append(p)
with open(os.path.join(WORK, "join_map.json"), encoding="utf-8") as f:
    old_idx = {int(k): v for k, v in json.load(f).items()}

REVIEW_COLS = {5: "香族", 6: "子香族", 7: "三调", 8: "主韵关键词", 9: "风格", 10: "概念/系列",
               11: "经典/流行/小众", 12: "情绪感受", 13: "人格特质", 14: "联觉", 15: "联觉-细分", 16: "联觉-词汇",
               17: "借鉴品牌", 18: "借鉴产品名称"}

def cell(v):
    return str(v).strip() if v not in (None, "") else ""

# find rows whose REVIEW fields changed
fixed_review = []
for sr, rec in sorted(orig_fixed.items()):
    oi = old_idx.get(sr)
    if oi is None:
        continue
    old = old_tsv[oi]
    changed = [fname for col, fname in REVIEW_COLS.items()
               if cell(rec.get(fname, "")) != cell(old[col] if len(old) > col else "")]
    if changed:
        fixed_review.append((sr, changed))
print("rows with corrected REVIEW fields:", len(fixed_review))
fc = collections.Counter()
for sr, ch in fixed_review:
    for f in ch:
        fc[f] += 1
for f, n in fc.most_common():
    print(f"  {f}: {n}")

# round-1 main view per source_row
r1_by_sr = {}
with open(os.path.join(WS, "output", "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        for sr in rec.get("source_rows", [rec["source_row"]]):
            r1_by_sr[sr] = rec

def review_context(rec):
    ctx = {fname: rec.get(fname, "").strip() for fname in
           ["香族", "子香族", "三调", "主韵关键词", "风格", "概念/系列", "经典/流行/小众",
            "情绪感受", "人格特质", "联觉", "联觉-细分", "联觉-词汇", "借鉴品牌", "借鉴产品名称"]}
    return {k: v for k, v in ctx.items() if v}

def r1_compact(rec):
    def lab(tid):
        if tid.startswith("A"):
            return f"{tid}:{A_LABEL.get(tid, '?')}"
        if tid.startswith("B"):
            return f"{tid}:{B_LABEL.get(tid, '?')}"
        return tid
    return {
        "category_ids": rec["category_ids"],
        "tags_A1": [lab(t) for t in rec["tags_A1"]],
        "tags_A2": [lab(t) for t in rec["tags_A2"]],
        "tags_A3": [lab(t) for t in rec["tags_A3"]],
        "tags_B": [lab(t) for t in rec["tags_B"]],
        "tags_C": {ck: [f"{tid}:{C_NAME_BY_ID.get(tid, '?')}" for tid in cids]
                   for ck, cids in rec["tags_C_by_category"].items()},
        "dupe_status": rec["dupe_status"],
        "product_candidates": sorted({(pc.get("brand_name") or "") + "/" + (pc.get("product_name") or "")
                                      for pc in rec["product_candidates"]}),
        "unresolved_terms": rec.get("unresolved_terms", []),
    }

rows_out = []
for sr, _ch in fixed_review:
    r1 = r1_by_sr.get(sr)
    if r1 is None:
        continue
    rows_out.append({
        "source_row": sr,
        "fragrance_id": r1["fragrance_id"],
        "fragrance_name": r1["fragrance_name"],
        "review": review_context(orig_fixed[sr]),
        "r1": r1_compact(r1),
    })
print("fix-pass input rows:", len(rows_out))

batches = [rows_out[i:i + BATCH_SIZE] for i in range(0, len(rows_out), BATCH_SIZE)]
print("fix batches:", len(batches))
for bi, batch in enumerate(batches):
    bid = f"batch_{100 + bi:03d}"
    cats_in = {c for r in batch for c in r["r1"]["category_ids"]}
    c_lines = []
    for cid, crow in C_BY_ID.items():
        if crow[1] in (CAT_NAME.get(c) for c in cats_in):
            c_lines.append(f"{cid} | {crow[1]} | {crow[2]} | {crow[5]} | {crow[6]}")
    with open(os.path.join(CTX, f"{bid}.jsonl"), "w", encoding="utf-8") as f:
        for r in batch:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(CTX, f"{bid}_ctx.json"), "w", encoding="utf-8") as f:
        json.dump({"C_tree": c_lines}, f, ensure_ascii=False)
print("wrote", len(batches), "fix batches (batch_100+)")
