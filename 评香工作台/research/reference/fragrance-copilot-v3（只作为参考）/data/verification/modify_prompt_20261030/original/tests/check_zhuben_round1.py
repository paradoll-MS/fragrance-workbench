"""Independent acceptance checklist for the supplied case, never production routing rules."""
from pathlib import Path
import json,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,understand
out=ROOT/'data/verification/逐本';s=json.loads((out/'state.json').read_text(encoding='utf-8'));pid=s['project_id']
c=db.connect();snap=understand.snapshot(c,pid)
if len(snap['artifacts'])>2 and (out/'round1_snapshot.json').exists():
 snap=json.loads((out/'round1_snapshot.json').read_text(encoding='utf-8'));run=json.loads((out/'round1_checks.json').read_text(encoding='utf-8'))['run']
 print('verifying frozen first-round snapshot')
else:
 with urllib.request.urlopen('http://127.0.0.1:8768/api/projects/'+pid+'/generation') as r:run=json.load(r)['run']
 if run['status']!='succeeded':sys.exit(2)
 if len(snap['artifacts'])!=2:raise RuntimeError('First-round snapshot requires exactly the two briefs')
 (out/'round1_snapshot.json').write_text(db.js(snap),encoding='utf-8')
checks=[]
def check(label,passed,detail=''):checks.append({'check':label,'passed':bool(passed),'detail':detail})
subs=snap['subprojects'];briefs={b['subproject_id']:json.loads(b['data_json']) for b in snap['briefs'] if b['subproject_id']}
expected={'茉莉冰荔枝':'S','气泡青苹果':'S','茉莉青提':'S','鲜莓芭乐':'S','海盐柚子':'A','青柠百香果':'A','爆汁青橙':'A','一口水蜜桃':'B','海风轻椰':'B','冰镇西瓜':'C','酸野青芒':'C','害羞乌梅':'C'}
check('首轮只读取两份brief',len(snap['artifacts'])==2)
check('十二个独立香型全部建项',len(subs)==12,str(len(subs)))
rows=[]
for name,tier in expected.items():
 hits=[x for x in subs if name in (x['title']+' '+briefs.get(x['id'],{}).get('product',{}).get('name',''))]
 check(name+'独立归属',len(hits)==1)
 if len(hits)!=1:continue
 sp=hits[0];b=briefs[sp['id']];planning=b.get('planning',{});tier_text=str(planning.get('launch_tier',''));requirements=b.get('customer_requirements',[])
 check(name+'三级品类',sp['category_l3']=='卸妆膏油',sp['category_l3'])
 check(name+'上市分层',tier in tier_text,tier_text)
 check(name+'未编造香精价格',sp['price_target'] is None,str(sp['price_target']))
 check(name+'没有把香气比例当添加量',b.get('product',{}).get('dosage') in ('',None),str(b.get('product',{}).get('dosage')))
 check(name+'客户额外要求逐项有来源',bool(requirements) and all(r.get('source_refs') for r in requirements),str(len(requirements)))
 check(name+'ABC有语义依据',bool(json.loads(sp.get('abc_basis_json') or '{}').get('labels')))
 rec=db.one(c,'select * from recommendations where subproject_id=? order by rowid desc limit 1',(sp['id'],))
 meta=json.loads(rec['filters_json'])['meta'] if rec else {}
 check(name+'已生成推荐或明确零候选',bool(rec),str(meta.get('total')))
 if tier=='C':
  bad=[r['text'] for r in requirements if '9香正式商品' in r.get('text','') or ('IFRA' in r.get('text','') and not any(k in r['text'] for k in ['不要求','不推进','暂不','未来','若','仅在']))]
  check(name+'没有继承九款商品化验收',not bad,'；'.join(bad))
 rows.append({'name':name,'tier':tier_text,'type':sp['task_type'],'id':sp['id'],'price':sp['price_target'],'abc_counts':{k:len(json.loads(sp.get(k+'_json') or '[]')) for k in ['a1','a2','a3','b','target_cs']},'requirements':requirements,'scent':b.get('scent'),'planning':planning,'candidate_total':meta.get('total')})
report={'run':run,'project_id':pid,'checks':checks,'details':rows,'passed':all(x['passed'] for x in checks)}
(out/'round1_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASSED',sum(x['passed'] for x in checks),'/',len(checks))
for x in checks:
 if not x['passed']:print('FAIL',json.dumps(x,ensure_ascii=True))
print('subs',json.dumps([{k:r[k] for k in ['name','type','tier','candidate_total']} for r in rows],ensure_ascii=True))
c.close()
