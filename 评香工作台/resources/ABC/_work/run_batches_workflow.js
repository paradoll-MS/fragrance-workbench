// 中央闻香库第一轮冷启动 · LLM 批次判定编排(v3: 基线+修正, 每批30行)
const WORK = "C:\\Users\\26519\\Desktop\\交付总控\\ABC\\_work";
const CTX = WORK + "\\ctx";
const batchCount = 130;
const waveSize = 13;

const batchIds = Array.from({ length: batchCount }, (_, i) => String(i + 1).padStart(3, "0"));

function promptFor(id) {
  return [
    "你是「中央闻香库」标签判定员,负责审查一个批次的香精记录基线并输出修正。",
    "",
    `工作区: C:\\Users\\26519\\Desktop\\交付总控\\ABC`,
    `指令文件: ${CTX}\\batch_${id}\\instructions.md  (必须先完整读取,严格按其规则与输出契约执行)`,
    `合并字典: ${CTX}\\shared\\dicts.txt  (约65KB,一次读完;内含categories/tags_A/tags_B/alias_AB/brands/c_decision/legacy)`,
    `C 子树: ${CTX}\\batch_${id}\\C.txt`,
    `产品字典: ${CTX}\\batch_${id}\\products.txt`,
    `批次输入: ${CTX}\\batch_${id}\\batch.jsonl  (每行 {"input":..., "baseline":...},共30行)`,
    `结果输出: ${WORK}\\batches\\batch_${id}_result.jsonl  (UTF-8,每输入行对应一行修正 JSON,顺序一致,行数必须相等)`,
    "",
    "执行步骤:",
    "1. 用 read 工具完整读取 instructions.md,再读取 dicts.txt、C.txt、products.txt、batch.jsonl。",
    "2. 逐行审查 baseline 并输出修正 JSON(省略/null=保留基线;只补你判断的 A2/B/C、校验 A1/A3、处理产品歧义与品类修正)。",
    "3. 所有 ID 必须来自字典;不要输出占位符;C 只输出该品类下的叶子。",
    "4. 把结果写入结果文件(一行一个 JSON)。",
    "5. 完成后回复一行 JSON:`{\"batch\": \"${id}\", \"rows\": 30, \"ok\": true, \"notes\": \"...\"}`。",
  ].join("\n");
}

phase("llm-batches");
const summaries = [];
for (let start = 0; start < batchIds.length; start += waveSize) {
  const wave = batchIds.slice(start, start + waveSize);
  log(`wave ${start / waveSize + 1}: batches ${wave[0]}..${wave[wave.length - 1]} (${wave.length})`);
  const results = await parallel(
    wave.map((id) => () =>
      agent(promptFor(id), { label: `batch-${id}`, phase: "llm-batches" })
    )
  );
  let ok = 0, fail = 0;
  for (let i = 0; i < wave.length; i++) {
    const r = results[i];
    if (r && typeof r === "string" && r.includes('"ok"')) {
      ok++;
      summaries.push(r);
    } else {
      fail++;
      summaries.push(JSON.stringify({ batch: wave[i], ok: false, raw: r }));
    }
  }
  log(`wave done: ok=${ok} fail=${fail}`);
}

return { totalBatches: batchIds.length, summaries };
