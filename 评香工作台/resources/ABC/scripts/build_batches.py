# -*- coding: utf-8 -*-
"""Deterministic preprocessing: per-row hints + batch files for LLM rounds."""
import json, os, re, hashlib, collections

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
BATCH = os.path.join(WORK, "batches")
os.makedirs(BATCH, exist_ok=True)

BATCH_SIZE = 30

def load_tsv(fname, key_col=0, val_cols=None):
    """Load a tsv dict file -> {key: [col values]}."""
    out = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < max(val_cols or [0]) + 1:
                continue
            key = p[key_col]
            out[key] = p
    return out, header

# ---- load dictionaries ----
cat_map, _ = load_tsv("categories.txt", key_col=0)
A, _ = load_tsv("tags_A.txt")          # id -> [id, level, label]
B, _ = load_tsv("tags_B.txt")
C, _ = load_tsv("tags_C.txt")          # id -> [id, cat, dim, parent, label, ntype, path]
brands, _ = load_tsv("brands.txt")     # BR_xxx -> [id, cn, intl, aliases, status]
products, _ = load_tsv("products.txt") # PR_xxx -> [id, brand_id, brand, name, aliases, linked, verified, url, note]

# AB alias -> list of (term_id, scope)
alias_index = collections.defaultdict(list)
with open(os.path.join(WORK, "alias_AB.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2 and p[0]:
            scope = p[2] if len(p) > 2 else ""
            alias_index[p[0]].append((p[1], scope))

# dedupe alias entries -> alias -> (term_id, scope)
alias_index = {k: (v[0][0], v[0][1]) for k, v in alias_index.items()}

# tag-label self-index: 标签名 -> term_id (A/B/C leaf labels are also searchable terms)
label_index = {}
for k, row in list(A.items()) + list(B.items()):
    lbl = row[2]
    if lbl and lbl not in label_index:
        label_index[lbl] = k
for k, row in C.items():
    if row[5] == "叶子" and row[4] and row[4] not in label_index:
        label_index[row[4]] = k

# id -> label for A/B/C
A_label = {k: v[2] for k, v in A.items()}
B_label = {k: v[2] for k, v in B.items()}
C_label = {k: v[4] for k, v in C.items()}

# brand alias -> brand_id (longest match later)
brand_alias = {}
for bid, row in brands.items():
    cands = [row[1], row[2]] + [a for a in str(row[3]).split(";") if a]
    for c in cands:
        c = c.strip()
        if c:
            brand_alias.setdefault(c, bid)

# product alias -> product_id
product_alias = {}
for pid, row in products.items():
    cands = [row[3]] + [a for a in str(row[4]).split("；") if a]
    for c in cands:
        c = c.strip()
        if c:
            product_alias.setdefault(c, pid)

# ---- draft relations by source_row ----
draft_rel = collections.defaultdict(list)
with open(os.path.join(WORK, "product_candidate_draft.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) < 16:
            continue
        try:
            sr = int(p[0])
        except ValueError:
            continue
        if p[6]:
            draft_rel[sr].append({
                "source_row": sr, "fragrance_id": p[1], "fragrance_name": p[2],
                "brand_id": p[5], "product_id": p[6], "brand": p[7],
                "product_name": p[8], "matched_alias": p[9],
                "relation_status": p[10], "identity_status": p[11],
                "url": p[12], "note": p[13], "dup_confirmed": p[14], "edition": p[15],
            })

brand_only = {}
with open(os.path.join(WORK, "brand_only_draft.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 8 and p[0].isdigit():
            brand_only[int(p[0])] = {"brand_id": p[5], "brand": p[6], "matched_alias": p[7]}

# ---- load library ----
with open(os.path.join(WORK, "library_rows.json"), encoding="utf-8") as f:
    rows = json.load(f)
print("library rows:", len(rows))

# sort by source_row
rows.sort(key=lambda r: r["source_row"])

# ---- name normalization (for scent-tag matching; product matching uses raw name) ----
PAREN_PAT = re.compile(r"[（(][^（）()]*[)）]")
def strip_parens(name):
    return PAREN_PAT.sub("", name).strip()

def normalize_scent_name(name):
    s = strip_parens(name)
    # strip leading series marker like "缤纷田园系列-", "薰衣草系列-", "香氛系列-"
    s = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9]*系列[\s-]*", "", s)
    s = s.replace("（", " ").replace("）", " ").replace("(", " ").replace(")", " ")
    return s.strip()

# longest alias first
aliases_sorted = sorted(set(alias_index.keys()) | set(label_index.keys()), key=len, reverse=True)
brand_aliases_sorted = sorted(brand_alias.keys(), key=len, reverse=True)
product_aliases_sorted = sorted(product_alias.keys(), key=len, reverse=True)

def resolve_term(term):
    """Resolve a matched term string to one term_id (alias wins over label self-match)."""
    if term in alias_index:
        return alias_index[term][0], "alias"
    if term in label_index:
        return label_index[term], "label"
    return None, None

# merged term index for name matching (alias or label -> term_id)
term_index = {}
for k, v in alias_index.items():
    term_index.setdefault(k, v[0])
term_index.update(label_index)

def match_terms(text, terms):
    hits = []
    used = [False] * len(text)
    for al in terms:
        if len(al) < 2:
            continue
        start = 0
        while True:
            pos = text.find(al, start)
            if pos == -1:
                break
            if not any(used[pos:pos + len(al)]):
                for i in range(pos, pos + len(al)):
                    used[i] = True
                hits.append(al)
            start = pos + 1
    return hits

def match_aliases(text, aliases, index):
    hits = []
    used = [False] * len(text)
    for al in aliases:
        if len(al) < 2:
            continue
        start = 0
        while True:
            pos = text.find(al, start)
            if pos == -1:
                break
            # skip if overlapping already-matched area
            if not any(used[pos:pos + len(al)]):
                for i in range(pos, pos + len(al)):
                    used[i] = True
                hits.append((al, index[al]))
            start = pos + 1
    return hits

def build_row_hints(row):
    name = row["fragrance_name"]
    sn = normalize_scent_name(name)
    raw = strip_parens(name)

    tag_hits = []
    for al in match_terms(sn, aliases_sorted):
        tid, src = resolve_term(al)
        if not tid:
            continue
        scope = alias_index[al][1] if al in alias_index else ""
        tag_hits.append({"alias": al, "term_id": tid, "scope": scope, "match": src})
    b_hits = []
    for al, bid in match_aliases(raw, brand_aliases_sorted, brand_alias):
        b_hits.append({"alias": al, "brand_id": bid})

    p_hits = []
    for al, pid in match_aliases(raw, product_aliases_sorted, product_alias):
        pr = products[pid]
        p_hits.append({"alias": al, "product_id": pid, "brand_id": pr[1],
                       "product_name": pr[3], "brand": pr[2]})

    return {
        "scent_name": sn,
        "tag_hits": tag_hits,
        "brand_hits": b_hits,
        "product_hits": p_hits,
    }

# ---- build per-row context ----
out_rows = []
for r in rows:
    sr = r["source_row"]
    hints = build_row_hints(r)
    ctx = {
        "source_row": sr,
        "fragrance_id": r["fragrance_id"],
        "fragrance_name": r["fragrance_name"],
        "old_cat2": r["old_cat2"],
        "old_cat3": r["old_cat3"],
        "cat_remark": r["cat_remark"],
        "cat_id_screen": r["cat_id_screen"],
        "cat_screen": r["cat_screen"],
        "a3_id_screen": r["a3_id_screen"],
        "a3_cn_screen": r["a3_cn_screen"],
        "entry_logic": r["entry_logic"],
        "is_new": r["is_new"],
        "is_hot": r["is_hot"],
        "dupe_status_screen": r["dupe_status_screen"],
        "draft_product_candidates": draft_rel.get(sr, []),
        "brand_only_hint": brand_only.get(sr),
        "name_tag_hits": hints["tag_hits"],
        "name_brand_hits": hints["brand_hits"],
        "name_product_hits": hints["product_hits"],
    }
    out_rows.append(ctx)

# ---- input hash for manifest ----
def row_hash(ctx):
    core = {k: v for k, v in ctx.items() if k not in ("name_tag_hits",)}
    return hashlib.sha1(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]

# ---- write batches ----
n = len(out_rows)
for i in range(0, n, BATCH_SIZE):
    batch = out_rows[i:i + BATCH_SIZE]
    bnum = i // BATCH_SIZE + 1
    bnum = f"{bnum:03d}"
    with open(os.path.join(BATCH, f"batch_{bnum}.jsonl"), "w", encoding="utf-8") as f:
        for ctx in batch:
            rec = dict(ctx)
            rec["input_hash"] = row_hash(ctx)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"batch_{bnum}.jsonl: {len(batch)} rows")

# ---- summary stats for manifest ----
print("\n=== SUMMARY ===")
print("total rows:", n)
codes = [r["fragrance_id"] for r in rows]
zero = [r for r in rows if not r["fragrance_id"] or r["fragrance_id"] == "0"]
print("zero/missing code rows:", len(zero), [r["source_row"] for r in zero])
cc = collections.Counter(c for c in codes if c and c != "0")
dups = {k: v for k, v in cc.items() if v > 1}
print("dup codes:", len(dups), "extra rows:", sum(v - 1 for v in dups.values()))

with_draft = sum(1 for r in rows if r["source_row"] in draft_rel)
print("rows with draft product candidates:", with_draft)
with_brand_only = sum(1 for r in rows if r["source_row"] in brand_only)
print("rows with brand-only hint:", with_brand_only)
name_hit_rows = sum(1 for r in rows if build_row_hints(r)["tag_hits"])
print("rows with at least one name->tag alias hit:", name_hit_rows)

# persist quick stats
manifest = {
    "taxonomy_version": "品类与ABC标签体系_V2",
    "total_source_rows": n,
    "unique_valid_codes": len(cc),
    "zero_missing_code_rows": len(zero),
    "duplicate_codes": len(dups),
    "duplicate_extra_rows": sum(v - 1 for v in dups.values()),
    "batch_size": BATCH_SIZE,
    "batch_count": (n + BATCH_SIZE - 1) // BATCH_SIZE,
    "draft_product_candidate_rows": with_draft,
    "brand_only_rows": with_brand_only,
}
with open(os.path.join(WORK, "prep_manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
