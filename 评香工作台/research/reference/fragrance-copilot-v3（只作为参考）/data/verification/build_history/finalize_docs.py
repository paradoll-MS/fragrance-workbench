from pathlib import Path
import json,sys
root=Path('fragrance-copilot-v3').resolve();docs=root/'docs'
p=root/'tests/check_zhuben_round1.py';s=p.read_text(encoding='utf-8-sig');a=s.index('with urllib.request.urlopen');b=s.index('checks=[]',a);s=s[:a]+'''c=db.connect();snap=understand.snapshot(c,pid)
if len(snap['artifacts'])>2 and (out/'round1_snapshot.json').exists():
 snap=json.loads((out/'round1_snapshot.json').read_text(encoding='utf-8'));run=json.loads((out/'round1_checks.json').read_text(encoding='utf-8'))['run']
 print('verifying frozen first-round snapshot')
else:
 with urllib.request.urlopen('http://127.0.0.1:8768/api/projects/'+pid+'/generation') as r:run=json.load(r)['run']
 if run['status']!='succeeded':sys.exit(2)
 if len(snap['artifacts'])!=2:raise RuntimeError('First-round snapshot requires exactly the two briefs')
 (out/'round1_snapshot.json').write_text(db.js(snap),encoding='utf-8')
'''+s[b:];p.write_text(s,encoding='utf-8')
p=docs/'01_端到端流程与LLM节点.md';s=p.read_text(encoding='utf-8');s=s.replace('生产理解 prompt：','一个逻辑理解阶段通常一次调用；仅在已有标签缺少语义依据时，允许一次有界的内部契约补全调用。补全只回答缺失的标签依据，不改客户事实、任务路由或原文。有效完整输出不触发第二次调用。失败输出保留供追查。\n\n生产理解 prompt：');s += '\n## 完整上下文与引用校验\n\n原始全文完整发送；重复的派生段落以全文定位代替，重复的工单简报以子简报引用代替，避免相同内容成倍占用上下文。完整输入快照仍独立保存。所有所选ABC必须有语义依据；跨品类C剔除并显示审查说明。引用按原文锚定；空白或非连续拼接可校正定位并记录校对方式，数字、否定与关键化学/方向变化拒绝。\n';p.write_text(s,encoding='utf-8')
p=docs/'07_任务派发与完成终点.md';s=p.read_text(encoding='utf-8').replace('改香：内部号/原样与改动要求 → 调香；缺基准号先创建确认改香基准任务，不能凭空编号。','改香：内部号/原样与改动要求 → 调香。关联上一轮的改香自动承袭最近已完成寄样工单的实际寄出编号；无寄样记录时，两类推荐、找香、对香可使用上一轮已选定内部号。创香/改香的评香参考号不能冒充实发号。\n\n上一轮编号尚未同步时保留原样、父子关系和改动要求，调香工单等待原样编号同步；首轮实发号补齐后自动唤醒。多个实发号而无法唯一对应时不猜测。只有独立发起且没有父项目引用的改香，才保留确认改香基准入口。\n\n');s += '\n实际寄样编号在寄样工单填写，支持真实调香试样号；它只进入项目执行记录，不自动创建香精库条目。待执行后续工单同步项目客户、项目对接与交期、子简报和原样引用。\n';p.write_text(s,encoding='utf-8')
p=docs/'02_项目_子项目_任务_样品模型.md';s=p.read_text(encoding='utf-8');s += '\n改香的 `context_json.inherited_base` 保存父子关联、原样名称、实发工单、编号及来源状态。`base_formula_code` 仅保存可唯一确认的实际基准号。项目级客户与对接事项进入工单上下文，产品额外要求在子项目层按适用范围物化；空的子字段不会抹掉已知共有事实。\n';p.write_text(s,encoding='utf-8')
(docs/'模型配置与调用.md').write_text('''# v3 模型配置与调用

配置沿用本地 `data/config.json`，不把凭证写进文档。解析/识别、全景理解、项目问答分别记录调用。全景理解显式开启深度思考并采用高推理强度；分类与有界契约补全关闭深度思考。协议参照 [DeepSeek 官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)。

理解输出默认上限 48000 token，超时 420 秒；本地可配置 `understanding_max_tokens`。输入容量上限 900000 字符，原文不静默截断。需要更多容量或输出达到上限时明确报错，旧结果保留。

一个逻辑理解阶段可包含一次标签依据契约补全。所有调用分别留痕；完整有效输出只有一次理解调用。项目运行持久化，刷新可恢复；同项目重复点击不会启动并发理解。无输入变化复用已完成结果。

调用上下文采用线程隔离，不把不同项目的来源串在一起。日志与界面显示实际 token 和耗时，不将旧版估算金额作为账单。
''',encoding='utf-8')
report='''# 逐本案例：v3 两轮验收

验收日期：2026-10-29。项目为“逐本 · v3 两轮验证”，主项目 `p_bafd3133cc154ffa`。v3 独立位于 `fragrance-copilot-v3`，端口8768；v2目录和业务数据未改写。

## 结果

第一轮仅使用两份初始brief，生成12个独立香型子项目并保存简报、上市分层、ABC依据、客户额外要求和推荐快照，101项检查通过。之后才加入第二轮会议纪要，新增4个关联改香子项目；原12个子项目、首轮简报和原文保持不变，60项检查通过。确定性回归测试57项通过。上述计数是具体验收项通过数，不是对所有模型语义的无条件准确率承诺。

可在 [逐本项目](http://127.0.0.1:8768/?project=p_bafd3133cc154ffa&tab=subprojects) 查看16个子项目。主项目存客户、联系人、总体交期和协调事项；产品专属及适用的共有额外要求存入各子项目，并带来源进入工单。

## 原始资料与分轮隔离

1. 第一轮：《逐本活力系列水果卸妆膏产品线完整策划Brief.docx》，2026-08-29，12款气味方向、结构和排除项。
2. 第一轮：《逐本活力系列卸妆膏_味道分层上市节奏与供.pdf》，2026-08-30，上市分层与供样边界。
3. 第二轮：《20260911163823-逐本×双马会议-纪要文本.pdf》，2026-09-11，四款修改及交期、寄料、稳定性要求。

三份资料原件、提取全文和页段定位保留；两份PDF关键页面已渲染核对。首轮冻结快照只含前两份资料，会议纪要在首轮通过后加入，因此首轮结果没有提前看到会议反馈。

## 首轮拆分与推荐

| 香型 | 上市层级 | 当前候选数 |
| --- | --- | ---: |
| 茉莉冰荔枝 | S | 14 |
| 气泡青苹果 | S | 1 |
| 茉莉青提 | S | 15 |
| 鲜莓芭乐 | S | 1 |
| 海盐柚子 | A | 0 |
| 青柠百香果 | A | 2 |
| 爆汁青橙 | A | 2 |
| 一口水蜜桃 | B | 2 |
| 海风轻椰 | B | 3 |
| 冰镇西瓜 | C | 1 |
| 酸野青芒 | C | 1 |
| 害羞乌梅 | C | 0 |

全部归入内部三级品类“卸妆膏油”。S4首发、A3后续跟进、B2测试、C3储备分别保存。客户上市等级与本体ABC分开，9款商品化的文件/稳定性/放大等要求没有强塞给3款储备香。

香气结构比例保存在气味结构/原则中，没有被当成产品添加量；资料未给香精采购价，目标价保持为空。已有共同产品与人群信息不会被子项空占位覆盖。每款额外要求有来源，ABC选择有语义理由。零候选如实显示，可由人调整条件；系统未自动放宽硬筛制造结果。

候选数仅表示当前库和条件下的确定性检索结果，不代表完成实物评香。候选自身ABC、直接得分、候选C映射AB得分和用样次数可逐项查看。

## 第二轮跟进

| 原首轮香型 | 关联改香重点 |
| --- | --- |
| 茉莉冰荔枝 | 减轻荔枝甜腻，增加清脆、冰凉感并明确茉莉 |
| 气泡青苹果 | 增强酸脆、清新及料体中气泡爆发，增加复合感并避免洗发水意象 |
| 茉莉青提 | 识别“青提茉莉”别名，去发酵/酒感，青提与茉莉各半 |
| 鲜莓芭乐 | 降低脂粉、芭乐主导，微量草莓增加酸甜 |

4项均创建新的modify子项目并指向正确首轮父项。首轮历史需求和执行记录不被新反馈覆盖。统一的50℃或UV、8至24小时梯度和观察一周以上要求在4项客户额外要求中均保留。仍是计划或待执行的事项没有被写成已完成。

项目层保存9月底定版、负责人和两路寄料：上海约200g用于打样/闻香，天津约500g用于稳定性。纪要“下周一”依据会议日期2026-09-11解析为2026-09-14，原始说法和来源也保留。逯柏松寄料/纪要、李玲提供测试方法、畅执行4款修改分别记录；刘扬没有被凭空分配行动。

## 首轮实发香精号承袭

编号来源优先级是“首轮最近已完成寄样的实际寄出号”，再按合法路线使用首轮已选定号。创香/改香的参考候选不会冒充真实寄出号。调香试样号允许进入实发记录，不写香精库。

案例原文没有内部编号，因此4个改香保留首轮原样引用、父子关系、改动要求及待同步状态，不新增要求用户重新描述基准的任务，也不编造编号。实际首轮寄样号一旦补齐，关联待执行工单自动取得基准并唤醒。多个实发号无法唯一匹配时不猜测。该逻辑用独立临时数据库测试了实发优先、延后同步、多号歧义、参考号隔离以及库不写入。

## 检查中发现并修正的问题

- 旧代码可能按有限关键词拆分、遗漏完整语境；现在使用全量资料的统一理解，保存逐项覆盖和来源。
- 真实输出曾使用别名字段导致空表单、漏标签理由、拼接引用和单字笔误。修正了契约与别名、空占位继承、一次有界依据补全和原文定位校验。被拒绝输出保留，校验失败不覆盖项目；先前拒绝结果通过通用校验修正后复验，未手工编造客户事实或号码。
- 跨品类C不会进入打分，而是留下可见审查说明。字段流转保留人工覆盖与已执行快照。
- 第二轮既保留历史又新增后续，避免重复创建原香型和同时改写父项。
- 任务按依赖分段生成；人工确认GC后才接调香，参考选择不直接跳到打样。入库前后端均关闭。
- 酒店历史案例原来错走创香的子项已改为国外大牌推荐；未开始的错误类型有历史，已开始的类型不能被静默覆盖。

## 数据与复核入口

库的8张表逐表计数和SHA-256与v2一致：6331条香精、92864条标签关联、571个C节点等均保持。对比结果在 `data/verification/library_integrity.json`。

逐本证据位于 `data/verification/逐本/`：`round1_snapshot.json`、`round1_checks.json`、`round2_snapshot.json`、`round2_checks.json`、原文提取及PDF页面。成功首轮run为 `g_79fb648f5f454c96`；成功第二轮run为 `g_8d0bc5b28cf24ceb`。57项回归的输出为 `data/test-results.txt`。

复核命令：`python tests/test_v3.py`、`python tests/check_zhuben_round1.py`、`python tests/check_zhuben_round2.py`、`python tests/check_library_integrity.py`。两轮完成后首轮复核读取冻结首轮快照，不把第二轮数据覆盖进基线。模型原输出、补全输出、输入快照和拒绝原因保存在generation_runs与decisions中。

真实实物评香、收样、GC结果、寄样完成、法规/质量核对仍由实际执行人确认。系统已具备这组案例的首轮萃取保存、拆分推荐及关联下一轮能力；现实编号和执行结果以真实记录为准。
'''
(docs/'逐本两轮验收.md').write_text(report,encoding='utf-8')
p=root/'README.md';s=p.read_text(encoding='utf-8');s+='\n逐本两轮实测：12个首轮香型 + 4个关联改香；101项首轮与60项次轮检查通过，57项回归通过。见 [逐本两轮验收](docs/逐本两轮验收.md)。\n\n关联改香自动承袭首轮实际寄样号；样例缺号时保留原样引用并等待同步。寄样工单可填写实发调香试样号，不写库。\n';p.write_text(s,encoding='utf-8')
p=root/'data/verification/逐本/state.json';state=json.loads(p.read_text(encoding='utf-8'));state.update(round1_accepted_run='g_79fb648f5f454c96',round2_accepted_run='g_8d0bc5b28cf24ceb');p.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
sys.path.insert(0,str(root));from app import db,understand
c=db.connect()
for pid,rid in [('p_bafd3133cc154ffa','g_8d0bc5b28cf24ceb'),('p_a90dcb3fe91c4f4a','g_2971af3ac4694740')]:
 row=db.one(c,'select * from generation_runs where id=?',(rid,));result=json.loads(row['output_json']);result['applied_fingerprint']=understand.input_hash(understand.snapshot(c,pid));c.execute('update generation_runs set output_json=? where id=?',(db.js(result),rid))
c.commit();c.close()
print('docs, read-only replay guard, and final run fingerprints saved')
