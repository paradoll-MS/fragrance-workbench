from pathlib import Path
p=Path('fragrance-copilot-v3/app/understand.py');s=p.read_text(encoding='utf-8-sig');start=s.index('def repair_abc(');end=s.index('\ndef apply(',start)
replacement='''def repair_abc(s, draft, issue):
    """Complete only missing evidence inside the same understanding run; do not rewrite facts."""
    con = db.connect()
    terms = {x['id']:x for x in db.rows(con,'select id,domain,layer,label,definition from terms')}
    nodes = {x['id']:x for x in db.rows(con,'select * from c_nodes')}
    con.close()
    missing = []
    for item in draft['subprojects']:
        explained = {x.get('id') for x in item.get('abc_basis',[]) if x.get('reason')}
        for field in ('a1','a2','a3','b','target_cs'):
            for tid in item.get(field,[]):
                if tid not in explained:
                    missing.append({'key':item.get('key'),'id':tid,'field':field,'tag':terms.get(tid) or nodes.get(tid)})
    if not missing: return draft
    payload = {'project':s['project'], 'artifacts':inference_context(s)['artifacts'],
               'subproject_contexts':[{'key':x.get('key'),'title':x['title'],'direction':x.get('direction'),
                                      'brief':x.get('brief'),'category':x.get('cat')} for x in draft['subprojects']],
               'missing_evidence':missing, 'validation_error':issue}
    system = ''''''你在修复同一个全景理解节点的标签依据完整性。原有客户事实、子项目和任务关系都不能改。
逐条处理missing_evidence，每个(key,id)必须恰好输出一条。A、B、C完全同样处理，C也必须给reason，不能遗漏。
C是商业定位/场景/体验分类，请结合产品用途、定位、人群、风格与意图理解；不是字面摘词。tag字段已给出这个标签的完整路径和定义。
只返回JSON：{"evidence":[{"key":"输入的key","id":"输入的id","reason":"针对该标签的简短语义理由","confidence":0.8,"source_refs":[{"artifact_id":"真实资料id","locator":"页段","quote":"短的逐字原文子串，不要拼接不相邻段落"}],"keep":true}]}。
有充分语境支持时keep=true并给理由及来源；确实不合适或跨品类时keep=false并解释，不得给空reason。必须覆盖所有missing_evidence，只处理这些标签，不输出其它字段。''''''
    llm.begin(s['project']['id'],'understand_project_v3_contract_repair')
    patch = llm.chat_json([{'role':'system','content':system},{'role':'user','content':db.js(payload)}],max_tokens=32000,timeout=420,temperature=0)
    answers = {(x.get('key'),x.get('id')):x for x in patch.get('evidence',[])}
    requested = {(x['key'],x['id']) for x in missing}
    if set(answers) != requested: raise ValueError('标签依据修复未逐条覆盖请求')
    by_key = {x.get('key'):x for x in draft['subprojects']}
    for request in missing:
        answer = answers[(request['key'],request['id'])]
        item = by_key[request['key']]
        if answer.get('keep') is False:
            item[request['field']] = [x for x in item[request['field']] if x != request['id']]
            item.setdefault('rejected_labels',[]).append({'id':request['id'],'reason':answer.get('reason','依据不足')})
        else:
            if not answer.get('reason') or not answer.get('source_refs'): raise ValueError('标签依据修复仍缺理由/来源')
            item.setdefault('abc_basis',[]).append({k:v for k,v in answer.items() if k in ('id','reason','confidence','source_refs')})
    draft.setdefault('_contract_repair_outputs',[]).append(patch)
    draft.setdefault('warnings',[]).append('标签依据经过一次完整性修复，客户事实、任务类型和关联未在修复中改动。')
    return draft

'''
# Delimit the embedded prompt independently from this utility's string literal.
replacement=replacement.replace("system = 你在", "system = '''你在").replace('不输出其它字段。\n    llm.begin','不输出其它字段。\'\'\'\n    llm.begin')
p.write_text(s[:start]+replacement+s[end:],encoding='utf-8')
