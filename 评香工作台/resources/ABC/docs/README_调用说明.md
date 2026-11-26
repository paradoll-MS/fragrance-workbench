# 中央闻香库第一轮+1.5+第二轮 · 输出数据调用说明

本说明记录中央闻香库清洗产物的字段和来源。机器可读数据在 [output](../output)，人可读工作簿和复核清单在本目录。第二轮人可读表是较早的 838 款增量快照。选香模块接手准备见 [ABC 目录首页](../README.md)。

## 文件清单与用途

| 文件 | 内容 | 主键 | 说明 |
|---|---|---|---|
| `fragrance.jsonl` | 香精主视图(唯一有效编号一行;冲突编码保留多行并带 `conflict` 标记) | `fragrance_id`(原编码,字符串) | 含 category_ids、tags_A1/A2/A3/B、tags_C_by_category、dupe_status、product_candidates、tag_evidence、is_new/is_hot/entry_logic_raw、source_row(s)、batch_id、input_hash |
| `fragrance_tags.jsonl` | 每条标签一行 | `fragrance_id` + `tag_id` + `category_id` | A/B 不绑品类(category_id=null),C 绑定品类;含 inference_type、confidence、status |
| `brand.jsonl` | 品牌目录 | `brand_id` | canonical_name、international_name、aliases[]、status |
| `product.jsonl` | 产品目录 | `product_id` | brand_id、product_name、aliases[]、identity_status(verified/待核验)、verification_url、edition_note |
| `fragrance_product.jsonl` | 香精↔产品候选关系 | `fragrance_id` + `product_id`(或候选名) | relation_status(strong_candidate/ambiguous/candidate)、identity_status;**未确认的仿香关系不得当作精确命中** |
| `review_queue.xlsx` | 复核清单 | — | 缺码/0码/#REF!、原始库未关联、重复编码合并与冲突、品类未定、未识别术语、产品待核验、校验错误 |
| `batch_manifest.json` | 批次与覆盖率统计 | — | taxonomy_version、行数、编码、品类覆盖、标签分布、dupe 分布、round15 增量、价格字段、错误数 |
| `中央库第一轮清洗结果_人可读.xlsx` | 全库人可读视图(第一轮+1.5) | `source_row` | 每行含 ID 与中文标签、原字段、评香字段(香族/子香族/三调/主韵/风格/人格/联觉)、系统报价、价格段、证据与状态 |
| `中央库第二轮历史工单补标结果_人可读.xlsx` | 第二轮增量人可读视图(838 款) | 编码 | 每款含历史新增 A1/A2/A3/B/C(中文)、涉及工单数、反证数、新增品类候选 |
| `qa_vs_draft.json` | 与人工试跑示范(33行)的一致性对照 | — | 逐字段一致率 |

## Round 1.5(评香字段补标)说明

- 补读原始《【wip】中央闻香库20260623.xlsx》,**openpyxl 直读**(多行单元格完整),按 `source_row`+编码+名称校验关联(3886/3890 行,4 行见复核清单「原始库未关联」;行序错位 37 条已按编码+名称对齐)。
- 修复原始读取异常(原 TSV 中转导致多行单元格截断/列错位):三调 412、主韵 90、风格 30、报价 418、价格段 388 行逐字段修正;**系统报价恢复 2610→3199 行非空,价格段 1049→1436 行**。
- 评香字段修正的 **1578 行**已重跑 LLM 补标(fix 批次 batch_100+),与首轮 r15 结果分层合并(旧增量保留 + 修正增量叠加),共 1963 行经 LLM 判定。
- **三调(前/中/后调)仅用于 A3/C 整体香型方向,禁止直接依据三调新增 A1/A2**;A1/A2 证据以主韵关键词/香族/子香族/风格/名称为准。已核查 fix 批新增 A1/A2 中「仅在三调原文出现」的 **1808 条(A1 1782 / A2 26)已移除**,清单见 `_work/r15/triad_removals.jsonl`,复核见 review_queue。
- A1/A2/A3/B/C 新增与冲突修订均已合并,证据 `inference_type=legacy_review` 指向评香字段;层级混用/跨品类等 54 条校验错误已剔除入复核清单。
- 保留第一轮新品(265)/爆品(1171)/产品候选(711)成果,不重复品牌搜索。
- `#REF!` 等无效编码已移出主视图,仅存于复核清单;第二轮冲突编号按 source_row + 工单香精名称区分,不盲目合并。
- 新增字段:`system_quote`(系统报价,3199 行)、`price_segment`(大众/中端/高端/价格未知,1436 行)、评香原文字段(family/subfamily/three_accords/main_notes/style/personality/synesthesia),供 wanted 价格段筛选。价格段为原库字段,非市场断言。
- 执行通道:`llmapi.paratera.com`(THU dsflash DeepSeek-V4-Flash-0731,PARATERA_API_KEY 直连,`thinking` 禁用以提速),全量断点续跑。

## Round 2(历史工单补标)说明

- 数据:**完整香精工单 SQLite**(`标签和静态数据/05_清洗过的项目工单数据/香精工单.sqlite3`,任务文档 canonical schema):工单 3566 / 项目 2578 / 用样 10819 / central formula_refs 3832;与文档基线一致。
- 任务:**1716 张工单**(1233 有用样 + 483 仅正文提及),覆盖在库 1358 款;一张工单一次综合 LLM 判断(§3 Prompt + §4 分组输出协议),关闭 reasoning 直连批量,940 张复用首轮结果、776 张新增执行,0 失败,断点续跑。
- 新增交付物(本轮机器可读数据,供 wanted 与检索直接调用):
  - `work_contexts.jsonl`(1716 行):每单原始语义单元(direction/query_abc/categories/notes),`task_id` 对应 `history_*` 的 `work_order_id`;
  - `history_relations.jsonl`(3426 行):香精↔工单↔方向关系(含 kind:direct_evaluation/selected/recommended/near_match/reference_only/logistics_only/ambiguous 等);
  - `history_category_evidence.jsonl`(1940 行):香精在历史应用品类中的证据(仅实际使用依据:recommended/selected/direct_evaluation/near_match 类);
  - `history_tag_evidence.jsonl`(29081 行):香精×标签×工单证据明细(tag_id 全部为字典合法 ID,仅合法 C 叶子、C 品类零错位);
  - `history_counterevidence.jsonl`(125 行):明确缺少/冲突属性反证(合并时按「香精,标签」阻断同属性正向写入)。
- 主视图合并:history 标签 **7623 条**(A1 2174 / A2 849 / A3 806 / B 3261 / C 533)已同时写入 `fragrance_tags.jsonl`(`inference_type=history`、`status=trial`)与 `fragrance.jsonl` 的 ABC 字段(两视图一致,已校验 0 缺失);推荐类历史品类进 `category_candidates`(777 行,保留历史候选身份,不视为应用测试已通过)。
- 校验:**reference_only/logistics_only/modification_base/ambiguous/rejected 类关系不继承客户目标标签**(程序层阻断,仅保留 relations 记录与对该香精的实际描述 individual);C 品类中文名统一转 CAT ID 校验,仅叶子可写;复核新增 1578 条(gaps 1268 / 真实校验错误 310:闸门 225 + 跨品类 85)。

## 调用示例(伪代码)

```python
# 按标准品类筛选
rows = [r for r in load("fragrance.jsonl") if "CAT_07" in r["category_ids"]]
# 按 A1/A2/A3/B/C 标签检索(候选检索可用,精确匹配仅限 confirmed)
hits = [r for r in rows if "A1_578f5613cd" in r["tags_A1"]]
# 产品身份精确查找要求 identity_status=verified 且 relation_status=confirmed
exact = [fp for fp in load("fragrance_product.jsonl")
         if fp["relation_status"] == "confirmed" and fp["identity_status"] == "verified"]
# 未确认产品只作候选入口
candidates = [fp for fp in load("fragrance_product.jsonl")
              if fp["relation_status"] in ("strong_candidate", "ambiguous")]
```

## 重要边界

- 本轮为**冷启动试跑**:候选覆盖优先,弱证据可贴标(trial);未人工确认前不得视为已确认属性。
- `is_new`/`is_hot` 为原库标识(0=原库未标记),不是对市场现状的断言。
- `dupe_status=strong_candidate/ambiguous` 不等于仿香关系已确认;`brand_only` 仅品牌线索。
- 历史工单证据(inference_type=history)已并入 fragrance_tags.jsonl,全部为 trial 级弱证据,参与候选检索,不视为已确认属性;反证见 history_counterevidence.jsonl。
- 0/空码记录仅以 source_row 暂存于 review_queue,未写入正式身份表。
- 字典外的未识别术语集中在 review_queue「未识别术语」,待补充字典后二次检查,未擅自扩字典。
