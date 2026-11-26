# -*- coding: utf-8 -*-
"""Fix Round 1.5 source fields: re-read original XLSX directly (openpyxl, multi-line safe),
validate join by code+name+row order, diff review/price fields against previous dump,
and write fixed original rows for rebuild."""
import json, os, re, collections
import openpyxl

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
SRC = r"C:\Users\26519\Documents\Projects\FF-R\样品管理\data\【wip】中央闻香库20260623.xlsx"

# ---------- 1. read original XLSX directly (data_only, values intact, multi-line safe) ----------
wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
ws = wb["Sheet1"]
orig = []
hdr = None
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i == 0:
        hdr = list(row)
        continue
    vals = [("" if v is None else v) for v in row]
    while len(vals) < 30:
        vals.append("")
    orig.append(vals)
print("orig xlsx rows:", len(orig))

def cell_str(v):
    if isinstance(v, float):
        return repr(v) if v != int(v) else str(int(v))
    return str(v)

# ---------- 2. join by (code, name), normalized-code unique, name unique ----------
with open(os.path.join(WORK, "library_rows.json"), encoding="utf-8") as f:
    lib = json.load(f)

def norm_code(c):
    return re.sub(r"[\s\-_/]+", "", str(c)).upper()

by_cn = collections.defaultdict(list)
by_ncode = collections.defaultdict(list)
by_name = collections.defaultdict(list)
for o in orig:
    by_cn[(o[0], o[1])].append(o)
    by_ncode[norm_code(o[0])].append(o)
    by_name[o[1]].append(o)

join = {}      # source_row -> orig row object
order_ok = 0
order_bad = []
for r in lib:
    sr = r["source_row"]
    code, name = r.get("fragrance_id", ""), r.get("fragrance_name", "")
    if (code, name) in by_cn:
        o = by_cn[(code, name)][0]
    elif len(by_ncode[norm_code(code)]) == 1:
        o = by_ncode[norm_code(code)][0]
    elif len(by_name[name]) == 1:
        o = by_name[name][0]
    else:
        join[sr] = None
        continue
    join[sr] = o
    if sr == orig.index(o) + 2:  # source_row aligns with sheet row order
        order_ok += 1
    else:
        order_bad.append((sr, code, name))

print("joined:", sum(1 for v in join.values() if v is not None), "| unjoined:", sum(1 for v in join.values() if v is None))
print("row-order aligned:", order_ok, "| misaligned:", len(order_bad))
for b in order_bad[:15]:
    print("  order-bad:", b)

# ---------- 3. diff vs previous dump fields ----------
def load_prev():
    rows = []
    with open(os.path.join(WORK, "original_library.tsv"), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if not any(p):
                continue
            while len(p) < 30:
                p.append("")
            rows.append(p)
    return rows

prev = load_prev()
# previous join_map (idx-based)
prev_map = {}
with open(os.path.join(WORK, "join_map.json"), encoding="utf-8") as f:
    for k, v in json.load(f).items():
        prev_map[int(k)] = v

FIELDS = {5: "香族", 6: "子香族", 7: "三调", 8: "主韵关键词", 9: "风格", 10: "概念/系列",
          11: "经典/流行/小众", 12: "情绪感受", 13: "人格特质", 14: "联觉", 15: "联觉-细分", 16: "联觉-词汇",
          17: "借鉴品牌", 18: "借鉴产品名称", 21: "系统报价", 22: "价格段"}

fixed = collections.defaultdict(list)   # source_row -> [field names changed]
prev_dump = collections.defaultdict(list)  # source_row -> prev field values
for sr, o in join.items():
    if o is None:
        continue
    pi = prev_map.get(sr)
    p = prev[pi] if pi is not None else None
    for col, fname in FIELDS.items():
        nv = cell_str(o[col]).strip() if o[col] != "" else ""
        pv = cell_str(p[col]).strip() if p is not None and p[col] != "" else ""
        if nv != pv:
            fixed[sr].append(fname)
            prev_dump[sr].append((fname, pv, nv))

field_cnt = collections.Counter()
for sr, fs in fixed.items():
    for f in fs:
        field_cnt[f] += 1
print("--- field corrections (prev dump -> fixed) ---")
for f, n in field_cnt.most_common():
    print(f"  {f}: {n}")

# classify: three-accords truncated / main-notes mismatch / style mismatch / quote missing
detail_three = [sr for sr, fs in fixed.items() if "三调" in fs]
detail_main = [sr for sr, fs in fixed.items() if "主韵关键词" in fs]
detail_style = [sr for sr, fs in fixed.items() if "风格" in fs]
detail_quote = [sr for sr, fs in fixed.items() if "系统报价" in fs]
print("rows with 三调 fixed:", len(detail_three))
print("rows with 主韵 fixed:", len(detail_main))
print("rows with 风格 fixed:", len(detail_style))
print("rows with 报价 fixed:", len(detail_quote))
all_fixed_rows = sorted(set(fixed.keys()))
print("total source_rows with ANY field fixed:", len(all_fixed_rows))

# quote stats in fixed read
q = collections.Counter(cell_str(o[21]).strip() for o in orig if o[21] != "")
print("系统报价非空(fixed read):", sum(1 for o in orig if o[21] not in ("", None)),
      "| 分布:", q.most_common(8))
ps = collections.Counter(cell_str(o[22]).strip() for o in orig if o[22] != "")
print("价格段(fixed read):", ps.most_common())

# ---------- 4. persist ----------
with open(os.path.join(WORK, "original_library_fixed.jsonl"), "w", encoding="utf-8") as f:
    for sr in sorted(join.keys()):
        o = join[sr]
        rec = {"source_row": sr, "orig_index": (orig.index(o) if o is not None else None)}
        if o is not None:
            for col, fname in FIELDS.items():
                rec[fname] = cell_str(o[col]).strip()
            rec["_all"] = [cell_str(v) for v in o]
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("wrote original_library_fixed.jsonl")
