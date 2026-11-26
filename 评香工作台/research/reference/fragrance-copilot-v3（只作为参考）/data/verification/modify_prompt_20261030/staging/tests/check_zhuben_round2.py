from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,understand
out=ROOT/'data/verification/逐本';state=json.loads((out/'state.json').read_text(encoding='utf-8'));pid=state['project_id'];before=json.loads((out/'round1_snapshot.json').read_text(encoding='utf-8'));c=db.connect();after=understand.snapshot(c,pid)
(out/'round2_snapshot.json').write_text(db.js(after),encoding='utf-8')
checks=[]
def check(name,passed,detail=''):checks.append(dict(check=name,passed=bool(passed),detail=detail))
old={x['id']:x for x in before['subprojects']};current={x['id']:x for x in after['subprojects']};new=[x for x in after['subprojects'] if x['id'] not in old]
old_briefs={x['subproject_id']:json.loads(x['data_json']) for x in before['briefs'] if x['subproject_id']};briefs={x['subproject_id']:json.loads(x['data_json']) for x in after['briefs'] if x['subproject_id']}
check('累计三个原始资料',len(after['artifacts'])==3)
check('新增四个关联改香子项目',len(new)==4 and all(x['task_type']=='modify' and x['parent_subproject_id'] in old for x in new),str(len(new)))
check('原十二个子项目记录保持不变',all(current[k]==v for k,v in old.items()))
check('原十二份简报保持不变',all(briefs[k]==v for k,v in old_briefs.items()))
check('原始资料文字保留不变',all(any(y['id']==x['id'] and y['text']==x['text'] for y in after['artifacts']) for x in before['artifacts']))
meeting_id=next(x['id'] for x in after['artifacts'] if x['filename'].startswith('2026'))
expected={'茉莉冰荔枝':['甜','冰','茉莉'],'气泡青苹果':['气泡','酸脆','洗发水','复合'],'茉莉青提':['发酵','酒','一半'],'鲜莓芭乐':['脂粉','芭乐','草莓']}
details=[]
for parent_name,keywords in expected.items():
 parent=next(x for x in old.values() if parent_name in x['title']);children=[x for x in new if x['parent_subproject_id']==parent['id']]
 check(parent_name+'正确承接首轮',len(children)==1)
 if len(children)!=1:continue
 sp=children[0];b=briefs[sp['id']];text=json.dumps({'scent':b.get('scent'),'modification':b.get('modification'),'requirements':b.get('customer_requirements')},ensure_ascii=False)
 for keyword in keywords:check(parent_name+'修改包含'+keyword,keyword in text)
 check(parent_name+'没有虚构内部号',not sp.get('base_formula_code'))
 check(parent_name+'原样引用保留',bool(sp.get('base_sample_reference') or json.loads(sp.get('context_json') or '{}').get('inherited_base')))
 check(parent_name+'新纪要作为依据',any(r.get('artifact_id')==meeting_id for r in json.loads(sp.get('source_refs_json') or '[]')))
 check(parent_name+'50度和UV要求',('50' in text and ('紫外' in text or 'UV' in text)))
 check(parent_name+'承袭首轮上市分层',b.get('planning',{}).get('launch_tier')==old_briefs[parent['id']].get('planning',{}).get('launch_tier'))
 check(parent_name+'承袭仍有效商品化验收',any('9款' in q.get('text','') and '法规' in q.get('text','') for q in b.get('customer_requirements',[])))
 if parent_name=='茉莉青提':
  structure=b.get('scent',{}).get('structure','');check('青提茉莉新配比写入结构而非只写备注',any(x in structure for x in ['50','一半','各半']) and '75' not in structure and '80' not in structure,structure)
  check('青提茉莉不再受旧水果主导比例检查',not any('主水果' in q.get('text','') and ('70' in q['text'] or '80' in q['text']) for q in b.get('customer_requirements',[])))
 tasks=[x for x in after['tasks'] if x['subproject_id']==sp['id'] and x['status']!='cancelled'];perf=[x for x in tasks if x['type']=='调香']
 check(parent_name+'已形成承袭原样的调香工单',len(perf)==1)
 check(parent_name+'等待原编号同步而不伪造完成',bool(perf) and perf[0]['status']=='waiting' and bool(json.loads(perf[0]['payload_json']).get('base_pending')))
 check(parent_name+'待执行工单与新简报完全同步',bool(perf) and json.loads(perf[0]['payload_json']).get('requirements')==b)
 details.append(dict(parent=parent_name,id=sp['id'],parent_id=sp['parent_subproject_id'],requirements=b.get('customer_requirements'),modification=b.get('modification'),scent=b.get('scent'),tasks=[{'type':t['type'],'status':t['status']} for t in tasks]))
coord=json.loads(after['project']['coordination_json']);events=coord.get('events',[])
check('总体定香节点保存在项目',('9月' in coord.get('overall_deadline','') and ('月底' in coord.get('overall_deadline','') or '30' in coord.get('overall_deadline',''))),coord.get('overall_deadline'))
for place,grams,purpose in [('上海','200','闻香'),('天津','500','稳定')]:
 e=next((e for e in events if place in e.get('destination','') and grams in str(e.get('quantity'))),None)
 check(place+'寄料规格分开保存',bool(e))
 if e:
  check(place+'用途正确',purpose in e.get('purpose',''))
  check(place+'负责人明确','逯柏松' in e.get('owner',''))
  check(place+'下周一按会议日定位','2026-09-14' in e.get('due_resolved',''),e.get('due_resolved'))
  check(place+'只是计划而非已寄','planned'==e.get('status'))
check('测试方法同步有负责人',any('李玲' in e.get('owner','') and '稳定' in e.get('action','') for e in events))
check('四款配方调整有负责人',any(e.get('owner')=='畅' and '四款' in e.get('action','') for e in events))
check('没有把实际任务标记完成',not any(t['status']=='done' for t in after['tasks']))
report={'passed':all(x['passed'] for x in checks),'checks':checks,'details':details,'project_coordination':coord,'project_id':pid}
(out/'round2_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASSED',sum(x['passed'] for x in checks),'/',len(checks))
for x in checks:
 if not x['passed']:print('FAIL',json.dumps(x,ensure_ascii=True))
print('new',json.dumps([{k:r[k] for k in ['parent','id','parent_id','tasks']} for r in details],ensure_ascii=True))
c.close()
