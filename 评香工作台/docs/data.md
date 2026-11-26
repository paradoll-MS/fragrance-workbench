# Data ／ 存了什么、存在哪

## 1. 位置

- 主库：`data/workbench.sqlite3`。WAL 模式，外键开启，每个命令一个事务（`BEGIN IMMEDIATE`）。
- 资料原件：直接以 BLOB 存在 `source.raw`，同一份文件用 `(project_id, name, sha256)` 去重；解析出的段落与定位存在 `source.extracted`，不落外部目录，备份一个库文件即可。
- 只读资料：ABC 资产、产品关系、标签体系在 `resources/`；审查规则在 `resources/审查/香精审查规则_轻量版.json`；选香权重在 `scoring.json`。这些文件不在运行时改写。
- 试验库：`tests/modules`、`tests/workflows` 与 `_scratch/` 使用 `data/` 下的固定文件，不用临时目录，方便直接打开查看。

## 2. 表的分组

订单侧：

- `project`：项目。`revision` 用于并发保护，`updated_at` 供列表排序。
- `subproject`：交付方向。`requirement_type` 是入口，`final_endpoint` 是终点，`parent_slot_id` 只对开发子项有值。
- `round`：轮次，`(subproject_id, no)` 唯一。
- `goal`：目标，`fields` 存结构化字段，`provenance` 逐字段记来源（source / manual）。
- `slot`：目标位，`payload` 只放流程临时事实（sample_id、shipment_kind、returned_from、paused），能决定结论的字段一律建列。

检查侧：

- `check_set`：一版检查条件，`scope` 区分 shipment / warehouse，`coverage` 记「为什么少了某些项」。
- `requirement`：一条要求，`(check_set_id, metric_id, subitem, source_key)` 唯一，`deferral` 决定初寄样能否缓。
- `evidence`：证据，按「香精 + 版本 + 指标 + 子项 + 条件键」建索引，跨清单复用。
- `release_decision`：每次放行尝试一行，通过与否都留。

开发与中台：

- `job`、`trial`、`evaluation`：开发过程、试作、评香结论；`(job_id, iteration)` 唯一。
- `warehouse_record`：入库结果，带当时的 check_set 与 release_decision。
- `shipment`：实发记录，以行为准，不以布尔标记为准。
- `task`：部门任务，适配层唯一写入的业务单据，`spec` 是这次要做什么。
- `quote`、`mock_default`：模拟中台的报价覆盖与默认回执。

资料与留痕：

- `source`：原件，`(project_id, name, sha256)` 唯一。
- `parse_draft`：拆解草案与确认结果，模型原始输出不改写。
- `llm_call`：每次模型请求的完整快照，按 `(project_id, id)` 查询；请求含 system/user，回复含原文，图片以占位符入库。
- `asset_edit`：人工改标签/关系，`payload` 带 manual 标记与前后值。
- `issue`：当前阻断，`(scope_type, scope_id, code)` 唯一，`state` 为 open / resolved。
- `audit`：每次写库一条，含命令、对象、动作、摘要与 revision。

## 3. 关系与级联

- 项目 → 方向 → 轮次 → 目标 → 目标位，逐级外键。
- 目标位 → 检查集 → 要求；要求 → 证据（可空，表示还没核销）。
- 目标位 → 任务（多类型同名表）；任务回执后写证据或寄样或入库记录。
- 开发子项 `parent_id` 指回父方向，`parent_slot_id` 指回父目标位；两个字段同时存在才构成「回到父项」。
- 删除目前不做级联：业务上不删项目，只改状态。人工清理时按上面的顺序从下往上删。

## 4. 并发与一致性

- 一个进程一个连接池入口，写操作在 `Store.transaction()` 里串行。
- 页面对目标位的写操作必须带 `revision`，与库里不一致时返回 400「目标位已更新，请刷新」。
- 证据与放行记录只追加，不更新；要求状态是证据匹配的结果，可以重算。
- `audit` 只追加，用于回溯「谁在什么时候把哪个字段从什么改成了什么」。

## 5. 迁移

`SCHEMA_VERSION` 在 `app/store/schema.py`，建表全部用 `CREATE TABLE IF NOT EXISTS`，`Store` 启动时把它们执行一遍，并把版本写进 `meta`。当前版本 1，还没有破坏性变更。

现在没有自动迁移：加字段时改 DDL，然后手工 `ALTER TABLE ... ADD COLUMN`，或者删库重建。表里已有的数据只有演示项目时可删；有真实项目时先备份，再执行一条 `ALTER TABLE`。等第一次真实变更发生时再补迁移脚本，不提前写空壳。

## 6. 备份与重来

- 备份：停止服务后复制 `data/workbench.sqlite3`（含 `-wal`、`-shm`）。
- 重来：删掉 `data/workbench.sqlite3*`，重启即得到空库；只读资料不受影响。
- 演示数据可以随时重建：本地脚本 `_scratch/e2e_http.py` 通过 HTTP 走一遍完整链路，产出一个示例项目（该目录不纳入版本库）。

