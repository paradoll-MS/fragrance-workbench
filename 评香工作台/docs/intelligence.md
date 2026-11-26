# 信息提取与标签映射

这一份说的是「客户资料怎么变成可执行的字段」，以及「这些字段怎么进筛选」。
两个 LLM 节点：parse/拆解 与 targeting/贴标签。其它环节不调模型。

## 1 两层 brief

ProjectBrief 项目级，所有方向继承，来自客户资料里只出现一次的条件：

- 身份：customer、brand、project_code、brief_goal
- 应用：application_id（CAT_xx）、application_name、substrate、form、end_product、dosage_text
- 人群与市场：target_audience、age_band、gender、markets（规则文件的市场码）
- 商业：price_text、price_rule、price_min、price_max、price_target、quantity_text、sample_due、launch_date、deadline_text、delivery_note
- 合规：stability_required、stability_note、flash_point、regulatory[]、prohibitions[]、certifications[]、allergen_scope[]
- 其它要求：requirements[]，每条 `{text, kind, mandatory, metric_id}`
- open_questions[]：资料里确实没写、需要人补的问题

DirectionBrief 方向级，只写与项目级不同或项目级没有的：

- 身份：title、scent_text（客户对这个方向的香气原话）、scent_notes、scent_families[]
- 取舍：exclusions[]（明确不要）、feelings[]、scenes[]、references[]
- 覆盖：application_id、review_category_id、substrate、end_product、dosage_text、target_audience、markets
- 模式：mode（recommend_simple / recommend_brand / with_sample），由入口决定，确认时落进 `goal.fields`
- 该方向额外要求：requirements[]

继承规则：方向没有写的字段沿用项目级；写了就覆盖；两边都没有就留空，不推断。
展开后的结果写进 `goal.fields`，同时把原始的 `{shared, direction}` 存在 `round.brief`，
`parse_draft.result` 保存模型原样输出，三处都可回看。

## 2 parse/拆解

`intelligence.parse.propose(segments, context, application_categories, review_categories, model)`
输入是可读资料片段，每条带 `id / locator / kind / text`；输出只进草案，不改业务状态。

模型必须输出 `{project_name, summary, shared, directions[], open_questions[]}`。
硬规则写在提示里，代码再校验一遍：

- 一个「建议方向」就是一条 direction，不合并、不拆成单个香调；不同产品、不同应用、不同参照样、不同市场、不同交付终点也各成一条。
- 法规、禁用物、过敏原、闪点、稳定性要求逐条保留原文，不压缩、不判断合规、不补限值。
- 否定、条件、例外进 exclusions 或 open_questions，不能压成无条件结论。
- 每条 direction 的 `basis` 必须是来源原文的逐字片段；代码用去空白后的子串核对，核对不上就丢进 open_questions。
- 价格、添加量、数量只抄原文，不猜；缺字段直接省略。

代码做的归一：

- `normalize_shared` 把市场转规则码，按稳定性原话推断 `stability_required`（「否」→ false）。
- `brief.requirement` 把 `requirements` 统一成 `{text, kind, mandatory, metric_id}`；`kind` 决定走哪类检查：stability → `Q_STABILITY`，其余 → `R_EXTRA`。
- 客户勾了「不做稳定性考察」时，那条说明按 `R_EXTRA` 记，不生成稳定性检测；勾了「做」才生成 `Q_STABILITY`。
- 模型把对象写成字符串时会被拆开一次，避免整段变成 `{'text': ...}`。
- `application_id`、`review_category_id` 只接受词表里的值，不在词表就留空并记一条问题。

失败策略：模型失败抛 `ModelError`，页面提示可重试或手填；不会留下半份草案。
缺字段不是失败，草案照常成立，空字段在确认页可见可补。

## 3 targeting/贴标签

`intelligence.targeting.tag_direction(brief, mode, catalog, scoring_config, model)`

输入是展开后的 `goal.fields`，实际送模型的有：

- mode：recommend_simple / recommend_brand / with_sample
- category：application_id 对应的应用品类名
- target_audience：人群原话
- markets：市场
- scent_text、scent_notes：这个方向的香气原文
- scent_families、exclusions、feelings、scenes
- requirements：客户要求原文（法规、性能、稳定性都算，但提示明确它们不是选 C 的依据）
- candidates：该应用品类下所有可选 C 叶子，每个带 `c_id / path / dimension / guidance / ab_terms`
- rules：表 `LLM判断规则` 的统一判断规则

`guidance` 来自 `品类与ABC标签体系_V2.xlsx` 的 `C左侧判定补充` 页，`ab_terms` 来自
`C到AB关联映射`。`Catalog.c_candidates(category)` 只给叶子，闸门节点不参与。

模型输出：

```
{"c_ids":[],"primary_c":"","items":[{"c_id":"","basis":"","confidence":0.0}],
 "used_conditions":[],"unmapped":[]}
```

校验与后处理：

- `c_id` 必须在候选里，否则进 unmapped。
- `basis` 按 `；，、` 切开后每一段都要在客户文本里出现；引用不上的进 unmapped，不采纳。
- basis 里出现「主打/核心/必须/主调/以…为主」，并且 C 的名字出现在 basis 里，才标 required；其余 preference。
- with_sample 一律 preference，避免把参照样需求变成硬筛。
- C → A/B 不靠模型，直接查 `catalog.edges`，由排序函数 `score_branch` 用；这样 C 的语义和 A/B 的命中是同一套字典。
- 模型不可用或没给出可用 C 时，退回 `ranking.parse_text` 的词面匹配，仍返回可用的 A/B 组，`method` 记「字典词面」。

输出另有 `items`（C 名称、路径、依据）、`used_conditions`、`unmapped`、`method`、
`dictionary_version`。这些全部写进 `goal.fields.targeting`，页面展开可见。

## 4 字段去向

- 项目级合规与人群 → 每个方向 `goal.fields`，检查清单 `check_set.context`，要求条目 `requirement.origin_text`。法规原文因此能从要求直接回到客户原话。
- 方向香气原文 → `goal.fields.scent_text`，打标输入，查询的 `text`，也是界面「需求」块的第一行。
- 打标结果 → `goal.fields.targeting`；检索时 `search(goal_id=...)` 直接取这些 C 组，不再重新解析文字。
- 客户要求 → `requirement` 表，source 为 customer；发布与入库的阻断看这些要求，不看模型输出。
- 未决问题 → `parse_draft.result.open_questions` 与 `round.brief.open_questions`，只展示，不阻断。

## 5 查询时怎么用

`search` 给 `goal_id` 时按目标字段组装查询：

- `categories` 用目标的 application_id，保证 C 标签有归属。
- `groups` 用 `targeting.groups`；没有就打一次 tag_direction 并缓存到目标上。
- 价格上下限用目标字段；文字只作展示，不再覆盖标签。
- 没给 goal_id 时仍可按自由文字检索，走 `parse_text` 的老路。

## 6 每次调用在哪里看

项目页最下面有「模型调用」，按时间倒序列出这个项目的每一次请求：

- 一行一条：用途（拆解资料／打标签／图片转写）、模型、状态、耗时、时间。
- 点「看请求」打开三块：产出要求（system）、输入（user）、返回（或错误）。
- 产出要求就是当次真正发给模型的 system 原文，包含字段清单、拆分规则和输出 JSON 形状；不是事后重写的说明。
- 输入是真正发给模型的 user 原文，已做联系方式脱敏；图片调用的 base64 不入库，只留「[图片已省略]」。
- 返回保留原文，即使 JSON 解析失败或被校验拒绝，也能看到模型到底写了什么。

对应的表和接口：

- 表 `llm_call`：`project_id / purpose / model / status / request / response / error / seconds`。
- `GET /api/projects/{id}/llm-calls`：列表，只带长度，不带全文。
- `GET /api/llm-calls/{id}`：单次全文。
- 代码里的固定文本：`intelligence/parse.py` 的 `PROMPT`、`intelligence/targeting.py` 的 `INSTRUCTIONS`；组装输入的 `propose()` 与 `tag_direction()` 紧挨着它们。

没有记录的调用：在进入模型前就返回的（如品类未定、没有香气描述），因为不存在请求；这些情况在打标结果的 `method` 和 `unmapped` 里说明。

## 7 明确不做的事

- 不在 parse 阶段判断方向类型之外的事（不选香、不判合规）。
- 不把法规条文变成 C 标签，也不让法规条文进 required 香气组。
- 不对缺失字段做行业默认值；需要默认值的地方在审查规则里，有来源字段。
- 不因为某个字段缺失阻断流程；阻断只来自检查要求未满足或动作不在当前阶段。

