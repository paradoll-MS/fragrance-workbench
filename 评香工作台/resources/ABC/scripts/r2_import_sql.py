# -*- coding: utf-8 -*-
"""Round 2 ETL step 1: import MySQL dumps (工单主表/工单明细/项目) into SQLite.
Generic MySQL->SQLite: strips engine-specific CREATE syntax, parses INSERT tuples."""
import sqlite3, re, os, sys

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
R2 = os.path.join(WS, "_work", "r2")
DB = os.path.join(R2, "香精工单.sqlite3")

def strip_mysql_type(t):
    t = t.strip()
    t = re.sub(r"\s+(CHARACTER|COLLATE|COMMENT|DEFAULT|AUTO_INCREMENT|UNSIGNED|NOT\s+NULL|NULL).*", "", t, flags=re.I)
    t = re.sub(r"\((?:0|\d+)\)$", "", t)
    t = t.strip().upper()
    if t.startswith("DATETIME") or t.startswith("TIMESTAMP"):
        return "TEXT"
    if t.startswith("INT") or t.startswith("BIGINT") or t.startswith("SMALLINT") or t.startswith("TINYINT"):
        return "INTEGER"
    if t.startswith("DECIMAL") or t.startswith("FLOAT") or t.startswith("DOUBLE"):
        return "REAL"
    return "TEXT"

def parse_insert(line):
    """parse one INSERT INTO ... VALUES (...),(...); line -> (cols, rows)"""
    m = re.match(r"INSERT INTO `?(\w+)`?\s*(?:\(([^)]*)\))?\s*VALUES\s*(.*)$", line, re.I | re.S)
    if not m:
        return None
    table, colpart, rest = m.group(1), m.group(2) or "", m.group(3)
    cols = [c.strip().strip("`") for c in colpart.split(",") if c.strip()] if colpart else None
    # split rows on "),(" at top level (no quote awareness needed: values are quoted strings; a "),(" inside a string is possible but rare; use char scan)
    rows = []
    cur, depth, in_str, esc = [], 0, False, False
    for ch in rest:
        if esc:
            cur.append(ch); esc = False; continue
        if in_str:
            cur.append(ch)
            if ch == "\\": esc = True
            elif ch == "'": in_str = False
            continue
        if ch == "'": in_str = True; cur.append(ch)
        elif ch == "(": depth += 1; cur.append(ch)
        elif ch == ")":
            depth -= 1; cur.append(ch)
            if depth == 0:
                rows.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur and "".join(cur).strip():
        rows.append("".join(cur).strip())
    parsed = []
    for r in rows:
        vals = split_values(r)
        parsed.append(vals)
    return table, cols, parsed

def split_values(tup):
    vals, cur, in_str, esc, just_closed = [], "", False, False, False
    for ch in tup:
        if esc:
            cur += ch; esc = False; just_closed = False
            continue
        if in_str:
            cur += ch
            if ch == "\\":
                esc = True
            elif ch == "'":
                in_str = False
                vals.append(cur)
                cur = ""
                just_closed = True
            continue
        if ch == "'":
            in_str = True; cur = "'"; just_closed = False
        elif ch == ",":
            if not just_closed:
                vals.append(cur.strip())
                cur = ""
            just_closed = False
        else:
            cur += ch
            just_closed = False
    if cur.strip():
        vals.append(cur.strip())
    out = []
    for v in vals:
        if v.startswith("'") and v.endswith("'"):
            inner = v[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\r", "\r")
            out.append(inner)
        elif v == "NULL":
            out.append(None)
        else:
            v2 = v.replace("\\'", "'")
            try:
                out.append(int(v2))
            except ValueError:
                out.append(v2)
    return out

def split_statements(text):
    """split SQL on ';' that are OUTSIDE string literals and comments"""
    stmts, cur = [], ""
    in_str, esc, in_line_comment = False, False, False
    for ch in text:
        if in_line_comment:
            cur += ch
            if ch == "\n":
                in_line_comment = False
            continue
        if esc:
            cur += ch; esc = False; continue
        if in_str:
            cur += ch
            if ch == "\\": esc = True
            elif ch == "'": in_str = False
            continue
        if ch == "-" and cur.endswith("-"):
            in_line_comment = True; cur += ch
            continue
        if ch == "'":
            in_str = True; cur += ch
            continue
        if ch == ";":
            stmts.append(cur); cur = ""
            continue
        cur += ch
    if cur.strip():
        stmts.append(cur)
    return stmts

def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    files = [("工单主表数据.sql", "work_orders_raw"),
             ("工单明细表.sql", "sample_details_raw"),
             ("项目.sql", "projects_raw")]
    for fn, fallback in files:
        path = os.path.join(R2, fn)
        print("importing", fn, flush=True)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        table = None
        for st in split_statements(text):
            st = st.strip()
            if not st or st.startswith("--") or st.startswith("/*"):
                continue
            if st.upper().startswith("CREATE TABLE"):
                m = re.search(r"CREATE TABLE `?(\w+)`?\s*\((?P<body>.*)\)\s*ENGINE", st, re.S | re.I)
                if not m:
                    m = re.search(r"CREATE TABLE `?(\w+)`?\s*\((?P<body>.*)\)\s*;?\s*$", st, re.S | re.I)
                if not m:
                    print("  SKIP create (unparsed):", st[:80], flush=True)
                    continue
                tname = m.group(1)
                cols = []
                for line in m.group("body").splitlines():
                    line = line.strip().strip(",").strip()
                    cm = re.match(r"`?(\w+)`?\s+([\w\s(0-9,)]+)", line)
                    if cm:
                        cols.append((cm.group(1), strip_mysql_type(cm.group(2))))
                if not cols:
                    continue
                table = tname
                colnames = [c[0] for c in cols]
                coltypes = {c[0]: c[1] for c in cols}
                cur.execute(f"DROP TABLE IF EXISTS `{table}`")
                cur.execute(f"CREATE TABLE `{table}` ({','.join(f'`{c}` {coltypes[c]}' for c in colnames)})")
                con.commit()
                print(f"  table {table}: {len(colnames)} cols", flush=True)
                continue
            if st.upper().startswith("INSERT INTO"):
                parsed = parse_insert(st)
                if not parsed:
                    continue
                tname, cols, rows = parsed
                tname = tname.strip("`")
                cur.execute(f"PRAGMA table_info(`{tname}`)")
                tcols = [r[1] for r in cur.fetchall()]
                if not tcols:
                    continue
                if cols:
                    idx = [tcols.index(c) if c in tcols else None for c in cols]
                else:
                    idx = list(range(len(tcols)))
                for vals in rows:
                    row = [None] * len(tcols)
                    for i, v in enumerate(vals):
                        if i < len(idx) and idx[i] is not None:
                            row[idx[i]] = v
                    cur.execute(f"INSERT INTO `{tname}` VALUES ({','.join('?' * len(row))})", row)
        con.commit()
        print(f"  done {fn}", flush=True)
    con.commit()
    for t in ["work_orders_raw", "sample_details_raw", "projects_raw"]:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM `{t}`").fetchone()[0]
            print(t, "rows:", n)
        except sqlite3.Error as e:
            print(t, "ERR", e)
    con.close()
    print("wrote", DB)

if __name__ == "__main__":
    main()
