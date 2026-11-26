# -*- coding: utf-8 -*-
"""v4: slim per-agent context (fit small context windows) — no alias list, minimal fields."""
import json, os, re, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
BATCH = os.path.join(WORK, "batches")
CTX = os.path.join(WORK, "ctx")
SLIM = os.path.join(CTX, "slim")
os.makedirs(SLIM, exist_ok=True)

def load_tsv(fname, key_col=0):
    out = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[key_col]:
                out[p[key_col]] = p
    return out

A = load_tsv("tags_A.txt")   # id, level, label, desc, parent
B = load_tsv("tags_B.txt")
C = load_tsv("tags_C.txt")   # id, cat, dim, parent, label, ntype, path
cats = load_tsv("categories.txt")
brands = load_tsv("brands.txt")
products = load_tsv("products.txt")
legacy_cat = load_tsv("legacy_category_map.txt")
legacy_fam = load_tsv("legacy_family_map.txt")
cdec = load_tsv("c_decision.txt")

CAT_NAME = {k: v[1] for k, v in cats.items()}

# ---- 1. slim shared dicts ----
lines = []
lines.append("===== 应用品类 (CAT_xx 代码\t品类名) =====")
for k in sorted(cats):
    lines.append(f"{k}\t{cats[k][1]}")
lines.append("")
lines.append("===== A标签 (id\t层级\t标签名) — 直接输出用 =====")
for k in sorted(A):
    lines.append(f"{k}\t{A[k][1]}\t{A[k][2]}")
lines.append("")
lines.append("===== B标签 (id\t层级\t标签名) =====")
for k in sorted(B):
    lines.append(f"{k}\t{B[k][1]}\t{B[k][2]}")
lines.append("")
lines.append("===== 品牌 (brand_id\t品牌名) =====")
for k in sorted(brands):
    lines.append(f"{k}\t{brands[k][1]}")
lines.append("")
lines.append("===== C判定补充 (要点) =====")
seen = set()
for k in sorted(cdec):
    line = "\t".join(cdec[k])
    if line not in seen:
        seen.add(line)
        lines.append(line)
lines.append("")
lines.append("===== 旧品类→品类 转换 (旧二级\t转换结果或说明) =====")
for k in sorted(legacy_cat):
    lines.append(f"{k}\t{legacy_cat[k][1]}")
lines.append("")
lines.append("===== 旧香族→A3 转换 (旧子香族\tA3名 或 '保留') =====")
for k in sorted(legacy_fam):
    lines.append(f"{k}\t{legacy_fam[k][1]}")
with open(os.path.join(SLIM, "dicts.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("slim dicts bytes:", os.path.getsize(os.path.join(SLIM, "dicts.txt")))

# ---- 2. per-batch slim C + products + batch.jsonl ----
for bf in sorted(f for f in os.listdir(BATCH) if re.fullmatch(r"batch_\d{3}\.jsonl", f)):
    bid = bf.replace(".jsonl", "")
    rows = []
    with open(os.path.join(CTX, bid, "batch.jsonl"), encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    # categories needed
    cat_set = set()
    prod_ids = set()
    brand_ids = set()
    slim_rows = []
    for r in rows:
        bl = r.get("baseline", {})
        for cid in bl.get("category_ids", []):
            cat_set.add(cid)
        for pc in bl.get("product_candidates", []):
            if pc.get("product_id"):
                prod_ids.add(pc["product_id"])
            if pc.get("brand_id"):
                brand_ids.add(pc["brand_id"])
        for ph in r.get("input", {}).get("name_product_hits", []):
            if ph.get("product_id"):
                prod_ids.add(ph["product_id"])
        for bh in r.get("input", {}).get("name_brand_hits", []):
            if bh.get("brand_id"):
                brand_ids.add(bh["brand_id"])
        if r.get("input", {}).get("brand_only_hint"):
            brand_ids.add(r["input"]["brand_only_hint"]["brand_id"])
        inp = r["input"]
        slim_rows.append({
            "source_row": inp["source_row"],
            "fragrance_id": inp.get("fragrance_id", ""),
            "fragrance_name": inp.get("fragrance_name", ""),
            "old_cat2": inp.get("old_cat2", ""),
            "cat_remark": inp.get("cat_remark", ""),
            "cat_id_screen": inp.get("cat_id_screen", ""),
            "cat_screen": inp.get("cat_screen", ""),
            "a3_id_screen": inp.get("a3_id_screen", ""),
            "a3_cn_screen": inp.get("a3_cn_screen", ""),
            "is_new": inp.get("is_new", 0),
            "is_hot": inp.get("is_hot", 0),
            "dupe_status_screen": inp.get("dupe_status_screen", ""),
            "draft_product_candidates": [{"brand_id": d.get("brand_id"), "product_id": d.get("product_id"),
                                          "brand": d.get("brand"), "product_name": d.get("product_name"),
                                          "matched_alias": d.get("matched_alias"), "relation_status": d.get("relation_status")}
                                         for d in inp.get("draft_product_candidates", [])],
            "brand_only_hint": inp.get("brand_only_hint"),
            "name_tag_hits": [{"term_id": h.get("term_id"), "alias": h.get("alias", ""), "scope": h.get("scope", "")}
                              for h in inp.get("name_tag_hits", [])],
            "name_brand_hits": [{"brand_id": h.get("brand_id"), "alias": h.get("alias", "")}
                                for h in inp.get("name_brand_hits", [])],
            "name_product_hits": [{"product_id": h.get("product_id"), "alias": h.get("alias", "")}
                                  for h in inp.get("name_product_hits", [])],
            "input_hash": inp.get("input_hash", ""),
            "baseline": bl,
        })
    # C slim: only leaves of involved categories, id+label+path
    c_lines = ["id\t品类\t标签\t完整标签路径"]
    for cid in sorted(cat_set):
        cat_name = CAT_NAME.get(cid, "")
        for k, v in C.items():
            if v[1] == cat_name and v[5] == "叶子":
                c_lines.append(f"{k}\t{cat_name}\t{v[4]}\t{v[6]}")
    with open(os.path.join(SLIM, f"{bid}_C.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(c_lines) + "\n")
    # products slim
    p_lines = ["product_id\t品牌\t产品名\t别名\t存在核验"]
    for pid in sorted(prod_ids):
        if pid in products:
            p = products[pid]
            p_lines.append(f"{pid}\t{p[2]}\t{p[3]}\t{p[4]}\t{p[6] if len(p) > 6 else ''}")
    with open(os.path.join(SLIM, f"{bid}_products.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(p_lines) + "\n")
    with open(os.path.join(SLIM, f"{bid}_batch.jsonl"), "w", encoding="utf-8") as f:
        for r in slim_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("slim ctx built")

# size check
tot = 0
for f in os.listdir(SLIM):
    tot += os.path.getsize(os.path.join(SLIM, f))
print("slim dir total bytes:", tot)
