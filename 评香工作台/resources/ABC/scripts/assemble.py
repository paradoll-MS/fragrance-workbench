# -*- coding: utf-8 -*-
"""v3 assembly: merge baseline+corrections per row, validate, build deliverables."""
import json, os, re, sys, collections, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
BATCH = os.path.join(WORK, "batches")
CTX = os.path.join(WORK, "ctx")
OUT = os.path.join(WS, "output")
DOCS = os.path.join(WS, "docs")
os.makedirs(OUT, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)
TAXONOMY_VERSION = "品类与ABC标签体系_V2"

# ---------------- load dictionaries ----------------
def load_tsv(fname):
    out = {}
    with open(os.path.join(WORK, fname), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0]:
                out[p[0]] = p
    return out

cats = load_tsv("categories.txt")
A = load_tsv("tags_A.txt")
B = load_tsv("tags_B.txt")
C = load_tsv("tags_C.txt")
brands = load_tsv("brands.txt")
products = load_tsv("products.txt")

CAT_NAME = {k: v[1] for k, v in cats.items()}
CAT_CODE_BY_NAME = {v[1]: k for k, v in cats.items()}
A_LEVEL = {k: v[1] for k, v in A.items()}
A_LABEL = {k: v[2] for k, v in A.items()}
B_LEVEL = {k: v[1] for k, v in B.items()}
B_LABEL = {k: v[2] for k, v in B.items()}
C_CAT = {k: v[1] for k, v in C.items()}
C_TYPE = {k: v[5] for k, v in C.items()}
C_PATH = {k: v[6] for k, v in C.items()}
C_LABEL = {k: v[4] for k, v in C.items()}
BRAND_NAME = {k: v[1] for k, v in brands.items()}

DUP_STATUSES = {"confirmed", "strong_candidate", "ambiguous", "brand_only", "unidentified", "rejected"}
REL_STATUSES = {"strong_candidate", "ambiguous", "candidate", "confirmed"}
ID_STATUSES = {"verified", "待核验"}
INF_TYPES = {"legacy_mapping", "name_inference", "description", "semantic", "alias_mapping", "product_clue", "legacy_review", "history"}
CONFS = {"high", "medium", "low"}
STATUSES = {"trial", "confirmed", "rejected"}

# ---------------- load library & batch inputs ----------------
with open(os.path.join(WORK, "library_rows.json"), encoding="utf-8") as f:
    lib = json.load(f)
lib_by_sr = {r["source_row"]: r for r in lib}

hash_by_sr = {}
batch_input_by_sr = {}
batch_id_by_sr = {}
for bf in sorted(f for f in os.listdir(BATCH) if re.fullmatch(r"batch_\d{3}\.jsonl", f)):
    bid = bf.replace(".jsonl", "")
    with open(os.path.join(BATCH, bf), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            sr = rec["source_row"]
            hash_by_sr[sr] = rec.get("input_hash", "")
            batch_id_by_sr[sr] = bid
# baseline per source_row from ctx batch.jsonl
baseline_by_sr = {}
for bf in sorted(f for f in os.listdir(CTX) if f.startswith("batch_")):
    p = os.path.join(CTX, bf, "batch.jsonl")
    if not os.path.exists(p):
        continue
    with open(p, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            sr = rec["input"]["source_row"]
            baseline_by_sr[sr] = (rec["input"], rec["baseline"])

# ---------------- corrections ----------------
result_files = sorted(f for f in os.listdir(BATCH) if re.fullmatch(r"batch_\d{3}_result\.jsonl", f))
print("result files:", len(result_files))

corr_by_sr = {}
errors = []
def clean_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()]

for rf in result_files:
    bid = rf.replace("_result.jsonl", "")
    path = os.path.join(BATCH, rf)
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    inp_path = os.path.join(BATCH, bid + ".jsonl")
    with open(inp_path, encoding="utf-8") as f:
        n_in = len([l for l in f.read().splitlines() if l.strip()])
    if len(lines) != n_in:
        errors.append((bid, None, "row-count-mismatch", f"in={n_in} out={len(lines)}"))
    for ln, line in enumerate(lines, start=1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append((bid, None, "json-error", f"line {ln}: {e}"))
            continue
        if not isinstance(rec, dict):
            errors.append((bid, None, "not-dict", f"line {ln}"))
            continue
        sr = rec.get("source_row")
        try:
            sr = int(sr)
        except (TypeError, ValueError):
            errors.append((bid, sr, "bad-source_row", ""))
            continue
        if sr in corr_by_sr:
            errors.append((bid, sr, "duplicate-source_row", ""))
        corr_by_sr[sr] = rec

# ---------------- merge corrections into baseline ----------------
def apply_corrections(inp, baseline, corr):
    final = dict(baseline)
    final["tags_C_by_category"] = {k: list(v) for k, v in baseline.get("tags_C_by_category", {}).items()}
    final["product_candidates"] = [dict(pc) for pc in baseline.get("product_candidates", [])]
    final["tag_evidence"] = [dict(e) for e in baseline.get("tag_evidence", [])]
    if corr.get("category_ids") is not None:
        final["category_ids"] = clean_list(corr.get("category_ids"))
    if corr.get("category_candidates") is not None:
        final["category_candidates"] = clean_list(corr.get("category_candidates"))
    for key, add_key, rem_key in [("tags_A1", "tags_A1_add", "tags_A1_remove"),
                                  ("tags_A2", "tags_A2_add", "tags_A2_remove"),
                                  ("tags_A3", "tags_A3_add", "tags_A3_remove"),
                                  ("tags_B", "tags_B_add", "tags_B_remove")]:
        s = set(baseline.get(key, []))
        s |= set(clean_list(corr.get(add_key)))
        s -= set(clean_list(corr.get(rem_key)))
        final[key] = sorted(s)
    for ckey, cids in (corr.get("tags_C_add") or {}).items():
        final["tags_C_by_category"].setdefault(ckey, [])
        for c in clean_list(cids):
            if c not in final["tags_C_by_category"][ckey]:
                final["tags_C_by_category"][ckey].append(c)
    for ckey, cids in (corr.get("tags_C_remove") or {}).items():
        for c in clean_list(cids):
            if c in final["tags_C_by_category"].get(ckey, []):
                final["tags_C_by_category"][ckey].remove(c)
        if ckey in final["tags_C_by_category"] and not final["tags_C_by_category"][ckey]:
            del final["tags_C_by_category"][ckey]
    rem = set(clean_list(corr.get("product_candidates_remove")))
    final["product_candidates"] = [pc for pc in final["product_candidates"]
                                   if (pc.get("product_id") or pc.get("product_name")) not in rem]
    for pc in (corr.get("product_candidates_add") or []):
        if isinstance(pc, dict):
            final["product_candidates"].append(dict(pc))
    if corr.get("dupe_status"):
        final["dupe_status"] = corr["dupe_status"]
    ev = {e["tag_id"]: e for e in final["tag_evidence"]}
    for e in (corr.get("evidence_add") or []):
        if isinstance(e, dict) and e.get("tag_id"):
            ev[e["tag_id"]] = e
    final["tag_evidence"] = list(ev.values())
    ut = list(baseline.get("unresolved_terms", []))
    for t in clean_list(corr.get("unresolved_terms")):
        if t not in ut:
            ut.append(t)
    final["unresolved_terms"] = ut
    rn = list(baseline.get("review_notes", []))
    for n in (corr.get("review_notes_add") or []):
        if n and n not in rn:
            rn.append(str(n).strip())
    final["review_notes"] = rn
    if corr.get("status"):
        final["status"] = corr["status"]
    return final

# ---------------- validate merged record ----------------
def validate_record(sr, inp, final, bid):
    """Return normalized record; append errors."""
    out = {
        "source_row": sr,
        "fragrance_id": inp.get("fragrance_id", ""),
        "fragrance_name": inp.get("fragrance_name", ""),
        "category_ids": [],
        "category_candidates": [],
        "tags_A1": [], "tags_A2": [], "tags_A3": [], "tags_B": [],
        "tags_C_by_category": {},
        "dupe_status": final.get("dupe_status") or "unidentified",
        "is_big_brand_dupe": None,
        "product_candidates": [],
        "tag_evidence": [],
        "unresolved_terms": [],
        "review_notes": [],
        "status": final.get("status") or "trial",
    }
    for cid in clean_list(final.get("category_ids")):
        if cid not in cats:
            errors.append((bid, sr, f"unknown-category {cid}", ""))
        elif cid not in out["category_ids"]:
            out["category_ids"].append(cid)
    for cid in clean_list(final.get("category_candidates")):
        if cid not in cats:
            errors.append((bid, sr, f"unknown-category-cand {cid}", ""))
        elif cid not in out["category_candidates"]:
            out["category_candidates"].append(cid)
    for lvl, key in (("A1", "tags_A1"), ("A2", "tags_A2"), ("A3", "tags_A3")):
        for tid in clean_list(final.get(key)):
            if tid not in A or A_LEVEL[tid] != lvl:
                errors.append((bid, sr, f"bad-{key} {tid}", ""))
            elif tid not in out[key]:
                out[key].append(tid)
    for tid in clean_list(final.get("tags_B")):
        if tid not in B:
            errors.append((bid, sr, f"bad-tags_B {tid}", ""))
        elif tid not in out["tags_B"]:
            out["tags_B"].append(tid)
    for ckey, cids in (final.get("tags_C_by_category") or {}).items():
        if ckey not in cats:
            errors.append((bid, sr, f"C-key-not-category {ckey}", ""))
            continue
        for cid in clean_list(cids):
            if cid not in C:
                errors.append((bid, sr, f"unknown-C {cid}", ""))
                continue
            if C_TYPE[cid] != "叶子":
                errors.append((bid, sr, f"C-not-leaf {cid}", ""))
                continue
            if C_CAT[cid] not in CAT_CODE_BY_NAME or CAT_CODE_BY_NAME[C_CAT[cid]] != ckey:
                errors.append((bid, sr, f"C-category-mismatch {cid} in {ckey} (belongs {C_CAT[cid]})", ""))
                continue
            out["tags_C_by_category"].setdefault(ckey, [])
            if cid not in out["tags_C_by_category"][ckey]:
                out["tags_C_by_category"][ckey].append(cid)
    ds = final.get("dupe_status")
    if ds not in DUP_STATUSES:
        errors.append((bid, sr, f"bad-dupe_status {ds!r}", ""))
        ds = "unidentified"
    out["dupe_status"] = ds
    for pc in final.get("product_candidates") or []:
        if not isinstance(pc, dict):
            errors.append((bid, sr, "bad-product_candidate", ""))
            continue
        norm = {}
        norm["brand_id"] = pc.get("brand_id")
        norm["product_id"] = pc.get("product_id")
        norm["brand_name"] = pc.get("brand_name") or ""
        norm["product_name"] = pc.get("product_name") or ""
        norm["edition"] = pc.get("edition")
        norm["matched_alias"] = pc.get("matched_alias") or ""
        norm["identity_status"] = pc.get("identity_status") or "待核验"
        norm["relation_status"] = pc.get("relation_status") or "candidate"
        norm["is_new_product"] = bool(pc.get("is_new_product"))
        if norm["identity_status"] not in ID_STATUSES:
            norm["identity_status"] = "待核验"
        if norm["relation_status"] not in REL_STATUSES:
            errors.append((bid, sr, f"bad-relation_status {norm['relation_status']!r}", ""))
            norm["relation_status"] = "candidate"
        if norm["product_id"] and norm["product_id"] not in products:
            errors.append((bid, sr, f"unknown-product {norm['product_id']}", ""))
            norm["product_id"] = None
        if norm["brand_id"] and norm["brand_id"] not in brands:
            errors.append((bid, sr, f"unknown-brand {norm['brand_id']}", ""))
            norm["brand_id"] = None
        if not norm["product_name"] and not norm["product_id"]:
            errors.append((bid, sr, "empty-product-candidate", ""))
            continue
        out["product_candidates"].append(norm)
    emitted = set(out["tags_A1"] + out["tags_A2"] + out["tags_A3"] + out["tags_B"])
    for cids in out["tags_C_by_category"].values():
        emitted.update(cids)
    for ev in final.get("tag_evidence") or []:
        if not isinstance(ev, dict) or not ev.get("tag_id"):
            errors.append((bid, sr, "bad-evidence", ""))
            continue
        tid = ev["tag_id"]
        if tid not in emitted:
            continue  # stale evidence after multi-layer corrections: drop silently
        inf = ev.get("inference_type")
        if inf not in INF_TYPES:
            inf = "semantic"
            errors.append((bid, sr, f"bad-inference_type {ev.get('inference_type')!r}", ""))
        conf = ev.get("confidence")
        if conf not in CONFS:
            conf = "low"
            errors.append((bid, sr, f"bad-confidence {conf!r}", ""))
        out["tag_evidence"].append({
            "tag_id": tid, "source_field": ev.get("source_field") or "",
            "source_text": ev.get("source_text") or "", "inference_type": inf, "confidence": conf})
    for tid in emitted:
        if not any(e["tag_id"] == tid for e in out["tag_evidence"]):
            # auto-generate evidence for emitted tags lacking it (program-side补证)
            out["tag_evidence"].append({"tag_id": tid, "source_field": "名称",
                                        "source_text": inp.get("fragrance_name", ""),
                                        "inference_type": "semantic", "confidence": "low"})
    for t in clean_list(final.get("unresolved_terms")):
        if t and t not in out["unresolved_terms"]:
            out["unresolved_terms"].append(t)
    for n in final.get("review_notes") or []:
        n = str(n).strip()
        if n and n not in out["review_notes"]:
            out["review_notes"].append(n)
    st = final.get("status")
    if st not in STATUSES:
        errors.append((bid, sr, f"bad-status {st!r}", ""))
        st = "trial"
    out["status"] = st
    return out

# ---------------- assemble final rows ----------------
rows = []
missing_sr = []
for r in lib:
    sr = r["source_row"]
    if sr not in corr_by_sr:
        missing_sr.append(sr)
        continue
    if sr not in baseline_by_sr:
        errors.append(("", sr, "missing-baseline", ""))
        continue
    inp, baseline = baseline_by_sr[sr]
    corr = corr_by_sr[sr]
    final = apply_corrections(inp, baseline, corr)
    rec = validate_record(sr, inp, final, batch_id_by_sr.get(sr, ""))
    rec["batch_id"] = batch_id_by_sr.get(sr, "")
    rec["input_hash"] = hash_by_sr.get(sr, "")
    rec["is_new"] = inp.get("is_new", 0)
    rec["is_hot"] = inp.get("is_hot", 0)
    rec["entry_logic_raw"] = inp.get("entry_logic", "")
    rec["old_cat2"] = inp.get("old_cat2", "")
    rec["old_cat3"] = inp.get("old_cat3", "")
    rec["cat_remark"] = inp.get("cat_remark", "")
    rec["cat_id_screen"] = inp.get("cat_id_screen", "")
    rec["cat_screen"] = inp.get("cat_screen", "")
    rec["a3_id_screen"] = inp.get("a3_id_screen", "")
    rec["a3_cn_screen"] = inp.get("a3_cn_screen", "")
    rows.append(rec)
rows.sort(key=lambda x: x["source_row"])
print("finalized rows:", len(rows), "| missing:", len(missing_sr))

# ---------------- Round 1.5 layer (--r15) ----------------
R15 = "--r15" in sys.argv
r15_stats = {"refined_rows": 0, "added": collections.Counter(), "removed": collections.Counter()}
if R15:
    r15_dir = os.path.join(WORK, "r15")
    r15_files = sorted(f for f in os.listdir(r15_dir) if re.fullmatch(r"batch_\d{3}_result\.jsonl", f))
    print("r15 result files:", len(r15_files))
    r15_by_sr = collections.defaultdict(list)
    for rf in r15_files:
        with open(os.path.join(r15_dir, rf), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sr = rec.get("source_row")
                if sr is not None:
                    r15_by_sr[sr].append(rec)  # layered: batch_0xx (旧r15) 先, batch_1xx (修正) 后
    for i, r in enumerate(rows):
        sr = r["source_row"]
        corrs = r15_by_sr.get(sr)
        if not corrs:
            continue
        final = r
        for corr in corrs:
            corr = dict(corr)
            corr["product_candidates_add"] = []
            corr["product_candidates_remove"] = []
            final = apply_corrections(final, final, corr)
        rec = validate_record(sr, r, final, batch_id_by_sr.get(sr, ""))
        for k in ("batch_id", "input_hash", "is_new", "is_hot", "entry_logic_raw", "old_cat2", "old_cat3",
                  "cat_remark", "cat_id_screen", "cat_screen", "a3_id_screen", "a3_cn_screen"):
            rec[k] = r.get(k)
        rec["r15_refined"] = True
        for k in ("tags_A1", "tags_A2", "tags_A3", "tags_B"):
            r15_stats["added"][k] += len(set(rec[k]) - set(r[k]))
            r15_stats["removed"][k] += len(set(r[k]) - set(rec[k]))
        for ck in set(list(r["tags_C_by_category"].keys()) + list(rec["tags_C_by_category"].keys())):
            a = set(rec["tags_C_by_category"].get(ck, [])) - set(r["tags_C_by_category"].get(ck, []))
            b = set(r["tags_C_by_category"].get(ck, [])) - set(rec["tags_C_by_category"].get(ck, []))
            r15_stats["added"][f"C:{ck}"] += len(a)
            r15_stats["removed"][f"C:{ck}"] += len(b)
        r15_stats["refined_rows"] += 1
        rows[i] = rec
    print("r15 refined rows:", r15_stats["refined_rows"])

# ---------------- attach original-library fields (评香/报价/价格段) ----------------
# uses corrected direct-XLSX read (multi-line safe); keyed by source_row
orig_fixed = {}
fixed_path = os.path.join(WORK, "original_library_fixed.jsonl")
if os.path.exists(fixed_path):
    with open(fixed_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            orig_fixed[rec["source_row"]] = rec
if orig_fixed:
    for r in rows:
        rec = orig_fixed.get(r["source_row"])
        if rec is None:
            r["family"] = r["subfamily"] = r["three_accords"] = r["main_notes"] = ""
            r["style"] = r["personality"] = r["synesthesia"] = ""
            r["system_quote"] = None
            r["price_segment"] = None
            continue
        r["family"] = rec.get("香族", "")
        r["subfamily"] = rec.get("子香族", "")
        r["three_accords"] = rec.get("三调", "")
        r["main_notes"] = rec.get("主韵关键词", "")
        r["style"] = rec.get("风格", "")
        r["personality"] = rec.get("人格特质", "")
        r["synesthesia"] = rec.get("联觉", "")
        sq = str(rec.get("系统报价", "") or "").strip()
        ps = str(rec.get("价格段", "") or "").strip()
        r["system_quote"] = sq if sq and sq not in ("#N/A",) else None
        r["price_segment"] = ps if ps in ("大众", "中端", "高端", "价格未知") else None

# ---------------- merge duplicate codes ----------------
def tag_fingerprint(rec):
    return json.dumps({
        "category_ids": rec["category_ids"],
        "tags_A1": rec["tags_A1"], "tags_A2": rec["tags_A2"], "tags_A3": rec["tags_A3"],
        "tags_B": rec["tags_B"], "tags_C_by_category": rec["tags_C_by_category"],
        "dupe_status": rec["dupe_status"],
        "product_candidates": sorted((pc.get("product_id") or pc.get("product_name")) for pc in rec["product_candidates"]),
    }, ensure_ascii=False, sort_keys=True)

by_code = collections.defaultdict(list)
for r in rows:
    cid = r["fragrance_id"]
    if cid and cid != "0" and "#REF" not in cid:
        by_code[cid].append(r)

frag_main = []
merge_notes = collections.defaultdict(list)
for code, group in sorted(by_code.items()):
    fps = {tag_fingerprint(r) for r in group}
    if len(fps) == 1:
        base = dict(group[0])
        base["source_rows"] = [r["source_row"] for r in group]
        base["merged_rows"] = len(group)
        ev = {e["tag_id"]: e for e in base["tag_evidence"]}
        for r in group[1:]:
            for e in r["tag_evidence"]:
                if e["tag_id"] not in ev:
                    ev[e["tag_id"]] = e
            for t in r["unresolved_terms"]:
                if t not in base["unresolved_terms"]:
                    base["unresolved_terms"].append(t)
            for n in r["review_notes"]:
                if n not in base["review_notes"]:
                    base["review_notes"].append(n)
        base["tag_evidence"] = list(ev.values())
        for fld in ("system_quote", "price_segment", "family", "subfamily", "three_accords",
                    "main_notes", "style", "personality", "synesthesia"):
            vals = [r[fld] for r in group if r.get(fld)]
            if vals:
                base[fld] = vals[0]
        frag_main.append(base)
        if len(group) > 1:
            merge_notes["merged"].append((code, [r["source_row"] for r in group]))
    else:
        for r in group:
            rr = dict(r)
            rr["source_rows"] = [r["source_row"]]
            rr["merged_rows"] = 1
            rr["conflict"] = True
            frag_main.append(rr)
        merge_notes["conflict"].append((code, [r["source_row"] for r in group]))

print("frag_main:", len(frag_main), "| merged:", len(merge_notes["merged"]), "| conflicts:", len(merge_notes["conflict"]))

# ---------------- build tags / product-relations ----------------
fragrance_tags = []
fragrance_product = []
for rec in frag_main:
    for cid in rec["category_ids"]:
        fragrance_tags.append({"fragrance_id": rec["fragrance_id"], "category_id": cid, "tag_id": None,
                               "tag_level": "CATEGORY", "tag_name": CAT_NAME[cid],
                               "inference_type": "legacy_mapping", "confidence": "high",
                               "status": rec["status"], "source_row": rec["source_row"]})
    for tid in rec["tags_A1"] + rec["tags_A2"] + rec["tags_A3"] + rec["tags_B"]:
        ev = next((e for e in rec["tag_evidence"] if e["tag_id"] == tid), None)
        fragrance_tags.append({"fragrance_id": rec["fragrance_id"], "category_id": None, "tag_id": tid,
                               "tag_level": "A" if tid.startswith("A") else "B",
                               "tag_name": A_LABEL.get(tid) or B_LABEL.get(tid),
                               "inference_type": ev["inference_type"] if ev else "semantic",
                               "confidence": ev["confidence"] if ev else "low",
                               "status": rec["status"], "source_row": rec["source_row"]})
    for ckey, cids in rec["tags_C_by_category"].items():
        for tid in cids:
            ev = next((e for e in rec["tag_evidence"] if e["tag_id"] == tid), None)
            fragrance_tags.append({"fragrance_id": rec["fragrance_id"], "category_id": ckey, "tag_id": tid,
                                   "tag_level": "C", "tag_name": C_LABEL.get(tid), "tag_path": C_PATH.get(tid),
                                   "inference_type": ev["inference_type"] if ev else "semantic",
                                   "confidence": ev["confidence"] if ev else "low",
                                   "status": rec["status"], "source_row": rec["source_row"]})
    for pc in rec["product_candidates"]:
        fragrance_product.append({
            "fragrance_id": rec["fragrance_id"],
            "product_id": pc.get("product_id"),
            "brand_id": pc.get("brand_id"),
            "brand_name": pc.get("brand_name") or (BRAND_NAME.get(pc.get("brand_id"), "") if pc.get("brand_id") else ""),
            "product_name": pc.get("product_name"),
            "edition": pc.get("edition"),
            "matched_alias": pc.get("matched_alias"),
            "identity_status": pc.get("identity_status"),
            "relation_status": pc.get("relation_status"),
            "source_row": rec["source_row"],
        })

brand_rows = [{"brand_id": bid, "canonical_name": p[1], "international_name": p[2],
                "aliases": [a for a in str(p[3]).split(";") if a], "status": p[4]} for bid, p in brands.items()]
product_rows = [{"product_id": pid, "brand_id": p[1], "brand_name": p[2], "product_name": p[3],
                 "aliases": [a for a in str(p[4]).split("；") if a], "linked_library_rows": p[5],
                 "identity_status": "verified" if p[6] and "已核验" in str(p[6]) else "待核验",
                 "verification_url": p[7], "edition_note": p[8]} for pid, p in products.items()]

def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print("wrote", path, len(items))

write_jsonl(os.path.join(OUT, "fragrance.jsonl"), frag_main)
write_jsonl(os.path.join(OUT, "fragrance_tags.jsonl"), fragrance_tags)
write_jsonl(os.path.join(OUT, "brand.jsonl"), brand_rows)
write_jsonl(os.path.join(OUT, "product.jsonl"), product_rows)
write_jsonl(os.path.join(OUT, "fragrance_product.jsonl"), fragrance_product)

# ---------------- review_queue.xlsx ----------------
wb = Workbook()
def sheet_with_header(ws, headers, rows, widths=None):
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
    for r in rows:
        ws.append(r)
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

sr_index = {r["source_row"]: r for r in rows}
review_rows = []
for r in rows:
    cid = r["fragrance_id"]
    if not cid or cid == "0" or "#REF" in cid:
        review_rows.append([cid, r["source_row"], r["fragrance_name"], "缺码/0码/#REF!",
                            "编码缺失或为Excel错误值,待确认真实编号,不写入正式身份表", r["dupe_status"], r["status"]])
    elif len(cid) < 4:
        review_rows.append([cid, r["source_row"], r["fragrance_name"], "疑似异常编码",
                            "编码过短或格式可疑,建议人工核对", r["dupe_status"], r["status"]])
for code, srs in merge_notes.get("conflict", []):
    review_rows.append([code, "|".join(map(str, srs)),
                        "|".join(str(sr_index[s]["fragrance_name"]) for s in srs),
                        "重复编码冲突", "属性不一致,保留不同源行待人工核对", "", ""])
for code, srs in merge_notes.get("merged", []):
    review_rows.append([code, "|".join(map(str, srs)),
                        "|".join(str(sr_index[s]["fragrance_name"]) for s in srs),
                        "重复编码已合并", "属性一致,证据已合并;建议人工复核", "", ""])
for r in rows:
    if not r["category_ids"]:
        review_rows.append([r["fragrance_id"], r["source_row"], r["fragrance_name"], "品类未定",
                            f"旧二级={r['old_cat2']!r} 三级={r['old_cat3']!r} 备注={r['cat_remark']!r}",
                            r["dupe_status"], r["status"]])
term_counter = collections.Counter()
for r in rows:
    for t in r["unresolved_terms"]:
        term_counter[t] += 1
for t, n in term_counter.most_common():
    review_rows.append(["", "", t, "未识别术语", f"出现{n}次,待补充字典", "", ""])
for r in rows:
    for pc in r["product_candidates"]:
        if pc.get("identity_status") != "verified":
            review_rows.append([r["fragrance_id"], r["source_row"], r["fragrance_name"], "产品待核验",
                                f"{pc.get('brand_name')} / {pc.get('product_name')} ({pc.get('relation_status')})",
                                r["dupe_status"], r["status"]])
        break
if orig_fixed:
    for r in rows:
        rec = orig_fixed.get(r["source_row"])
        if rec is None or rec.get("orig_index") is None:
            review_rows.append([r["fragrance_id"], r["source_row"], r["fragrance_name"], "原始库未关联",
                                "原库无对应编码/名称,评香与报价字段缺失,证据暂存待二轮按工单名称判断",
                                r["dupe_status"], r["status"]])
for (bid, sr, kind, detail) in errors:
    review_rows.append(["", sr if sr else "", kind, "校验错误", f"{detail} (batch {bid})", "", ""])
ws1 = wb.active
ws1.title = "复核清单"
sheet_with_header(ws1, ["编码", "source_row", "名称", "类型", "说明", "dupe_status", "status"], review_rows,
                  widths=[16, 12, 24, 16, 60, 14, 10])
ws2 = wb.create_sheet("校验错误明细")
sheet_with_header(ws2, ["batch_id", "source_row", "错误类型", "详情"],
                  [[e[0], e[1] if e[1] else "", e[2], e[3]] for e in errors],
                  widths=[14, 12, 30, 80])
wb.save(os.path.join(DOCS, "review_queue.xlsx"))
print("wrote review_queue.xlsx | review rows:", len(review_rows), "| errors:", len(errors))

# ---------------- batch_manifest.json ----------------
cat_cov = {cat: sum(1 for r in rows if cid in r["category_ids"]) for cid, cat in CAT_NAME.items()}
manifest = {
    "taxonomy_version": TAXONOMY_VERSION,
    "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "total_source_rows": len(lib),
    "rows_processed": len(rows),
    "rows_missing": len(missing_sr),
    "unique_valid_codes": len(by_code),
    "fragrance_main_rows": len(frag_main),
    "zero_missing_code_rows": sum(1 for r in rows if not r["fragrance_id"] or r["fragrance_id"] == "0" or "#REF" in r["fragrance_id"]),
    "duplicate_codes": sum(1 for g in by_code.values() if len(g) > 1),
    "duplicate_extra_rows": sum(len(g) - 1 for g in by_code.values() if len(g) > 1),
    "merged_duplicate_codes": len(merge_notes["merged"]),
    "conflict_duplicate_codes": len(merge_notes["conflict"]),
    "category_coverage": cat_cov,
    "tags_count": {
        "A1": sum(1 for r in rows if r["tags_A1"]),
        "A2": sum(1 for r in rows if r["tags_A2"]),
        "A3": sum(1 for r in rows if r["tags_A3"]),
        "B": sum(1 for r in rows if r["tags_B"]),
        "C": sum(1 for r in rows if r["tags_C_by_category"]),
    },
    "fragrance_tags_total": len(fragrance_tags),
    "product_candidates_links": len(fragrance_product),
    "verified_products": sum(1 for p in product_rows if p["identity_status"] == "verified"),
    "unverified_product_links": sum(1 for fp in fragrance_product if fp["identity_status"] != "verified"),
    "dupe_status_distribution": dict(collections.Counter(r["dupe_status"] for r in rows)),
    "is_new_count": sum(1 for r in rows if r["is_new"] == 1),
    "is_hot_count": sum(1 for r in rows if r["is_hot"] == 1),
    "status_distribution": dict(collections.Counter(r["status"] for r in rows)),
    "errors": len(errors),
    "round15": ({"refined_rows": r15_stats["refined_rows"],
                 "added": dict(r15_stats["added"]), "removed": dict(r15_stats["removed"])} if R15 else None),
    "price_fields": {
        "system_quote_rows": sum(1 for r in rows if r.get("system_quote")),
        "price_segment_rows": sum(1 for r in rows if r.get("price_segment")),
        "price_segment_distribution": dict(collections.Counter(r["price_segment"] for r in rows if r.get("price_segment"))),
    },
    "original_join": ({"mapped_rows": sum(1 for r in rows if orig_fixed.get(r["source_row"], {}).get("orig_index") is not None),
                       "unmapped_rows": sum(1 for r in rows if orig_fixed.get(r["source_row"], {}).get("orig_index") is None)}
                      if orig_fixed else None),
    "batches": {"total": 130, "results": len(result_files),
                "missing_result_files": sorted({str(i + 1).zfill(3) for i in range(130)} - {rf.replace("_result.jsonl", "").replace("batch_", "") for rf in result_files})},
}
with open(os.path.join(OUT, "batch_manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("wrote batch_manifest.json")

# ---------------- human-readable Excel ----------------
wb2 = Workbook()
ws = wb2.active
ws.title = "全库第一轮+1.5结果"
headers = ["source_row", "原编码", "香精名称", "品类IDs", "品类", "A1 IDs", "A1 中文", "A2 IDs", "A2 中文",
           "A3 IDs", "A3 中文", "B IDs", "B 中文", "C IDs", "C 完整路径", "is_new", "is_hot",
           "dupe_status", "候选产品", "原入库逻辑", "证据及复核提示", "status", "batch_id",
           "旧香族", "旧子香族", "三调", "主韵关键词", "风格", "人格特质", "联觉",
           "系统报价", "价格段", "r15已补标"]
ws.append(headers)
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="4472C4")
for r in frag_main:
    ws.append([
        r["source_row"], r["fragrance_id"], r["fragrance_name"],
        ";".join(r["category_ids"]), ";".join(CAT_NAME[c] for c in r["category_ids"]),
        ";".join(r["tags_A1"]), ";".join(A_LABEL.get(t, "") for t in r["tags_A1"]),
        ";".join(r["tags_A2"]), ";".join(A_LABEL.get(t, "") for t in r["tags_A2"]),
        ";".join(r["tags_A3"]), ";".join(A_LABEL.get(t, "") for t in r["tags_A3"]),
        ";".join(r["tags_B"]), ";".join(B_LABEL.get(t, "") for t in r["tags_B"]),
        ";".join(f"{ck}:{','.join(cids)}" for ck, cids in r["tags_C_by_category"].items()),
        ";".join(C_PATH.get(cid, "") for cids in r["tags_C_by_category"].values() for cid in cids),
        r["is_new"], r["is_hot"], r["dupe_status"],
        ";".join(f"{pc.get('brand_name', '')}/{pc.get('product_name', '')}" for pc in r["product_candidates"]),
        r["entry_logic_raw"],
        " | ".join(f"{e['tag_id']}({e['inference_type']},{e['confidence']}):{e['source_text']}" for e in r["tag_evidence"]),
        r["status"], r["batch_id"],
        r.get("family", ""), r.get("subfamily", ""), r.get("three_accords", ""), r.get("main_notes", ""),
        r.get("style", ""), r.get("personality", ""), r.get("synesthesia", ""),
        r.get("system_quote", ""), r.get("price_segment", ""),
        "是" if r.get("r15_refined") else "",
    ])
widths = [10, 12, 26, 22, 26, 30, 26, 30, 26, 30, 26, 30, 26, 40, 40, 7, 7, 16, 34, 12, 70, 10, 10,
          14, 16, 20, 24, 14, 14, 16, 12, 10, 10]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A2"
wb2.save(os.path.join(DOCS, "中央库第一轮清洗结果_人可读.xlsx"))
print("wrote 人可读 Excel:", len(frag_main))

# ---------------- report stats ----------------
print("\n===== REPORT =====")
print("原始行数:", len(lib), "| 处理行数:", len(rows), "| 缺结果:", len(missing_sr))
print("唯一有效编码:", len(by_code))
print("重复编码组:", manifest["duplicate_codes"], "| 额外行:", manifest["duplicate_extra_rows"],
      "| 冲突组:", manifest["conflict_duplicate_codes"])
print("品类覆盖:", {k: v for k, v in cat_cov.items() if v})
print("标签非空:")
for k, v in manifest["tags_count"].items():
    print(f"  {k}: {v} ({v/len(rows)*100:.1f}%)" if rows else f"  {k}: {v}")
print("产品候选关联:", len(fragrance_product), "| 已核验产品:", manifest["verified_products"])
print("dupe分布:", manifest["dupe_status_distribution"])
print("新品:", manifest["is_new_count"], "| 爆品:", manifest["is_hot_count"])
print("校验错误:", len(errors))
