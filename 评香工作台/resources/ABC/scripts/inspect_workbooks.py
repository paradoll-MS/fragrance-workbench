# -*- coding: utf-8 -*-
"""Inspect structure of the two input workbooks: sheets, headers, row counts."""
import sys
from openpyxl import load_workbook

def dump_sheet(wb, ws_name, max_rows=8):
    ws = wb[ws_name]
    print(f"\n===== SHEET: {ws_name} | dims={ws.dimensions} | max_row={ws.max_row} | max_col={ws.max_column} =====")
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i > max_rows:
            print(f"  ... ({ws.max_row - max_rows} more rows)")
            break
        # truncate long values for display
        vals = []
        for v in row:
            s = repr(v)
            if len(s) > 60:
                s = s[:60] + "..."
            vals.append(s)
        print(f"  R{i}: {vals}")

for path in [r"C:\Users\26519\Desktop\交付总控\ABC\品类与ABC标签体系_V2.xlsx",
             r"C:\Users\26519\Desktop\交付总控\ABC\中央库冷启动_试跑与品牌产品候选.xlsx"]:
    print("\n\n##############################")
    print("WORKBOOK:", path)
    wb = load_workbook(path, data_only=True, read_only=False)
    print("SHEETS:", wb.sheetnames)
    for name in wb.sheetnames:
        dump_sheet(wb, name, max_rows=6)
