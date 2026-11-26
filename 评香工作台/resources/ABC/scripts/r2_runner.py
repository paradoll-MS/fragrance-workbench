# -*- coding: utf-8 -*-
"""r2_runner.py — 第二轮历史工单补标:一张工单一次 LLM 调用(§3 Prompt + §4 分组协议)。
直连 llmapi.paratera.com (THU dsflash), thinking disabled。断点续跑按 task_id。
用法: python r2_runner.py [task_id...]  — 无参数则全部; 支持 'task_id1,task_id2' 或前缀
输出: _work/r2/results/<task_id>.json (原始模型输出翻译后的分组协议)
"""
import json, os, re, sys, time, hashlib
import urllib.request, urllib.error
import concurrent.futures as cf

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
WORK = os.path.join(WS, "_work")
R2 = os.path.join(WORK, "r2")
RES = os.path.join(R2, "results")
CTX = os.path.join(R2, "full_contexts.jsonl")
KEY_FILE = r"C:\Users\26519\.dsh\.credentials.yaml"
MODEL = os.environ.get("R2_MODEL", "DeepSeek-V4-Flash-0731")
API_URL = "https://llmapi.paratera.com/chat/completions"
MAX_TOKENS = 8192
TEMPERATURE = 0.0
CONCURRENCY = int(os.environ.get("R2_CONCURRENCY", "12"))
RETRIES = 4

def load_key():
    text = open(KEY_FILE, encoding="utf-8").read()
    m = re.search(r"PARATERA_API_KEY:\s*(sk-[^\s,}]+)", text)
    if not m:
        raise SystemExit("PARATERA_API_KEY not found")
    return m.group(1).strip()

KEY = load_key()

SYSTEM = """你是香精公司的评香数据标注助手。根据一张历史工单的完整语境,给其中相关中央库香精补充适用品类和 ABC 候选标签。你不负责数据库操作、联网或逐标签审计。

当前是冷启动,有>准。把评香实际推荐行为视为有价值的弱证据:如果某款香精被推荐给一个明确的需求方向,通常可以合理继承该方向的公共定位、香韵、感受等,不需要客户逐款确认。结合内部名、对客名、第一轮标签及反馈积极推断;对于合理但不完全确定的标签,允许输出。不要为了填满维度硬猜,也不要因没有实测证据而拒绝一切推断。

在一次综合判断中完成以下工作:
1. 判断本轮真实终端应用(原文及用样指令优先于旧品类和项目标题);识别公共需求、独立方向,以及哪些香精属于哪些方向。允许多对多、跨品类。仅处理本单实际涉及的应用,不广播整个项目的用途。方向不清时仍可补公共品类/定位。纯补库、参照样或排除对象不等同于应用推荐。
2. 理解方向的需求 ABC,再判断可合理归给相关香精的 ABC。公共标签按组返回一次,个别差异单独返回;具体香气不要从其他独立方向随意复制。若一款香精可能近似匹配,优先继承宽泛香韵和定位;名称明显指向某个方向时可以推断具体气味。直接评价可作为更强证据。修改目标不是原香已有属性;负面评价若描述实际存在的气味,仍可作为正向气味证据;明确缺少的属性记录反证,不自动删除已有标签。当方向明确且字典存在对应标签时,公共组 tags 必须给出(用字典 ID 或字典内中文均可,程序会映射);不要因保守而留空可用标签。
3. A1=气味对象,A2=香韵及气味特征,A3=整体香调,B=感官、情绪及审美。可以依据语义和市场常识推断,不把成分宣称等同闻感,不凭单一原料硬推复合香调。
4. C 按真实应用品类分别判断:理解完整路径,必要时经过闸门并参考左侧解释,只输出有效叶子。允许直接理解明确叶子,不必逐层报告判断过程。多维度、多叶子均可命中;不要求填满四维度。场景本身不必然等于其下某个香气偏好,但上下文足够时应积极推断。若只有 AB 或无法选出合理 C,可以不贴 C。不能将其他品类 C 借来使用,不能通过 C→AB 映射或 AB 反推定位。
5. 只输出所给字典中的合法 ID;真实存在但字典表达不了的定位简短记入 gaps,不创建标签。品类不明不妨碍 AB 补标。仅输出相关中央库对象。无需逐标签理由、置信度或原文复述,只需给每组共用的证据备注编号;真正冲突、反证、无法归属或字典缺口才写简短说明。

6. 工单性质识别(重要):若标题/正文表明本单是「补样申请/补库/仅寄样/参照样/对比样/排除/取消/不再寄/仅提及编号」等非推荐行为:
   - 该单(或其中对应样品)kind 用 logistics_only / reference_only / rejected / ambiguous,不新增终端品类,不产出 C,不把仅重复已有信息的对客名当作新需求证据;
   - 对确实描述到真实气味的样品,只可在 individual 中给出原有真实描述,不继承任何目标方向标签。
7. 反证必录:原文明确说「没有/缺少/不要/不想要/差」某个属性(如"没有水汽和湿气、只有凉意")时,必须在 counter 中记录该缺失/冲突属性,text 简述原文;不得将该属性补进该香精标签。
8. 组名 g 全单唯一(如 d1/d2/d3),方向不同必须用不同组名;同方向同品类同类目不要重复建组。

按约定 JSON 结构直接返回结果;公共标签和个别标签均为本次历史证据支持的标签,是否已在第一轮存在由程序去重。允许返回空组/空标签。不要输出分析过程、Markdown 或额外说明。

输出协议(JSON):
{"groups": [{"g":"d1","direction":"简短需求方向名","cat":["CAT_02"],"samples":[1,2],"kind":"recommended","n":[1],"query":{"A1":[],"A2":[],"A3":[],"B":[],"C":[]},"tags":{"A1":[],"A2":[],"A3":[],"B":[],"C":[]}}],
 "individual": [{"s":1,"g":"d1","cat":[],"kind":"direct_evaluation","n":[2],"tags":{"A1":[],"A2":[],"A3":[],"B":[],"C":[]}}],
 "counter": [{"s":2,"n":[3],"tag":"","text":"明确缺少水汽"}],
 "gaps": [{"cat":"CAT_04","text":"面部纯果香定位无适当C叶子"}],
 "unresolved": [{"s":3,"reason":"只被提及,未明确推荐"}]}
约定:空字段可省略;query=方向目标(不直接写给香精),tags=可继承的香精候选属性;若相同用 "tags_same_as_query": true。groups.samples 只列真正可共享该组 tags 的中央库对象;单款新增/修正放 individual;重叠组允许,程序取并集。cat 是真实应用品类集合,C ID 必须属于其中相应品类;individual.cat 为空时继承 g 的品类;无 g 时必须明确给出 C 所属品类。AB 即便品类未知也可输出。kind 用 direct_evaluation/selected/recommended/near_match/modification_base/reference_only/rejected/logistics_only/ambiguous。n 是支持整组判断的备注引用,仅用样行提供线索时 n 可空。不要求置信度;一律 trial。"""

def load_c_trees(task):
    """load C tree lines for categories involved in this task"""
    cats = set()
    for s in task.get("samples", []):
        p = s.get("prior", {})
        for c in p.get("categories", []):
            cats.add(c)
    # map Chinese cat -> CAT code
    cat_code = {}
    with open(os.path.join(WORK, "categories.txt"), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0]:
                cat_code[p[1]] = p[0]
    codes = {cat_code.get(c) for c in cats if c in cat_code}
    if not codes:
        codes = set()
    lines = []
    with open(os.path.join(WORK, "tags_C.txt"), encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 7 and p[0] and (not codes or p[1] in codes):
                lines.append(f"{p[0]} | {p[1]} | {p[2]} | {p[6]}")
    return lines

def build_user(task):
    with open(os.path.join(WORK, "ctx", "slim", "dicts.txt"), encoding="utf-8") as f:
        dicts = f.read()
    c_lines = load_c_trees(task)
    c_text = ("C 判定树(id | 品类 | 维度 | 完整路径 | 判定说明):\n" + "\n".join(c_lines)) if c_lines else ""
    payload = json.dumps({k: v for k, v in task.items() if k != "notes" and v is not None}, ensure_ascii=False)
    # notes as-is (with n indices)
    notes = task.get("notes", [])
    samples = task.get("samples", [])
    mentions = task.get("mentions", [])
    compact = {"task_id": task["task_id"]}
    if task.get("old_category"): compact["old_category"] = task["old_category"]
    if task.get("title"): compact["title"] = task["title"]
    if task.get("project_name"): compact["project_context"] = task["project_name"]
    if notes: compact["notes"] = notes
    if samples: compact["samples"] = samples
    if mentions: compact["mentions"] = mentions
    return (f"字典(品类/A/B标签/品牌/C判定补充/旧转换):\n{dicts}\n\n{c_text}\n\n"
            f"工单上下文:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            "按输出协议返回该工单的分组 JSON,仅 JSON 文本。")

def call_api(user):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
        "thinking": {"type": "disabled"},
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
    return data["choices"][0]["message"]["content"]

def parse_output(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None

def process(task):
    tid = task["task_id"]
    out_path = os.path.join(RES, f"{tid}.json")
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            rec = json.load(f)
        return {"task_id": tid, "state": "resumed", "rows": len(rec.get("groups", [])) + len(rec.get("individual", []))}
    user = build_user(task)
    last_err = None
    for attempt in range(RETRIES):
        try:
            out = call_api(user)
            rec = parse_output(out)
            if rec is None or "groups" not in rec and "individual" not in rec:
                last_err = "unparseable"
                time.sleep(2 * (attempt + 1))
                continue
            os.makedirs(RES, exist_ok=True)
            rec["_raw_len"] = len(out)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            return {"task_id": tid, "state": "ok",
                    "groups": len(rec.get("groups", [])), "individual": len(rec.get("individual", []))}
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    return {"task_id": tid, "state": "failed", "error": last_err}

def main():
    only = None
    if len(sys.argv) > 1:
        only = set(a.strip() for a in sys.argv[1].split(","))
    with open(CTX, encoding="utf-8") as f:
        tasks = [json.loads(l) for l in f if l.strip()]
    if only:
        tasks = [t for t in tasks if t["task_id"] in only]
    print(f"r2 tasks to process: {len(tasks)}", flush=True)
    done, failed = [], []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(process, t): t["task_id"] for t in tasks}
        for fut in cf.as_completed(futs):
            tid = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"task_id": tid, "state": "exception", "error": str(e)}
            if res["state"] == "ok":
                done.append(tid)
            else:
                failed.append(res)
            if len(done) + len(failed) % 20 == 0 or len(failed) > 0 and len(done) + len(failed) % 50 == 0:
                pass
            print(json.dumps(res, ensure_ascii=False), flush=True)
    print(f"done: {len(done)} | failed: {len(failed)} | elapsed: {round(time.time()-t0)}s", flush=True)
    for f in failed[:10]:
        print("FAILED:", json.dumps(f, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
