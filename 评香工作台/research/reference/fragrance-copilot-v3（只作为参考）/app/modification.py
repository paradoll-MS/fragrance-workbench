"""Modification workbench: verified base, explicit change request, draft and issue."""
from . import db,model


def brief(con,sp):
    row=db.one(con,'select data_json from briefs where subproject_id=? order by version desc limit 1',(sp['id'],))
    return model.brief(db.jload((row or {}).get('data_json'),{}))


def issued(task):
    p=db.jload(task.get('payload_json'),{})
    return p.get('dispatch_state')=='issued' or task['status'] in ('doing','done') or (task['status']=='waiting' and not p.get('base_pending') and not p.get('modification_draft'))


def base_options(con,sp):
    parent=db.one(con,'select * from subprojects where id=?',(sp.get('parent_subproject_id'),)) if sp.get('parent_subproject_id') else None
    if not parent:return []
    shipment=db.one(con,"select * from department_tasks where subproject_id=? and type='寄样' and status='done' order by rowid desc limit 1",(parent['id'],))
    payload=db.jload((shipment or {}).get('payload_json'),{});codes=payload.get('shipped_codes') or []
    source='shipment'
    if not codes and parent['task_type'] in ('recommend_brand','recommend_simple','find_product','match_sample'):
        codes=payload.get('selected_codes') or db.jload(parent.get('selected_codes_json'),[]);source='shipment' if shipment else 'parent_selection'
    return [{'code':code,'name':(db.one(con,'select name from library_items where code=?',(code,)) or {}).get('name','已确认实发试样' if source=='shipment' else '前轮选定对象'),
             'source':source,'parent_subproject_id':parent['id'],'shipment_task_id':(shipment or {}).get('id')} for code in dict.fromkeys(codes)]


def state(con,sp):
    bd=brief(con,sp);code=sp.get('base_formula_code') or '';ctx=db.jload(sp.get('context_json'),{});lock=ctx.get('modification_lock') or {}
    task=db.one(con,"select * from department_tasks where subproject_id=? and type='调香' and status!='cancelled' order by rowid desc limit 1",(sp['id'],))
    library=db.one(con,'select code,name,new_class from library_items where code=?',(code,)) if code else None
    options=base_options(con,sp);proof=next((o for o in options if o['code']==code),None)
    locked=bool(lock) or bool(task and issued(task))
    verified=bool(library or (proof and proof['source']=='shipment') or (lock.get('code')==code and lock.get('verified')))
    change=bd.get('modification') or ''
    if not isinstance(change,str):raise ValueError('改动要求必须是文本')
    blockers=[]
    if not code:blockers.append('请选择一个被改对象；关联首轮未同步编号时可先保存要求。')
    elif not verified:blockers.append('被改编号尚未在库内或前轮实际寄样记录中确认。')
    if not change.strip():blockers.append('请填写明确的改动要求。')
    return {'base_code':code,'base_name':(library or proof or {}).get('name') or lock.get('name',''),'base_verified':verified,
            'base_source':'library' if library else (proof or {}).get('source') or lock.get('source',''),'base_options':options,
            'locked':locked,'lock':lock,'modification':change,'ready':not blockers,'blockers':blockers,
            'task_id':(task or {}).get('id'),'dispatch_state':'issued' if locked else 'draft',
            'department':(task or {}).get('department') or '调香','owner':(task or {}).get('owner') or '',
            'due':(task or {}).get('due') or bd['deliverables'].get('deadline') or bd['commercial'].get('sample_due') or ''}


def guard_changes(con,sp,base_code=None,change=None):
    if sp['task_type']!='modify':return
    current=state(con,sp)
    if base_code is not None and not isinstance(base_code,str):raise ValueError('被改对象编号必须是文本')
    if current['locked'] and base_code is not None and base_code!=current['base_code']:raise ValueError('已派发改香工单的被改对象已锁定；更换对象请创建关联改香。')
    if change is not None:
        if not isinstance(change,str):raise ValueError('改动要求必须是文本')
        started=db.one(con,"select id from department_tasks where subproject_id=? and type='调香' and status in ('doing','done')",(sp['id'],))
        if started and change!=current['modification']:raise ValueError('调香已执行，新的修改要求请另建关联改香，保留原工单。')


def ensure_draft(con,sp):
    from . import workflow
    if not sp.get('base_formula_code'):
        bd=brief(con,sp);sources=[a.get('text') or '' for a in db.rows(con,'select text from artifacts where project_id=?',(sp['project_id'],))]
        candidates={x.strip() for x in [bd['scent'].get('old_formula'),bd['product'].get('name'),sp.get('base_sample_reference')] if isinstance(x,str) and db.one(con,'select code from library_items where code=?',(x.strip(),)) and any(x.strip() in text for text in sources)}
        if len(candidates)==1:
            code=candidates.pop();con.execute('update subprojects set base_formula_code=? where id=?',(code,sp['id']))
            bd['scent']['old_formula']=code;db.save_brief(con,sp['project_id'],bd,sp['id'],actor='system')
            db.audit(con,'subproject',sp['id'],'base_formula_code','',code,actor='system',reason='局部结构化原对象与库内编号完全相同，并在原资料中确认；未从候选或标题猜测')
            sp=db.one(con,'select * from subprojects where id=?',(sp['id'],))
    current=state(con,sp);task=db.one(con,'select * from department_tasks where id=?',(current['task_id'],)) if current['task_id'] else None
    if task and issued(task):
        if not current['lock'] and current['base_code']:
            ctx=db.jload(sp.get('context_json'),{});ctx['modification_lock']={'code':current['base_code'],'name':current['base_name'],'source':current['base_source'],'verified':current['base_verified'],'task_id':task['id'],'locked_at':db.now(),'origin':'existing_issued_task'}
            con.execute('update subprojects set context_json=? where id=?',(db.js(ctx),sp['id']))
        return task['id']
    payload=workflow.context(con,sp);payload.update(modification_draft=True,dispatch_state='draft',base_verified=current['base_verified'],base_name=current['base_name'],modification=current['modification'],blockers=current['blockers'])
    detail=payload['handoff']+'\n工单状态：待确认派发'+('\n待补：'+'；'.join(current['blockers']) if current['blockers'] else '')
    if task:
        old=db.jload(task.get('payload_json'),{});payload={**old,**payload};payload.pop('base_pending',None)
        con.execute("update department_tasks set status='draft',payload_json=?,detail=?,department=coalesce(nullif(department,''),'调香'),updated_at=? where id=?",(db.js(payload),detail,db.now(),task['id']));tid=task['id']
        if task['status']!='draft':db.audit(con,'task',tid,'draft_preparation',task['status'],'draft',actor='system',reason='未执行的改香任务改为可核对的预编工单')
    else:
        tid=db.uid('t_');con.execute("insert into department_tasks(id,subproject_id,type,title,detail,department,due,status,depends_on_json,payload_json,created_at,updated_at) values(?,?,'调香','调香',?,'调香',?,'draft','[]',?,?,?)",(tid,sp['id'],detail,current['due'],db.js(payload),db.now(),db.now()))
        db.audit(con,'task',tid,'draft_preparation',None,'draft',actor='system',reason='改香预编工单，尚未派发')
    for old in db.rows(con,"select * from department_tasks where subproject_id=? and type='确认改香基准' and status='todo'",(sp['id'],)):
        con.execute("update department_tasks set status='cancelled',result='基准确认已整合到改香工作台',updated_at=? where id=?",(db.now(),old['id']));db.audit(con,'task',old['id'],'status',old['status'],'cancelled',actor='system',reason='由工作台的基准校验取代，未标为完成')
    con.execute("update subprojects set status='tasks',workflow_stage='modification_draft' where id=?",(sp['id'],))
    return tid


def save(con,sp,data):
    from . import workflow
    current=state(con,sp)
    if current['locked'] and any(k in data and str(data[k]).strip()!=str(current.get(k) or '').strip() for k in ('owner','department','due')):raise ValueError('工单已派发；负责人和交期请通过任务入口更新。')
    code=data.get('base_formula_code',sp.get('base_formula_code') or '')
    change=data.get('modification',brief(con,sp).get('modification') or '')
    guard_changes(con,sp,code,change)
    old=brief(con,sp);bd=model.brief(old);bd['modification']=change;bd['scent']['old_formula']=code
    con.execute('update subprojects set base_formula_code=?,updated_at=? where id=?',(code,db.now(),sp['id']))
    if 'base_formula_code' in data and code!=(sp.get('base_formula_code') or ''):
        ctx=db.jload(sp.get('context_json'),{});ctx['inherited_base']={'source':'manual','codes':[code] if code else []};con.execute('update subprojects set context_json=? where id=?',(db.js(ctx),sp['id']))
    fresh=db.one(con,'select * from subprojects where id=?',(sp['id'],));project=db.one(con,'select * from projects where id=?',(sp['project_id'],)) or {}
    bd=model.track_manual(old,bd);bd['handoff']=model.handoff(project,fresh,bd);db.save_brief(con,sp['project_id'],bd,sp['id'],actor='evaluator')
    db.audit(con,'subproject',sp['id'],'fields',{'base_formula_code':sp.get('base_formula_code')},{'base_formula_code':code},reason='明确指定改香对象，不是选参考香')
    if not state(con,fresh)['locked']:workflow.start(con,fresh)
    else:
        for task in db.rows(con,"select * from department_tasks where subproject_id=? and type='调香' and status='todo'",(sp['id'],)):
            payload=db.jload(task['payload_json'],{});payload.update(workflow.context(con,fresh));payload['modification']=change
            con.execute('update department_tasks set payload_json=?,detail=? where id=?',(db.js(payload),payload['handoff'],task['id']))
    current=state(con,fresh)
    if current['task_id']:
        updates={k:str(data[k]).strip() for k in ('owner','department','due') if k in data}
        if updates:con.execute('update department_tasks set '+','.join(k+'=?' for k in updates)+' where id=?',(*updates.values(),current['task_id']))
    return current


def dispatch(con,sp,data):
    current=save(con,sp,data);fresh=db.one(con,'select * from subprojects where id=?',(sp['id'],));current=state(con,fresh)
    if current['locked']:return current['task_id']
    if current['blockers']:raise ValueError('暂不能派发：'+'；'.join(current['blockers']))
    task=db.one(con,'select * from department_tasks where id=?',(current['task_id'],));payload=db.jload(task['payload_json'],{});payload.update(dispatch_state='issued',modification_draft=False,issued_at=db.now(),blockers=[])
    lock={'code':current['base_code'],'name':current['base_name'],'source':current['base_source'],'verified':True,'task_id':task['id'],'locked_at':db.now()}
    ctx=db.jload(fresh.get('context_json'),{});ctx['modification_lock']=lock
    deps=[tid for tid in db.jload(task.get('depends_on_json'),[]) if (db.one(con,'select status from department_tasks where id=?',(tid,)) or {}).get('status')=='done']
    con.execute("update department_tasks set status='todo',payload_json=?,detail=?,depends_on_json=?,updated_at=? where id=?",(db.js(payload),payload['handoff'],db.js(deps),db.now(),task['id']))
    con.execute("update subprojects set context_json=?,workflow_stage='perfumery',status='tasks',updated_at=? where id=?",(db.js(ctx),db.now(),sp['id']))
    db.audit(con,'task',task['id'],'dispatch','draft','todo',reason='确认被改对象与改动要求后派发调香工单；基准锁定')
    return task['id']
