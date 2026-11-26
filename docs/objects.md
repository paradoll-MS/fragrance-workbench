# Objects ／ 业务对象与不变量

对象只描述业务事实，不描述页面。字段名对应 `app/store/schema.py`，不变量由 `app/domain/models.py` 与 `app/workflow/service.py` 保证。

## 1. 订单侧

- **Project 项目**：一次委托或一次内部开发。有 `kind`（customer / internal_upgrade / invent）、客户、编号、状态（active / completed / cancelled）、revision。一个项目可以含多个交付方向，也可以含开发子项。
- **Subproject 交付方向**：项目下的一个独立需求。有 `requirement_type`（7 个入口之一）、`final_endpoint`（shipment / warehouse / warehouse_return）、状态。开发子项的 `final_endpoint` 是 warehouse_return，并且带 `parent_id` 与 `parent_slot_id`，指回触发它的父级目标位。
- **Round 轮次**：方向下的一轮需求。`kind` 为 initial / continue / resend，`no` 递增，`brief` 存这一轮的原话与字段快照。
- **Brief 需求简报**：分两层。ProjectBrief 存项目级条件（客户、品牌、人群、市场、基质、添加量、合规要求、价格、数量、交期），DirectionBrief 只存该方向不同或额外的部分（香气原文、香调家族、排除项、情绪场景、参照样、方向级要求）。`round.brief` 存原始两层，`goal.fields` 存继承展开后的结果。两处都可回看，`parse_draft.result` 再存模型原样输出。
- **Goal 目标位目标**：轮次下的一条可执行目标。有 `label`、`endpoint`、`requested_count`、`fields`（展开后的 brief，含 `targeting` 打标结果）、`provenance`（每个字段来自 source 还是 manual）。状态由目标位推导，不单独维护。
- **Slot 目标位**：目标的一次具体执行。有策略（select / duplicate / create / modify / resend）、阶段、香精编号、配方版本、payload（流程内的临时事实，如 sample_id、shipment_kind、returned_from）与 revision。

目标位的阶段只有 6 个：planned、developing、checking、shipping、complete、cancelled。没有「released」阶段——放行是一次记录，不是阶段。

不变量：

- 一个目标位同一时刻只有一个任务在等回执，任务类型随阶段变化（analysis → perfumery → check → warehouse → shipment）。
- `fragrance_id` 为空时不能生成检查清单，也不能放行。
- 目标位的 `revision` 每次写库加 1；页面提交时必须带上读到的 revision，否则拒绝。
- 开发子项完成后把香精编号与版本写回父目标位，父目标位从 developing 回到 checking，需要自己再走一次检查与放行（二查）。

## 2. 检查与放行

- **CheckSet 检查清单**：某个目标位某一版检查条件的结果，记录 `scope`（shipment 或 warehouse）、审查品类、市场、规则版本、coverage。重新生成会新增一版，不覆盖旧版。
- **Requirement 检查要求**：清单里的一条。有指标、子项、部门、判定口径、来源（default / customer / both）、状态（unverified、pending、passed、failed、needs_review、not_applicable）、`deferral`（blocked 或 deferrable）与 `conditions_key`。客户要求按 `kind` 落到不同指标：稳定性要求 → `Q_STABILITY`；法规、禁用物、过敏原、闪点、文件与其它 → `R_EXTRA`，原文进 `origin_text`。
- **Evidence 证据**：部门回执或人工记录落成的证据。带香精编号、配方版本、指标、结论、测试时间。证据跨清单、跨项目复用，是「不重复送检」的依据。入库时给出的正式编号与版本会同步改证据的键，因为那是改名而不是换配方。
- **ReleaseDecision 放行记录**：每次放行尝试一行，含 action（warehouse / initial / formal / resend）、结论、阻断项、暂缓项、备注、操作人。未通过的尝试也留一行，便于回看。

不变量：

- 检查要求的状态只由证据或人工判定改变，不由放行动作改变。
- 放行只读当前版本的清单；旧版本清单的结论不能拿来放行新版本。
- 有 `failed` 时任何放行都不过；有未核销项时 warehouse / formal / resend 不过，initial 只在未核销项全部是 deferrable 且写了备注时通过。

## 3. 开发与中台

- **Job 开发任务**：一个目标位的开发过程。有 `dev_type`、迭代次数、GC 报告编号、已验收试作。仿香先派分析，GC 回执到齐再派调香；创香直接派调香。
- **Trial 试作**：调香的一次产出，带试作香精编号、配方版本、说明。
- **Evaluation 评香结论**：对某次试作的通过或退回，退回必须写清下一次意见，并触发下一轮调香。
- **Task 部门任务**：派给某个部门的待办。有 `task_type`、`department`、`spec`（这次要做什么的结构化内容）、外部编号、状态（queued / sent / done / failed / cancelled）与回执时间。
- **Shipment 寄样**：一次实际寄出。有 kind（initial / formal / resend）、香精、版本、形态、数量、快递单号、寄出时间。一个目标位可有多条，同一 kind 只记一次。
- **WarehouseRecord 入库记录**：开发子项验收入库的结果，含香精编号、版本、数量、批次。
- **Quote 报价 / MockDefault 默认回执**：模拟中台的输入，前者覆盖库价，后者让新任务立即回执。

## 4. 资料与留痕

- **Source 资料**：导入的原件或粘贴的文字。有文件名、类型、大小、正文、落盘路径、读取告警。
- **ParseDraft 拆解草案**：模型或手填产出的方向草案，确认前可反复修改；确认后写入方向、轮次与目标，草案保留 `committed` 结果。
- **AssetEdit 资产改动**：人工改标签、改关系，带 manual 标记与改动前后值。
- **Issue 工作流问题**：某个对象当前卡在哪。有原因码、缺什么、等什么、下一步、恢复事件。问题随数据变化自动收掉，不需要手工关。
- **Audit 审计**：每次写库记一条，含动作、对象、操作、摘要、时间。

不变量：

- 资料只读；拆解决议以草案与人工修改为准，模型不直接写业务表。
- 人工覆盖一律留 manual 痕迹：字段来源、资产改动、放行备注。
- 问题不阻塞页面浏览，只影响对应动作是否可点。

