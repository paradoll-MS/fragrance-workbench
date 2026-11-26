# Architecture ／ 分层与依赖

工作台是一个本地单机应用：一个 Python 进程提供 HTTP，一份 SQLite 存业务状态，三个页面。分层的目的只有一个——让「业务规则」和「执行细节」分开，改规则时不用碰 HTTP，接真实中台时不用碰业务。

## 1. 依赖方向

    api  →  workflow  →  checking  →  recommendation / assets
             ↓            ↓            ↓
          adapters      domain  ←──────┘
             ↓
          store（唯一写库入口）

只能向下依赖，不能反向。`domain` 不导入任何其它层；`assets` 只读资源文件；`recommendation` 是纯计算，不碰库也不碰网络；`checking` 不写库，只计算要求、核销与放行结论；`workflow` 负责编排与写库；`api` 只做参数与 DTO。

## 2. 目录与职责

    app/
      config.py            路径、端口、模型、参数上限
      store/
        schema.py          建表与迁移（唯一的表定义处）
        db.py              连接、事务、审计、自增 ID 规则
      domain/
        enums.py           入口、策略、阶段、部门、状态、原因码
        models.py          纯数据对象与不变量
        normalize.py       文本／数字／单位／日期的通用规范化
        brief.py           两层 brief、字段继承、要求分类与检查指标映射
      assets/
        catalog.py         ABC 资产、品牌、产品、关系（只读）
        rules.py           审查规则装载与要求模板
      recommendation/
        ranking.py         查询归一、硬筛、评分、排序（纯函数）
                           ｜ 自由文字解析 parse_text 也在这里，不调模型
      intelligence/
        client.py          Paratera 调用（超时、结构校验、禁用思考）
        parse.py           资料 → 两层 brief 与方向草案（只产出提案）
        targeting.py       方向 brief → C 标签，再按字典边展开 A/B（只产出提案）
        extract.py         各格式正文与图片定位
      checking/
        build.py           F17 生成 CheckSet 与 Requirement
        evidence.py        F18 证据匹配与核销
        release.py         F20 放行判定
      workflow/
        routing.py         F05 判型
        planning.py        F10/F12 目标位与开发子项
        gates.py           每个阶段可做的动作及其前提
        issues.py          WorkflowIssue 生成、恢复、投影
        service.py         命令层 F01–F24
        views.py           给页面的读模型
      adapters/
        port.py            PlatformPort 协议
        mock_platform.py   本地模拟中台（任务、回执、报价、库存）
      api/
        http.py            路由、静态文件、错误映射
    frontend/
      style.css  common.js
      index.html  projects.js      项目列表
      project.html project.js      项目详情
      select.html  select.js       选香
    mock_platform/
      index.html  app.js           模拟中台，独立于业务前端
    resources/             只读：ABC 资产、审查规则
    data/
      workbench.sqlite3    processed 业务库（原件以 BLOB 存库）
      source/ processed/ feedback/{parse,targeting,recommendation}/
    tests/
      modules/             domain / brief / rules / ranking
      workflows/           workflow / http / acceptance
      cases/               验收用例入口（真实案例在 research/cases）
    research/
      cases/ reference/    案例库与旧版对照
      model_trials/ recommendation/

## 3. 三条不变的约定

1. **写库只在 service**。其它层返回对象或结论，由 service 在同一事务里落库并写 audit。
2. **业务阻断不是异常**。命令在正常路径上返回 `issues[]`（原因码、缺什么、等什么、下一步），页面据此显示；只有「动作已执行但结论是不放行」这一种情况用 `StepBlocked` 控制流，并在命令边界转成同样的返回形状；非法参数、越权、对象不存在才抛 `ValueError`。
3. **资产只读、人工改动留痕**。ABC 库、产品关系、审查规则都是只读文件；人工改标签写 `asset_edits` 并记 manual，人工改需求写新的 brief 修订并留 origin。

## 4. 文档索引

- [对象与不变量](objects.md)：项目到目标位、检查与证据、开发与中台各自的事实与约束。
- [信息提取与标签映射](intelligence.md)：两层 brief、字段继承、parse 与 targeting 的输入输出、C 左侧判定指导。
- [功能契约](functions.md)：F01–F24 的落点、输入、写什么、拒绝什么。
- [阶段与动作](workflow.txt)：状态机、两条主链、三种阻断。
- [检查与放行](checking.md)：规则如何变成要求，证据如何复用，初寄与正式的差别。
- [数据](data.md)：表分组、关系、并发、迁移与备份。
- [页面](ui.md)：三个页面、动作命名、错误显示。
- [本机验收](acceptance.md)：能证明什么、还不能证明什么。
- [取舍](decisions.md)：为什么这样搭，以及第一版哪里错了。

## 4. 与第一版的差别

第一版把建表、LLM 输出校验、业务特判、模拟派发和页面投影都放在 `app/workflow.py` 一个文件里，用 `tasks.result` 布尔值代替部门回执，用 `flow_slots.context` JSON 代替开发迭代与检查记录。重搭后：

- 表定义集中在 `store/schema.py`，业务字段不再藏在 JSON 里；
- 检查与放行成为独立模块，规则来自 `香精审查规则_轻量版.json`，证据落库可跨项目复用；
- 目标位有明确阶段与动作表，缺条件产生 Issue 而不是报错；
- 中台被隔离在 `adapters`，换真实接口不改业务；
- 特例（指定产品、系列编号、交期锚定）改为通用规则，不再逐个案例写死。


