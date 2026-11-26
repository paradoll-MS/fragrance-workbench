# Functions ／ 功能契约 F01–F24

契约只有一条主线：读资料 → 定方向 → 选香或开发 → 检查与放行 → 寄样 → 结束。每个功能都能在代码里找到唯一落点，接口只做参数与返回，不写业务。

约定：

- 输入缺字段时留空、用默认值或明确跳过，不拦人；只有真正无法继续的动作才返回阻断（`blocked` + `issues`）。
- 非法参数、对象不存在、越权抛 `ValueError`，由 HTTP 映射成 400 与一句中文说明。
- 所有写库在 `Workbench` 的同一个事务里完成，并写 `audit`。

## 资料与方向

- **F01 建项** `create_project` / `rename_project`：名称必填，其余可留空；建项后 revision 为 1。接口 `POST /api/projects`、`PATCH /api/projects/{id}`。拒绝：空名称。
- **F02 收资料** `add_source` + `source_segments`：文字、JSON base64 或文件；按 txt / md / csv / pdf / docx / pptx / xlsx 解析，图片只有勾选视觉时才送模型。原件与定位落盘，读不出的部分记 `warnings` 而不是失败。接口 `POST /api/projects/{id}/sources`。
- **F03 拆方向** `analyze` → `intelligence.parse.propose`：把资料拆成项目级 brief 与 1–6 个方向 brief。项目级放人群、市场、基质、添加量、合规、价格、数量、交期；方向只放自己的香气原文、家族、排除项、参照样与额外要求。客户列出的每个建议方向各成一条，法规与稳定性原文逐条保留。模型失败时抛 `ModelError` 并提示可手填，不生成半成品。接口 `POST /api/projects/{id}/analyze`。
- **F03a 展开 brief** `domain.brief.merge`：方向继承项目级字段，覆盖同名项；客户要求按 kind 标成 `Q_STABILITY` 或 `R_EXTRA`，合规原文进入 `requirements`；结果写 `goal.fields`，两层原文写 `round.brief`。
- **F04 确认方向** `manual_draft` / `confirm_draft` / `add_direction`：手填与模型产出同一种形状；确认时按入口判型、写方向、轮次、目标与字段来源。重复确认返回第一次的结果。接口 `POST .../draft`、`POST .../draft/{id}/confirm`。拒绝：没有方向标题。
- **F05 判型** `routing.route` / `reroute`：入口决定可执行策略与终点。允许在未建目标位前改型；已建方案则拒绝，避免同一目标位两套执行。接口 `POST .../goals/{id}/reroute`。

## 选香

- **F06 解析参照** `search` + `_exact`：产品名与版本走精确匹配，允许的目录关系才进结果，仅「建议」关系的进线索。接口 `POST /api/search`、`POST /api/target`。
- **F06a 贴标签** `intelligence.targeting.tag_direction(brief, mode, catalog, scoring_config, model)`：输入是目标字段，至少含应用品类、人群、市场、香气原文与家族、排除项、客户要求；候选是本品类的 C 叶子，每个带 C 左侧判定指导与可展开的 A/B。模型只选 C 并给逐字依据，C→A/B 由 `catalog.edges` 展开。结果含 `groups / items / used_conditions / unmapped / method / dictionary_version`，写 `goal.fields.targeting`，检索时直接使用。模型不可用时退回 `ranking.parse_text` 的词面匹配。
- **F06b 按目标检索** `search(..., goal_id=)`：用目标的 `application_id` 作为品类、`targeting.groups` 作为标签组、目标价格作为上下限；没有打标结果时先打一次并缓存。
- **F07 记外部样品**：对香方向的 `sample_reference` 存在目标字段里，随方向一起确认；不单独建表，也不要求先有香精编号。
- **F08 准备查询** `ranking.parse_text` / `normalize_query`：自由文字里认品类、价格、标签、品牌、产品与版本，写成标准查询；识别不出的词忽略，不报错。
- **F09 排序香精** `ranking.rank`：硬条件先筛，A/B/C 打分，避开项扣分，价格与标记只影响排序。结果分「推荐 / 线索 / 同类候选」，并给 diagnostics 说明差在哪。接口 `POST /api/search`。
- **F10 定方案** `plan`：select 直接建目标位；duplicate / create / modify 建开发子项并派第一个任务；resend 复用上一次实发。同一香精重复选定返回已有目标位。接口 `POST .../goals/{id}/plan`。
- **F11 改资产标签** `edit_asset`：人工改标签或关系，写 `asset_edits` 并带 manual。接口 `POST /api/asset`。
- **F12 准备开发** `planning.spawn_development`：父目标位留在原方向，子方向带 `parent_slot_id`；子方向完成后回到父目标位。

## 执行与回执

- **F13 派任务** `_dispatch`：任务带类型、部门、spec 与外部编号；同一目标位同时只允许一个待回执任务。接口 `POST .../slots/{id}/advance`。
- **F14 收回执** `apply_receipt`：按任务类型分派到分析 / 调香 / 检查 / 入库 / 寄样处理；重复回执拒绝。接口 `POST /api/platform/receipt`。
- **F15 评试作** `accept_trial` / `reject_trial` / `confirm_gc`：验收写 evaluation 并带出香精与版本；退回必须写意见并自动派下一轮调香；GC 确认后才派调香。
- **F16 验收入库** `accept_warehouse`：写入库记录，把香精与版本写回父目标位，父目标位进入 checking（二查）。接口 `.../advance` 的 `accept_warehouse`。

## 检查与放行

- **F17 生成清单** `checking.build` + `_do_build_checks`：按审查品类、市场、客户原话与通用要求生成要求；审查品类可留空，只出通用、市场与客户项。接口 `.../advance` 的 `build_checks`。
- **F18 匹配证据** `checking.evidence.match` + `_rematch`：按香精、版本、指标、子项、条件键匹配历史证据；命中的直接核销，并给出复用条数。
- **F19 排检查计划** `_do_dispatch_checks`：按部门分组派发，只派未核销项；全部已核销时提示可直接放行。
- **F20 放行判定** `checking.release.decide` + `_decide`：见 [检查与放行](checking.md)。未通过时写一条 blocked 记录并抛 `StepBlocked`，阶段不动。
- **F21 准备寄样** `_do_prepare_sample`：向中台预留样品，记录 sample_id、形态与数量；库存不足返回 `stock_short`。
- **F22 派寄样** `_do_dispatch_shipment`：一条寄样任务，带快递信息与形态数量。
- **F23 记寄样** `_apply_shipment` / `_record_shipment`：回执后写 `shipment`，同一目标位同一 kind 只记一次；初寄样回执后目标位回到 checking，正式寄样后进入 complete。
- **F24 刷新进度** `recompute` + `views.project_view`：目标位完成 → 目标完成 → 方向完成 → 项目完成；开发子项完成后单独记为 completed，父项继续。接口 `GET /api/projects/{id}`。

