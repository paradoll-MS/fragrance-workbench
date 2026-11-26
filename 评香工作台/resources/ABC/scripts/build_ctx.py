# -*- coding: utf-8 -*-
"""Build per-batch sliced context dirs for faster LLM batches (batch size 30)."""
import json, os, shutil, collections, re

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
BATCH = os.path.join(WORK, "batches")
CTX = os.path.join(WORK, "ctx")
SHARED = os.path.join(CTX, "shared")
BATCH_SIZE = 30

os.makedirs(SHARED, exist_ok=True)

# ---- shared files ----
for f in ["tags_A.txt", "tags_B.txt", "alias_AB.txt", "brands.txt", "c_decision.txt"]:
    src = os.path.join(WORK, f)
    dst = os.path.join(SHARED, f)
    if not os.path.exists(dst) or os.path.getsize(src) != os.path.getsize(dst):
        shutil.copy2(src, dst)
print("shared files ready")

# ---- parse products ----
products = {}
with open(os.path.join(WORK, "products.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        products[p[0]] = p

# ---- parse C tree ----
C_tree = []
with open(os.path.join(WORK, "tags_C.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        C_tree.append(p)
C_BY_CAT = collections.defaultdict(list)
for p in C_tree:
    C_BY_CAT[p[1]].append(p)

# ---- legacy maps concat ----
with open(os.path.join(SHARED, "legacy.txt"), "w", encoding="utf-8") as f:
    for name in ["legacy_category_map.txt", "legacy_family_map.txt"]:
        with open(os.path.join(WORK, name), encoding="utf-8") as g:
            f.write(g.read())
print("legacy.txt written")

# ---- batches ----
batch_files = sorted(f for f in os.listdir(BATCH) if re.fullmatch(r"batch_\d{3}\.jsonl", f))
print("batch files:", len(batch_files))

def copy_instr(bid):
    """copy instructions and rewrite §0 file pointers to ctx paths"""
    with open(os.path.join(WORK, "llm_instructions.md"), encoding="utf-8") as f:
        txt = f.read()
    txt = txt.replace(r"_work\batches\batch_XXX.jsonl", rf"_work\ctx\{bid}\batch.jsonl")
    txt = txt.replace(r"_work\batches\batch_XXX_result.jsonl", rf"_work\batches\{bid}_result.jsonl")
    txt = txt.replace("`tags_C.txt`", "`C.txt`(仅含本批品类子树)")
    txt = txt.replace("`products.txt`", "`products.txt`(仅含本批相关产品)")
    txt = txt.replace("`brands.txt`", "`brands.txt`(完整品牌字典)")
    txt = txt.replace("`alias_AB.txt`", "`alias_AB.txt`(完整AB别名)")
    txt = txt.replace("`legacy_family_map.txt`", "`legacy.txt`(旧品类+旧香族转换)")
    txt = txt.replace("`legacy_category_map.txt`", "`legacy.txt`(旧品类+旧香族转换)")
    txt = txt.replace("legacy_category_map.txt", "legacy.txt")
    txt = txt.replace("`c_decision.txt`", "`c_decision.txt`(完整)")
    with open(os.path.join(CTX, bid, "instructions.md"), "w", encoding="utf-8") as f:
        f.write(txt)

for bf in batch_files:
    bid = bf.replace(".jsonl", "")
    d = os.path.join(CTX, bid)
    os.makedirs(d, exist_ok=True)
    # batch rows
    rows = []
    with open(os.path.join(BATCH, bf), encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    # categories in batch
    cats = set()
    prod_ids = set()
    for r in rows:
        if r["cat_id_screen"]:
            cats.add(r["cat_screen"])
        for pc in r.get("draft_product_candidates", []):
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
    # C slice
    c_lines = []
    for cat in sorted(cats):
        for p in C_BY_CAT.get(cat, []):
            c_lines.append("\t".join(p))
    with open(os.path.join(d, "C.txt"), "w", encoding="utf-8") as f:
        f.write("id\t品类\t维度\t父ID\t标签\t节点类型\t完整标签路径\n" + "\n".join(c_lines) + "\n")
    # products slice (keep full rows for referenced products; include brand rows)
    with open(os.path.join(d, "products.txt"), "w", encoding="utf-8") as f:
        f.write("product_id\tbrand_id\t品牌\t产品国际名\t产品中文候选别名\t关联行数\t存在核验\tURL\t版本备注\n")
        for key in sorted(prod_ids):
            if key.startswith("B:"):
                continue
            if key in products:
                f.write("\t".join(products[key]) + "\n")
    with open(os.path.join(d, "batch.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    copy_instr(bid)

print("ctx dirs built for", len(batch_files), "batches")
