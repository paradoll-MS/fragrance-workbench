# -*- coding: utf-8 -*-
"""llm_runner.py — 直连 DeepSeek API 的批次判定 runner(确认+增量模式)。
每批:程序基线 + 精简 AB 字典 + 对应品类 C 完整判定树(含左侧判定补充)。
LLM 只输出增量与异常(紧凑契约);程序翻译为 v4 契约并写结果文件(断点续跑)。
"""
import json, os, re, sys, time, concurrent.futures as cf
import urllib.request, urllib.error

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
SLIM = os.path.join(WORK, "ctx", "slim")
BATCH = os.path.join(WORK, "batches")
KEY_FILE = r"C:\Users\26519\.dsh\.credentials.yaml"

MODEL = "deepseek-chat"
MAX_TOKENS = 8192
TEMPERATURE = 0.0
CONCURRENCY = 12
RETRIES = 4

# ---------------- load key ----------------
def load_key():
    text = open(KEY_FILE, encoding="utf-8").read()
    m = re.search(r"DEEPSEEK_API_KEY:\s*(sk-[^\s,}]+)", text)
    if not m:
        raise SystemExit("DEEPSEEK_API_KEY not found")
    return m.group(1).strip()

KEY = load_key()

# ---------------- load C tree + 判定补充 ----------------
C_TREE = {}   # id -> [id, cat, dim, parent, label, ntype, path]
with open(os.path.join(WORK, "tags_C.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if p[0]:
            C_TREE[p[0]] = p

C_SUPP = {}   # id -> 判定补充 text
with open(os.path.join(WORK, "c_decision.txt"), encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if p[0] and len(p) > 4 and p[4]:
            C_SUPP[p[0]] = p[4]

# ---------------- system prompt ----------------
SYSTEM = """你是「中央闻香库」标签判定员。程序已给出每条记录的基线(确定性规则结果)。你的任务:逐行核对基线,只输出需要修正的内容(增量),其余行输出 {"source_row": N}。

规则:
1. 品类:基线来自规则初筛,保留。仅旧二级为「其他家庭护理&其他家庭清洁」「天然香养」或为空且基线为空时,按备注判断;仍无法确认保持空并在 notes 说明。ALL 不自动全贴。
2. A1/A3:基线来自名称命中/旧香族转换,保留;明显错误才移除,并补正确 ID(必须存在于字典且层级正确)。
3. A2:基线可能为空,由你补:直接描述或有把握的 A1 语义(鲜茉莉→花香、柠檬→果香、檀香→木质)。只输出字典中层级 A2 的 ID。不要把香水名解析成原料。
4. B:有把握才补:洗护/织物香水语境→香水感;「蓝色」→冷色调(弱);描述词→对应 B。无把握留空。
5. C:只用提供 C 树中该品类的叶子(节点类型=叶子),沿闸门路径判断。允许合理弱推断;无明确或合理弱语义支持就留空,不发明。不要从 AB 反推商业定位 C。产品形态不明的洗护/织物行一般可不贴 C。
6. 产品:基线候选一般保留。明显歧义改 relation_status=ambiguous 或移除;漏掉的强线索补 prod_add(字典中 product_id;没有的给产品名并 is_new_product=true);仅品牌名→dupe=brand_only 不加产品。identity_status:产品存在核验为「官网已核验存在」→verified,否则待核验。is_big_brand_dupe 本轮一律 null。
7. dupe:confirmed/strong_candidate/ambiguous/brand_only/unidentified/rejected。强产品线索=strong_candidate,歧义=ambiguous,仅品牌=brand_only,无线索=unidentified。本轮无 confirmed/rejected。
8. 名称/备注中的未识别气味术语放入 unresolved(去重);基线正确行输出 {"source_row": N},不要写理由。

输出契约(每输入行一行 JSON,行数与输入一致):
{"source_row": N, "cat_ids": null, "cat_cand": [], "add_A1": [], "rem_A1": [], "add_A2": [], "rem_A2": [], "add_A3": [], "rem_A3": [], "add_B": [], "rem_B": [], "add_C": {}, "rem_C": {}, "prod_add": [], "prod_rem": [], "dupe": null, "unresolved": [], "notes": []}
- 省略或 null=保留基线;add/remove 作用于基线。add_C/rem_C 形如 {"CAT_07": ["C_980"]}。
- prod_add 元素:{"brand_id": "BR_001", "product_id": "PR_0001", "brand_name": "香奈儿", "product_name": "COCO", "edition": null, "matched_alias": "COCO小姐", "identity_status": "待核验", "relation_status": "strong_candidate"};新产品加 "is_new_product": true。
- 所有 ID 必须来自提供的字典;不要输出占位符;不要解释、不要多余文本,只输出 JSON 行。"""

# ---------------- build C slice text for a batch ----------------
def c_slice_text(cat_names):
    lines = ["C 判定树(id | 品类 | 维度 | 节点类型 | 标签 | 完整路径 | 判定补充):"]
    for cid, v in sorted(C_TREE.items()):
        if v[1] in cat_names:
            supp = C_SUPP.get(cid, "")
            lines.append(f"{cid} | {v[1]} | {v[2]} | {v[5]} | {v[4]} | {v[6]}" + (f" | {supp}" if supp else ""))
    return "\n".join(lines)

# ---------------- one batch call ----------------
def process_batch(bid):
    result_path = os.path.join(BATCH, f"{bid}_result.jsonl")
    if os.path.exists(result_path):
        with open(result_path, encoding="utf-8") as f:
            n = len([l for l in f.read().splitlines() if l.strip()])
        return {"batch": bid, "state": "resumed", "rows": n}
    with open(os.path.join(SLIM, f"{bid}_batch.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f.read().splitlines() if l.strip()]
    with open(os.path.join(SLIM, "dicts.txt"), encoding="utf-8") as f:
        dicts = f.read()
    cat_names = set()
    for r in rows:
        for cid in r.get("baseline", {}).get("category_ids", []):
            # map CAT_xx -> name via dicts text (categories section)
            pass
    # category names: parse from dicts.txt categories section
    cat_name_by_code = {}
    for line in dicts.splitlines():
        if re.match(r"CAT_\d+\t", line):
            c, n = line.split("\t", 1)
            cat_name_by_code[c] = n.strip()
    for r in rows:
        for cid in r.get("baseline", {}).get("category_ids", []):
            if cid in cat_name_by_code:
                cat_names.add(cat_name_by_code[cid])
    c_text = c_slice_text(cat_names)

    user = (f"字典(品类/A/B标签/品牌/C判定补充/旧转换):\n{dicts}\n\n"
            f"{c_text}\n\n"
            f"批次 {bid}({len(rows)} 行,每行 input+baseline):\n"
            + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            + f"\n\n输出 {len(rows)} 行修正 JSON(每输入行一行,顺序一致),写入下面的结果文件之外,仅输出 JSON 行文本即可。")

    last_err = None
    for attempt in range(RETRIES):
        try:
            out = call_api(user)
            lines = parse_output(out, rows)
            if len(lines) != len(rows):
                last_err = f"row-count {len(lines)} != {len(rows)}"
                time.sleep(2 * (attempt + 1))
                continue
            # translate compact -> v4 contract
            with open(result_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
            return {"batch": bid, "state": "ok", "rows": len(lines)}
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    return {"batch": bid, "state": "failed", "error": last_err}

def call_api(user):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
    return data["choices"][0]["message"]["content"]

def parse_output(text, rows):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    lines = [l for l in text.splitlines() if l.strip().startswith("{")]
    out = []
    for l in lines:
        try:
            rec = json.loads(l)
        except json.JSONDecodeError:
            continue
        # find matching input row for source_text
        row = next((r for r in rows if r.get("source_row") == rec.get("source_row")), None)
        out.append(translate(rec, row))
    return out

def translate(rec, row):
    """compact -> v4 corrections contract; auto-generate evidence for added tags"""
    v = {
        "source_row": rec.get("source_row"),
        "category_ids": rec.get("cat_ids"),
        "category_candidates": rec.get("cat_cand") or [],
        "tags_A1_add": rec.get("add_A1") or [], "tags_A1_remove": rec.get("rem_A1") or [],
        "tags_A2_add": rec.get("add_A2") or [], "tags_A2_remove": rec.get("rem_A2") or [],
        "tags_A3_add": rec.get("add_A3") or [], "tags_A3_remove": rec.get("rem_A3") or [],
        "tags_B_add": rec.get("add_B") or [], "tags_B_remove": rec.get("rem_B") or [],
        "tags_C_add": rec.get("add_C") or {}, "tags_C_remove": rec.get("rem_C") or {},
        "product_candidates_add": rec.get("prod_add") or [],
        "product_candidates_remove": rec.get("prod_rem") or [],
        "dupe_status": rec.get("dupe"),
        "unresolved_terms": rec.get("unresolved") or [],
        "review_notes_add": rec.get("notes") or [],
        "evidence_add": rec.get("evidence") or [],
        "status": rec.get("status"),
    }
    # auto evidence for LLM-added tags (program-side; source = fragrance_name)
    name = (row or {}).get("fragrance_name", "")
    added_ids = list(v["tags_A1_add"]) + list(v["tags_A2_add"]) + list(v["tags_A3_add"]) + list(v["tags_B_add"])
    for cids in v["tags_C_add"].values():
        added_ids.extend(cids)
    seen = {e.get("tag_id") for e in v["evidence_add"] if e.get("tag_id")}
    for tid in added_ids:
        if tid not in seen:
            v["evidence_add"].append({"tag_id": tid, "source_field": "名称",
                                      "source_text": name, "inference_type": "semantic",
                                      "confidence": "medium"})
            seen.add(tid)
    return v

# ---------------- main ----------------
def main():
    only = None
    if len(sys.argv) > 1:
        only = sys.argv[1]
    bids = sorted(f.replace("_batch.jsonl", "") for f in os.listdir(SLIM)
                  if re.fullmatch(r"batch_\d{3}_batch\.jsonl", f))
    if only:
        bids = [b for b in bids if b == only or b.startswith(only)]
    print(f"batches to process: {len(bids)}", flush=True)
    done, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(process_batch, b): b for b in bids}
        for fut in cf.as_completed(futs):
            b = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"batch": b, "state": "exception", "error": str(e)}
            if res["state"] == "ok":
                done.append(b)
            else:
                failed.append(res)
            print(json.dumps(res, ensure_ascii=False), flush=True)
    print(f"done: {len(done)} | failed: {len(failed)}", flush=True)
    for f in failed:
        print("FAILED:", json.dumps(f, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
