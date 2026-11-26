# -*- coding: utf-8 -*-
"""QA: compare final results against the 33-row manual trial draft (试跑示范)."""
import json, os, collections
from openpyxl import load_workbook

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "output")

def load_draft():
    wb = load_workbook(os.path.join(WS, "中央库冷启动_试跑与品牌产品候选.xlsx"), data_only=True, read_only=True)
    ws = wb["试跑示范"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) if h is not None else "" for h in rows[0]]
    idx = {name: i for i, name in enumerate(hdr)}
    out = {}
    for r in rows[1:]:
        if r[0] is None:
            continue
        sr = int(r[idx["source_row"]])
        out[sr] = {
            "name": r[idx["fragrance_name"]],
            "cat_ids": [x for x in str(r[idx["category_ids"]] or "").split(";") if x],
            "a1": [x for x in str(r[idx["A1 IDs"]] or "").split("；") if x],
            "a2": [x for x in str(r[idx["A2 IDs"]] or "").split("；") if x],
            "a3": [x for x in str(r[idx["A3 IDs"]] or "").split("；") if x],
            "b": [x for x in str(r[idx["B IDs"]] or "").split("；") if x],
            "c": [x for x in str(r[idx["C IDs"]] or "").split("；") if x],
            "prod_ids": [x for x in str(r[idx["candidate_product_ids"]] or "").split("；") if x],
            "dupe": str(r[idx["is_big_brand_dupe"]] or ""),
            "notes": str(r[idx["证据及复核提示"]] or ""),
        }
    return out

draft = load_draft()
print("draft rows:", len(draft))

frag = []
with open(os.path.join(OUT, "fragrance.jsonl"), encoding="utf-8") as f:
    for line in f:
        frag.append(json.loads(line))
by_sr = {r["source_row"]: r for r in frag}

def seteq(a, b):
    return sorted(set(a)) == sorted(set(b))

agree = collections.Counter()
detail = []
for sr, d in sorted(draft.items()):
    r = by_sr.get(sr)
    if r is None:
        detail.append((sr, d["name"], "MISSING_RESULT", "", ""))
        agree["missing"] += 1
        continue
    checks = {
        "cat": seteq(d["cat_ids"], r["category_ids"]),
        "A1": seteq(d["a1"], r["tags_A1"]),
        "A2": seteq(d["a2"], r["tags_A2"]),
        "A3": seteq(d["a3"], r["tags_A3"]),
        "B": seteq(d["b"], r["tags_B"]),
        "C": seteq(d["c"], [cid for cids in r["tags_C_by_category"].values() for cid in cids]),
    }
    prod_d = set(d["prod_ids"])
    prod_r = set(pc.get("product_id") or pc.get("product_name") for pc in r["product_candidates"])
    checks["prod"] = prod_d == prod_r
    n_agree = sum(1 for v in checks.values() if v)
    for k, v in checks.items():
        agree[k] += 1 if v else 0
    if n_agree < 7:
        detail.append((sr, d["name"], f"{n_agree}/7",
                       ";".join(f"{k}:{'Y' if v else 'N'}" for k, v in checks.items()),
                       f"draft_note={d['notes'][:60]}"))

print("agreement by field:", dict(agree))
total = len(draft)
print("full agreement (7/7):", sum(1 for sr, d in draft.items() if sr in by_sr and all(
    seteq(d[k], by_sr[sr][k2]) for k, k2 in
    [("cat_ids", "category_ids"), ("a1", "tags_A1"), ("a2", "tags_A2"), ("a3", "tags_A3"), ("b", "tags_B")]) and
    seteq(d["c"], [cid for cids in by_sr[sr]["tags_C_by_category"].values() for cid in cids])))

with open(os.path.join(OUT, "qa_vs_draft.json"), "w", encoding="utf-8") as f:
    json.dump({"draft_rows": total, "agreement_by_field": dict(agree), "partial_rows": detail},
              f, ensure_ascii=False, indent=2)
print("wrote qa_vs_draft.json; partial rows:", len(detail))
for d in detail[:25]:
    print("  ", d)
