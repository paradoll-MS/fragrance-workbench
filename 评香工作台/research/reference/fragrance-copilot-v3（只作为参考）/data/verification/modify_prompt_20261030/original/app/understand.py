"""One full-context model node; durable asynchronous execution and atomic application."""
from __future__ import annotations
import json
import threading
import re
import copy
import difflib
from . import db, llm, model, reco, workflow, service, business, source_refs

MAX_CONTEXT_CHARS = 900_000
RATIO_CHANGE = r'各半|一半|(?:调整|修改|改变|变更|重新).{0,10}(?:比例|配比|占比)|(?:比例|配比|占比).{0,6}(?:改|调|变|控制|设)|\d+\s*[/：:]\s*\d+'


def followup_conflict(parent, current):
    if not re.search(RATIO_CHANGE,str(current.get('modification') or '')): return False
    structure = (parent.get('scent') or {}).get('structure')
    unchanged = structure and current['scent'].get('structure')==structure
    inherited_ratio = any(r.get('category')=='scent' and r.get('source_scope')=='inherited' and re.search(r'\d\s*[%％]',r.get('text','')) for r in current.get('customer_requirements',[])+current.get('requirement_register',[]))
    return bool(unchanged or inherited_ratio)


def snapshot(con, pid):
    p = db.one(con, 'select * from projects where id=?', (pid,))
    if not p: raise KeyError('项目不存在')
    arts = db.rows(con, 'select * from artifacts where project_id=? order by created_at,id', (pid,))
    briefs = db.rows(con, 'select * from briefs where project_id=? order by coalesce(subproject_id,\'\'),version', (pid,))
    subs = db.rows(con, 'select * from subprojects where project_id=? order by created_at,id', (pid,))
    tasks = db.rows(con, 'select t.* from department_tasks t join subprojects s on s.id=t.subproject_id where s.project_id=? order by t.id', (pid,))
    samples = db.rows(con, 'select * from external_samples where project_id=? order by id', (pid,))
    decisions = db.rows(con, '''select * from decisions where (entity='project' and entity_id=?) or entity_id in
          (select id from subprojects where project_id=?) or entity_id in
          (select id from department_tasks where subproject_id in (select id from subprojects where project_id=?))
          order by id''', (pid, pid, pid))
    story = db.one(con, 'select * from stories where project_id=? order by updated_at desc limit 1', (pid,))
    return dict(project=p, artifacts=arts, briefs=briefs, subprojects=subs, tasks=tasks, samples=samples, decisions=decisions, story=story)


def input_hash(s):
    return model.fingerprint({'business_policy':model.BUSINESS_POLICY,'source_contract':'span_handles_v1','context':s})


def inference_context(s):
    """Reference repeated derived data instead of feeding duplicate copies; raw text stays complete."""
    out = copy.deepcopy(s)
    briefs = {}
    for b in out['briefs']:
        b['data'] = db.jload(b.pop('data_json'), {})
        briefs[b.get('subproject_id')] = b
    for a in out['artifacts']:
        meta = db.jload(a.pop('text_meta_json', None), [])
        source = a.get('text') or ''
        locators = []
        cursor = 0
        for m in meta:
            text = m.get('text') or ''
            start = source.find(text, cursor) if text else -1
            if start < 0 and text: start = source.find(text)
            if start >= 0:
                locators.append({'locator':m.get('locator'), 'start':start, 'end':start+len(text)})
                cursor = start + len(text)
            elif text:
                locators.append(m)
        a['locators'] = locators
        a['annotation'] = db.jload(a.pop('annotation_json', None), {})
    for t in out['tasks']:
        p = db.jload(t.pop('payload_json', None), {})
        b = briefs.get(t['subproject_id']) or {}
        bd = b.get('data') or {}
        for key, field in [('requirements', None), ('customer_requirements','customer_requirements'), ('handoff','handoff')]:
            target = bd if field is None else bd.get(field)
            if key in p and p[key] == target:
                del p[key]; p[key+'_ref'] = {'brief_id':b.get('id'), 'field':field or 'data'}
        if t.get('detail') and t['detail'] == bd.get('handoff'):
            t.pop('detail'); t['detail_ref'] = {'brief_id':b.get('id'), 'field':'handoff'}
        t['payload'] = p
    for sp in out['subprojects']:
        for key in list(sp):
            if key.endswith('_json'):
                sp[key[:-5]] = db.jload(sp.pop(key), None)
    if out.get('story'):
        out['story']['data'] = db.jload(out['story'].pop('sections_json'), {})
        out['story'].pop('search_text', None)
    for d in out['decisions']:
        if d['actor'] == 'llm':
            d.pop('old_value',None); d.pop('new_value',None)
        else:
            for key in ('old_value','new_value'):
                d[key] = db.jload(d.get(key),d.get(key))
    lookup=source_refs.index(s['artifacts'])
    for a in out['artifacts']:
        a['locators']=[{'source_id':sid,'locator':ref['locator'],'start':ref['source_start'],'end':ref['source_end']} for sid,ref in lookup.items() if ref['artifact_id']==a['id']]
    return source_refs.compact(out,lookup,{a['id']:a for a in s['artifacts']})


def start(pid, force=False):
    con = db.connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        s = snapshot(con, pid)
        active = db.one(con, "select * from generation_runs where project_id=? and status in ('queued','running')", (pid,))
        if active: return public(active)
        if not s['artifacts'] or not any((a['text'] or '').strip() for a in s['artifacts']):
            raise ValueError('先上传可读取的资料，或补充解析文本')
        if any(a['status'] != 'parsed' or not (a['text'] or '').strip() for a in s['artifacts']):
            raise ValueError('有资料尚未解析完整；请补充文本或重新解析后再生成，避免漏读')
        prior = db.one(con, "select * from generation_runs where project_id=? and status='succeeded' order by rowid desc limit 1", (pid,))
        signature = input_hash(s)
        if prior and not force:
            output = db.jload(prior['output_json'], {})
            if output.get('applied_fingerprint') == signature: return public(prior)
        rid = db.uid('g_')
        con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',
                    (rid, pid, 'queued', '准备完整上下文', signature, db.js(s), None, '', db.now(), db.now()))
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()
    threading.Thread(target=run, args=(rid,), daemon=True, name='understand-' + rid).start()
    return dict(id=rid, status='queued', stage='准备完整上下文')


def public(r):
    out={k: r.get(k) for k in ('id', 'project_id', 'status', 'stage', 'error', 'created_at', 'updated_at')}
    out['policy_stale']=r.get('status')=='succeeded' and db.jload(r.get('output_json'),{}).get('business_policy')!=model.BUSINESS_POLICY
    return out


def refs_valid(refs, artifacts):
    if not isinstance(refs, list): raise ValueError('来源引用必须是数组')
    expanded = []
    for ref in list(refs):
        if isinstance(ref,dict) and ref.get('source_id'):
            anchor=source_refs.index(artifacts).get(ref['source_id'])
            if not anchor:raise ValueError('引用了不存在的原文定位段')
            if ref.get('artifact_id') and ref['artifact_id']!=anchor['artifact_id']:raise ValueError('来源定位段与资料不一致')
            if ref.get('quote'):
                original=artifacts[anchor['artifact_id']]['text'][anchor['source_start']:anchor['source_end']]
                if ref['quote'] not in original:raise ValueError('引用不是定位段中的原话')
            ref.update(anchor)
        if not isinstance(ref, dict) or ref.get('artifact_id') not in artifacts:
            raise ValueError('理解结果引用了不存在的资料')
        quote = ref.get('quote') or ''
        if not isinstance(quote, str): raise ValueError('引用必须是原文文本')
        source = artifacts[ref['artifact_id']]['text'] or ''
        if quote and quote not in source:
            # Repair formatting only, and save the actual original substring, never a fuzzy paraphrase.
            q = re.sub(r'\s+', '', quote.replace('\\n', '\n').replace('\\r', '\r'))
            positions = [i for i, ch in enumerate(source) if not ch.isspace()]
            compact = ''.join(source[i] for i in positions)
            pos = compact.find(q) if len(q) >= 4 else -1
            if pos < 0:
                # A model may concatenate separate quoted list lines. Keep them as separate real quotes.
                pieces = [x.strip() for x in re.split(r'[\n；;]+',quote.replace('\\n','\n').replace('\\r','\r')) if x.strip()]
                if len(pieces) > 1:
                    candidates = [{**ref,'quote':piece} for piece in pieces]
                    try:
                        refs_valid(candidates,artifacts)
                    except ValueError:
                        candidates = []
                    if candidates:
                        expanded.extend(candidates)
                        continue
                # Anchor a single non-critical transcription typo in a long, uniquely matching quote.
                # Numeric, negation, concentration and chemical changes are never corrected this way.
                if len(q)>=50:
                    match=difflib.SequenceMatcher(None,q,compact,autojunk=False).find_longest_match(0,len(q),0,len(compact))
                    start=match.b-match.a
                    candidate=compact[start:start+len(q)] if start>=0 else ''
                    differences=[(i,a,b) for i,(a,b) in enumerate(zip(q,candidate)) if a!=b]
                    protected=set('不无未非禁限免否高低大小前后甲乙丙丁戊己庚辛壬癸苯酚醇醛酮酸酯一二三四五六七八九十百千万零')
                    if len(candidate)==len(q) and compact.count(candidate)==1 and len(differences)==1 and match.size>=len(q)*0.9 and all(not(a.isdigit() or b.isdigit() or a in protected or b in protected) for _,a,b in differences):
                        ref['model_quote']=quote
                        ref['quote_normalization']='one_character_source_anchor'
                        pos=start
                if pos<0:
                    raise ValueError(f"引用不是原文子串：{artifacts[ref['artifact_id']]['filename']} · {quote[:70]}")
            ref['quote'] = source[positions[pos]:positions[pos + len(q)-1]+1]
        actual = ref.get('quote') or ''
        if actual:
            for meta in db.jload(artifacts[ref['artifact_id']].get('text_meta_json'), []):
                if actual in (meta.get('text') or ''):
                    ref['locator'] = meta.get('locator') or ref.get('locator')
                    break
        expanded.append(ref)
    refs[:] = expanded


def missing_mapping(item):
    """An empty array is not evidence that the semantic mapping was completed."""
    if item.get('task_type')!='recommend_brand':return set()
    scent=(item.get('brief') or {}).get('scent') or {}
    a=item.get('a1',[])+item.get('a2',[])+item.get('a3',[])
    needed=set('ABC') if not (a or item.get('b') or item.get('target_cs')) else set()
    if not a and (scent.get('main_accord') or scent.get('families')):needed.add('A')
    if not item.get('b') and scent.get('feelings'):needed.add('B')
    review=item.get('mapping_review') or {}
    def explained(domain):
        r=review.get(domain) or {}
        if r.get('status') not in ('insufficient_context','ontology_gap','reference_only') or not r.get('reason') or not r.get('source_refs'):return False
        # Already extracted feelings are usable B evidence, even without a literal label hit.
        return not (domain=='B' and scent.get('feelings') and r['status']!='ontology_gap')
    return {d for d in needed if not explained(d)}


def prepare_contract(s,result,con):
    """Normalize already explicit structured intent, without keyword classification.

    One initial branch can inherit its project brief. Multi-branch projects must
    use explicit shared/local scopes; their aggregate brief is never broadcast.
    Concrete target_products is an execution field, unlike scent.references.
    """
    items=result.get('subprojects') or []
    root=model.brief(result.get('brief') or {})
    sole=len(items)==1 and len(s['subprojects'])<=1 and not items[0].get('parent_subproject_id')
    if sole:
        common={g:root[g] for g in ('product','scent','commercial','compliance','deliverables')}
        if root.get('evidence'):common['evidence']=root['evidence']
        items[0]['brief']=model.inherit(common,items[0].get('brief') or {})
    additions=[];identities=None
    for item in list(items):
        if item.get('task_type') not in ('recommend_brand','recommend_simple'):continue
        targets=[p for p in item.get('target_products',[]) if p.get('brand') and p.get('product')]
        if not targets:continue
        if identities is None:
            from .identity import Index
            identities=Index(con)
        common=model.brief(model.inherit(result.get('shared_brief') or {},item.get('brief') or {}))
        total=root['deliverables'].get('quantity') or common['deliverables'].get('quantity') or ''
        group='同一推荐组合'+('，合计'+str(total) if total else '；总数量待确认')+'（包含指定产品）'
        item['brief']=common
        item['brief'].setdefault('planning',{}).update(selection_group=group,selection_role='其余风格候选')
        item['brief']['deliverables']['quantity']='其余款；与指定款合计'+str(total) if total else '补足同一组合；总数量待确认'
        item['target_products']=[]
        for p in targets:
            refs=p.get('source_refs') or item.get('source_refs') or []
            required={**p,'source_refs':refs}
            required_list=result.setdefault('brief',{}).setdefault('deliverables',{}).setdefault('required_products',[])
            if not any(all(x.get(k,'')==p.get(k,'') for k in ('brand','product','version')) for x in required_list):required_list.append(required)
            # Stable across later re-generation; existing matching find entries remain intact.
            def same_target(x):return x.get('task_type')=='find_product' and any(identities.product_match({'brand':t.get('brand',''),'product':t.get('product','')},p['product'],p['brand']) and t.get('version','')==p.get('version','') for t in (x.get('target_products') or db.jload(x.get('target_products_json'),[])))
            if any(same_target(x) for x in items+additions+s['subprojects']):continue
            key=(item.get('key') or item.get('id') or 'selection')+'__required_'+model.fingerprint({k:p.get(k,'') for k in ('brand','product','version')})[:12]
            brief={g:copy.deepcopy(common[g]) for g in ('product','commercial','compliance','deliverables')}
            brief['scent']={'theme':'指定必选：'+p['brand']+' '+p['product']}
            brief['planning']={'selection_group':group,'selection_role':'指定必选款'}
            brief['deliverables']['quantity']='指定产品1款；与其余款合计'+str(total) if total else '指定产品1款'
            additions.append({'key':key,'title':'找香：'+p['brand']+' '+p['product'],'task_type':'find_product','category_k_code':item.get('category_k_code'),'brief':brief,'target_products':[p],'source_refs':refs,'type_basis':{'reason':'客户明确指定的具体产品，独立于其余风格选型并行检索。','confidence':1}})
            result.setdefault('coverage',[]).append({'requirement':'必选 '+p['brand']+' '+p['product'],'subproject_keys':[key],'disposition':'独立并行找香，与其余风格选型共享总数量和供样方式','source_refs':refs})
    items.extend(additions)


def reconcile_tag_names(item,terms,nodes,cat):
    """Look up model-selected label names, never keywords in customer text."""
    fields=('a1','a2','a3','b','target_cs')
    original={tid:field for field in fields for tid in item.get(field,[])}
    resolved=[]
    for basis in item.get('abc_basis') or []:
        old=basis.get('id');label=basis.get('label')
        if old not in original or not isinstance(label,str) or not label.strip():continue
        field=original[old];domain='C' if field=='target_cs' else 'B' if field=='b' else 'A'
        if domain=='C' and old in nodes and nodes[old]['label']==label.strip() and (not cat or nodes[old]['new_class']!=cat['new_class']):continue
        pool=list(nodes.values()) if domain=='C' else [t for t in terms.values() if t['domain']==domain]
        if domain=='C':pool=[t for t in pool if cat and t['new_class']==cat['new_class']]
        matches=[t for t in pool if t['label']==label.strip() and (not basis.get('path') or domain!='C' or t['path']==basis['path'])]
        exact=next((t for t in matches if t['id']==old),None)
        target=exact or (matches[0] if len(matches)==1 else None)
        if target is None:raise ValueError('ABC推断缺少语义依据')
        new_field='target_cs' if domain=='C' else 'b' if domain=='B' else target['layer'].lower()
        resolved.append((old,target['id'],new_field));basis['id']=target['id'];basis['label']=target['label']
        if old!=target['id']:
            item.setdefault('label_identity_corrections',[]).append({'old_id':old,'id':target['id'],'label':target['label'],'reason':'按模型明确选择的名称查权威词表，校正编号；不按原文关键词猜标签。'})
    replaced={r[0] for r in resolved}
    for field in fields:item[field]=list(dict.fromkeys([tid for tid in item.get(field,[]) if tid not in replaced]+[tid for _,tid,f in resolved if f==field]))


def validate(con, s, result, require_label_names=False):
    if not isinstance(result, dict): raise ValueError('模型输出不是对象')
    prepare_contract(s,result,con)
    result['brief'] = model.brief(model.merge(result.get('shared_brief') or {}, result.get('brief') or {}))
    if not any(result['brief'][g].get(k) for g, k in [('project','summary'), ('scent','theme'), ('product','name')]):
        raise ValueError('模型返回了空简报，保留现有结果')
    if not isinstance(result.get('story'), dict) or not result['story'].get('summary'):
        raise ValueError('模型未返回项目故事')
    arts = {a['id']: a for a in s['artifacts']}
    def anchor_all(value):
        if isinstance(value,list):
            for child in value:anchor_all(child)
        elif isinstance(value,dict):
            if value.get('source_id'):refs_valid([value],arts)
            for child in list(value.values()):anchor_all(child)
    anchor_all(result)
    anns = result.get('artifact_annotations')
    if not isinstance(anns, list) or len(anns) != len(arts) or {a.get('artifact_id') for a in anns} != set(arts):
        raise ValueError('模型没有逐份覆盖全部资料')
    old = {x['id']: x for x in s['subprojects']}
    terms = {x['id']: x for x in db.rows(con, 'select * from terms')}
    cats = {x['k_code']: x for x in db.rows(con, 'select * from category_map')}
    cnodes = {x['id']: x for x in db.rows(con, 'select * from c_nodes')}
    items = result.get('subprojects')
    if not isinstance(items, list) or (not items and not old): raise ValueError('模型没有返回子项目')
    all_keys = {x.get('key') for x in items} | {x.get('understanding_key') for x in old.values()}
    for req in (result.get('shared_brief') or {}).get('customer_requirements', []):
        applies = req.get('applies_to_keys')
        if applies is not None and (not isinstance(applies, list) or set(applies)-all_keys):
            raise ValueError('共用要求的适用子项目标识无效')
        restricted = [int(n) for n in re.findall(r'(\d+)\s*(?:款|香|个子项目)', req.get('text',''))]
        if not applies and any(n < len(all_keys - {None}) for n in restricted):
            raise ValueError('部分产品适用的要求不能继承给全部子项目，请明确 applies_to_keys')
    seen, keys = set(), set()
    for item in items:
        if item.get('task_type') not in model.TYPES or not item.get('title'):
            raise ValueError('子项目标题或主类型无效')
        sid, key = item.get('id'), item.get('key')
        if not sid and key:
            match = next((x for x in old.values() if x.get('understanding_key') == key), None)
            if match:
                sid = match['id']; item['id'] = sid
        if sid:
            if sid not in old or sid in seen: raise ValueError('现有子项目身份不正确或重复')
            if old[sid]['status'] in model.TERMINAL: raise ValueError('已结束子项目不能覆盖；应新建关联子项目')
            if item['task_type'] != old[sid]['task_type']:
                started = any(t['subproject_id'] == sid and t['status'] in ('doing','waiting','done') for t in s['tasks'])
                if started or db.jload(old[sid].get('selected_codes_json'), []):
                    raise ValueError('已执行的任务类型变化应新建关联子项目，保留旧任务')
            seen.add(sid)
        elif not key or key in keys:
            raise ValueError('新子项目需要唯一稳定标识')
        keys.add(key)
        parent = item.get('parent_subproject_id')
        if sid and not parent:
            parent = old[sid].get('parent_subproject_id')
            item['parent_subproject_id'] = parent
        if parent and parent not in old: raise ValueError('关联的来源子项目不存在')
        if parent and parent == sid: raise ValueError('子项目不能关联自己作为来源')
        if item.get('category_k_code') and item['category_k_code'] not in cats: raise ValueError('品类K码无效')
        cat = cats.get(item.get('category_k_code'))
        if not item.get('_v3_materialized'):
            shared = result.get('shared_brief') or {}
            specific = item.get('brief') or {}
            materialized = model.inherit(shared, specific)
            if shared:
                materialized['customer_requirements'] = [{**r,'source_scope':'inherited'} for r in shared.get('customer_requirements',[]) if not r.get('applies_to_keys') or key in r['applies_to_keys']] + specific.get('customer_requirements',[])
                materialized['customer_requirements'] = list({(r.get('text'),r.get('category')):r for r in materialized['customer_requirements']}.values())
            item['brief'] = model.brief(materialized)
            item['_v3_materialized'] = True
        if parent and item['task_type']=='modify':
            parent_brief = next((db.jload(b['data_json'],{}) for b in s['briefs'] if b.get('subproject_id')==parent),{})
            item['brief'] = model.followup_defaults(parent_brief,item['brief'],item.get('superseded_requirement_texts',[]))
            if followup_conflict(parent_brief,item['brief']):
                raise ValueError('比例修改与气味结构或继承要求冲突，未覆盖旧结果')
        item['brief']=model.brief(item['brief'])
        customer_requirements = item['brief'].get('customer_requirements',[]) + item['brief'].get('requirement_register',[])
        if not isinstance(customer_requirements, list): raise ValueError('客户额外要求必须逐项列出')
        for req in customer_requirements:
            if not isinstance(req, dict) or not req.get('text') or req.get('status', 'recorded') != 'recorded':
                raise ValueError('客户要求应逐项标注为已记录，不可推断已满足')
            refs_valid(req.get('source_refs', []), arts)
            if not req.get('source_refs'):
                prior_requirements = [r for b in s['briefs'] if b.get('subproject_id') in (sid,parent,None) for r in db.jload(b['data_json'],{}).get('customer_requirements',[])+db.jload(b['data_json'],{}).get('requirement_register',[])]
                if not any(r.get('text') == req['text'] and r.get('source') == 'evaluator' for r in prior_requirements):
                    raise ValueError('客户额外要求缺少资料来源')
        item['price_target'] = model.number(item['brief']['commercial'].get('target_price'), '目标价')
        item['cat'] = cat
        reconcile_tag_names(item,terms,cnodes,cat)

        for level in ('a1','a2','a3','b'):
            vals = item.get(level, [])
            if not isinstance(vals, list): raise ValueError('ABC标签必须是数组')
            for tid in vals:
                t = terms.get(tid)
                if not t or (t['domain'] != 'B' if level == 'b' else t['layer'] != level.upper()):
                    raise ValueError(f'无效的 {level} 标签 {tid}')
        valid_cs = []
        for tid in item.get('target_cs', []):
            if tid not in cnodes or not cat or cnodes[tid]['new_class'] != cat['new_class']:
                item.setdefault('rejected_labels',[]).append({'id':tid,'reason':'标签不属于当前内部品类，未用于筛选或计分'})
                result.setdefault('warnings',[]).append(f"{item['title']} 的跨品类 C 标签 {tid} 未采用，请在当前品类标签中核对。")
            else:
                valid_cs.append(tid)
        item['target_cs'] = valid_cs
        if missing_mapping(item):raise ValueError('ABC语义映射未完成')
        for review in (item.get('mapping_review') or {}).values():refs_valid(review.get('source_refs',[]),arts)
        inferred = set(item.get('a1', []) + item.get('a2', []) + item.get('a3', []) + item.get('b', []) + item.get('target_cs', []))
        bases = [x for x in item.get('abc_basis') or [] if x.get('id') in inferred]
        item['abc_basis'] = bases
        a_ids=set(item.get('a1',[])+item.get('a2',[])+item.get('a3',[]))
        if inferred - {b.get('id') for b in bases if b.get('reason') and (b['id'] not in a_ids or b.get('evidence_role') in model.A_EVIDENCE_ROLES) and (not require_label_names or b.get('label')==(terms.get(b['id']) or cnodes.get(b['id']) or {}).get('label'))}:
            raise ValueError('ABC推断缺少语义依据')
        for b in bases: refs_valid(b.get('source_refs', []), arts)
        refs_valid(item.get('source_refs', []), arts)
        if not item.get('source_refs'): raise ValueError('子项目缺少资料关联')
        for req in item.get('brand_requirements', []):
            if req.get('kind') not in ('dupe', 'brand') or not req.get('value'): raise ValueError('大牌/品牌分支无效')
        for flag in ('wants_hot', 'wants_new'):
            if not isinstance(item.get(flag, False), bool): raise ValueError('爆品/新品要求必须是布尔值')
        if item['task_type'] == 'find_product' and not any(p.get('product') for p in item.get('target_products', [])):
            raise ValueError('找香任务缺具体产品名称')
        if item['task_type'] == 'create' and not (sid and any(t['subproject_id'] == sid and t['status'] in ('doing','waiting','done') for t in s['tasks'])):
            request = (item.get('create_basis') or {}).get('request_quote')
            if not isinstance(request, dict) or not (request.get('quote') or request.get('source_id')):
                raise ValueError('创香需明确委托制作的原话；仅有香气方向和初样要求应先推荐试香')
            refs_valid([request], arts)
            if not request.get('quote'):
                request['quote']=arts[request['artifact_id']]['text'][request['source_start']:request['source_end']]
        if item['task_type'] in ('recommend_simple','recommend_brand') and item.get('target_products'):
            raise ValueError('具体产品找香需求应独立拆分')
        base = item.get('base_formula_code') or ''
        parent_record = old.get(item.get('parent_subproject_id')) or {}
        known_bases = db.jload(parent_record.get('selected_codes_json'), []) + [parent_record.get('base_formula_code'), (old.get(sid) or {}).get('base_formula_code')]
        for shipment in s['tasks']:
            if shipment['subproject_id']==parent_record.get('id') and shipment['type']=='寄样' and shipment['status']=='done':
                known_bases += db.jload(shipment.get('payload_json'),{}).get('shipped_codes',[])
        if item['task_type'] == 'modify' and base and base not in known_bases and not any(base in (a.get('text') or '') for a in s['artifacts']):
            raise ValueError('改香基准编号在资料或来源子项目中没有依据')
    for a in anns: refs_valid(a.get('source_refs', []), arts)
    new_modify_parents = {x.get('parent_subproject_id') for x in items if not x.get('id') and x.get('task_type') == 'modify'}
    if any(x.get('id') in new_modify_parents for x in items if x.get('id')):
        raise ValueError('同一轮不能同时改写首轮子项目并新建关联改香；请保留首轮原始记录')
    for e in result['story'].get('timeline', []): refs_valid(e.get('source_refs', []), arts)
    if not isinstance(result.get('coverage'), list) or not result['coverage']:
        raise ValueError('缺少需求覆盖说明')
    valid_keys = keys | set(old) | {o.get('understanding_key') for o in old.values()}
    for e in result['coverage']:
        refs_valid(e.get('source_refs', []), arts)
        if set(e.get('subproject_keys', [])) - valid_keys: raise ValueError('覆盖说明指向不存在的子项目')
    required=result['brief']['deliverables'].get('required_products',[])
    if required:
        from .identity import Index
        identities=Index(con)
        for product in required:
            refs_valid(product.get('source_refs',[]),arts)
            if not product.get('product') or not product.get('source_refs'):raise ValueError('指定必选产品缺少产品名或来源')
            targets=[p for item in items+s['subprojects'] if item['task_type']=='find_product' for p in (item.get('target_products') or db.jload(item.get('target_products_json'),[]))]
            if not any(identities.product_match({'brand':p.get('brand',''),'product':p.get('product','')},product['product'],product.get('brand','')) and p.get('version','')==product.get('version','') for p in targets):
                raise ValueError('指定必选产品没有独立找香入口')
    return result


def repair_mapping(s,draft,issue):
    """Batch all omitted mappings once, using the full source context and ontology."""
    con=db.connect();ontology=business.ontology(con);con.close()
    affected=[x for x in draft['subprojects'] if missing_mapping(x)]
    payload={'ontology':ontology,'context':inference_context(s),'items':[{'key':x.get('key'),'title':x['title'],'brief':x.get('brief'),'category':x.get('cat'),'a1':x.get('a1',[]),'a2':x.get('a2',[]),'a3':x.get('a3',[]),'b':x.get('b',[]),'target_cs':x.get('target_cs',[]),'abc_basis':x.get('abc_basis',[])} for x in affected]}
    system=(db.ROOT/'spec/business_rules.md').read_text(encoding='utf-8')+'''
你只修复同一理解节点漏做的ABC语义映射；所有原文、事实、子项目类型/身份与关系不变。不是只给已有标签补reason，而是从完整业务语义和词典推断实际需要的标签，不能照抄旧空数组。
例如清新淡雅微甜女香、可以花香为主：花香主体支持相应A2/A3，A1不必强填；清新/淡雅等风格支持B；微甜按本体真实定义归域，不能假设本体存在B甜标签，保留低甜度原意；女香及用途用于对应品类C。指定TF白麝香是独立产品要求，不拿该产品名给整个组合强加麝香A1。不得凭此例固定任何标签ID。
每个key恰好输出一个update：{"updates":[{"key":"...","a1":[],"a2":[],"a3":[],"b":[],"target_cs":[],"abc_basis":[{"id":"词典真实ID","label":"该ID对应的词典原名","evidence_role":"explicit_scent_target/main_accord/reference_pyramid/context","reason":"语义理由","confidence":0.8,"source_refs":[{"source_id":"S1"}]}],"mapping_review":{"A/B/C":{"status":"insufficient_context/ontology_gap/reference_only","reason":"该域确实不能映射的具体原因","source_refs":[{"source_id":"S1"}]}}}]}。
有依据的域应给标签；真正空的域才给mapping_review，不以保守为由全部留空。B感受已从原文提取时不能声称没有信息；词表确无对应才说明ontology_gap。C只能选本品类，定位允许有来源的语义推断。ABC只给少量有依据标签，按域合并复核所有items，不分项目逐次调用。
'''
    llm.begin(s['project']['id'],'understand_project_v3_mapping_repair')
    patch=llm.chat_json([{'role':'system','content':system},{'role':'user','content':db.js(payload)}],**business.budget(s,llm.config()),temperature=0)
    draft.setdefault('_mapping_repair_outputs',[]).append(copy.deepcopy(patch))
    updates=patch.get('updates',[])
    if len(updates)!=len(affected) or {x.get('key') for x in updates}!={x.get('key') for x in affected}:raise ValueError('ABC映射复核没有覆盖全部待修复子项目')
    by_key={x.get('key'):x for x in affected}
    for update in updates:
        for field in ('a1','a2','a3','b','target_cs','abc_basis','mapping_review'):
            by_key[update['key']][field]=update.get(field,{} if field=='mapping_review' else [])
        item=by_key[update['key']]
        for field in ('a1','a2','a3'):
            invalid={b['id'] for b in item.get('abc_basis',[]) if b.get('id') in item.get(field,[]) and b.get('evidence_role') not in model.A_EVIDENCE_ROLES}
            item[field]=[tid for tid in item.get(field,[]) if tid not in invalid]
            for tid in invalid:item.setdefault('rejected_labels',[]).append({'id':tid,'reason':'复核只有语境/感受支持，没有主体气味依据，不提升为A；客户原始感受仍保留。'})
    return draft


def repair_abc(s, draft, issue):
    """Complete only missing evidence inside the same understanding run; do not rewrite facts."""
    con = db.connect()
    terms = {x['id']:x for x in db.rows(con,'select id,domain,layer,label,definition from terms')}
    nodes = {x['id']:x for x in db.rows(con,'select * from c_nodes')}
    con.close()
    missing = []
    for item in draft['subprojects']:
        a_ids=set(item.get('a1',[])+item.get('a2',[])+item.get('a3',[]))
        explained = {x.get('id') for x in item.get('abc_basis',[]) if x.get('reason') and x.get('label')==(terms.get(x.get('id')) or nodes.get(x.get('id')) or {}).get('label') and (x['id'] not in a_ids or x.get('evidence_role') in model.A_EVIDENCE_ROLES)}
        for field in ('a1','a2','a3','b','target_cs'):
            for tid in item.get(field,[]):
                if tid not in explained:
                    missing.append({'key':item.get('key'),'id':tid,'field':field,'tag':terms.get(tid) or nodes.get(tid)})
    if not missing: return draft
    payload = {'project':s['project'], 'artifacts':inference_context(s)['artifacts'],
               'subproject_contexts':[{'key':x.get('key'),'title':x['title'],'direction':x.get('direction'),
                                      'brief':x.get('brief'),'category':x.get('cat')} for x in draft['subprojects']],
               'missing_evidence':missing, 'validation_error':issue}
    system = '''你在修复同一个全景理解节点的标签依据完整性。原有客户事实、子项目和任务关系都不能改。
逐条处理missing_evidence，每个(key,id)必须恰好输出一条。A、B、C完全同样处理，C也必须给reason，不能遗漏。
C是商业定位/场景/体验分类，请结合产品用途、定位、人群、风格与意图理解；不是字面摘词。tag字段已给出这个标签的完整路径和定义。
只返回JSON：{"evidence":[{"key":"输入的key","id":"输入的id","reason":"针对该标签的简短语义理由","confidence":0.8,"source_refs":[{"artifact_id":"真实资料id","locator":"页段","quote":"短的逐字原文子串，不要拼接不相邻段落"}],"keep":true}]}。
有充分语境支持时keep=true并给理由及来源；确实不合适或跨品类时keep=false并解释，不得给空reason。必须覆盖所有missing_evidence，只处理这些标签，不输出其它字段。'''
    llm.begin(s['project']['id'],'understand_project_v3_contract_repair')
    system=(db.ROOT/'spec/business_rules.md').read_text(encoding='utf-8')+'\n'+system+'\nA类keep=true必须附evidence_role=explicit_scent_target或main_accord。仅来自三调/候选香材/AI建议的A应keep=false，不得因为词面出现就称为主韵。B/C可用reference_pyramid或context。'
    patch = llm.chat_json([{'role':'system','content':system},{'role':'user','content':db.js(payload)}],max_tokens=32000,timeout=420,temperature=0)
    draft.setdefault('_contract_repair_outputs',[]).append(copy.deepcopy(patch))
    answers = {(x.get('key'),x.get('id')):x for x in patch.get('evidence',[])}
    requested = {(x['key'],x['id']) for x in missing}
    if set(answers) != requested: raise ValueError('标签依据修复未逐条覆盖请求')
    by_key = {x.get('key'):x for x in draft['subprojects']}
    for request in missing:
        answer = answers[(request['key'],request['id'])]
        item = by_key[request['key']]
        item['abc_basis']=[b for b in item.get('abc_basis',[]) if b.get('id')!=request['id']]
        if answer.get('keep') is False:
            item[request['field']] = [x for x in item[request['field']] if x != request['id']]
            item.setdefault('rejected_labels',[]).append({'id':request['id'],'reason':answer.get('reason','依据不足')})
        else:
            if not answer.get('reason') or not answer.get('source_refs'): raise ValueError('标签依据修复仍缺理由/来源')
            answer.setdefault('label',request['tag']['label'])
            item.setdefault('abc_basis',[]).append({k:v for k,v in answer.items() if k in ('id','label','path','reason','confidence','source_refs','evidence_role')})
    draft.setdefault('warnings',[]).append('标签依据经过一次完整性修复，客户事实、任务类型和关联未在修复中改动。')
    return draft


def repair_followup(s, draft, issue):
    """One bounded semantic repair; only conflicting scent fields can change."""
    affected = []
    for item in draft['subprojects']:
        if not item.get('parent_subproject_id'): continue
        parent = next((db.jload(b['data_json'],{}) for b in s['briefs'] if b.get('subproject_id')==item.get('parent_subproject_id')),{})
        if item.get('task_type')=='modify' and followup_conflict(parent,item['brief']):
            affected.append({'key':item['key'],'title':item['title'],'parent_scent':parent.get('scent'),'current_brief':item['brief'],'source_refs':item.get('source_refs',[])})
    if not affected: raise ValueError(issue)
    llm.begin(s['project']['id'],'understand_project_v3_coherence_repair')
    instruction = ('修复跨轮气味结构与有效要求之间的矛盾。只修改指定key的scent字段与有效scent要求，不能改产品、项目、ABC、任务或基准号。'
        '按资料日期、局部具体反馈优先于旧通用规则；最新各半等意象配比不能再机械追加旧空气感百分比。'
        'structure表达最新感官意象，不等于实际配方成分比例。若意象两者各半，空气感仅定性描述；不要写50%+50%再加旧5-10%等矛盾结构。'
        '旧通用百分比与新局部配比冲突时从有效要求中移除，旧记录已保留在父项历史。'
        '共同的水果第一等原则若与新的平衡主次冲突也要改清楚。保留未冲突的要求。'
        '只用有来源的数字，不编配方；所有新增要求必须带逐字source_refs。'
        '返回JSON {"updates":[{"key":"原key","scent":{使用现有scent字段键},"scent_requirements":[完整有效的scent类要求，含text/category=scent/source_scope/source_refs/status=recorded],"reason":"新旧覆盖依据"}]}。')
    sources = [{'id':a['id'],'filename':a['filename'],'text':a.get('text','')} for a in s['artifacts']]
    patch = llm.chat_json([{'role':'system','content':instruction},{'role':'user','content':db.js({'issue':issue,'items':affected,'sources':sources})}],max_tokens=12000,timeout=240,temperature=0.1)
    draft.setdefault('_contract_repair_outputs',[]).append(copy.deepcopy(patch))
    updates = {u.get('key'):u for u in patch.get('updates',[])}
    if set(updates)!={i['key'] for i in affected}: raise ValueError('跨轮修复未逐项覆盖')
    for item in draft['subprojects']:
        if item.get('key') not in updates: continue
        u=updates[item['key']]
        if not u.get('reason') or not isinstance(u.get('scent'),dict) or not isinstance(u.get('scent_requirements'),list): raise ValueError('跨轮修复契约不完整')
        if 'old_formula' in u['scent']:
            if u['scent']['old_formula']!=item['brief']['scent'].get('old_formula',''): raise ValueError('跨轮修复不能改变基准号')
            u['scent'].pop('old_formula')
        if set(u['scent'])-set(model.GROUPS['scent']): raise ValueError('跨轮修复包含未知字段：'+','.join(set(u['scent'])-set(model.GROUPS['scent'])))
        unchanged_non_scent = {(r.get('category'),r.get('text')) for r in item['brief'].get('customer_requirements',[])+item['brief'].get('requirement_register',[]) if r.get('category')!='scent'}
        if any((r.get('category'),r.get('text')) not in unchanged_non_scent for r in u['scent_requirements'] if r.get('category')!='scent'): raise ValueError('跨轮修复不能改变非气味要求')
        u['scent_requirements']=[r for r in u['scent_requirements'] if r.get('category')=='scent']
        before=copy.deepcopy(item['brief'])
        prior_texts={r.get('text') for r in before.get('customer_requirements',[])+before.get('requirement_register',[])}
        for req in u['scent_requirements']:
            if req.get('text') not in prior_texts: req['source_scope']='specific'
        item['brief']['scent']=model.merge(item['brief']['scent'],u['scent'])
        item['brief']['customer_requirements']=[r for r in before.get('customer_requirements',[]) if r.get('category')!='scent']
        item['brief']['requirement_register']=[r for r in before.get('requirement_register',[]) if r.get('category')!='scent']+u['scent_requirements']
        changed_refs=[ref for r in u['scent_requirements'] if r.get('source_scope')=='specific' for ref in r.get('source_refs',[])] or item.get('source_refs',[])
        for field in u['scent']: item['brief'].setdefault('evidence',{})['scent.'+field]=copy.deepcopy(changed_refs)
        item.setdefault('contract_resolutions',[]).append({'issue':issue,'reason':u['reason'],'prior_scent':before['scent'],'prior_requirements':before.get('customer_requirements',[])})
    draft.setdefault('warnings',[]).append('跨轮气味结构与有效要求已做一致性校验；旧配比保留在父项及修复审计中。')
    return draft


def apply(con, s, result, rid):
    pid = s['project']['id']
    prior = next((db.jload(b['data_json'], {}) for b in s['briefs'] if not b.get('subproject_id')), {})
    result['brief'] = model.preserve_manual(prior, result['brief'])
    bid = db.save_brief(con, pid, result['brief'])
    pb = result['brief']
    project = pb['project']
    con.execute('update projects set customer_info_json=?,coordination_json=? where id=?',
                (db.js({'customer':project.get('customer') or s['project']['customer'], 'brand':project.get('brand') or s['project']['brand'],
                        'profile':project.get('customer_profile',''), 'contacts':project.get('contacts',[])}),
                 db.js({'overall_deadline':project.get('overall_deadline') or pb['deliverables'].get('deadline',''),
                        'sample_due':pb['commercial'].get('sample_due',''), 'recipient':pb['deliverables'].get('recipient',''),
                        'sales':project.get('sales') or s['project']['sales'], 'evaluator':project.get('evaluator') or s['project']['evaluator'],
                        'notes':project.get('coordination_notes',''), 'events':project.get('coordination_events',[])}), pid))
    story = dict(result['story'], coverage=result['coverage'], ontology_gaps=result.get('ontology_gaps', []), warnings=result.get('warnings', []), source_manifest=[{'id':a['id'],'filename':a['filename']} for a in s['artifacts']])
    con.execute('delete from stories where project_id=?', (pid,))
    con.execute('insert into stories values(?,?,?,?,?)', (db.uid('story_'), pid, db.js(story), db.js(story), db.now()))
    for a in result['artifact_annotations']:
        con.execute('update artifacts set annotation_json=?,updated_at=? where id=?', (db.js(a), db.now(), a['artifact_id']))
    created, updated = [], []
    for item in result['subprojects']:
        old = db.one(con, 'select * from subprojects where id=? and project_id=?', (item.get('id') or '', pid))
        if not old and item.get('key'):
            old = db.one(con, 'select * from subprojects where project_id=? and understanding_key=?', (pid, item['key']))
        if old and old['status'] in model.TERMINAL: raise ValueError('已结束子项目应使用新的需求标识')
        sid = old['id'] if old else db.uid('s_')
        cat = item.get('cat') or {}
        bd = item['brief']
        manual_keys = set()
        if old:
            prior = next((db.jload(b['data_json'], {}) for b in s['briefs'] if b.get('subproject_id') == sid), {})
            bd = model.preserve_manual(prior, bd)
        bd['project']=model.project_context(s['project'],project)
        bd['manual_overrides']={k:v for k,v in bd.get('manual_overrides',{}).items() if not k.startswith('project.')}
        bd['product'].update(category_l1=cat.get('level1',''), category_l2=cat.get('level2',''), category_l3=cat.get('level3',bd['product'].get('category_l3','')), new_class=cat.get('new_class',''))
        vals = dict(project_id=pid, title=item['title'], task_type=item['task_type'], category_l1=cat.get('level1',''), category_l2=cat.get('level2',''), category_l3=bd['product']['category_l3'],
                    norm_class=cat.get('norm_class',''), new_class=cat.get('new_class',''), target_c=(item.get('target_cs') or [''])[0],
                    target_cs_json=db.js(item.get('target_cs',[])), a1_json=db.js(item.get('a1',[])), a2_json=db.js(item.get('a2',[])), a3_json=db.js(item.get('a3',[])), b_json=db.js(item.get('b',[])),
                    brand_requirements_json=db.js(item.get('brand_requirements',[])), wants_hot=int(item.get('wants_hot',False)), wants_new=int(item.get('wants_new',False)),
                    target_products_json=db.js(item.get('target_products',[])), base_formula_code=item.get('base_formula_code',''), price_target=item['price_target'],
                    direction=item.get('direction',''), source_refs_json=db.js(item.get('source_refs',[])), abc_basis_json=db.js({'labels':item.get('abc_basis',[]),'type_basis':item.get('type_basis',{}),'rejected_labels':item.get('rejected_labels',[]),'mapping_review':item.get('mapping_review',{}),'label_identity_corrections':item.get('label_identity_corrections',[])}),
                    planning_json=db.js(bd.get('planning',{})), base_sample_reference=item.get('base_sample_reference',''),
                    understanding_key=item.get('key') or (old or {}).get('understanding_key'), context_json=db.js({'run_id':rid}), updated_at=db.now())
        if old:
            if old.get('base_formula_code') and not vals.get('base_formula_code'):
                vals['base_formula_code']=old['base_formula_code']
            vals['context_json']=db.js({**db.jload(old.get('context_json'),{}),'run_id':rid})
            for decision in s['decisions']:
                if decision['entity_id'] == sid and decision['actor'] == 'evaluator' and decision['field'] == 'fields':
                    manual_keys.update(db.jload(decision['new_value'], {}).keys())
            for key in manual_keys - {'updated_at'}:
                if key in vals: vals[key] = old.get(key)
            if old['task_type'] != vals['task_type']:
                history = db.jload(old.get('type_history_json'), [])
                vals['type_history_json'] = db.js(history + [{'from':old['task_type'],'to':vals['task_type'],'reason':'尚未执行，按全景理解修正','run_id':rid,'at':db.now()}])
                con.execute("update department_tasks set status='cancelled',result='需求类型修正，未执行工单归档',updated_at=? where subproject_id=? and status='todo'", (db.now(), sid))
        vals['customer_requirements_json'] = db.js(bd.get('customer_requirements', []))
        if not old:
            vals.update(id=sid, status='briefed', price_elasticity=20, created_at=db.now(), parent_subproject_id=item.get('parent_subproject_id') or None)
            con.execute(f"insert into subprojects({','.join(vals)}) values({','.join('?' for _ in vals)})", tuple(vals.values()))
            created.append(sid)
        else:
            # Once a downstream task has been dispatched, its payload and selected formulas are historical.
            con.execute(f"update subprojects set {','.join(k+'=?' for k in vals)} where id=?", (*vals.values(), sid))
            updated.append(sid)
        sp = db.one(con, 'select * from subprojects where id=?', (sid,))
        if not old or old.get('hard_filters_json') is None or ('hard_filters_json' not in manual_keys and db.jload(old.get('hard_filters_json'),{})==reco.default_filters(old)):
            con.execute('update subprojects set hard_filters_json=? where id=?', (db.js(reco.default_filters(sp)), sid))
        bd['product'].update(category_l1=sp['category_l1'],category_l2=sp['category_l2'],category_l3=sp['category_l3'],new_class=sp['new_class'])
        bd['commercial']['target_price'] = sp['price_target']
        bd['scent']['old_formula'] = sp.get('base_formula_code') or ''
        bd['handoff'] = model.handoff(s['project'], sp, bd)
        sbid = db.save_brief(con, pid, bd, sid)
        con.execute('update subprojects set brief_id=? where id=?', (sbid, sid))
        db.audit(con, 'subproject', sid, 'understanding', old, vals, actor='llm', reason=rid)
        sp = db.one(con, 'select * from subprojects where id=?', (sid,))
        if sp['task_type'] in model.TYPES:
            service.recommendations(con, sp)
        workflow.start(con, sp)
    con.execute("update projects set status='active',updated_at=? where id=?", (db.now(), pid))
    return dict(created=created, updated=updated, brief_id=bid)


def run(rid):
    result = None
    con = db.connect()
    r = db.one(con, 'select * from generation_runs where id=?', (rid,))
    con.execute("update generation_runs set status='running',stage='正在全景理解所有资料与项目进展',updated_at=? where id=?", (db.now(), rid)); con.commit()
    s = db.jload(r['input_json'], {})
    ontology = business.ontology(con)
    con.close()
    try:
        contract = model.brief()
        contract['planning'] = dict(launch_tier='',development_target='',commercialization_target='',launch_timing='',priority_reason='')
        payload = json.dumps({'ontology':ontology,'canonical_brief_contract':contract,'context':inference_context(s)},ensure_ascii=False,separators=(',',':'))
        if len(payload) > MAX_CONTEXT_CHARS:
            raise ValueError('项目全文超过单次理解容量；本次未截断或覆盖现有结果，请分项目整理资料')
        llm.begin(r['project_id'], 'understand_project_v3')
        system = (db.ROOT/'spec/business_rules.md').read_text(encoding='utf-8')+'\n'+(db.ROOT/'prompts/understand_project.md').read_text(encoding='utf-8')
        budget=business.budget(s,llm.config())
        result = llm.chat_json([{'role':'system','content':system}, {'role':'user','content':payload}], **budget, temperature=0.1)
        con = db.connect()
        try:
            result = validate(con, s, result,require_label_names=True)
        except ValueError as issue:
            if str(issue) not in ('ABC语义映射未完成','ABC推断缺少语义依据','比例修改与气味结构或继承要求冲突，未覆盖旧结果'): raise
            con.close()
            progress = db.connect()
            progress.execute("update generation_runs set stage=?,updated_at=? where id=?",('正在复核遗漏的ABC语义映射' if str(issue)=='ABC语义映射未完成' else '正在校验ABC依据完整性' if str(issue)=='ABC推断缺少语义依据' else '正在校验跨轮气味结构与有效要求',db.now(),rid))
            progress.commit(); progress.close()
            result = repair_mapping(s,result,str(issue)) if str(issue)=='ABC语义映射未完成' else repair_abc(s,result,str(issue)) if str(issue)=='ABC推断缺少语义依据' else repair_followup(s,result,str(issue))
            con = db.connect()
            result = validate(con,s,result,require_label_names=True)
        con.execute('BEGIN IMMEDIATE')
        current = snapshot(con, r['project_id'])
        if input_hash(current) != r['fingerprint']:
            raise ValueError('生成期间资料或人工内容发生变化；未覆盖已有内容，请再次生成')
        change = apply(con, s, result, rid)
        change['result'] = result
        change['business_policy'] = model.BUSINESS_POLICY
        change['applied_fingerprint'] = input_hash(snapshot(con, r['project_id']))
        con.execute("update generation_runs set status='succeeded',stage='理解完成',output_json=?,error='',updated_at=? where id=?", (db.js(change), db.now(), rid))
        con.commit()
    except Exception as e:
        if con:
            try: con.rollback(); con.close()
            except Exception: pass
        con = db.connect()
        diagnostic={'diagnostics':e.details} if isinstance(e,llm.ModelOutputLimit) else ({'rejected_output':result} if result is not None else None)
        con.execute("update generation_runs set status='failed',stage='未更新项目',error=?,output_json=?,updated_at=? where id=?", (str(e), db.js(diagnostic) if diagnostic is not None else None, db.now(), rid)); con.commit()
    finally:
        if con: con.close()
