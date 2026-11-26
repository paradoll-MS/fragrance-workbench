from pathlib import Path
p=Path('fragrance-copilot-v3/app/understand.py');s=p.read_text(encoding='utf-8');at=s.index('\ndef apply(con, s, result, rid):');code='''
def repair_followup(s, draft, issue):
    """One bounded semantic repair; only conflicting scent fields can change."""
    affected = []
    for item in draft['subprojects']:
        parent = next((db.jload(b['data_json'],{}) for b in s['briefs'] if b.get('subproject_id')==item.get('parent_subproject_id')),{})
        if item.get('task_type')=='modify' and followup_conflict(parent,item['brief']):
            affected.append({'key':item['key'],'title':item['title'],'parent_scent':parent.get('scent'),'current_brief':item['brief'],'source_refs':item.get('source_refs',[])})
    if not affected: raise ValueError(issue)
    llm.begin(s['project']['id'],'understand_project_v3_contract_repair')
    instruction = ('修复跨轮气味结构与有效要求之间的矛盾。只修改指定key的scent字段与有效scent要求，不能改产品、项目、ABC、任务或基准号。'
        '按资料日期、局部具体反馈优先于旧通用规则；最新各半等意象配比不能再机械追加旧空气感百分比。'
        '旧通用百分比与新局部配比冲突时从有效要求中移除，旧记录已保留在父项历史。'
        '共同的水果第一等原则若与新的平衡主次冲突也要改清楚。保留未冲突的要求。'
        '只用有来源的数字，不编配方；所有新增要求必须带逐字source_refs。'
        '返回JSON {"updates":[{"key":"原key","scent":{使用现有scent字段键},"scent_requirements":[完整有效的scent类要求，含text/category=scent/source_scope/source_refs/status=recorded],"reason":"新旧覆盖依据"}]}。')
    sources = [{'id':a['id'],'filename':a['filename'],'text':a.get('text','')} for a in s['artifacts']]
    patch = llm.chat_json([{'role':'system','content':instruction},{'role':'user','content':db.js({'issue':issue,'items':affected,'sources':sources})}],max_tokens=8000,timeout=180,temperature=0.1)
    updates = {u.get('key'):u for u in patch.get('updates',[])}
    if set(updates)!={i['key'] for i in affected}: raise ValueError('跨轮修复未逐项覆盖')
    for item in draft['subprojects']:
        if item.get('key') not in updates: continue
        u=updates[item['key']]
        if not u.get('reason') or not isinstance(u.get('scent'),dict) or not isinstance(u.get('scent_requirements'),list): raise ValueError('跨轮修复契约不完整')
        if set(u['scent'])-set(model.GROUPS['scent']): raise ValueError('跨轮修复包含未知字段')
        if any(r.get('category')!='scent' for r in u['scent_requirements']): raise ValueError('跨轮修复不能改变非气味要求')
        before=copy.deepcopy(item['brief'])
        item['brief']['scent']=model.merge(item['brief']['scent'],u['scent'])
        item['brief']['customer_requirements']=[r for r in before.get('customer_requirements',[]) if r.get('category')!='scent']+u['scent_requirements']
        item.setdefault('contract_resolutions',[]).append({'issue':issue,'reason':u['reason'],'prior_scent':before['scent'],'prior_requirements':before.get('customer_requirements',[])})
    draft.setdefault('_contract_repair_outputs',[]).append(patch)
    draft.setdefault('warnings',[]).append('跨轮气味结构与有效要求已做一致性校验；旧配比保留在父项及修复审计中。')
    return draft

''';s=s[:at]+code+s[at:];s=s.replace("if str(issue) != 'ABC推断缺少语义依据': raise", "if str(issue) not in ('ABC推断缺少语义依据','比例修改与气味结构或继承要求冲突，未覆盖旧结果'): raise");s=s.replace("result = repair_abc(s,result,str(issue))", "result = repair_abc(s,result,str(issue)) if str(issue)=='ABC推断缺少语义依据' else repair_followup(s,result,str(issue))");p.write_text(s,encoding='utf-8')
p=Path('fragrance-copilot-v3/web/app.js');s=p.read_text(encoding='utf-8').replace("understand_project_v3_contract_repair:'依据完整性校验'","understand_project_v3_contract_repair:'契约一致性校验'");p.write_text(s,encoding='utf-8')
