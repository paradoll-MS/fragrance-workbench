# -*- coding: utf-8 -*-
"""Analyze preprocessed library + build compact dictionary reference files for LLM batches."""
import json, os, collections
from openpyxl import load_workbook

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "_work")
os.makedirs(OUT, exist_ok=True)

def rows_of(path, sheet):
    wb = load_workbook(path, data_only=True, read_only=False)
    ws = wb[sheet]
    data = list(ws.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in data[0]]
    return header, data[1:]

def to_txt(fname, header, rows, cols):
    with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
        f.write("\t".join(header[i] for i in cols) + "\n")
        for r in rows:
            f.write("\t".join("" if r[i] is None else str(r[i]).replace("\t"," ").replace("\n"," ") for i in cols) + "\n")
    print("wrote", fname, len(rows))

CAT_WB = os.path.join(WS, "品类与ABC标签体系_V2.xlsx")
RUN_WB = os.path.join(WS, "中央库冷启动_试跑与品牌产品候选.xlsx")

# ---- categories ----
h, rows = rows_of(CAT_WB, "应用品类")
to_txt("categories.txt", h, rows, [0,1])

# ---- A tags ----
h, rows = rows_of(CAT_WB, "A标签")
to_txt("tags_A.txt", h, rows, [0,1,2])
a_counts = collections.Counter(r[1] for r in rows)
print("A tag level counts:", dict(a_counts))

# ---- B tags ----
h, rows = rows_of(CAT_WB, "B标签")
to_txt("tags_B.txt", h, rows, [0,1,2])
b_counts = collections.Counter(r[1] for r in rows)
print("B tag level counts:", dict(b_counts))

# ---- C tree ----
h, rows = rows_of(CAT_WB, "C标签树")
to_txt("tags_C.txt", h, rows, [0,1,2,3,4,5,6])
c_cats = collections.Counter(r[1] for r in rows)
print("C tree categories:", dict(c_cats))
c_types = collections.Counter(r[5] for r in rows)
print("C node types:", dict(c_types))
# leaves only
leaves = [r for r in rows if r[5] == "叶子"]
print("C leaves:", len(leaves))

# ---- AB alias ----
h, rows = rows_of(CAT_WB, "AB别名")
to_txt("alias_AB.txt", h, rows, [0,1,2])

# ---- legacy category map ----
h, rows = rows_of(RUN_WB, "品类旧值转换")
to_txt("legacy_category_map.txt", h, rows, [0,1,2,3,4])

# ---- legacy family map ----
h, rows = rows_of(RUN_WB, "旧香族转换")
to_txt("legacy_family_map.txt", h, rows, [0,1,2,3,4])

# ---- C decision aids ----
h, rows = rows_of(CAT_WB, "C左侧判定补充")
to_txt("c_decision.txt", h, rows, [0,1,2,3,4])

# ---- expert confirm ----
h, rows = rows_of(CAT_WB, "专家确认")
to_txt("expert_confirm.txt", h, rows, [0,1,2,3,4,5])

# ---- brand dict ----
h, rows = rows_of(RUN_WB, "品牌字典")
to_txt("brands.txt", h, rows, [0,1,2,3,4])

# ---- product dict ----
h, rows = rows_of(RUN_WB, "产品身份字典")
to_txt("products.txt", h, rows, [0,1,2,3,4,5,6,7,8])

# ---- product candidate relations (draft) ----
h, rows = rows_of(RUN_WB, "香精产品候选关系")
to_txt("product_candidate_draft.txt", h, rows, list(range(16)))

# ---- brand-only rows ----
h, rows = rows_of(RUN_WB, "仅品牌待解析")
to_txt("brand_only_draft.txt", h, rows, list(range(8)))

# ---- duplicate codes pending ----
h, rows = rows_of(RUN_WB, "重复编码待处理")
to_txt("dup_codes_draft.txt", h, rows, list(range(6)))

# ---- full library preprocessed ----
h, rows = rows_of(RUN_WB, "全库第一轮预处理")
print("preprocessed cols:", h)
to_txt("library_preprocessed.txt", h, rows, list(range(16)))

# ---- stats on the library ----
print("\n=== LIBRARY STATS ===")
print("data rows:", len(rows))
codes = [r[1] for r in rows]
names = [r[2] for r in rows]
missing_or_zero = [r for r in rows if r[1] is None or str(r[1]).strip() == "" or str(r[1]).strip() == "0"]
print("rows with missing/0 code:", len(missing_or_zero))
code_counter = collections.Counter(str(c) for c in codes if c is not None and str(c).strip() != "" and str(c).strip() != "0")
dups = {k: v for k, v in code_counter.items() if v > 1}
print("unique non-empty codes:", len(code_counter), "| codes appearing >1:", len(dups))
print("dup extra rows:", sum(v - 1 for v in dups.values()))

status_counter = collections.Counter(r[15] for r in rows)
print("任务状态:", dict(status_counter))

entry_counter = collections.Counter(r[10] for r in rows)
print("原入库逻辑 top:", entry_counter.most_common(10))
print("is_new=1:", sum(1 for r in rows if r[11] == 1), "is_hot=1:", sum(1 for r in rows if r[12] == 1))

# dup status values
dupstat = collections.Counter(str(r[13]) for r in rows)
print("仿香状态:", dict(dupstat))

# category pre-screen distribution
catpre = collections.Counter(str(r[7]) for r in rows)
print("品类初筛 top20:", catpre.most_common(20))

# A3 pre-screen
a3pre = collections.Counter(str(r[8]) for r in rows)
print("A3初筛 filled:", sum(1 for r in rows if r[8]), "| top:", a3pre.most_common(15))

# product candidate ids filled
pcand = sum(1 for r in rows if r[14])
print("rows with candidate_product_ids:", pcand)

# 任务状态 != 待LLM语义清洗
other = [r for r in rows if r[15] and r[15] != "待LLM语义清洗"]
print("rows with other task status:", len(other))
for r in other[:10]:
    print("   other:", r[0], r[1], r[2], r[15])

# save per-row normalized library for batches
with open(os.path.join(OUT, "library_rows.json"), "w", encoding="utf-8") as f:
    json.dump([{
        "source_row": r[0], "fragrance_id": ("" if r[1] is None else str(r[1]).strip()),
        "fragrance_name": ("" if r[2] is None else str(r[2]).strip()),
        "old_cat2": ("" if r[3] is None else str(r[3]).strip()),
        "old_cat3": ("" if r[4] is None else str(r[4]).strip()),
        "cat_remark": ("" if r[5] is None else str(r[5]).strip()),
        "cat_id_screen": ("" if r[6] is None else str(r[6]).strip()),
        "cat_screen": ("" if r[7] is None else str(r[7]).strip()),
        "a3_id_screen": ("" if r[8] is None else str(r[8]).strip()),
        "a3_cn_screen": ("" if r[9] is None else str(r[9]).strip()),
        "entry_logic": ("" if r[10] is None else str(r[10]).strip()),
        "is_new": r[11], "is_hot": r[12],
        "dupe_status_screen": ("" if r[13] is None else str(r[13]).strip()),
        "candidate_product_ids": ("" if r[14] is None else str(r[14]).strip()),
        "task_status": ("" if r[15] is None else str(r[15]).strip()),
    } for r in rows], f, ensure_ascii=False, indent=1)
print("wrote library_rows.json")
