# -*- coding: utf-8 -*-
"""v3: bundle shared dicts into one file; pre-fill per-row baseline; build ctx dirs."""
import json, os, shutil, collections, re

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
BATCH = os.path.join(WORK, "batches")
CTX = os.path.join(WORK, "ctx")

# ---- 1. bundle shared dicts ----
SHARED = os.path.join(CTX, "shared")
os.makedirs(SHARED, exist_ok=True)
bundle = []
for f in ["categories.txt", "tags_A.txt", "tags_B.txt", "alias_AB.txt", "brands.txt", "c_decision.txt"]:
    with open(os.path.join(WORK, f), encoding="utf-8") as g:
        bundle.append(f"===== FILE: {f} =====")
        bundle.append(g.read())
legacy = []
for f in ["legacy_category_map.txt", "legacy_family_map.txt"]:
    with open(os.path.join(WORK, f), encoding="utf-8") as g:
        legacy.append(f"===== FILE: {f} =====")
        legacy.append(g.read())
bundle.append("===== FILE: legacy.txt =====")
bundle.append("\n".join(legacy))
with open(os.path.join(SHARED, "dicts.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(bundle))
print("dicts.txt size:", os.path.getsize(os.path.join(SHARED, "dicts.txt")))

# ---- 2. load dictionaries for baseline pre-fill ----
def load_tsv(fname, key_col=0):
    out = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[key_col]:
                out[p[key_col]] = p
    return out

A = load_tsv("tags_A.txt")          # id -> [id, level, label, desc, parent]
B = load_tsv("tags_B.txt")
C = load_tsv("tags_C.txt")          # id -> [id, cat, dim, parent, label, ntype, path]
cats = load_tsv("categories.txt")
brands = load_tsv("brands.txt")
products = load_tsv("products.txt")

CAT_NAME = {k: v[1] for k, v in cats.items()}
C_LEAF_BY_CAT = collections.defaultdict(list)
for k, v in C.items():
    if v[5] == "叶子":
        C_LEAF_BY_CAT[v[1]].append(k)

def C_LEAF_LINES(cat):
    out = []
    for k, v in C.items():
        if v[1] == cat:
            out.append("\t".join(v))
    return out

# clear-cut C mappings (name/context -> C leaf per category), conservative subset
CLEAR_C = {
    ("空间香氛", "茶"): "C_954",      # 茶香调
    ("空间香氛", "木质"): "C_958",    # 木质调
    ("空间香氛", "东方"): "C_960",    # 东方调
    ("空间香氛", "花香"): "C_948",    # 花香调
    ("身体洗护", "香水"): "C_376",    # 香氛护理-香水转化
    ("织物护理", "香水"): "C_980",    # 香氛护理-香水转化
    ("头发洗护", "香水"): "C_502",    # 香氛护理-香水转化
    ("面部洗护", "香水"): "C_1244",   # placeholder; verified below
    ("个人香氛", "花香西普"): "C_314",
    ("个人香氛", "花香调"): "C_272",
}

# verify placeholders exist & are leaves of right category
for (cat, kw), cid in list(CLEAR_C.items()):
    if cid not in C or C[cid][5] != "叶子" or C[cid][1] != cat:
        print(f"  fix CLEAR_C {(cat,kw)} -> {cid}: {C.get(cid, ('MISSING',))}")
        # fallback: search leaf by label contains kw
        hits = [k for k, v in C.items() if v[5] == "叶子" and v[1] == cat and kw in v[4]]
        if hits:
            CLEAR_C[(cat, kw)] = hits[0]
            print(f"    -> replaced with {hits[0]} ({C[hits[0]][4]})")
        else:
            del CLEAR_C[(cat, kw)]
            print("    -> dropped (no leaf)")

# ---- 3. pre-fill baselines per row ----
batch_files = sorted(f for f in os.listdir(BATCH) if re.fullmatch(r"batch_\d{3}\.jsonl", f))
print("batch files:", len(batch_files))

B5_SHUISHUI = "B5_dd6d753261"  # 香水感

def prefilled_tags(row):
    """Deterministic baseline from input hints + rules."""
    tag_hits = row.get("name_tag_hits", [])
    a1 = []
    a2 = []
    a3 = []
    for h in tag_hits:
        tid = h.get("term_id", "")
        if tid.startswith("A1") and tid not in a1:
            a1.append(tid)
        elif tid.startswith("A2") and tid not in a2:
            a2.append(tid)
        elif tid.startswith("A3") and tid not in a3:
            a3.append(tid)
    if row.get("a3_id_screen") and row["a3_id_screen"] not in a3:
        a3.append(row["a3_id_screen"])
    # B: clear-cut 香水感 for 身体洗护/织物护理/头发洗护/面部洗护 with 香水/香氛 context in name
    b = []
    name = row.get("fragrance_name", "")
    cat = row.get("cat_screen", "")
    if any(k in name for k in ("香水", "香氛")) and cat in ("身体洗护", "织物护理", "头发洗护", "面部洗护"):
        b.append(B5_SHUISHUI)
    return a1, a2, a3, b

def prefilled_c(row, cat_ids):
    """Clear-cut C candidates; conservative."""
    name = row.get("fragrance_name", "")
    out = {}
    for cid in cat_ids:
        cat = CAT_NAME.get(cid, "")
        hits = []
        for (ccat, kw), cleaf in CLEAR_C.items():
            if ccat == cat and kw in name:
                hits.append(cleaf)
        # also check scent_name normalized
        sn = row.get("scent_name", "") or name
        for (ccat, kw), cleaf in CLEAR_C.items():
            if ccat == cat and kw in sn:
                if cleaf not in hits:
                    hits.append(cleaf)
        if hits:
            out[cid] = sorted(set(hits))
    return out

def build_baseline(row):
    cat_ids = []
    if row.get("cat_id_screen"):
        cat_ids.append(row["cat_id_screen"])
    cat_ids = sorted(set(cat_ids))
    a1, a2, a3, b = prefilled_tags(row)
    c = prefilled_c(row, cat_ids)
    # product candidates from draft
    pcs = []
    for pc in row.get("draft_product_candidates", []):
        pcs.append({
            "brand_id": pc.get("brand_id"),
            "product_id": pc.get("product_id"),
            "brand_name": pc.get("brand") or "",
            "product_name": pc.get("product_name") or "",
            "edition": None,
            "matched_alias": pc.get("matched_alias") or "",
            "identity_status": "verified" if pc.get("identity_status") and "已核验" in str(pc.get("identity_status")) else "待核验",
            "relation_status": "strong_candidate" if pc.get("relation_status") == "名称强线索候选" else ("ambiguous" if pc.get("relation_status") == "歧义候选" else "candidate"),
        })
    # dupe status from draft/brand-only
    if row.get("brand_only_hint"):
        ds = "brand_only"
    elif any(pc.get("relation_status") == "strong_candidate" for pc in pcs):
        ds = "strong_candidate"
    elif pcs:
        ds = "ambiguous"
    else:
        ds = "unidentified"
    # evidence auto
    ev = []
    for tid in a1:
        h = next((x for x in row.get("name_tag_hits", []) if x.get("term_id") == tid), None)
        ev.append({"tag_id": tid, "source_field": "名称", "source_text": h.get("alias", "") if h else "",
                   "inference_type": "name_inference", "confidence": "low"})
    for tid in a3:
        src = row.get("a3_cn_screen", "")
        ev.append({"tag_id": tid, "source_field": "a3_id_screen", "source_text": src,
                   "inference_type": "legacy_mapping", "confidence": "high" if src else "medium"})
    return {
        "category_ids": cat_ids,
        "category_candidates": [],
        "tags_A1": a1, "tags_A2": a2, "tags_A3": a3, "tags_B": b,
        "tags_C_by_category": c,
        "dupe_status": ds,
        "product_candidates": pcs,
        "tag_evidence": ev,
        "unresolved_terms": [],
        "review_notes": [pc.get("note", "") for pc in row.get("draft_product_candidates", []) if pc.get("note")],
        "status": "trial",
    }

# ---- 4. write ctx dirs with batch.jsonl including baseline ----
for bf in batch_files:
    bid = bf.replace(".jsonl", "")
    d = os.path.join(CTX, bid)
    os.makedirs(d, exist_ok=True)
    rows = []
    with open(os.path.join(BATCH, bf), encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    cats_in_batch = set()
    prod_ids = set()
    out_rows = []
    for r in rows:
        baseline = build_baseline(r)
        cats_in_batch.update(CAT_NAME[c] for c in baseline["category_ids"])
        for pc in baseline["product_candidates"]:
            if pc.get("product_id"):
                prod_ids.add(pc["product_id"])
            if pc.get("brand_id"):
                prod_ids.add("B:" + pc["brand_id"])
        for ph in r.get("name_product_hits", []):
            if ph.get("product_id"):
                prod_ids.add(ph["product_id"])
        for bh in r.get("name_brand_hits", []):
            if bh.get("brand_id"):
                prod_ids.add("B:" + bh["brand_id"])
        if r.get("brand_only_hint"):
            prod_ids.add("B:" + r["brand_only_hint"]["brand_id"])
        out_rows.append({"input": r, "baseline": baseline})
    # C slice
    c_lines = []
    for cat in sorted(cats_in_batch):
        for p in C_LEAF_LINES(cat):
            c_lines.append(p)
    with open(os.path.join(d, "C.txt"), "w", encoding="utf-8") as f:
        f.write("id\t品类\t维度\t父ID\t标签\t节点类型\t完整标签路径\n" + "\n".join(c_lines) + "\n")
    # products slice
    with open(os.path.join(d, "products.txt"), "w", encoding="utf-8") as f:
        f.write("product_id\tbrand_id\t品牌\t产品国际名\t产品中文候选别名\t关联行数\t存在核验\tURL\t版本备注\n")
        for key in sorted(prod_ids):
            if not key.startswith("B:") and key in products:
                f.write("\t".join(products[key]) + "\n")
    with open(os.path.join(d, "batch.jsonl"), "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("ctx v3 built for", len(batch_files), "batches")
