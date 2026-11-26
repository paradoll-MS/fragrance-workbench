# Functions ／ 函数契约

命令参数共有 actor_id、command_id 和已存在对象的 expected_revision。命令返回 `affected_ids[], revision, issues[], next_actions[]`，下文另列本函数的业务输出。纯函数只读取传入快照，返回结果由调用方存储。读取、中台临时故障、版本冲突和业务阻断分别报告，允许逐对象恢复。

## 1. 建项目、读资料与判型

- **F01 open_project**（确定性命令/读取）。`{kind?, name?, project_id?, external_project_ref?, customer_ref?}` → Project + 最新有效简报、在途工作、实发索引。新建至少 kind 和名称；相同外部引用归同项目，无法唯一匹配列候选，允许先开本地项目后关联。
- **F02 ingest_source**（读取 + 可选 Parse 模型）。`{project_id, text/blob/url, format, occurred_at?, note?}` → Source + SourceSegment[] + ParseRun。内容哈希及定位可重用，资料与业务关联单独保存。按格式读取，扫描页/OCR、图像及音频按需走视觉或转写。返回 coverage、已读段和未读位置。重试指定部位，人工补摘录产生新段。模型细节见 [workspace](workspace-工作台与模型.md)。
- **F03 propose_intents**（Parse 模型 + 字段校验）。`{project_id, source_ids[], frozen_context, dictionaries_version}` → IntentDraft。读取选中资料、现行事实、近期相关真实寄样和人工决定，输出独立目标、共享/局部事实、跟进建议、引用、未分配信息。核对引用与原文数字、否定、单位，未知允许 null。仅明确测试、认证、文件、宣称等转审查候选。草稿晚于手动更新时可看差异后采用；本次失败留旧结果可手填。
- **F04 commit_intents**（人工命令）。`{draft_id? 或 manual_intents[], accepted_intents[], brief_edits, goal_group_edits, association_choices}` → Project/BriefRevision/Subproject/Round/Goal。稳定 intent_key 防止同批重复提交；人工选择合并、拆分、承袭或继续。共享值只应用于明确适用的分支；历史快照保留。继续时按所选补目标或新增，拒绝项来自具体客户反馈与对应方向，禁止全库拉黑。复寄开新 Round 与独立 Goal。
- **F05 route_requirement**（固定顺序）。`{intent_signals, brief_revision_id, reference_resolution?}` → `{requirement_type, reason_refs, permitted_strategies[], issues[]}`。按主树 1 优先判断。明确有基准但配方未知时保留 modify，等 F06；确认没有可用配方后切 with_sample 并存原改动。只涉及灵感的产品信号归品牌推荐；模型不给“直接入库/寄样”动作。执行后改型须取消/替代当前目标位或另开分支。
- **F06 resolve_reference**（确定性查询 + 人工确认）。`{kind: base/product/fragrance, raw_names_or_codes, scope, lineage?, known_edition?, selected_ref?}` → `{status, candidates[], selected_ref?, version_ref?, basis?}`。base 先用明确内部号或原实发行，接中台查配方版本状态；相同对客号只在对应项目与寄样范围查。product 先品牌归一、再品牌内产品别名和明确版本匹配，系列/同名/未核验分别展示。按编号查时保留原编码，编码冲突要求确认，模型无法证明存在性。
- **F06 confirm_reference**（授权资产命令）。`{kind: product_identity/product_relation/catalog_identity, candidate_ref, resolution, basis_ref, expected_revision}` → 新字典或目录修订与 audit event。产品核验写 product_id 与 edition_key；仿香关系确认写 catalog_key 与该具体 edition_key；内部编码纠错写 ExternalRef 和对应源行。暂未核实但已认定的项目目标写 BriefRevision，按项目作用域留存。当前查询可重跑，历史引用不迁移。
- **F07 save_external_sample**（命令）。`{project_id, sample_id?, type, source_party?, external_number?, base?, observed_receipt?, usable_for[]}` → ExternalSample + sample_changed。允许先登记 pending；只有授权确认或模拟中台回执可标到样/可用。复核 sample_changed 时只唤醒依赖对应 sample_id 与用途的操作。

## 2. 独立选香

- **F08 prepare_query**（规则 + 可选 Targeting + 手工保存）。`{mode, round_id, brief_revision_id, chosen_application_categories[], keywords?, previous_query_id?, manual_patch?, dictionary_versions}` → SearchQuery + issues。明确目录及强条件按简报带入，唯一别名直接解析；歧义与复杂语义走 Targeting。保存改动时只更新当前查询，追加 TargetingFeedback。变更品类时清除旧查询 C 并提示重映，保留历史。算法细节见 [recommendation](recommendation-ABC选香.md)。
- **F09 rank_fragrances**（确定性）。`{query_id, catalog_snapshot, quote_snapshot, scoring_config}` → SearchRun。加载有效身份及原生标签，先过滤，再计算 A/B/C 与映射分。返回总候选、逐条件排除及放宽诊断、分页排序明细。缺标签可发起目录浏览；相同快照可复用。**F09 lookup_exact_product** 另用 `{verified_product_id, edition_selection, confirmed_relations, catalog_snapshot, quote_snapshot, boundary_filters}` → `{verified_hits[], conflicts[], candidate_clues[], status}`。完整展示身份命中与价格/品类/状态冲突；只接受符合已确认业务边界的库香。身份唯一但关系未确认时显示待核验。无 ABC 分。
- **F10 plan_actions**（人工原子命令）。`{subproject_id, round_id, changes[{goal_id?, strategy, fragrance_ref?, reference_id?, search_run_id?, override_reason?, skip_search?}], confirmed_group_count?}` → Goal/PlanSlot 和可选开发子项/Job。F05 校验该路线可用策略。引用本次检索，手动编号时重新核对身份与条件；硬筛例外需明确说明，并同步当前决定。保留是否跳过检索、原因及人。开发子项记录 parent_id/round/slot，用独立开发目标位。继续处理已执行方案时，替代记录和新快照一起存。
- **F11 edit_catalog_tags**（资产写入）。`{catalog_key, expected_catalog_revision, tag_ops[], name_patch?, application_category_patch?, reason?}` → CatalogFragrance 新版本 + CatalogChange。C 只允许该香精已确认应用品类的合法叶，AB 校验 ID 与层级。删除写 manual tombstone，避免批次导入加回。修改应用品类时同事务隔离不再适用的 C，并显示待补标。自动导入保留人工字段覆盖；本次需求修订或映射命中留在查询。

## 3. 开发与共用任务传输

- **F12 prepare_development**（确定性组装 + 人工确认）。`{job_id, effective_brief_revision_id, reference?, analysis_sample_id?, base_formula_version_id?, patch?, confirm_step?}` → confirmed BriefRevision + DevelopmentJob + 可派发动作。dup 的方法由人确认，分析派发需可用样，调香需该样本有效且经评香确认的 GC。create 需确认方向、应用及可操作目标，价格和交期可空；modify 需可用基准版本和具体改动。调香 brief 的条款源自生效需求、父项和人工输入，确定性渲染预览。确认 GC 复用本命令并记录报告 ID、样品身份与评香决定。
- **F13 dispatch_task**（命令 + Adapter）。`{task_type, scope_ref, spec, dependency_refs[], business_key, attempt}` → DepartmentTask + Outbox。后端查依赖与字段，写任务和 outbox 后异步发。相同业务键及版本/任务规格只生成一条有效任务；任务重做递增 attempt，新版简报先检查旧任务在途状态。协议数据见 [data](data-数据与模拟中台.md)。
- **F14 receive_result**（事件应用）。`{env, system, event_id, external_task_id, local_task_id, attempt, type, happened_at, payload}` → Job/Trial/Check Evidence/MaterialSample/待入库或寄样回执，并发出对应恢复事件。核对任务身份、版本、样品、要求与数量；同事件同内容返回原结果，同 ID 不同内容报冲突；旧尝试或外部环境不符进入待处理。试样可后补，检查逐项部分返回；回执更正用新事件和 supersedes_event_id。到样等非任务事件以 external_sample_id 路由，版本匹配的配方状态补充同理。
- **F15 evaluate_trial**（人工命令）。`{job_id, trial_id, verdict, comments?, next_brief_patch?}` → Evaluation + 新迭代或入库 CheckSet 请求。校验当前试作、版本、可用样。退回需下一轮意见，保留历史迭代。通过冻结试作、凭证和版本。评香替换原通过版本时，原放行撤销，仓库在途任务进入核对。
- **F16 accept_warehouse**（事实落库）。`{task_result_id 或 adoption_input, approval_ref, check_set_id, release_decision_id}` → WarehouseRecord 或 Adoption + DevelopmentReturn/Goal 更新。核对实际正式编号、调香锁定版本、放行快照、入库权限。若子项同时回父项，在同事务标记回流并写父 slot 后才能完成。中台无回执继续待确认；已入库但回流地址无效保留待认领。已有香内部替代由评香与入库权限确认，引用既有入库记录和本次用途审查，记录替代原香的原因。

## 4. 检查与寄样

- **F17 build_checks**（规则）。`{slot_id, fragrance_id, formula_version_id, check_scope, active_brief, frozen_context, rule_version}` → CheckSet + Requirement[]。对适用范围已知者加载品类/公共/条件/地区规则，未知制 coverage_issue。默认与客户同标准同适用条件按规范键合并；不同条件分别列，冲突建待确认，客户文字可追加，不能删除强制项。按对象拆原液、终产品、用途、市场。生成键和活跃快照保证同条件复用；新条件生新修订，已有证据重新适用性匹配。
- **F18 match_evidence**（规则）。`{check_set_id, eligible_evidences[], as_of}` → requirement 状态、依据与不匹配原因。核对版本、指标子项、对象/方法、范围（含实际国家、用途、添加量/基质等）、标准版本和有效期。明确有效失败置 failed；互相矛盾的有效证据交授权人核对，标 needs_review 并阻止放行。合适证据按当前标准算或按授权签核使用。未知标准允许业务人员补批准口径，未知数据保持 unverified。入库证据供二查复用。
- **F19 plan_checks**（规则 + 人工确认）。`{check_set_id, selected_requirement_ids[], patch_test_context?, owner_assignments?}` → TaskSpec[] + issues。按部门、版本、对象、方法、可共用的条件与样品归组；同等既有任务挂接本次要求，已有凭证只差附件时可派补文件。缺条件仅暂停相关条目，确认后 F13 派发；回执 F14 留原件并用 F18 核销相应条目。
- **F20 decide_release**（规则 + 授权确认）。`{check_set_id, action: warehouse/initial/formal/resend, slot_id, inventory_status?, confirmation?}` → ReleaseDecision。入库/正式/复寄要求所有适用条目通过或有授权的不适用结论；适用性未决和有效失败不可放行。初寄还需路径允许、仓库确认、批准策略和所有不可暂缓项通过。暂缓只允许策略白名单的未完成条目，确认人和理由、责任人与截止时间入库。任何动作遇到已知失败、证据冲突或强制条件未满足时返回具体阻断原因。放行绑定 CheckSet 当前修订、版本和证据有效期。入库、寄样队列在发送前再验一次；实际已发生的事件即使不合约仍按事实留存并标异常。
- **F21 prepare_shipment**（命令 + Adapter）。`{round_id, kind, proposed_lines[], recipient_ref?, attachment_refs[]}` → ShipmentPlan + Reservation 或 SamplePrep TaskSpec。提前备样可保存计划和打样请求。按明确的配方版本、样品形态、基质/剂量和单位预留实际样并校验批次有效期。部分库存可先保留，缺口进入打样。预留过期/取消可释放，短缺回执可重算余量。
- **F22 dispatch_shipment**（命令）。`{shipment_plan_id, final_line_ids[], release_decision_ids[]}` → 寄样 DepartmentTask + 锁定清单。每行核查正式库状态、有效放行、样品和配方版本、数量、预留、地址及文件。允许分批确认通过的行，原计划剩余仍可继续。发出后再次更改地址或样品时先取消未执行任务或创建后续批次，保留在途记录。
- **F23 apply_shipment**（事实落库）。`{shipment_task_result_id}` → Shipment + ShipmentLine + 已消耗/释放预留 + remaining_goals[]。按实际行更新，只有版本、数量、单位和目标一致的有效正式/复寄行满足对应目标；初寄仅记实发。处理中断、重复回执、部分回执均按行和事件幂等。错版或超发进入异常；若已寄出，记录实际事实、待补寄及人工纠错，历史不可销毁。
- **F24 refresh_progress**（事件投影 + 恢复）。`{scope_id, incoming_event?, command?}` → WorkflowIssue[] + allowed_actions[] + 状态投影。重算受影响 node，具备前提后开放用户动作或更新既有队列。手工暂存/恢复写 issue，缩减或取消写 Goal/PlanSlot 状态与 AuditEvent，附业务确认和原因。取消同时核对在途任务与库存预留。管理员可重新匹配异常回执，保存原事件和更正原因；同事件回放得到相同归属。

