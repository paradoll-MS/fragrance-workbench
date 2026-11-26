# -*- coding: utf-8 -*-
"""Dump full content of key sheets to UTF-8 text files for reading."""
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_work" / "workbook_dumps"
OUT.mkdir(parents=True, exist_ok=True)

def dump_sheet_full(wb, ws_name, out_path, max_rows=None):
    ws = wb[ws_name]
    lines = []
    lines.append(f"SHEET: {ws_name} | dims={ws.dimensions} | max_row={ws.max_row} | max_col={ws.max_column}")
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if max_rows and i > max_rows:
            lines.append(f"... ({ws.max_row - max_rows} more rows)")
            break
        vals = []
        for v in row:
            s = "" if v is None else str(v).replace("\n", "\\n")
            vals.append(s)
        lines.append(f"R{i}\t" + "\t".join(vals))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"wrote {out_path} ({len(lines)} lines)")

wb1 = load_workbook(ROOT / "品类与ABC标签体系_V2.xlsx", data_only=True, read_only=False)
for name in wb1.sheetnames:
    dump_sheet_full(wb1, name, OUT / ("_dump_cat_" + name + ".tsv"))

wb2 = load_workbook(ROOT / "中央库冷启动_试跑与品牌产品候选.xlsx", data_only=True, read_only=False)
for name in wb2.sheetnames:
    dump_sheet_full(wb2, name, OUT / ("_dump_run_" + name + ".tsv"))
print("ALL DONE")
