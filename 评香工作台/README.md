# 评香工作台

本地单机应用。一个 Python 进程提供 HTTP 与静态页面，一份 SQLite 存业务状态。
评香在这里读资料、确认方向、定方案、做检查、放行、寄样；中台是另一页的模拟实现。

## 启动

双击 [启动.cmd](启动.cmd)，服务就绪后自动打开项目列表。默认 `http://127.0.0.1:18761/`。

- 首次运行先装依赖：`python -m pip install -r requirements.txt`
- 换端口：`python -X utf8 launch.py --port 18762`
- 不开浏览器：`python -X utf8 launch.py --no-browser`
- 端口上还开着旧版本时，`launch.py` 会自动换一个空闲端口并打印新地址；确认不需要旧窗口后关掉它，再用默认端口启动。

## 页面

- `http://127.0.0.1:18761/index.html` 项目列表。新建项目，进入某个项目。
- `http://127.0.0.1:18761/project.html?id=1` 项目详情。导入资料、确认方向、看需求与标签、定方案、生成检查清单、放行、备样与寄样。页面最下方「模型调用」可回看每次 LLM 请求的产出要求、输入和返回。
- `http://127.0.0.1:18761/select.html` 选香。从目标位进入时按该方向的人群、市场、香气原文和标签筛选，选定后回到目标位。
- `http://127.0.0.1:18761/mock.html` 模拟中台。部门默认回执、待处理任务、最近回执。

## 目录

- `app/`：`domain`（对象、brief、规范化）、`store`（表、连接、审计）、`assets`（ABC 资产与审查规则，只读）、`recommendation`（查询解析与排序，纯函数）、`intelligence/parse`（资料到两层 brief）、`intelligence/targeting`（方向 brief 到 C 标签）、`checking`（要求、证据、放行）、`workflow`（命令层、阶段、问题、投影）、`adapters`（中台协议与模拟实现）、`api`（路由与静态文件）。
- `frontend/`：项目列表、项目详情、选香三页及公共 js、css。
- `mock_platform/`：模拟中台的单独页面与脚本，走同一套 `/api/platform`。
- `resources/`：`ABC/` 标签体系与资产、`审查/` 规则文件，全部只读。
- `data/`：`workbench.sqlite3` 是 processed 业务库；`source/` 放导出的原始资料，`processed/` 放清洗结果，`feedback/{parse,targeting,recommendation}/` 放人工修正与推荐复盘的落点。当前原件仍以 BLOB 存库，这三个目录先留位。
- `tests/modules/`：domain、brief、rules、ranking 的独立测试。
- `tests/workflows/`：workflow、http、acceptance 的链路测试。
- `tests/cases/`：验收用例的入口与说明，真实案例库在 `research/cases/`。
- `research/cases/`：客户真实案例库，只读素材。
- `research/reference/`：第一版原型，只作参考。
- `research/model_trials/`：模型选型与提示词试验记录。
- `research/recommendation/`：推荐结果逐案反思。
- `docs/`：先看 [分层与依赖](docs/architecture.md)；需求怎么变成字段看 [信息提取与标签映射](docs/intelligence.md)。
- `scoring.json`：选香权重，唯一来源。

## 运行测试

```
python -X utf8 -m unittest discover -s tests -t .
```

测试使用 `data/` 下的固定库文件，不用临时目录；跑完会自行清理。模型调用点都可替换，测试不发外部请求。

## 资料与规则

- 业务标准：[wanted.txt](docs/wanted.txt)；原始取舍：[thinking.md](docs/thinking.md)；第一轮设计（历史）：[第一轮设计](docs/设计历史/第一轮设计/README.md)。
- 审查规则：`resources/审查/香精审查规则_轻量版.json`，只读；系统只生成要求，不自动判定数值。
- ABC 资产与标签：`resources/ABC/`，只读；人工改动写 `asset_edits` 并留 manual。
- C 左侧判定指导来自 `resources/ABC/品类与ABC标签体系_V2.xlsx` 的 `C左侧判定补充` 页，打标时随候选一起给模型。
- 模型：Paratera OpenAI 兼容接口，拆解用 `DeepSeek-V4.1-Flash`，打标用 `DeepSeek-V4-Flash-0731`，图片用视觉模型。密钥读环境变量 `PARATERA_API_KEY`，没有时回退到既有密钥文件。

## 当前边界

- 中台是本地模拟：任务、回执、报价、库存都带 `MOCK-` 前缀，真实配方、实物库存、物流未接。
- 检查回执按部门整组通过或退回，没有逐项录入。
- 单机单人，不做登录与权限。
- 还没有迁移脚本：表结构变更前请先备份 `data/workbench.sqlite3`。
