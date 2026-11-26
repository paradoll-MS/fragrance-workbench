# Data ／ 数据与模拟中台

## 1. 导入与权威

1. **选香库**取 `ABC/output/fragrance.jsonl` 为当前资产主视图。已核实有 3,853 行、其中 44 行带编码冲突标记、3,165 行有库报价字段。读取 fragrance_id、name、source_row(s)、category_ids、category_candidates、A1/A2/A3/B、C_by_category、new/hot、大牌状态、system_quote、price_segment 和必要展示字段。以 `fragrance_product.jsonl` 的关系状态判定目录可执行性，不能把粗标或历史候选当成精确关系。无效编码隔离，冲突按源行保留待核验，导入生成 catalog_version 和问题清单。
2. **标签和品类字典**取 [ABC V2 工作簿](../../../resources/ABC/品类与ABC标签体系_V2.xlsx) 的「应用品类」「A标签」「B标签」「C标签树」「AB别名」「C到AB关联映射」「C左侧判定补充」「LLM判断规则」。`fragrance_tags.jsonl` 用于完整性核查、历史回放，线上匹配不依赖 inference_type/confidence。只接受字典有效叶/维度，旧二三级字段保存为导入映射线索。
3. **产品目录**加载 `brand.jsonl`、`product.jsonl`、`fragrance_product.jsonl`，用 brand_id、product_id、edition_key、catalog_key 确定关系。实查 277 个产品有 26 个标 verified，711 条关系全处于 strong_candidate 或 ambiguous。第一批生产前需要优先逐条核实常用产品的标准名、版本及库内仿香关系；仅核验公开产品存在不能证明库存配方身份。可把已确认关系作为人工增量写入 product_relations，保留确认人、依据和时间。现有大牌标志按确认状态展示。
4. **项目工单库**以只读方式读取 [香精工单 SQLite](../../../research/cases/项目工单数据/香精工单.sqlite3)。`projects/customers` 供项目身份，`work_orders` 供目标与历史阶段，`notes/note_links/attributes` 供原文和范围，`sample_occurrences/formula_refs` 供用样与编号，`shipment_mentions` 供填报寄送、运单及交接依据，`attachments` 供附件引用，`catalog_entries/physical_samples` 供旧库和实物线索。关联用原始 ID，不能只按重名项目或同一运单聚合。历史配方号不等于可调用配方版本；库存快照不当实时库存；历史寄样提及不直接生成已确认 Shipment。
5. **审核规则**以 [审查轻量版](../../../resources/审查/香精审查规则_轻量版.json) 的 18 个审查品类、metric_dictionary、common/category/conditional/market defaults 为原始业务输入。应用品类有 12 类，应用和审查体系各自确认。例如线香和无火可同属 CAT_06，而审查走 burning_diffusion、passive_diffusion。婴童/宠物等实际用途另录，按审查规则转合规确认。市场存实际国家，可多选。地区未提及保持待确认。旧规范类与地区 V3 说明仅用于对照。这里使用内部审查配置草案的字段和分工。
6. **真实案例**以 [案例目录](../../../research/cases/真实案例) 为 Parse 和走查原件；V3 快照仅用于对照旧结论。文本/页段、格式覆盖、资料时间及跨轮冲突据原件校验。API 密钥只由后端在运行时加载，业务快照、网页、任务和日志只带非密钥的模型标识，收件和联系人不进标签模型上下文。

## 2. 两类香精资产表

- `catalog_fragrances` 是本地静态搜索资产，含身份、ABC、应用品类、目录和库报价快照。额外关联 `catalog_changes` 的 manual 覆盖和 `product_relations`，保存资产校正。库内表不写窄口径检测结论。
- `fragrance_evidence` 是按版本、指标和条件存的凭证记录，一款可以多行。按 `fragrance_id + formula_version_id + metric_id + subject_scope` 索引，保留条件、范围、方法、数值/文件、适用标准、有效期和审签。第二轮先建空表让模拟回执走通，真实证据后续接入。未知或只有历史文档名称时显示线索，不自动核销。
- `price_quotes` 存中台价和静态价来源及生效时间；`formula_version_refs`、`warehouse_records` 存执行事实。应用自己的 SQLite 还存 projects/brief_revisions/subprojects/rounds/goals/plan_slots、sources/source_segments、search_queries/search_runs/targeting_feedback、development_jobs/trials/evaluations、department_tasks/result_events、check_sets/requirements/release_decisions、external_samples/sample_refs/reservations/shipments/shipment_lines、workflow_issues/audit_events/outbox/inbox。明细归属按 [objects](objects-对象与字段.md)。

## 3. 第二轮要建或核准的字典

- **可直接导入**。12 类应用与 ABC、18 类审查与指标目录、存量产品/品牌候选。源工作簿和 JSON 冻结一个版本，导入脚本产生标准 ID 和错误清单。
- **要配置可执行的关卡**。按 warehouse/initial/formal/resend 定义何时适用、阶段、指标分组、适用对象、实际测试前置字段、授权人、可暂缓白名单和适用标准。轻量版字段含 `stage`、`activation` 或检测提示。它们先转待确认规则，不从提示直接造阈值、标准值或豁免。指标负责人用 metric_dictionary 映射，项目可授权改派。缺应用签核口径、市场确认、合规要求解释、组包附件标准的项目照样可拆解、选香及起草任务，放行等待相关核准。
- **要补外部标识和口径**。中台项目、客户、香精、版本、样品、任务、运单 ID 映射；配方可用状态、样品形态与单位、单位价格换算（含币种/税口径/时点）、样品库存与预留、角色权限、测试方法/报告证明类型、规则和附件版本。跨体系品类映射只给建议。客户说法的证照/宣称/测试别名逐步补，未知明确检查送评香分类。
- **仍缺的生产资料**。正式可调用配方版本、当前库存及可售状态、下发和回执接口、正式入库编号、历史检测报告正文与适用条件、可执行规则版本、已确认的产品版本关系。第二轮模拟数据按 `env=mock` 单独建库或分区。

## 4. PlatformAdapter ／ 中台接口

快照读取返回 `{value, external_refs, observed_at, source, env, status}`。本地 ID 与外部 ID 分层，不把模型提供的编号直接接受为中台事实。

- `get_project(external_ref)` 读取项目号、客户、联系人授权引用、业务员、评香、交期及可用历史。接真实中台后，新增或关联项目用 `upsert_project` 写最小项目头和 local_ref，并保留中台返回 ID。
- `get_fragrance_refs(fragrance_ids[])` 批量取正式编号/状态、当前可用配方版本、确认时间和已有仓库记录。 `get_quotes(fragrance_ids[], context)` 批量取当前有效价、适用客户/范围、币种、单位、报价时点、价种；取不到时返回 unavailable，搜索可展示导入价作为兜底提示，实际价格确认时显示旧价状态。
- `get_sample_inventory(queries[])` 按目标香精版本、样品形态、剂量/基质和单位查批次、库存和有效期。 `reserve_samples(lines[], idempotency_key)` 原子校验当前可用量并返回逐行预留或短缺。 `finish_reservations(actual_lines[], action, key)` 幂等消耗已实寄、取消或释放未用。可重复查、对账、续租。
- `submit_task(task_envelope, idempotency_key)` 写部门任务，返回外部任务 ID、接收状态、预计完成时间和负责人。自动或手工回执经 `read_events(cursor)` 或等价回调进入 F14，支持 `get_task_status`、`cancel_task` 及按原键查询。 `publish_progress` 写已确认入库/寄出/项目状态摘要。外部任务结果按环境、来源系统与事件 ID 去重。映射和同步状态可追溯。
- 读写传输可统一用浏览器无关的 JSON。任务包包含 schema_version、env、local_task_id、attempt、project/subproject/round/slot ID、外部引用、type、deadline?、dependencies、spec。回执包用 F14 约定。回执和附件先保留，然后做内容和权限验证。外部已执行但本地未收到时按 task ID 和幂等键查询再补回执。失败与旧版本保留在 inbox 待处理，UI 显示重试/确认入口。

## 5. TaskSpec 与部门回流

1. **analysis／分析**。输入已确认的 analysis_sample_id、reference、要求和简报引用。回 GCReport，含同一分析样品编号、报告文件、结构化摘要和异常。评香确认可用才接续调香，错误时可重新认样或派发。
2. **perfumery／调香**。输入 development_type、brief_snapshot、iteration、此前评香反馈，dup 必带 GC、modify 必带可用基准版本。回试作香精/配方版本、调香说明、可用试样号或待备样状态。检验及评香面板消费回执。调香可补试样，配方变化走新试作。
3. **compliance／合规**。输入版本、用途、审查品类、国家、声明、指标及标准、剂量和原液/成品对象。逐项回结论、条件、签核人及 IFRA/过敏原/其他所需文件。适用性判断也是有依据的回执。
4. **quality／质量**。输入版本、样品/批次、原液或终产品对象、指标、方法、温度/时间/光照等检查条件与目标。逐项回测值、单位、实际方法/条件、结论和报告。
5. **application／应用**。输入版本、实际用途、基质、添加量、制备步骤、对照样（如需）和指标。回实际基质/剂量、各时点/相容或感官结论、报告。部门由指标字典配置；相容、稳定性按规则归质量或应用。
6. **warehouse／入库**。输入已验收 trial_id、版本、放行与凭证、名称、品类、标签及价格快照（可未知）。回正式香精编号、冻结版本、入库回执号和状态。正式库投影在 F16 入账，失败可用原任务恢复，开发结果回原目标位。
7. **sample_prep／备样**。输入目标样品形态、配方版本、基质/添加量、缺量、单位、交期。回实物样 ID、批次、版本、实际数量、单位和何时可用。F21 重查库存并预留。试跑负责人暂放寄样/样品组，可按配置改派。
8. **shipment／寄样**。输入批准的每行计划、库存预留、实际版本、形态、数量、单位、收件与随附文件。回外部寄样 ID、每行实物与版本、实际寄量、时间、运单/交接凭证。部分回执标行级进度；只有实际事实才写入实推，错版保留为异常。

## 6. 模拟中台 Web

单独入口 `/mock-platform`，一览分析、调香、合规、质量、应用、入库、备样、寄样。任务卡显示引用、要求、交期、状态和回执表单，允许模拟领取、完成、部分完成、失败、补回执、重复回执。样品/库存页面可登记到样、补库存、推出库存短缺，报价与版本页面可设置已知、未知、更新。所有数据带 mock 环境，使用与正式 Adapter 同一接口，评香页面通过回执进入原等待节点。评香确认与部门填报使用对应权限入口。本地模拟可以由一人切换。真实接入时使用部门/身份对应权限和独立环境，模拟凭证不会流入真实资产。

