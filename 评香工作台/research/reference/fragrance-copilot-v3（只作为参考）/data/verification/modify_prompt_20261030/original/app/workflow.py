"""Department work is created by an actual decision or completed predecessor."""
from __future__ import annotations
from . import db, model

STATUS = {'todo', 'doing', 'waiting', 'done', 'cancelled'}


def inherit_base(con, sp):
    if sp['task_type'] != 'modify' or not sp.get('parent_subproject_id'):
        return sp
    previous = db.jload(sp.get('context_json'),{}).get('inherited_base') or {}
    if sp.get('base_formula_code'):
        if previous.get('source')!='parent_selection': return sp
        if db.one(con,"select id from department_tasks where subproject_id=? and status in ('doing','done')",(sp['id'],)): return sp
    parent = db.one(con,'select * from subprojects where id=?',(sp['parent_subproject_id'],))
    if not parent: return sp
    shipment = db.one(con,"select * from department_tasks where subproject_id=? and type='寄样' and status='done' order by rowid desc limit 1",(parent['id'],))
    if sp.get('base_formula_code') and not shipment: return sp
    payload = db.jload((shipment or {}).get('payload_json'),{})
    codes = payload.get('shipped_codes') or []
    source = 'shipment'
    if not codes and parent['task_type'] in ('recommend_brand','recommend_simple','find_product','match_sample'):
        codes = payload.get('selected_codes') or db.jload(parent.get('selected_codes_json'),[])
        source = 'shipment' if shipment else 'parent_selection'
    codes = list(dict.fromkeys(codes))
    ref = {'subproject_id':parent['id'],'sample_label':parent['title'],
           'shipment_task_id':(shipment or {}).get('id'),'codes':codes,'source':source,
           'status':'resolved' if len(codes)==1 else 'awaiting_source_sync'}
    ctx = db.jload(sp.get('context_json'),{});ctx['inherited_base']=ref
    if sp.get('base_sample_reference') and sp['base_sample_reference']!=parent['title']:
        ctx.setdefault('original_sample_label',sp['base_sample_reference'])
    con.execute('update subprojects set context_json=?,base_sample_reference=? where id=?',(db.js(ctx),parent['title'],sp['id']))
    if len(codes)==1:
        con.execute('update subprojects set base_formula_code=?,updated_at=? where id=?',(codes[0],db.now(),sp['id']))
        db.audit(con,'subproject',sp['id'],'inherited_base',None,ref,actor='system',reason='承袭前轮实际寄样/已选定香精')
        fresh=db.one(con,'select * from subprojects where id=?',(sp['id'],))
        row=db.one(con,'select data_json from briefs where subproject_id=? order by version desc limit 1',(sp['id'],))
        if row:
            bd=model.brief(db.jload(row['data_json'],{}));bd['scent']['old_formula']=codes[0]
            project=db.one(con,'select * from projects where id=?',(sp['project_id'],)) or {}
            bd['handoff']=model.handoff(project,fresh,bd);db.save_brief(con,sp['project_id'],bd,sp['id'],actor='inherited')
        for task in db.rows(con,"select * from department_tasks where subproject_id=? and status in ('todo','waiting')",(sp['id'],)):
            p=db.jload(task.get('payload_json'),{});p.update(context(con,fresh))
            was_pending=p.pop('base_pending',False)
            con.execute('update department_tasks set payload_json=?,status=?,result=?,updated_at=? where id=?',
                        (db.js(p),'todo' if was_pending else task['status'],'' if was_pending else task['result'],db.now(),task['id']))
        return fresh
    return db.one(con,'select * from subprojects where id=?',(sp['id'],))


def refresh_followups(con, sid):
    for child in db.rows(con,"select * from subprojects where parent_subproject_id=? and task_type='modify'",(sid,)):
        if child['status'] not in model.TERMINAL: start(con,child)


def context(con, sp):
    row = db.one(con, 'select data_json from briefs where subproject_id=? order by version desc limit 1', (sp['id'],))
    bd = model.brief(db.jload(row['data_json'], {}) if row else {})
    project = db.one(con,'select * from projects where id=?',(sp['project_id'],)) or {}
    root=db.one(con,"select data_json from briefs where project_id=? and coalesce(subproject_id,'')='' order by version desc limit 1",(sp['project_id'],))
    project_delivery=model.brief(db.jload((root or {}).get('data_json'),{}))['deliverables']
    total_text='；'.join(str(project_delivery[k]) for k in ('type','quantity','deadline','recipient','notes') if project_delivery.get(k))
    handoff=bd.get('handoff','')
    if total_text:handoff+='\n项目总体交付（总量非本项独立数量，按适用范围执行）：'+total_text
    return {'title': sp['title'], 'task_type': sp['task_type'], 'target_products': db.jload(sp.get('target_products_json'), []),
            'project_customer':db.jload(project.get('customer_info_json'),{}),
            'project_coordination':db.jload(project.get('coordination_json'),{}),
            'project_delivery':project_delivery,
            'category': sp.get('category_l3'), 'norm_class': sp.get('norm_class'), 'substrate': bd['product'].get('substrate'),
            'dosage': bd['product'].get('dosage'), 'selected_codes': db.jload(sp.get('selected_codes_json'), []),
            'base_formula_code': sp.get('base_formula_code'), 'requirements': bd,
            'base_sample_reference': sp.get('base_sample_reference'), 'planning': bd.get('planning', {}),
            'base_reference':db.jload(sp.get('context_json'),{}).get('inherited_base'),
            'customer_requirements': bd.get('customer_requirements') or [],
            'source_refs': db.jload(sp.get('source_refs_json'), []), 'parent_subproject_id': sp.get('parent_subproject_id'),
            'handoff': handoff}


def ensure(con, sp, kind, deps=None, suffix=''):
    title = kind + suffix
    existing = db.one(con, "select * from department_tasks where subproject_id=? and title=? and status!='cancelled'", (sp['id'], title))
    if existing:
        payload = db.jload(existing.get('payload_json'),{})
        if existing['status']=='todo' or (existing['status']=='waiting' and payload.get('base_pending')):
            payload.update(context(con,sp))
            con.execute('update department_tasks set payload_json=?,detail=?,updated_at=? where id=?',
                        (db.js(payload),payload.get('handoff',''),db.now(),existing['id']))
        return existing['id']
    tid = db.uid('t_')
    payload = context(con, sp)
    reports = db.rows(con, '''select f.id,f.filename,f.task_id from task_files f join department_tasks t on t.id=f.task_id
                             where t.subproject_id=?''', (sp['id'],))
    payload['analysis_files'] = reports
    con.execute('''insert into department_tasks(id,subproject_id,type,title,detail,status,depends_on_json,payload_json,created_at,updated_at)
                   values(?,?,?,?,?,'todo',?,?,?,?)''',
                (tid, sp['id'], kind, title, payload['handoff'], db.js(deps or []), db.js(payload), db.now(), db.now()))
    return tid


def start(con, sp):
    if sp['status'] in model.TERMINAL:
        return
    task = sp['task_type']
    if task == 'modify': sp = inherit_base(con,sp)
    if task in ('modify', 'create'):
        # Missing base is an actionable missing field, not a dispatchable work order.
        if task == 'modify' and not sp.get('base_formula_code'):
            if sp.get('parent_subproject_id'):
                tid=ensure(con,sp,'调香')
                t=db.one(con,'select * from department_tasks where id=?',(tid,))
                if t['status']=='todo':
                    p=db.jload(t.get('payload_json'),{});p['base_pending']=True
                    con.execute("update department_tasks set status='waiting',payload_json=?,result=? where id=?",(db.js(p),'承袭首轮原样，等待寄样编号同步',tid))
                con.execute("update subprojects set status='tasks',workflow_stage='awaiting_source_sync',updated_at=? where id=?",(db.now(),sp['id']))
                return
            ensure(con, sp, '确认改香基准')
            return
        confirmation = db.one(con, "select * from department_tasks where subproject_id=? and type='确认改香基准' and status!='cancelled'", (sp['id'],)) if task == 'modify' else None
        if confirmation and confirmation['status'] != 'done':
            con.execute("update department_tasks set status='done',result=?,updated_at=? where id=?", ('已补充明确基准：'+sp['base_formula_code'],db.now(),confirmation['id']))
            db.audit(con,'task',confirmation['id'],'status',confirmation['status'],'done',reason='评香补充明确改香基准')
        tid=ensure(con, sp, '调香', [confirmation['id']] if confirmation else [])
        if sp.get('workflow_stage') in (None,'','draft','awaiting_source_sync','awaiting_base'):
            con.execute("update subprojects set status='tasks',workflow_stage='perfumery',updated_at=? where id=?",(db.now(),sp['id']))
    elif task == 'match_sample':
        ensure(con, sp, '评香对香')
    elif db.one(con, 'select id from recommendations where subproject_id=?', (sp['id'],)):
        ensure(con, sp, '评香选香')


def choose(con, sp, codes):
    codes = list(dict.fromkeys(str(x).strip() for x in codes if str(x).strip()))
    if not codes:
        raise ValueError('至少选择一个内部编号')
    for code in codes:
        if not db.one(con, 'select code from library_items where code=?', (code,)):
            raise ValueError(f'库中没有内部编号 {code}')
    if sp['task_type'] in ('create', 'modify'):
        con.execute('update subprojects set selected_codes_json=?,updated_at=? where id=?', (db.js(codes), db.now(), sp['id']))
        db.audit(con, 'subproject', sp['id'], 'reference_codes', db.jload(sp.get('selected_codes_json'), []), codes)
        fresh = db.one(con, 'select * from subprojects where id=?', (sp['id'],))
        for t in db.rows(con, "select * from department_tasks where subproject_id=? and status='todo'", (sp['id'],)):
            p = db.jload(t.get('payload_json'), {}); p.update(context(con, fresh))
            con.execute('update department_tasks set payload_json=? where id=?', (db.js(p), t['id']))
        return
    if sp['task_type'] == 'match_sample' and not db.one(con, 'select id from external_samples where subproject_id=?', (sp['id'],)):
        raise ValueError('先登记收到的外部样品')
    # Once actual downstream work exists, a new selection belongs to a new linked subproject.
    active = db.rows(con, "select * from department_tasks where subproject_id=? and type in ('打样','寄样') and status!='cancelled'", (sp['id'],))
    old = db.jload(sp.get('selected_codes_json'), [])
    if active and old != codes:
        raise ValueError('已派发打样任务；如需换样，请新建关联子项目保留历史')
    con.execute("update subprojects set selected_codes_json=?,workflow_stage='sampling',status='tasks',updated_at=? where id=?", (db.js(codes), db.now(), sp['id']))
    db.audit(con, 'subproject', sp['id'], 'selected_codes', old, codes)
    sp = db.one(con, 'select * from subprojects where id=?', (sp['id'],))
    predecessor = ensure(con, sp, '评香对香' if sp['task_type'] == 'match_sample' else '评香选香')
    con.execute("update department_tasks set status='done',result=?,updated_at=? where id=?", ('选择内部编号：' + '、'.join(codes), db.now(), predecessor))
    if sp['task_type'] == 'match_sample':
        con.execute("update external_samples set result='can_recommend',matched_formula_ids_json=? where subproject_id=?", (db.js(codes), sp['id']))
    ensure(con, sp, '打样', [predecessor])
    refresh_followups(con,sp['id'])


def request_analysis(con, sp):
    if sp['task_type'] not in ('find_product', 'match_sample'):
        raise ValueError('此子项目无需走找香/对香分析分支')
    if sp['task_type'] == 'find_product' and not db.jload(sp.get('target_products_json'), []):
        raise ValueError('先填写目标产品名称')
    if sp['task_type'] == 'match_sample' and not db.one(con, 'select id from external_samples where subproject_id=?', (sp['id'],)):
        raise ValueError('先登记收到的外部样品')
    if db.jload(sp.get('selected_codes_json'), []):
        raise ValueError('此子项目已选择库内香精；另建关联子项目执行分析')
    con.execute("update department_tasks set status='done',result='评香转交GC分析',updated_at=? where subproject_id=? and type in ('评香选香','评香对香') and status!='cancelled'", (db.now(), sp['id']))
    ensure(con, sp, '分析')
    con.execute("update subprojects set status='tasks',workflow_stage='analysis',updated_at=? where id=?", (db.now(), sp['id']))
    con.execute("update external_samples set analysis_status='requested' where subproject_id=?", (sp['id'],))


def update(con, tid, data):
    t = db.one(con, 'select * from department_tasks where id=?', (tid,))
    if not t:
        raise KeyError('任务不存在')
    if t['type'] == '入库':
        raise ValueError('本版仅展示待入库，入库操作已禁用')
    status = data.get('status', t['status'])
    if status not in STATUS:
        raise ValueError('任务状态无效')
    deps = db.jload(t.get('depends_on_json'), [])
    if status in ('doing', 'done'):
        for dep in deps:
            r = db.one(con, 'select status from department_tasks where id=?', (dep,))
            if not r or r['status'] != 'done':
                raise ValueError('前置任务尚未完成')
    if t['status'] == 'done' and status != 'done':
        raise ValueError('已完成任务保留历史；请创建后续任务')
    sp = db.one(con, 'select * from subprojects where id=?', (t['subproject_id'],))
    if sp['task_type']=='modify': sp=inherit_base(con,sp)
    if status == 'done':
        if t['type'] in ('评香选香', '评香对香'):
            raise ValueError('请用“选定香精并派发打样”或“提交分析”记录评香决定')
        if t['type'] == '确认改香基准' and not sp.get('base_formula_code'):
            raise ValueError('先在执行条件补充被修改的内部号或明确样品版本号')
        if t['type'] == '分析' and data.get('confirmed') is not True:
            raise ValueError('请手动确认 GC 分析已完成')
        if not str(data.get('result', t.get('result') or '')).strip():
            raise ValueError('完成任务时请填写结果或交付说明')
    if t['type']=='调香' and sp['task_type']=='modify' and status in ('doing','done') and not sp.get('base_formula_code'):
        raise ValueError('正在承袭首轮原样，待实际寄样编号同步后执行')
    if t['type']=='寄样' and 'shipped_codes' in data:
        if not isinstance(data['shipped_codes'],list) or any(not isinstance(x,str) or not x.strip() for x in data['shipped_codes']):
            raise ValueError('实际寄样编号应为非空文本数组')
        p=db.jload(t.get('payload_json'),{});p['shipped_codes']=data['shipped_codes']
        con.execute('update department_tasks set payload_json=? where id=?',(db.js(p),tid))
        db.audit(con,'task',tid,'shipped_codes',db.jload(t.get('payload_json'),{}).get('shipped_codes'),data['shipped_codes'],reason='记录实际寄出香精号')
    for k in ('status', 'owner', 'department', 'due', 'detail', 'result'):
        if k in data:
            con.execute(f'update department_tasks set {k}=?,updated_at=? where id=?', (data[k], db.now(), tid))
    db.audit(con, 'task', tid, 'status', t['status'], status)
    if status == 'done' and t['status'] != 'done':
        if t['type'] == '确认改香基准':
            ensure(con, sp, '调香', [tid]); stage = 'perfumery'
        elif t['type'] == '分析':
            ensure(con, sp, '调香', [tid])
            con.execute("update external_samples set analysis_status='done',analysis_result=? where subproject_id=?", (data.get('result', ''), sp['id']))
            stage = 'perfumery'
        elif t['type'] == '调香':
            ensure(con, sp, '评香验收', [tid]); stage = 'evaluation'
        elif t['type'] == '评香验收':
            ensure(con, sp, '打样', [tid]); stage = 'sampling'
        elif t['type'] == '打样':
            ensure(con, sp, '寄样', [tid]); stage = 'shipping'
        elif t['type'] == '寄样':
            ensure(con, sp, '法规', [tid]); ensure(con, sp, '质量', [tid]); stage = 'feedback'
        elif t['type'] in ('法规', '质量'):
            ready = all(db.one(con, "select id from department_tasks where subproject_id=? and type=? and status='done'", (sp['id'], kind)) for kind in ('法规', '质量'))
            stage = 'final_ready' if ready else 'verification'
            if ready and (sp['task_type'] in ('modify', 'create') or db.one(con, "select id from department_tasks where subproject_id=? and type='调香'", (sp['id'],))):
                ensure(con, sp, '入库', [r['id'] for r in db.rows(con, "select id from department_tasks where subproject_id=? and type in ('法规','质量') and status='done'", (sp['id'],))])
        else:
            stage = sp.get('workflow_stage') or 'tasks'
        con.execute('update subprojects set workflow_stage=?,updated_at=? where id=?', (stage, db.now(), sp['id']))
        if t['type']=='寄样': refresh_followups(con,sp['id'])
    elif t['type']=='寄样' and status=='done' and 'shipped_codes' in data:
        refresh_followups(con,sp['id'])
