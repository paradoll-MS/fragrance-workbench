# 评香工作台 · 第一轮设计

从 [workflow／主流程树](workflow-主流程树.txt) 开始。挑一条业务路径，可以沿树读到每一步的输入、看到的内容、确认动作、函数、写入和终点。

- [objects／对象与字段](objects-对象与字段.md) 给出对象层级、字段归属、可空约定和状态。
- [functions／函数契约](functions-函数契约.md) 给出每个调用的输入输出、依赖、写入和失败分支。
- [recommendation／ABC 选香](recommendation-ABC选香.md) 给出三个模式、硬筛和两轮计分，以及两种手工改动的落点。
- [data／数据与模拟中台](data-数据与模拟中台.md) 给出导入字段、缺口、部门接口和回流。
- [workspace／工作台与模型](workspace-工作台与模型.md) 给出界面、Parse 和 Targeting、开工顺序与目录。
- [walkthrough／路径验收](walkthrough-路径验收.txt) 用真实 brief、历史工单和明确标记的模拟回执逐条走查。
- [decisions／业务待定](decisions-业务待定.md) 集中列出需要业务定口径的事项和试跑值。

业务分支和终点依据 [wanted](../wanted.txt)。V3 用于参考文档解析、引用校验、增量理解和筛选交互。ABC V2 工作簿提供应用品类与标签，审查轻量版提供检查目录。模型只提供 Parse 和 Targeting，编号归一、路由、打分、放行及对接由程序完成。

Phase 2 ／ 实现时采用一个本地后端、一份应用 SQLite、一个评香页面和一个独立的模拟中台页面。先用手填数据走通业务，再接模型、导入真实库并逐单试香回看。第一轮的模拟回执只用于检查实现契约。

