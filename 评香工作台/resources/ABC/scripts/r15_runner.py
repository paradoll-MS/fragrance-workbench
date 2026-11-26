# -*- coding: utf-8 -*-
"""r15_runner.py — Round 1.5 补标:基于原库评香字段 + 第一轮结果,LLM 增量修订 A/B/C。
约束:三调(前中后调)不是 A 标签(香韵)的直接证据;A 证据以主韵关键词/香族/子香族为主。
产品候选与品牌搜索不重复执行(保留第一轮成果)。
"""
import json, os, re, sys, time, concurrent.futures as cf
import urllib.request, urllib.error

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
R15 = os.path.join(WORK, "r15")
CTX = os.path.join(R15, "ctx")
KEY_FILE = r"C:\Users\26519\.dsh\.credentials.yaml"

MODEL = os.environ.get("R15_MODEL", "DeepSeek-V4-Flash-0731")
API_URL = "https://llmapi.paratera.com/chat/completions"
MAX_TOKENS = 8192
TEMPERATURE = 0.0
CONCURRENCY = 12
RETRIES = 4
THINKING_DISABLED = True  # fast path: no reasoning tokens

def load_key():
    text = open(KEY_FILE, encoding="utf-8").read()
    m = re.search(r"PARATERA_API_KEY:\s*(sk-[^\s,}]+)", text)
    if not m:
        raise SystemExit("PARATERA_API_KEY not found")
    return m.group(1).strip()

KEY = load_key()

SYSTEM = """你是「中央闻香库」第二轮补标判定员。每行给出:第一轮结果(r1,含品类/A1/A2/A3/B/C/dupe/产品候选)+ 原库评香字段(review:香族/子香族/三调/主韵关键词/风格/人格特质/联觉/借鉴品牌等)。本轮核心目标:利用评香字段积极补强与修订。

硬性要求(逐行执行,不得偷懒):
1. 主动补强:评香字段(主韵关键词/香族/子香族/风格/人格)给出的明确香韵、香型、场景要素,若 r1 缺失且字典存在对应标签,必须补上(A1/A2=具体香韵,B=场景风格, C=香型调)。例如:香族=琥珀→补 A2 琥珀香韵;子香族=海洋花香→补 A2 海洋香;风格=清新→补对应 B。这是本轮的主要产出,不许省略。
2. 香韵(A 标签)证据来源:以「主韵关键词」「香族/子香族」为主,完整三调(前/中/后调)中的具体气味成分也可作为 A1/A2 香韵证据(如 前调=香柠檬→A1 香柠檬/果香);仅凭零散调名不得臆造。三调主要用于补充整体香型方向(C/A3)。
3. 修订冲突:评香与 r1 标签明确矛盾时,rem 旧标签并 add 正确标签(必须字典内 ID、层级正确)。例如 子香族=青滋柑橘 而 r1 为花香→rem 花香 add 青绿。
4. C:只用 C 树中该品类叶子(节点类型=叶子),按品类→闸门路径+判定补充判断;允许合理弱推断。不要利用 C→AB 映射反向填充香精属性。产品形态不明的洗护/织物行不强行贴 C。
5. 产品与品牌:不新增、不移除产品候选,不重复品牌搜索;prod_add/prod_rem 一律空数组。dupe 仅当评香/借鉴品牌给出明确强线索时才修订,否则 null。
6. 评香与名称都无据可依的标签不补;未识别气味术语放入 unresolved。
7. 仅当评香字段完全无法提供新信息且 r1 全部准确时,该行输出 {"source_row": N}(表示无修订);能补则补,能改则改。

输出契约(每输入行一行 JSON,行数与输入一致):
{"source_row": N, "cat_ids": null, "cat_cand": [], "add_A1": [], "rem_A1": [], "add_A2": [], "rem_A2": [], "add_A3": [], "rem_A3": [], "add_B": [], "rem_B": [], "add_C": {}, "rem_C": {}, "prod_add": [], "prod_rem": [], "dupe": null, "unresolved": [], "notes": []}
- 省略或 null=保留 r1 基线;add/remove 作用于 r1。add_C/rem_C 形如 {"CAT_07": ["C_980"]}。
- 所有 ID 必须来自提供的字典;不要输出占位符;不要解释,只输出 JSON 行。

示例(参考,非输入):
- review={"香族":"琥珀","子香族":"东方"}, r1={A3:["A3_东方调"],A2:[]} → {"source_row": N, "add_A2": ["A2_507b335ba9"]}
- review={"香族":"花香","子香族":"海洋花香"}, r1={A3:["A3_海洋花香调"],A2:[]} → {"source_row": N, "add_A2": ["A2_d7ffd3d58c"]}
- review={"子香族":"青滋柑橘"}, r1={A2:["A2_83fdd91606"],A3:["A3_青绿柑橘调"]} → {"source_row": N, "rem_A2": ["A2_83fdd91606"], "add_A2": ["A2_5d71794f8c"]}
- review={"香族":"果香","子香族":"红果与浆果","风格":"清新"}, r1={A1:[],A2:["A2_c6c54a254f"],A3:["A3_红果浆果调"],B:[]} → {"source_row": N, "add_A2": ["A2_ad99ceb2cd"], "add_B": ["B_清新"]}"""

# ---------------- one batch call ----------------
def process_batch(bid):
    result_path = os.path.join(R15, f"{bid}_result.jsonl")
    if os.path.exists(result_path):
        with open(result_path, encoding="utf-8") as f:
            n = len([l for l in f.read().splitlines() if l.strip()])
        return {"batch": bid, "state": "resumed", "rows": n}
    with open(os.path.join(CTX, f"{bid}.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f.read().splitlines() if l.strip()]
    with open(os.path.join(CTX, f"{bid}_ctx.json"), encoding="utf-8") as f:
        ctx = json.load(f)
    c_text = "C 判定树(id | 品类 | 维度 | 节点类型 | 标签 | 完整路径 | 判定补充):\n" + "\n".join(ctx["C_tree"])
    with open(os.path.join(WORK, "ctx", "slim", "dicts.txt"), encoding="utf-8") as f:
        dicts = f.read()

    user = (f"字典(品类/A/B标签/品牌/C判定补充/旧转换):\n{dicts}\n\n"
            f"{c_text}\n\n"
            f"批次 {bid}({len(rows)} 行,每行 review(评香字段)+r1(第一轮结果)):\n"
            + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            + f"\n\n输出 {len(rows)} 行修订 JSON(每输入行一行,顺序一致),仅输出 JSON 行文本。")

    last_err = None
    for attempt in range(RETRIES):
        try:
            out = call_api(user)
            lines = parse_output(out, rows)
            if len(lines) != len(rows):
                last_err = f"row-count {len(lines)} != {len(rows)}"
                time.sleep(2 * (attempt + 1))
                continue
            with open(result_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
            return {"batch": bid, "state": "ok", "rows": len(lines)}
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    return {"batch": bid, "state": "failed", "error": last_err}

def call_api(user):
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }
    if THINKING_DISABLED:
        payload["thinking"] = {"type": "disabled"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body,
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
        row = next((r for r in rows if r.get("source_row") == rec.get("source_row")), None)
        out.append(translate(rec, row))
    return out

def _ids(lst):
    """strip 'id:label' suffixes the LLM may mirror from r1 baseline"""
    out = []
    for x in lst or []:
        x = str(x).split(":")[0].strip()
        if x and x not in out:
            out.append(x)
    return out

def translate(rec, row):
    """compact -> v4 corrections contract; auto evidence referencing review fields"""
    cat_ids = rec.get("cat_ids")
    cat_ids = _ids([cat_ids])[:1] if isinstance(cat_ids, str) and cat_ids else (
        [_ids([cat_ids[0]])[0]] if isinstance(cat_ids, list) and cat_ids else None)
    v = {
        "source_row": rec.get("source_row"),
        "category_ids": cat_ids,
        "category_candidates": rec.get("cat_cand") or [],
        "tags_A1_add": _ids(rec.get("add_A1")), "tags_A1_remove": _ids(rec.get("rem_A1")),
        "tags_A2_add": _ids(rec.get("add_A2")), "tags_A2_remove": _ids(rec.get("rem_A2")),
        "tags_A3_add": _ids(rec.get("add_A3")), "tags_A3_remove": _ids(rec.get("rem_A3")),
        "tags_B_add": _ids(rec.get("add_B")), "tags_B_remove": _ids(rec.get("rem_B")),
        "tags_C_add": {k: _ids(v2) for k, v2 in (rec.get("add_C") or {}).items()},
        "tags_C_remove": {k: _ids(v2) for k, v2 in (rec.get("rem_C") or {}).items()},
        "product_candidates_add": rec.get("prod_add") or [],
        "product_candidates_remove": rec.get("prod_rem") or [],
        "dupe_status": rec.get("dupe"),
        "unresolved_terms": rec.get("unresolved") or [],
        "review_notes_add": rec.get("notes") or [],
        "evidence_add": rec.get("evidence") or [],
        "status": rec.get("status"),
    }
    # auto evidence: source = 评香字段(主韵/香族/子香族等,不含三调作为香韵证据)
    review = (row or {}).get("review") or {}
    src_parts = []
    for k in ("主韵关键词", "香族", "子香族", "风格", "人格特质", "联觉"):
        if review.get(k):
            src_parts.append(f"{k}={review[k]}")
    source_text = "；".join(src_parts) or (row or {}).get("fragrance_name", "")
    added_ids = list(v["tags_A1_add"]) + list(v["tags_A2_add"]) + list(v["tags_A3_add"]) + list(v["tags_B_add"])
    for cids in v["tags_C_add"].values():
        added_ids.extend(cids)
    seen = {e.get("tag_id") for e in v["evidence_add"] if e.get("tag_id")}
    for tid in added_ids:
        if tid not in seen:
            v["evidence_add"].append({"tag_id": tid, "source_field": "评香字段",
                                      "source_text": source_text, "inference_type": "legacy_review",
                                      "confidence": "medium"})
            seen.add(tid)
    return v

def main():
    only = None
    if len(sys.argv) > 1:
        only = sys.argv[1]
    bids = sorted(f.replace(".jsonl", "") for f in os.listdir(CTX)
                  if re.fullmatch(r"batch_\d{3}\.jsonl", f))
    if only:
        bids = [b for b in bids if b == only or b.startswith(only)]
    print(f"r15 batches to process: {len(bids)}", flush=True)
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
