from pathlib import Path
p=Path('fragrance-copilot-v3/prompts/understand_project.md');s=p.read_text(encoding='utf-8').replace('系统会先建确认改香基准任务，内部号补齐后再执行调香。','系统自动承袭首轮实际寄样号；暂未同步编号时保留原样关联，等待源记录同步，不要求重新描述基准。');s+='''
跨轮字段一致性与旧要求承袭（最高优先级）：
- 改香不仅在modification/theme里写新反馈，还必须同步scent.structure、principles、directions、exclusions等受影响字段。最新明确的局部要求覆盖旧通用规则；不允许一处说新配比，另一处仍保存旧配比。
- shared_brief中的旧通用配比、绝对主次原则若与某款最新反馈冲突，不能继承到该款；将共享要求限定applies_to_keys或改为各自specific。当前customer_requirements只列仍有效的要求，被替代的规则留在父项历史，不再作为新工单有效检查。
- 未改变的产品、基质、人群、价格、上市分层、法规/包材/量产验收等持续性约束承袭父项。首轮整体供样计划不等于要求后续改香重新执行全部首轮任务；新交期/新数量采用当前轮，不继承过期的局部交期。若新资料明确撤销某个持续性旧要求，可在子项附superseded_requirement_texts:[旧要求原文]并提供新来源说明。
- 已存在的关联modify子项如需纠错，返回其实际id与原parent_subproject_id，更新这一后续项即可；不得新建重复改香，也不得改写首轮父项。认真核对本轮结构字段与原文变化，不沿用旧模型错误。
''';p.write_text(s,encoding='utf-8')
