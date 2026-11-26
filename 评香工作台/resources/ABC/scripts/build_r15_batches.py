# -*- coding: utf-8 -*-
"""Round 1.5: build LLM input batches for rows with 评香字段.
Each row carries: original review fields + round-1 final tags (baseline).
Context: slim dicts + full C tree (gates+leaves) + 判定补充 for involved categories.
"""
import json, os, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
R15 = os.path.join(WORK, "r15")
os.makedirs(os.path.join(R15, "ctx"), exist_ok=True)
BATCH_SIZE = 30

def load_tsv_list(fname, has_header=True):
    out = []
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        if has_header:
            f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            out.append(p)
    return out

# dicts for context: id -> 标签 (A/B)
A_rows = [p for p in load_tsv_list("tags_A.txt") if p[0]]
B_rows = [p for p in load_tsv_list("tags_B.txt") if p[0]]
A_LABEL = {p[0]: p[2] for p in A_rows}
B_LABEL = {p[0]: p[2] for p in B_rows}
A_LEVEL = {p[0]: p[1] for p in A_rows}
B_LEVEL = {p[0]: p[1] for p in B_rows}

# C tree: id -> row (id,品类,维度,父ID,标签,节点类型,完整路径)
C_rows = [p for p in load_tsv_list("tags_C.txt") if p[0]]
C_BY_ID = {p[0]: p for p in C_rows}
C_NAME_BY_ID = {p[0]: p[5] for p in C_rows}
C_PATH_BY_ID = {p[0]: p[6] for p in C_rows}

# 判定补充 keyed by C id
C_SUPP = {}
with open(os.path.join(WORK, "c_decision.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            C_SUPP[p[0]] = p[1] if len(p) > 1 else ""

# categories (id + 中文名)
cats = {}
with open(os.path.join(WORK, "categories.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            cats[p[0]] = p[1]
CAT_NAME = {cid: cats[cid] for cid in cats}

# original library rows
orig_rows = []
with open(os.path.join(WORK, "original_library.tsv"), encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i == 0:
            continue
        p = line.rstrip("\n").split("\t")
        if not any(p):
            continue
        while len(p) < 30:
            p.append("")
        orig_rows.append(p)

with open(os.path.join(WORK, "join_map.json"), encoding="utf-8") as f:
    join_map = json.load(f)

with open(os.path.join(WORK, "review_rows.json"), encoding="utf-8") as f:
    review_rows = json.load(f)  # [[sr, orig_idx], ...]

# round-1 main view -> per source_row record (merged records shared across source_rows)
r1_by_sr = {}
with open(os.path.join(WS, "output", "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        for sr in rec.get("source_rows", [rec["source_row"]]):
            r1_by_sr[sr] = rec

def review_context(sr):
    oi = join_map.get(str(sr))
    if oi is None:
        return {}
    o = orig_rows[oi]
    ctx = {
        "香族": o[5].strip(), "子香族": o[6].strip(), "三调": o[7].strip(),
        "主韵关键词": o[8].strip(), "风格": o[9].strip(), "概念/系列": o[10].strip(),
        "经典/流行/小众": o[11].strip(), "情绪感受": o[12].strip(), "人格特质": o[13].strip(),
        "联觉": o[14].strip(), "联觉-细分": o[15].strip(), "联觉-词汇": o[16].strip(),
        "借鉴品牌": o[17].strip(), "借鉴产品名称": o[18].strip(),
    }
    return {k: v for k, v in ctx.items() if v}

def r1_compact(rec):
    def lab(tid):
        if tid.startswith("A"):
            return f"{tid}:{A_LABEL.get(tid, '?')}"
        if tid.startswith("B"):
            return f"{tid}:{B_LABEL.get(tid, '?')}"
        return tid
    c = {
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
    return c

rows_out = []
for sr_raw, oi in review_rows:
    sr = int(sr_raw)
    r1 = r1_by_sr.get(sr)
    if r1 is None:
        continue
    rows_out.append({
        "source_row": sr,
        "fragrance_id": r1["fragrance_id"],
        "fragrance_name": r1["fragrance_name"],
        "review": review_context(sr),
        "r1": r1_compact(r1),
    })
print("r15 input rows:", len(rows_out))

# split into batches
batches = []
for i in range(0, len(rows_out), BATCH_SIZE):
    batches.append(rows_out[i:i + BATCH_SIZE])
print("batches:", len(batches))

for bi, batch in enumerate(batches):
    bid = f"batch_{bi:03d}"
    cats_in = {c for r in batch for c in r["r1"]["category_ids"]}
    # C tree slice for involved categories (gates + leaves, full rows)
    c_lines = []
    for cid, crow in C_BY_ID.items():
        if crow[1] in (CAT_NAME.get(c) for c in cats_in):
            supp = C_SUPP.get(cid, "")
            c_lines.append(f"{cid} | {crow[1]} | {crow[2]} | {crow[5]} | {crow[6]} | {supp}")
    ctx = {
        "batch_id": bid,
        "rows": batch,
        "C_tree": c_lines,
    }
    with open(os.path.join(R15, "ctx", f"{bid}.jsonl"), "w", encoding="utf-8") as f:
        for r in batch:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(R15, "ctx", f"{bid}_ctx.json"), "w", encoding="utf-8") as f:
        json.dump({"C_tree": c_lines}, f, ensure_ascii=False)
print("wrote batches to", os.path.join(R15, "ctx"))
