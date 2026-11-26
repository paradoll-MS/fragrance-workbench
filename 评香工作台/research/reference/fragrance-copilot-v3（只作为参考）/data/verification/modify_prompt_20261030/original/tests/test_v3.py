"""Behavioral regression tests. Each test uses a disposable isolated database."""
import copy
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import db, model, reco, service, understand, workflow, business, llm, source_refs, identity
from app.server import Handler, session
from http.server import ThreadingHTTPServer

class Regression(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='copilot-v3-regression-')
  self.old_path=db.DB_PATH; self.old_uploads=db.UPLOADS
  db.DB_PATH=Path(self.tmp.name)/'test.sqlite3'; db.UPLOADS=Path(self.tmp.name)/'uploads'
  self.con=db.connect()
  c=self.con
  c.executemany('insert into terms values(?,?,?,?,?,?)',[
   ('a1','A','A1','茶','具体香材',''),('a2','A','A2','木质','家族',''),('a3','A','A3','柔和','宽香韵',''),('b','B','B1','高级','风格',''),('b2','B','B1','清新','风格','')])
  c.executemany('insert into c_nodes values(?,?,?,?,?,?,?)',[
   ('c','空间香氛','场景','','酒店','酒店','酒店定位'),('cc','空间香氛','场景','c','大堂','酒店/大堂','大堂'),('cx','空间香氛','场景','','礼赠','礼赠','赠礼'),('other','个人香氛','场景','','个人','个人','个人')])
  c.executemany('insert into c_ab values(?,?,?,?,?)',[('c','a2','A','木质','A2'),('cc','a1','A','茶','A1'),('cc','b','B','高级','B1'),('cx','a2','A','木质','A2')])
  c.executemany('insert into category_map values(?,?,?,?,?,?,?,?,?,?)',[
   ('K009','香氛','空间','扩香机液','无火扩香类','空间香氛','[]','{}','',''),('K001','香氛','身体','香水','身体香氛类','个人香氛','[]','{}','','')])
  for code,price,a1,a2,a3,b,cs,brand,hot,new,nc in [
   ('one',100,['a1'],['a2'],[],['b'],['cc'],['Le Labo'],1,1,'空间香氛'),
   ('two',80,[],['a2'],[],['b'],['cx'],['Chanel'],1,0,'空间香氛'),
   ('three',100,[],[],['a3'],['b2'],[],[],0,1,'空间香氛'),
   ('unknown',None,['a1'],[],[],[],[],[],0,0,'空间香氛'),
   ('other',90,['a1'],[],[],[],['other'],[],0,0,'个人香氛')]:
   c.execute('''insert into library_items(code,name,new_class,co_classes_json,price,usage_count,a1_ids_json,a2_ids_json,a3_ids_json,c_ids_json,brand_tags_json,is_brand_dupe,is_hot,is_new)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(code,code,nc,'[]',price,7,json.dumps(a1),json.dumps(a2),json.dumps(a3),json.dumps(cs),json.dumps(brand),int(bool(brand)),hot,new))
   for tid in a1+a2+a3+b+cs:
    term=db.one(c,'select * from terms where id=?',(tid,)) or db.one(c,'select * from c_nodes where id=?',(tid,))
    c.execute('insert into library_tags values(?,?,?,?,?,?,?,?,?,?)',(code,term.get('domain','C'),tid,term.get('layer','C'),term['label'],term.get('path',''),'main',nc,nc,''))
  c.execute("insert into projects(id,name,customer,brand,sales,evaluator,grade,status,created_at,updated_at) values('p','酒店项目','客户','品牌','销售','评香','B','draft','2026-10-29','2026-10-29')")
  c.execute("insert into artifacts(id,project_id,filename,text,status,created_at) values('art','p','会议纪要','酒店大堂需要木质茶香；另要大牌赠礼香。','parsed','2026-10-29')")
  c.commit()
 def tearDown(self):
  if hasattr(self,'http'):
   self.http.shutdown();self.http.server_close();self.http_thread.join()
  self.con.close();db._READY.discard(str(db.DB_PATH));db.DB_PATH=self.old_path;db.UPLOADS=self.old_uploads;self.tmp.cleanup()
 def sp(self,**kw):
  x=dict(id='s',project_id='p',title='大堂香',task_type='recommend_brand',status='briefed',new_class='空间香氛',norm_class='无火扩香类',category_l3='扩香机液',a1_json='["a1"]',a2_json='["a2"]',a3_json='["a3"]',b_json='["b"]',target_cs_json='["c"]',price_target=100,price_elasticity=20,brand_filter='',target_products_json='[]',base_formula_code='')
  x.update(kw);return x
 def insert_sp(self,**kw):
  sp=self.sp(**kw);c=self.con;c.execute(f"insert into subprojects({','.join(sp)}) values({','.join('?' for _ in sp)})",tuple(sp.values()));db.save_brief(c,'p',model.brief({'product':{'substrate':'乙醇水','category_l3':'扩香机液'},'scent':{'theme':'木质茶香'}}),sp['id']);c.commit();return db.one(c,'select * from subprojects where id=?',(sp['id'],))
 def request(self,path,method='GET',body=None):
  if not hasattr(self,'http'):
   self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http_thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.http_thread.start()
  req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}'+path,data=db.js(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read())
  except urllib.error.HTTPError as e:
   with e:return e.code,json.loads(e.read())
 def output(self):
  r={'artifact_id':'art','locator':'全文','quote':'酒店大堂需要木质茶香'}
  return {'brief':{'project':{'summary':'大堂香与赠礼香两条需求'}},'story':{'summary':'客户要两类产品','timeline':[{'event':'提出需求','source_refs':[r]}]},'artifact_annotations':[{'artifact_id':'art','source_type':'会议纪要','role':'需求'}],
   'subprojects':[{'key':'lobby','title':'大堂空间香','task_type':'recommend_brand','category_k_code':'K009','brief':{'commercial':{'target_price':100},'product':{'substrate':'乙醇水'}},'a1':['a1'],'a2':['a2'],'a3':[],'b':['b'],'target_cs':['c'],'abc_basis':[{'id':i,'label':{'a1':'茶','a2':'木质','b':'高级','c':'酒店'}[i],'evidence_role':'explicit_scent_target' if i in ('a1','a2') else 'context','reason':'根据整体语境推断','source_refs':[r]} for i in ['a1','a2','b','c']],'source_refs':[r]},
   {'key':'gift','title':'大牌赠礼香','task_type':'recommend_simple','category_k_code':'K001','brief':{'commercial':{'target_price':150}},'a1':[],'a2':[],'a3':[],'b':[],'target_cs':[],'brand_requirements':[{'kind':'dupe','value':'大牌香','path':['大牌香']}],'source_refs':[r]}],
   'coverage':[{'requirement':'大堂香','subproject_keys':['lobby'],'source_refs':[r]},{'requirement':'赠礼','subproject_keys':['gift'],'source_refs':[r]}]}
 def test_default_a1_or_and_direct_exclusion(self):
  rows,_=reco.recommend(self.con,self.sp());one=next(x for x in rows if x['code']=='one')
  self.assertEqual([x['code'] for x in rows],['one']);self.assertEqual(one['score'],6);self.assertEqual(one['a_score'],1);self.assertEqual(one['b_score'],1);self.assertEqual(one['c_score'],3);self.assertEqual(one['mapped_score'],1)
 def test_disable_a1_does_not_silently_enable_a23(self):
  sp=self.sp();f=reco.default_filters(sp);f['tags']=[];sp['hard_filters_json']=db.js(f)
  rows,_=reco.recommend(self.con,sp);self.assertEqual({x['code'] for x in rows},{'one','two','three'})
 def test_a2_a3_combined_or(self):
  rows,_=reco.recommend(self.con,self.sp(a1_json='[]'));self.assertEqual({x['code'] for x in rows},{'one','two','three'})
 def test_b_c_are_optional_hard_filters_and_excluded_from_direct_only(self):
  sp=self.sp();f=reco.default_filters(sp);f['tags']=[{'key':'B','ids':['b'],'mode':'any'},{'key':'C','ids':['c'],'mode':'any'}];sp['hard_filters_json']=db.js(f)
  rows,_=reco.recommend(self.con,sp);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['b_score'],0);self.assertEqual(rows[0]['c_score'],0);self.assertEqual(rows[0]['mapped_score'],1)
 def test_no_demand_c_means_no_c_associated_ab_bonus(self):
  sp=self.sp(a1_json='[]',a3_json='[]',target_cs_json='[]');rows,_=reco.recommend(self.con,sp)
  one=next(x for x in rows if x['code']=='one');two=next(x for x in rows if x['code']=='two')
  self.assertEqual(one['mapped_score'],0);self.assertEqual(two['mapped_score'],0)
 def test_demand_c_ab_matches_candidate_ab_not_reverse(self):
  # Candidate three's C would map to the requested B2 in the former, wrong direction.
  self.con.execute("insert into c_ab values('cc','b2','B','清新','B1')")
  self.con.execute("insert into library_tags values('three','C','cc','C','大堂','酒店/大堂','main','空间香氛','空间香氛','')")
  sp=self.sp(a1_json='[]',a2_json='[]',a3_json='[]',b_json='["b2"]',target_cs_json='["c"]')
  rows,meta=reco.recommend(self.con,sp);by_code={r['code']:r for r in rows}
  self.assertEqual(by_code['one']['mapped_score'],1);self.assertEqual(by_code['two']['mapped_score'],1);self.assertEqual(by_code['three']['mapped_score'],0)
  self.assertEqual(by_code['one']['mapped_hits'][0]['id'],'a2');self.assertEqual(by_code['one']['mapped_hits'][0]['via_demand_cs'],['c']);self.assertEqual(meta['demand_c_ab'][0]['id'],'a2')
 def test_multiple_demand_cs_do_not_double_count_same_ab(self):
  rows,_=reco.recommend(self.con,self.sp(target_cs_json='["c","cx"]'))
  self.assertEqual(rows[0]['mapped_score'],1);self.assertEqual(rows[0]['mapped_hits'][0]['via_demand_cs'],['c','cx'])
 def test_simple_and_brand_same_scoring(self):
  sp=self.sp();a,_=reco.recommend(self.con,sp);sp['task_type']='recommend_simple';b,_=reco.recommend(self.con,sp);self.assertEqual([(x['code'],x['score']) for x in a],[(x['code'],x['score']) for x in b])
 def test_brand_branch_leaf_or(self):
  sp=self.sp(task_type='recommend_simple',a1_json='[]',brand_requirements_json=db.js([{'kind':'dupe','value':'大牌香','path':['大牌香']},{'kind':'brand','value':'Le Labo','path':['大牌香','Le Labo']},{'kind':'brand','value':'Chanel','path':['大牌香','Chanel']}]));self.assertEqual(len(reco.requirements(sp)),2);rows,_=reco.recommend(self.con,sp);self.assertEqual({x['code'] for x in rows},{'one','two'})
 def test_hot_new_defaults_can_be_unchecked(self):
  sp=self.sp(task_type='recommend_simple',a1_json='[]',wants_hot=1,wants_new=1);rows,_=reco.recommend(self.con,sp);self.assertEqual([r['code'] for r in rows],['one']);f=reco.default_filters(sp);f.update(hot_enabled=False,new_enabled=False);sp['hard_filters_json']=db.js(f);rows,_=reco.recommend(self.con,sp);self.assertEqual(len(rows),3)
 def test_category_price_all_can_be_disabled(self):
  sp=self.sp();f=reco.default_filters(sp);f.update(category_enabled=False,price_enabled=False,tags=[]);sp['hard_filters_json']=db.js(f);rows,_=reco.recommend(self.con,sp);self.assertEqual(len(rows),5)
 def test_multiple_category_or(self):
  sp=self.sp();f=reco.default_filters(sp);f['categories']=['空间香氛','个人香氛'];sp['hard_filters_json']=db.js(f);rows,_=reco.recommend(self.con,sp);self.assertEqual({r['code'] for r in rows},{'one','other'})
 def test_brand_scoped_number_is_not_a_numeric_substring(self):
  self.con.execute("insert into formula_product_labels values('one','Le Labo','Another 13','同款','人工')")
  rows,_=reco.recommend(self.con,self.sp(task_type='find_product',target_products_json=db.js([{'brand':'Le Labo','product':'13'}])));self.assertEqual(len(rows),1)
  rows,_=reco.recommend(self.con,self.sp(task_type='find_product',target_products_json=db.js([{'brand':'Le Labo','product':'3'}])));self.assertEqual(rows,[])
  rows,_=reco.recommend(self.con,self.sp(task_type='find_product',target_products_json=db.js([{'brand':'Le Labo','product':'Another 13'}])));self.assertEqual(len(rows),1)
 def test_no_category_tuple_contract(self):
  with self.assertRaises(ValueError):reco.recommend(self.con,self.sp(new_class=''))
 def test_cached_recommendation_preserves_decision_and_usage(self):
  sp=self.insert_sp();items,_=service.recommendations(self.con,sp);iid=items[0]['id'];self.con.execute("update recommendation_items set decision='shortlist' where id=?",(iid,));items2,_=service.recommendations(self.con,sp);self.assertEqual(items2[0]['id'],iid);self.assertEqual(items2[0]['decision'],'shortlist');self.assertEqual(items2[0]['usage_count'],7)
 def test_model_validate_full_coverage(self):
  s=understand.snapshot(self.con,'p');out=self.output();understand.validate(self.con,s,out);out['artifact_annotations']=[]
  with self.assertRaises(ValueError):understand.validate(self.con,s,out)
 def test_invalid_quote_rejected(self):
  out=self.output();out['subprojects'][0]['source_refs'][0]['quote']='不存在的原话'
  with self.assertRaises(ValueError):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_invalid_tag_rejected(self):
  out=self.output();out['subprojects'][0]['b']=['a1']
  with self.assertRaises(ValueError):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_hotel_two_independent_subprojects_and_briefs(self):
  s=understand.snapshot(self.con,'p');out=understand.validate(self.con,s,self.output());change=understand.apply(self.con,s,out,'test');self.assertEqual(len(change['created']),2)
  subs=db.rows(self.con,'select * from subprojects');self.assertEqual({s['task_type'] for s in subs},{'recommend_brand','recommend_simple'})
  briefs=db.rows(self.con,"select data_json from briefs where coalesce(subproject_id,'')!=''");self.assertEqual(len(briefs),2);self.assertEqual({json.loads(r['data_json'])['commercial']['target_price'] for r in briefs},{100,150})
 def test_completed_subproject_preserved_new_modify_link(self):
  sp=self.insert_sp(status='sample_initial',selected_codes_json='["one"]');s=understand.snapshot(self.con,'p');out=self.output();item=out['subprojects'][0];item.update(key='lobby-modify',task_type='modify',parent_subproject_id='s',base_formula_code='one');out['coverage'][0]['subproject_keys']=['lobby-modify'];understand.validate(self.con,s,out);understand.apply(self.con,s,out,'follow');self.assertEqual(db.one(self.con,"select status from subprojects where id='s'")['status'],'sample_initial');self.assertEqual(db.one(self.con,"select parent_subproject_id from subprojects where task_type='modify'")['parent_subproject_id'],'s')
 def test_completed_cannot_be_overwritten(self):
  self.insert_sp(status='sample_initial');s=understand.snapshot(self.con,'p');out=self.output();out['subprojects'][0]['id']='s'
  with self.assertRaises(ValueError):understand.validate(self.con,s,out)
 def test_full_generation_worker_and_idempotence(self):
  s=understand.snapshot(self.con,'p');self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(s),db.js(s),None,'',db.now(),db.now()));self.con.commit()
  with patch('app.llm.chat_json',return_value=self.output()) as chat:understand.run('r')
  row=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(row['status'],'succeeded',row['error']);self.assertEqual(chat.call_count,1);self.assertEqual(understand.start('p')['id'],'r')
 def test_concurrent_edit_during_model_call_does_not_overwrite(self):
  s=understand.snapshot(self.con,'p');self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(s),db.js(s),None,'',db.now(),db.now()));self.con.commit()
  def changed(*args,**kw):
   with session() as c:c.execute("update artifacts set note='人工补充' where id='art'")
   return self.output()
  with patch('app.llm.chat_json',side_effect=changed):understand.run('r')
  row=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(row['status'],'failed');self.assertEqual(self.con.execute('select count(*) from subprojects').fetchone()[0],0)
 def test_find_gc_confirm_creates_perfumery_with_payload_and_dependency(self):
  sp=self.insert_sp(task_type='find_product',target_products_json='[{"brand":"Le Labo","product":"Another 13"}]');workflow.request_analysis(self.con,sp);task=db.one(self.con,"select * from department_tasks where type='分析'")
  with self.assertRaises(ValueError):workflow.update(self.con,task['id'],{'status':'done','result':'完成'})
  workflow.update(self.con,task['id'],{'status':'done','result':'GC完成，报告已收','confirmed':True});p=db.one(self.con,"select * from department_tasks where type='调香'");self.assertEqual(json.loads(p['depends_on_json']),[task['id']]);self.assertEqual(json.loads(p['payload_json'])['substrate'],'乙醇水');self.assertEqual(json.loads(p['payload_json'])['target_products'][0]['product'],'Another 13')
 def test_task_dependencies_block_early_completion(self):
  sp=self.insert_sp(task_type='create');first=workflow.ensure(self.con,sp,'调香');later=workflow.ensure(self.con,sp,'评香验收',[first])
  with self.assertRaises(ValueError):workflow.update(self.con,later,{'status':'done','result':'完成'})
 def test_select_sample_shipping_workflow(self):
  sp=self.insert_sp();workflow.choose(self.con,sp,['one']);sample=db.one(self.con,"select * from department_tasks where type='打样'");self.assertIsNotNone(sample);self.assertIsNone(db.one(self.con,"select * from department_tasks where type='寄样'"));workflow.update(self.con,sample['id'],{'status':'done','result':'已打样'});self.assertIsNotNone(db.one(self.con,"select * from department_tasks where type='寄样'"))
 def test_match_requires_actual_received_sample(self):
  sp=self.insert_sp(task_type='match_sample')
  with self.assertRaises(ValueError):workflow.choose(self.con,sp,['one'])
  with self.assertRaises(ValueError):workflow.request_analysis(self.con,sp)
 def test_intake_task_blocked(self):
  sp=self.insert_sp();tid=workflow.ensure(self.con,sp,'入库')
  with self.assertRaises(ValueError):workflow.update(self.con,tid,{'status':'done','result':'写入'})
 def test_check_detail_change_resets_confirmation(self):
  sp=self.insert_sp();d={'ifra':'IFRA用途1','regulatory_by_region':{},'performance_codes':[],'stability_codes':[]};service.endpoint_checks(self.con,sp,d);self.con.execute("update endpoint_checks set status='confirmed'");d['ifra']='用途变化';r=service.endpoint_checks(self.con,sp,d);self.assertEqual(r[0]['status'],'pending')
 def test_numeric_validation(self):
  for v in [-1,'NaN','inf',True]:
   with self.assertRaises(ValueError):model.number(v,'价格')
 def test_llm_context_is_thread_local(self):
  from app import llm
  llm.begin('parent','root');result=[]
  t=threading.Thread(target=lambda:(llm.begin('child','parse'),result.append(llm._CTX.get()['project_id'])));t.start();t.join();self.assertEqual(result,['child']);self.assertEqual(llm._CTX.get()['project_id'],'parent')
 def test_project_contact_deadline_storage_and_scope(self):
  self.insert_sp()
  b=model.brief({'project':{'summary':'客户总需求','customer':'酒店集团','contacts':[{'name':'张经理','role':'客户对接'}],'overall_deadline':'11月15日','coordination_notes':'先由销售汇总'},'deliverables':{'deadline':'11月15日'}})
  code,_=self.request('/api/projects/p/brief','PUT',{'brief':b});self.assertEqual(code,200)
  p=db.one(self.con,"select * from projects where id='p'");self.assertEqual(json.loads(p['customer_info_json'])['contacts'][0]['name'],'张经理');self.assertEqual(json.loads(p['coordination_json'])['overall_deadline'],'11月15日')
  child=json.loads(db.one(self.con,"select data_json from briefs where subproject_id='s'")['data_json']);self.assertEqual(child['deliverables']['deadline'],'11月15日')
 def test_specific_deadline_not_overwritten_by_project(self):
  self.insert_sp();bd=model.brief({'deliverables':{'deadline':'11月8日'}});db.save_brief(self.con,'p',bd,'s');self.con.commit()
  code,_=self.request('/api/projects/p/brief','PUT',{'brief':{'project':{'summary':'需求'},'deliverables':{'deadline':'11月15日'}}});self.assertEqual(code,200)
  child=json.loads(db.one(self.con,"select data_json from briefs where subproject_id='s'")['data_json']);self.assertEqual(child['deliverables']['deadline'],'11月8日')
 def test_ordinary_scent_requirement_is_not_an_extra_document(self):
  sp=self.insert_sp(task_type='create');requirement={'text':'不允许甜腻','category':'scent','source_scope':'specific','source_refs':[{'artifact_id':'art','quote':''}],'status':'recorded'}
  bd=model.brief({'product':{'substrate':'乙醇水','category_l3':'扩香机液'},'customer_requirements':[requirement]});code,_=self.request('/api/subprojects/s/brief','PUT',{'brief':bd});self.assertEqual(code,200)
  stored=db.one(self.con,"select customer_requirements_json from subprojects where id='s'");self.assertEqual(json.loads(stored['customer_requirements_json']),[])
  payload=json.loads(db.one(self.con,"select payload_json from department_tasks where type='调香'")['payload_json']);self.assertEqual(payload['customer_requirements'],[]);self.assertEqual(payload['requirements']['requirement_register'][0]['text'],'不允许甜腻')
  child=json.loads(db.one(self.con,"select data_json from briefs where subproject_id='s'")['data_json']);child['project']['customer']='其它客户';code,_=self.request('/api/subprojects/s/brief','PUT',{'brief':child});self.assertEqual(code,400);self.assertEqual(db.one(self.con,"select customer from projects where id='p'")['customer'],'客户')
 def test_manual_brief_survives_model_suggestion(self):
  old=model.brief({'product':{'target_audience':'成人'}});new=model.brief({'product':{'target_audience':'儿童'}});manual=model.track_manual(old,new);suggested=model.brief({'product':{'target_audience':'成人'}});model.preserve_manual(manual,suggested);self.assertEqual(suggested['product']['target_audience'],'儿童')
 def test_http_intake_blocked_on_every_mutation_route(self):
  sp=self.insert_sp();tid=workflow.ensure(self.con,sp,'入库');self.con.commit()
  for path,method,payload in [('/api/subprojects/s/endpoint','POST',{'endpoint':'library_intake','override':True}),('/api/subprojects/s','PATCH',{'status':'library_intake'}),('/api/tasks/'+tid,'PATCH',{'status':'done','result':'入库'})]:
   code,_=self.request(path,method,payload);self.assertEqual(code,400)
  self.assertEqual(self.con.execute('select count(*) from library_items').fetchone()[0],5)
 def test_http_condition_changes_sync_into_brief(self):
  self.insert_sp();code,_=self.request('/api/subprojects/s','PATCH',{'price_target':225,'direction':'茶香','category_l3':'香水'});self.assertEqual(code,200)
  sp=db.one(self.con,"select * from subprojects where id='s'");bd=json.loads(db.one(self.con,"select data_json from briefs where subproject_id='s'")['data_json']);self.assertEqual(sp['price_target'],bd['commercial']['target_price']);self.assertEqual(sp['category_l3'],bd['product']['category_l3']);self.assertEqual(json.loads(sp['target_cs_json']),[]);self.assertEqual(reco.filters(sp)['categories'],['个人香氛'])
 def test_http_analysis_attachment_is_linked_to_perfumery(self):
  import base64
  sp=self.insert_sp(task_type='find_product',target_products_json='[{"product":"Another 13"}]');workflow.request_analysis(self.con,sp);self.con.commit();t=db.one(self.con,"select * from department_tasks where type='分析'")
  code,d=self.request('/api/tasks/'+t['id']+'/files','POST',{'filename':'GC分析.txt','data_base64':base64.b64encode(b'GC report').decode(),'mime':'text/plain'});self.assertEqual(code,200,d)
  code,_=self.request('/api/tasks/'+t['id'],'PATCH',{'status':'done','result':'GC已完成','confirmed':True});self.assertEqual(code,200)
  p=json.loads(db.one(self.con,"select payload_json from department_tasks where type='调香'")['payload_json']);self.assertEqual(p['analysis_files'][0]['id'],d['id'])
 def test_legacy_unstarted_wrong_type_can_be_corrected_with_history(self):
  self.insert_sp(task_type='create');out=self.output();out['subprojects'][0]['id']='s';s=understand.snapshot(self.con,'p');understand.validate(self.con,s,out);understand.apply(self.con,s,out,'r');sp=db.one(self.con,"select * from subprojects where id='s'");self.assertEqual(sp['task_type'],'recommend_brand');self.assertEqual(json.loads(sp['type_history_json'])[0]['from'],'create')
 def test_active_work_cannot_change_type_in_place(self):
  sp=self.insert_sp(task_type='create');tid=workflow.ensure(self.con,sp,'调香');self.con.execute("update department_tasks set status='doing' where id=?",(tid,));out=self.output();out['subprojects'][0]['id']='s'
  with self.assertRaises(ValueError):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_http_create_project_works_after_additive_migration(self):
  code,d=self.request('/api/projects','POST',{'name':'新项目'});self.assertEqual(code,200);self.assertTrue(d['id'])
 def test_match_sample_tags_return_candidates_without_similarity_claim(self):
  rows,meta=reco.recommend(self.con,self.sp(task_type='match_sample'));self.assertEqual(meta['mode'],'tag_search');self.assertTrue(rows)
 def test_standard_brief_aliases_do_not_create_empty_forms(self):
  bd=model.brief({'product':{'product_name':'水果卸妆膏','base':'空白料体'},'scent':{'direction':'木质茶香'},'commercial':{'target_audience':'年轻人','tier':'S'},'compliance':{'requirements':['SDS']}})
  self.assertEqual(bd['product']['name'],'水果卸妆膏');self.assertEqual(bd['product']['substrate'],'空白料体');self.assertEqual(bd['scent']['theme'],'木质茶香');self.assertEqual(bd['product']['target_audience'],'年轻人');self.assertEqual(bd['planning']['launch_tier'],'S');self.assertEqual(bd['compliance']['regulatory'],['SDS'])
 def test_scoped_shared_requirements_only_reach_selected_children(self):
  out=self.output();req={'text':'提供特殊包材验证报告','category':'document','applies_to_keys':['lobby'],'status':'recorded','source_refs':[{'artifact_id':'art','quote':''}]};out['shared_brief']={'customer_requirements':[req]}
  out=understand.validate(self.con,understand.snapshot(self.con,'p'),out);self.assertEqual(len(out['subprojects'][0]['brief']['customer_requirements']),1);self.assertEqual(out['subprojects'][1]['brief']['customer_requirements'],[])
 def test_restricted_product_count_cannot_be_unconditionally_shared(self):
  out=self.output();out['shared_brief']={'customer_requirements':[{'text':'1款需要商品化','source_refs':[{'artifact_id':'art','quote':''}]}]}
  with self.assertRaises(ValueError):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_quote_repairs_only_whitespace_to_real_source(self):
  refs=[{'artifact_id':'x','quote':'鲜果\\n气息'}];understand.refs_valid(refs,{'x':{'filename':'原文','text':'这是鲜果\n\n气息。'}});self.assertEqual(refs[0]['quote'],'鲜果\n\n气息')
 def test_create_reference_selection_does_not_bypass_perfumery(self):
  sp=self.insert_sp(task_type='create');workflow.start(self.con,sp);workflow.choose(self.con,sp,['one']);self.assertIsNone(db.one(self.con,"select id from department_tasks where type='打样'"));self.assertIsNotNone(db.one(self.con,"select id from department_tasks where type='调香'"));p=json.loads(db.one(self.con,"select payload_json from department_tasks where type='调香'")['payload_json']);self.assertEqual(p['selected_codes'],['one'])
 def test_modify_missing_code_has_confirmation_task(self):
  sp=self.insert_sp(task_type='modify',base_sample_reference='首轮青提原样');workflow.start(self.con,sp);self.assertIsNotNone(db.one(self.con,"select id from department_tasks where type='确认改香基准'"));self.assertIsNone(db.one(self.con,"select id from department_tasks where type='调香'"))
 def test_followup_inherits_actual_shipped_formula_code(self):
  parent=self.insert_sp(selected_codes_json='["two"]');tid=workflow.ensure(self.con,parent,'寄样');self.con.execute("update department_tasks set status='done',payload_json=? where id=?",(db.js({'shipped_codes':['one']}),tid))
  child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='s',base_sample_reference='首轮原样');workflow.start(self.con,child)
  child=db.one(self.con,"select * from subprojects where id='child'");self.assertEqual(child['base_formula_code'],'one');self.assertEqual(json.loads(child['context_json'])['inherited_base']['shipment_task_id'],tid);self.assertEqual(json.loads(db.one(self.con,"select data_json from briefs where subproject_id='child'")['data_json'])['scent']['old_formula'],'one')
 def test_followup_without_sample_codes_keeps_reference_waiting(self):
  self.insert_sp();child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='s');workflow.start(self.con,child)
  t=db.one(self.con,"select * from department_tasks where subproject_id='child'");self.assertEqual(t['type'],'调香');self.assertEqual(t['status'],'waiting');self.assertTrue(json.loads(t['payload_json'])['base_pending'])
 def test_followup_resolves_automatically_after_shipment_sync(self):
  parent=self.insert_sp();child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='s');workflow.start(self.con,child);tid=workflow.ensure(self.con,parent,'寄样');workflow.update(self.con,tid,{'status':'done','result':'原样已寄','shipped_codes':['P-001']})
  child=db.one(self.con,"select * from subprojects where id='child'");self.assertEqual(child['base_formula_code'],'P-001');t=db.one(self.con,"select * from department_tasks where subproject_id='child' and type='调香'");self.assertEqual(t['status'],'todo');self.assertEqual(json.loads(t['payload_json'])['base_formula_code'],'P-001');self.assertEqual(self.con.execute('select count(*) from library_items').fetchone()[0],5)
 def test_multiple_shipped_codes_are_not_guessed(self):
  parent=self.insert_sp();tid=workflow.ensure(self.con,parent,'寄样');self.con.execute("update department_tasks set status='done',payload_json=? where id=?",(db.js({'shipped_codes':['one','two']}),tid));child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='s');workflow.start(self.con,child);self.assertFalse(db.one(self.con,"select base_formula_code from subprojects where id='child'")['base_formula_code'])
 def test_inherited_audience_not_erased_by_model_empty_placeholder(self):
  shared={'product':{'target_audience':'年轻消费者'}};local={'product':{'target_audience':'','name':'青提'}};result=model.inherit(shared,local);self.assertEqual(result['product']['target_audience'],'年轻消费者');self.assertEqual(result['product']['name'],'青提')
 def test_explicit_launch_tier_is_normalized_out_of_delivery_note(self):
  bd=model.brief({'deliverables':{'notes':'A级快速跟进；小批补货'}});self.assertEqual(bd['planning']['launch_tier'],'A');self.assertNotIn('launch_tier',model.brief({'deliverables':{'notes':'S级客户要求先打样'}})['planning'])
 def test_discontinuous_quote_lines_are_split_into_true_quotes(self):
  refs=[{'artifact_id':'x','quote':'第一句内容；第三句内容'}];understand.refs_valid(refs,{'x':{'filename':'原文','text':'第一句内容。中间另一句。第三句内容。'}});self.assertEqual([r['quote'] for r in refs],['第一句内容','第三句内容'])
 def test_long_quote_typo_is_anchored_without_allowing_numeric_changes(self):
  source='警惕变色风险：茉莉等原料存在变色风险（如变黄、变粉），需确保料体在高温50度或紫外线照射下保持颜色稳定，并记录每次观察结果。';art={'x':{'filename':'原文','text':source}};refs=[{'artifact_id':'x','quote':source.replace('警惕','警戒')}];understand.refs_valid(refs,art);self.assertEqual(refs[0]['quote'],source);self.assertIn('model_quote',refs[0])
  with self.assertRaises(ValueError):understand.refs_valid([{'artifact_id':'x','quote':source.replace('50','40')}],art)
 def test_inference_context_retains_full_text_and_uses_references(self):
  sp=self.insert_sp();workflow.start(self.con,sp);snapshot=understand.snapshot(self.con,'p');compact=understand.inference_context(snapshot);self.assertEqual(compact['artifacts'][0]['text'],snapshot['artifacts'][0]['text']);self.assertEqual(compact['briefs'][0]['data']['product']['substrate'],'乙醇水')
 def test_missing_abc_basis_gets_one_bounded_contract_repair(self):
  s=understand.snapshot(self.con,'p');out=self.output();out['subprojects'][0]['abc_basis']=[x for x in out['subprojects'][0]['abc_basis'] if x['id'] not in ('b','c')];evidence=[{'key':'lobby','id':tid,'reason':'完整语境支持','keep':True,'source_refs':[{'artifact_id':'art','quote':'酒店大堂'}]} for tid in ('b','c')]
  self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(s),db.js(s),None,'',db.now(),db.now()));self.con.commit()
  with patch('app.llm.chat_json',side_effect=[out,{'evidence':evidence}]) as chat:understand.run('r')
  r=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(r['status'],'succeeded',r['error']);self.assertEqual(chat.call_count,2);self.assertEqual(self.con.execute('select count(*) from subprojects').fetchone()[0],2)
 def test_cross_class_c_is_excluded_with_visible_review_note(self):
  out=self.output();out['subprojects'][0]['target_cs']=['other'];result=understand.validate(self.con,understand.snapshot(self.con,'p'),out);self.assertEqual(result['subprojects'][0]['target_cs'],[]);self.assertTrue(result['subprojects'][0]['rejected_labels']);self.assertTrue(result['warnings'])
 def test_followup_retains_stable_constraints_without_old_recipe(self):
  parent=model.brief({'product':{'substrate':'乳化基底'},'planning':{'launch_tier':'S'},'commercial':{'target_price':90,'sample_due':'旧交期'},'scent':{'structure':'旧比例'},'customer_requirements':[{'text':'合规文件','category':'document'},{'text':'旧比例','category':'scent'}]});child=model.followup_defaults(parent,{'scent':{'structure':'新比例'}})
  self.assertEqual(child['planning']['launch_tier'],'S');self.assertEqual(child['product']['substrate'],'乳化基底');self.assertEqual(child['commercial']['target_price'],90);self.assertEqual(child['commercial']['sample_due'],'');self.assertEqual(child['scent']['structure'],'新比例');self.assertEqual([r['text'] for r in child['customer_requirements']],['合规文件'])
 def test_unstarted_task_refreshes_brief_but_done_snapshot_is_immutable(self):
  sp=self.insert_sp(task_type='create');workflow.start(self.con,sp);t=db.one(self.con,'select * from department_tasks where subproject_id=?',(sp['id'],));b=model.brief({'scent':{'structure':'更新结构'}});db.save_brief(self.con,'p',b,sp['id']);workflow.start(self.con,sp);fresh=db.one(self.con,'select * from department_tasks where id=?',(t['id'],));self.assertEqual(json.loads(fresh['payload_json'])['requirements']['scent']['structure'],'更新结构');self.con.execute("update department_tasks set status='done' where id=?",(t['id'],));db.save_brief(self.con,'p',model.brief({'scent':{'structure':'再改'}}),sp['id']);workflow.start(self.con,sp);self.assertEqual(db.one(self.con,'select payload_json from department_tasks where id=?',(t['id'],))['payload_json'],fresh['payload_json'])
 def test_ratio_change_cannot_leave_parent_structure_unchanged(self):
  sp=self.insert_sp();b=model.brief({'scent':{'structure':'80/20'}});db.save_brief(self.con,'p',b,sp['id']);self.con.commit();out=self.output();item=out['subprojects'][0];item.update(task_type='modify',parent_subproject_id=sp['id']);item['brief']['modification']='调整两部分配比为各半';item['brief']['scent']={'structure':'80/20'}
  with self.assertRaisesRegex(ValueError,'气味结构'):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_already_completed_shipment_can_sync_later_recorded_code(self):
  parent=self.insert_sp(id='parent');tid=workflow.ensure(self.con,parent,'寄样');self.con.execute("update department_tasks set status='done',result='已寄出' where id=?",(tid,));child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='parent');workflow.start(self.con,child);workflow.update(self.con,tid,{'status':'done','result':'同步实发编号','shipped_codes':['trial-actual']});self.assertEqual(db.one(self.con,"select * from subprojects where id='child'")['base_formula_code'],'trial-actual');self.assertEqual(db.one(self.con,"select * from department_tasks where subproject_id='child' and type='调香'")['status'],'todo')
 def test_actual_shipment_replaces_provisional_parent_selection(self):
  parent=self.insert_sp(id='parent',selected_codes_json='["one"]');child=self.insert_sp(id='child',task_type='modify',parent_subproject_id='parent');workflow.start(self.con,child);tid=workflow.ensure(self.con,parent,'寄样');workflow.update(self.con,tid,{'status':'done','result':'实际寄出新试样号','shipped_codes':['actual-prototype']});self.assertEqual(db.one(self.con,"select * from subprojects where id='child'")['base_formula_code'],'actual-prototype')
 def test_model_can_reference_actual_shipped_prototype_outside_library(self):
  parent=self.insert_sp(id='parent',task_type='create');tid=workflow.ensure(self.con,parent,'寄样');self.con.execute("update department_tasks set status='done',payload_json=? where id=?",(db.js({'shipped_codes':['prototype-v1']}),tid));self.con.commit();out=self.output();out['subprojects'][0].update(task_type='modify',parent_subproject_id=parent['id'],base_formula_code='prototype-v1');validated=understand.validate(self.con,understand.snapshot(self.con,'p'),out);self.assertEqual(validated['subprojects'][0]['base_formula_code'],'prototype-v1')
 def test_followup_semantic_repair_is_bounded_and_preserves_fact_fields(self):
  parent=self.insert_sp(id='parent');db.save_brief(self.con,'p',model.brief({'scent':{'structure':'80/20'}}),'parent');self.con.execute("update artifacts set text=text||'两者各半。' where id='art'");self.con.commit();s=understand.snapshot(self.con,'p');out=self.output();out['subprojects'][0].update(task_type='modify',parent_subproject_id='parent');out['subprojects'][0]['brief'].update(modification='调整比例为各半',scent={'structure':'80/20'});ref={'artifact_id':'art','quote':'两者各半'};fix={'updates':[{'key':'lobby','scent':{'structure':'两者各半','old_formula':''},'scent_requirements':[{'text':'两者各半','category':'scent','source_scope':'specific','source_refs':[ref],'status':'recorded'}],'reason':'最新局部要求覆盖旧比例'}]};self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(s),db.js(s),None,'',db.now(),db.now()));self.con.commit()
  with patch('app.llm.chat_json',side_effect=[out,fix]) as chat:understand.run('r')
  run=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(run['status'],'succeeded',run['error']);self.assertEqual(chat.call_count,2);self.assertEqual(json.loads(run['output_json'])['result']['subprojects'][0]['brief']['scent']['structure'],'两者各半')
 def test_followup_inherits_known_manual_customer_constraint(self):
  parent=self.insert_sp(id='parent');db.save_brief(self.con,'p',model.brief({'customer_requirements':[{'text':'无指定原料','category':'compliance','source':'evaluator','status':'recorded'}]}),'parent');self.con.commit();out=self.output();out['subprojects'][0].update(task_type='modify',parent_subproject_id='parent');result=understand.validate(self.con,understand.snapshot(self.con,'p'),out);self.assertTrue(any(r['text']=='无指定原料' for r in result['subprojects'][0]['brief']['requirement_register']))

 def test_reference_pyramid_cannot_become_a_even_with_a_reason(self):
  out=self.output();out['subprojects'][0]['abc_basis'][0]['evidence_role']='reference_pyramid'
  with self.assertRaisesRegex(ValueError,'ABC'):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_reference_pyramid_is_allowed_for_b_and_c(self):
  out=self.output()
  for basis in out['subprojects'][0]['abc_basis']:
   if basis['id'] in ('b','c'):basis['evidence_role']='reference_pyramid'
  self.assertTrue(understand.validate(self.con,understand.snapshot(self.con,'p'),out))
 def test_natural_feeling_is_not_a_natural_origin_claim(self):
  b=model.brief({'customer_requirements':[{'text':'闻起来天然','category':'scent'},{'text':'提供天然来源证明','category':'document'},{'text':'支持对外天然来源宣称','category':'claim'}]})
  self.assertEqual([r['text'] for r in b['customer_requirements']],['提供天然来源证明','支持对外天然来源宣称']);self.assertEqual(b['requirement_register'][0]['text'],'闻起来天然')
 def test_normal_requirements_not_special_and_no_information_is_lost(self):
  req=[{'text':'DPM相容','category':'substrate'},{'text':'10/12前收到','category':'delivery'},{'text':'留香久','category':'performance'}];b=model.brief({'customer_requirements':req});self.assertEqual(b['customer_requirements'],[]);self.assertEqual([r['text'] for r in b['requirement_register']],[r['text'] for r in req]);self.assertEqual(model.brief(b),b)
 def test_compact_ontology_roundtrips_every_id_definition_and_path(self):
  restored=business.expand(business.ontology(self.con))
  for table in ('terms','c_nodes','categories'):
   original=db.rows(self.con,'select '+('id,domain,layer,label,definition' if table=='terms' else '*')+' from '+('category_map' if table=='categories' else table));self.assertEqual(sorted(restored[table],key=lambda x:str(x.get('id',x.get('k_code')))),sorted(original,key=lambda x:str(x.get('id',x.get('k_code')))))
 def test_default_understanding_disables_hidden_thinking(self):
  budget=business.budget(understand.snapshot(self.con,'p'),{});self.assertIsNone(budget['reasoning_effort']);self.assertFalse(budget['thinking']);self.assertEqual(budget['max_tokens'],24000)

 def test_source_handle_resolves_to_original_span(self):
  arts={a['id']:a for a in understand.snapshot(self.con,'p')['artifacts']};refs=[{'source_id':'S1'}];understand.refs_valid(refs,arts);r=refs[0];self.assertEqual(r['artifact_id'],'art');self.assertEqual(arts['art']['text'][r['source_start']:r['source_end']],arts['art']['text'])
 def test_nonexistent_source_handle_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'不存在'):understand.refs_valid([{'source_id':'S9999'}],{'art':{'id':'art','text':'原文','text_meta_json':'[]'}})
 def test_source_handle_does_not_allow_altered_numeric_quote(self):
  with self.assertRaisesRegex(ValueError,'原话'):understand.refs_valid([{'source_id':'S1','quote':'价格200'}],{'art':{'id':'art','text':'价格100','text_meta_json':'[]'}})
 def test_source_handle_cannot_point_to_another_artifact(self):
  with self.assertRaisesRegex(ValueError,'不一致'):understand.refs_valid([{'source_id':'S1','artifact_id':'other'}],{'art':{'id':'art','text':'原文','text_meta_json':'[]'}})
 def test_context_compacts_references_without_cutting_original_text(self):
  sp=self.insert_sp();b=model.brief({'evidence':{'scent.theme':[{'artifact_id':'art','quote':'酒店大堂'}]}});db.save_brief(self.con,'p',b,sp['id']);snapshot=understand.snapshot(self.con,'p');compact=understand.inference_context(snapshot);self.assertEqual(compact['artifacts'][0]['text'],snapshot['artifacts'][0]['text']);self.assertEqual(compact['briefs'][0]['data']['evidence']['scent.theme'],[{'source_id':'S1'}])
 def test_thinking_false_is_sent_even_for_understanding_node(self):
  data={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],'usage':{'prompt_tokens':10,'completion_tokens':2}};reply=__import__('io').BytesIO(db.js(data).encode());llm.begin('p','understand_project_v3')
  with patch('app.llm.provider',return_value=('deepseek',{'base_url':'https://example.test','api_key':'test','model':'model'})),patch('app.llm.urllib.request.urlopen',return_value=reply) as send:
   self.assertEqual(llm.chat([],thinking=False),'{}');body=json.loads(send.call_args.args[0].data);self.assertEqual(body['thinking'],{'type':'disabled'});self.assertNotIn('reasoning_effort',body)
 def test_output_limit_saves_partial_diagnostic_without_overwriting_project(self):
  sp=self.insert_sp();snapshot=understand.snapshot(self.con,'p');self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(snapshot),db.js(snapshot),None,'',db.now(),db.now()));self.con.commit();error=llm.ModelOutputLimit({'completion_tokens':16000,'content_characters':8},'{"brief":')
  with patch('app.llm.chat_json',side_effect=error):understand.run('r')
  run=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(run['status'],'failed');self.assertEqual(json.loads(run['output_json'])['diagnostics']['partial_content'],'{"brief":');self.assertEqual(db.one(self.con,"select * from subprojects where id='s'")['title'],sp['title'])
 def test_deep_thinking_requires_explicit_configuration(self):
  snapshot=understand.snapshot(self.con,'p');snapshot['artifacts']*=10;self.assertFalse(business.budget(snapshot,{})['thinking']);self.assertTrue(business.budget(snapshot,{'understanding_thinking':True})['thinking'])
 def test_json_failure_does_not_silently_repeat_on_another_provider(self):
  with patch('app.llm.chat',side_effect=RuntimeError('network')) as chat:
   with self.assertRaisesRegex(RuntimeError,'network'):llm.chat_json([])
  self.assertEqual(chat.call_count,1)

 def seed_tf(self):
  for code,name,brand,product,relation in [('tf1','白麝香','汤姆福特 Tom Ford','White Suede','仿香对象'),('tf2','TOM FORD WHITE SUEDE','汤姆福特 Tom Ford','White Suede／白麝香','名称明确同款'),('tf3','TF 白麝香（暗麝心魄）','汤姆福特 Tom Ford','White Suede','仿香对象'),('guerlain','幽白麝','娇兰 Guerlain','白麝香','名称明确同款')]:
   self.con.execute('insert into library_items(code,name,new_class,brand_tags_json,price) values(?,?,?,?,?)',(code,name,'个人香氛',db.js([brand]),100))
   self.con.execute('insert into formula_product_labels values(?,?,?,?,?)',(code,brand,product,relation,'brand_product_labels'))
  self.con.commit()
 def test_brand_and_bilingual_product_search(self):
  self.seed_tf();index=identity.Index(self.con)
  for query in ('TF','TF白麝香','TF 白麝香','Tom Ford White Suede','汤姆福特白麝香','White Suede','白麝香TF'):
   with self.subTest(query=query):
    rows,total=index.search(query);self.assertEqual({r['code'] for r in rows},{'tf1','tf2','tf3'});self.assertEqual(total,3)
  rows,total=index.search('tf1');self.assertEqual(rows[0]['code'],'tf1');self.assertEqual(total,1)
 def test_find_product_alias_and_brand_filter_share_identity_rules(self):
  self.seed_tf();rows,_=reco.find_product(self.con,self.sp(new_class='个人香氛',target_products_json=db.js([{'brand':'TF','product':'白麝香'}])))
  self.assertEqual({r['code'] for r in rows},{'tf1','tf2','tf3'});self.assertTrue(all(r['product_identity'] for r in rows))
  self.assertTrue(reco.brand_matches({'brand_tags_json':db.js(['汤姆福特 Tom Ford'])},[{'kind':'brand','value':'TF'}]));self.assertFalse(identity.same_brand('TF','娇兰 Guerlain'))
 def test_approximate_reference_does_not_become_exact_product(self):
  self.seed_tf();self.con.execute("insert into formula_product_labels values('other','汤姆福特 Tom Ford','White Suede','近似参考','manual')")
  rows,_=reco.find_product(self.con,self.sp(new_class='个人香氛',target_products_json=db.js([{'brand':'TF','product':'白麝香'}])))
  self.assertNotIn('other',{r['code'] for r in rows})
 def test_brand_recommendation_cannot_silently_skip_all_mapping(self):
  out=self.output();item=out['subprojects'][0]
  for field in ('a1','a2','a3','b','target_cs','abc_basis'):item[field]=[]
  with self.assertRaisesRegex(ValueError,'ABC语义映射未完成'):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
  rows,meta=reco.recommend(self.con,self.sp(a1_json='[]',a2_json='[]',a3_json='[]',b_json='[]',target_cs_json='[]'))
  self.assertEqual(rows,[]);self.assertTrue(meta['needs_abc_review'])
 def test_real_empty_mapping_requires_per_domain_explanation(self):
  out=self.output();item=out['subprojects'][0]
  for field in ('a1','a2','a3','b','target_cs','abc_basis'):item[field]=[]
  item['mapping_review']={domain:{'status':'insufficient_context','reason':'本域未提供可判断信息','source_refs':[{'source_id':'S1'}]} for domain in 'ABC'}
  understand.validate(self.con,understand.snapshot(self.con,'p'),out)
  item['brief']['scent']['feelings']=['清新']
  with self.assertRaisesRegex(ValueError,'ABC语义映射未完成'):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
 def test_omitted_mapping_gets_one_batched_semantic_repair(self):
  snapshot=understand.snapshot(self.con,'p');out=self.output();original=copy.deepcopy(out['subprojects'][0]);item=out['subprojects'][0]
  for field in ('a1','a2','a3','b','target_cs','abc_basis'):item[field]=[]
  update={k:original[k] for k in ('key','a1','a2','a3','b','target_cs','abc_basis')}
  self.con.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',('r','p','queued','',understand.input_hash(snapshot),db.js(snapshot),None,'',db.now(),db.now()));self.con.commit()
  with patch('app.llm.chat_json',side_effect=[out,{'updates':[update]}]) as chat:understand.run('r')
  result=db.one(self.con,"select * from generation_runs where id='r'");self.assertEqual(result['status'],'succeeded',result['error']);self.assertEqual(chat.call_count,2)
  sub=db.one(self.con,"select * from subprojects where task_type='recommend_brand'");self.assertEqual(json.loads(sub['b_json']),['b']);self.assertEqual(json.loads(sub['target_cs_json']),['c'])
 def test_single_branch_root_facts_flow_to_parallel_find_without_double_quantity(self):
  self.seed_tf();out=self.output();out['subprojects']=out['subprojects'][:1]
  out['brief'].update(product={'name':'香水','dosage':'18%'},scent={'theme':'清新淡雅，花香为主'},deliverables={'quantity':'5~7款','type':'18%加香小样','notes':'不寄香精'})
  out['subprojects'][0]['brief']={};out['subprojects'][0]['target_products']=[{'brand':'TF','product':'白麝香'}]
  snapshot=understand.snapshot(self.con,'p');understand.prepare_contract(snapshot,out,self.con)
  self.assertEqual(len(out['subprojects']),2);style,find=out['subprojects'];self.assertEqual(find['task_type'],'find_product');self.assertFalse(find.get('parent_subproject_id'));self.assertEqual(find['brief']['product']['dosage'],'18%');self.assertEqual(find['brief']['deliverables']['notes'],'不寄香精');self.assertIn('合计5~7',find['brief']['deliverables']['quantity']);self.assertIn('其余',style['brief']['deliverables']['quantity']);self.assertEqual(style['brief']['scent']['theme'],'清新淡雅，花香为主');self.assertNotEqual(find['brief']['scent']['theme'],style['brief']['scent']['theme'])
  understand.prepare_contract(snapshot,out,self.con);self.assertEqual(len(out['subprojects']),2)
 def test_aggregate_scent_is_not_inherited_into_multiple_branches(self):
  out=self.output();out['brief']['scent']={'theme':'项目汇总：茶香与赠礼玫瑰香'};understand.prepare_contract(understand.snapshot(self.con,'p'),out,self.con)
  self.assertFalse(out['subprojects'][0]['brief'].get('scent',{}).get('theme'))
 def test_existing_find_alias_is_not_duplicated(self):
  self.seed_tf();self.insert_sp(task_type='find_product',new_class='个人香氛',target_products_json=db.js([{'brand':'Tom Ford','product':'White Suede'}]));out=self.output();out['subprojects'][0]['target_products']=[{'brand':'TF','product':'白麝香'}]
  result=understand.validate(self.con,understand.snapshot(self.con,'p'),out);self.assertEqual(len(result['subprojects']),2);self.assertFalse(result['subprojects'][0]['target_products'])
 def test_required_product_must_have_parallel_find_entry(self):
  self.seed_tf();out=self.output();out['brief']['deliverables']={'quantity':'5–7款，含指定款1款','required_products':[{'brand':'TF','product':'白麝香','source_refs':[{'source_id':'S1'}]}]}
  with self.assertRaisesRegex(ValueError,'必选产品'):understand.validate(self.con,understand.snapshot(self.con,'p'),out)
  out['subprojects'][1].update(task_type='find_product',target_products=[{'brand':'Tom Ford','product':'White Suede'}])
  understand.validate(self.con,understand.snapshot(self.con,'p'),out)

 def test_each_product_reports_its_own_unverified_version(self):
  self.con.execute("insert into formula_product_labels values('one','Le Labo','Another 13','同款','人工')")
  missing={'brand':'Chanel','product':'No 5','version':'EDP'}
  rows,meta=reco.find_product(self.con,self.sp(target_products_json=db.js([{'brand':'Le Labo','product':'Another 13'},missing])))
  self.assertEqual(len(rows),1);self.assertEqual(meta['unverified_versions'],[missing])
 def test_restore_defaults_uses_backend_rules(self):
  self.insert_sp(task_type='recommend_simple',brand_filter='Le Labo',wants_hot=1,wants_new=1)
  custom={'category_enabled':False,'categories':[],'price_enabled':False,'tags':[],'brand_enabled':False,'hot_enabled':False,'new_enabled':False}
  self.assertEqual(self.request('/api/subprojects/s','PATCH',{'hard_filters':custom})[0],200)
  self.assertEqual(self.request('/api/subprojects/s','PATCH',{'reset_filters':True})[0],200)
  sp=db.one(self.con,"select * from subprojects where id='s'");self.assertEqual(db.jload(sp['hard_filters_json']),reco.default_filters(sp))
  self.assertEqual(self.request('/api/subprojects/s','PATCH',{'reset_filters':True,'hard_filters':custom})[0],400)
 def test_invalid_uploads_are_client_errors_without_partial_files(self):
  code,result=self.request('/api/projects/p/artifacts','POST',{'filename':'bad.pdf','data_base64':'!not-base64!'})
  self.assertEqual(code,400);self.assertIn('base64',result['error']);self.assertEqual(len(list(db.UPLOADS.iterdir())),0)
  sp=self.insert_sp();tid=workflow.ensure(self.con,sp,'分析');self.con.commit()
  self.assertEqual(self.request('/api/tasks/'+tid+'/files','POST',{'data_base64':'!bad!'})[0],400)
  self.assertEqual(db.rows(self.con,'select * from task_files'),[])
 def test_oversize_request_is_rejected_before_reading_body(self):
  self.request('/api/health')
  req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}/api/projects',data=b'{}',headers={'Content-Type':'application/json','Content-Length':str(73*1024*1024)},method='POST')
  with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req,timeout=3)
  self.assertEqual(caught.exception.code,400);caught.exception.close()
 def test_qa_uses_documented_live_prompt(self):
  with patch('app.llm.chat_json',return_value={'answer':'用于酒店大堂','citations':[{'artifact_id':'art','quote':'酒店大堂'}]}) as chat:
   self.assertEqual(self.request('/api/projects/p/qa','POST',{'q':'用于哪里？'})[0],200)
  self.assertEqual(chat.call_args.args[0][0]['content'],(db.ROOT/'prompts/qa.md').read_text(encoding='utf-8'))
 def test_creation_audits_cover_project_artifact_and_sample(self):
  status,result=self.request('/api/projects','POST',{'name':'审计项目'});self.assertEqual(status,200);self.assertTrue(db.one(self.con,"select id from decisions where entity='project' and entity_id=? and field='created'",(result['id'],)))
  with patch.object(Handler,'_auto_classify',return_value=None):status,result=self.request('/api/projects/p/artifacts','POST',{'text':'客户补充资料'})
  self.assertEqual(status,200);self.assertTrue(db.one(self.con,"select id from decisions where entity='artifact' and entity_id=? and field='created'",(result['id'],)))
  self.insert_sp();self.assertEqual(self.request('/api/subprojects/s/samples','POST',{'product':'客户原样'})[0],200)
  sample=db.one(self.con,'select id from external_samples');self.assertTrue(db.one(self.con,"select id from decisions where entity='sample' and entity_id=? and field='created'",(sample['id'],)))
 def test_overall_delivery_reaches_pending_tasks_but_not_done_snapshots(self):
  sp=self.insert_sp();db.save_brief(self.con,'p',model.brief({'deliverables':{'type':'18%加香小样','quantity':'5~7款总组合','notes':'只寄成品小样，不寄香精'}}))
  todo=workflow.ensure(self.con,sp,'打样');done=workflow.ensure(self.con,sp,'寄样');self.con.execute("update department_tasks set status='done',payload_json=? where id=?",(db.js({'locked':True}),done));Handler.refresh_pending(self.con,sp)
  payload=db.jload(db.one(self.con,'select payload_json from department_tasks where id=?',(todo,))['payload_json']);self.assertIn('不寄香精',payload['handoff']);self.assertEqual(payload['project_delivery']['quantity'],'5~7款总组合')
  self.assertEqual(db.jload(db.one(self.con,'select payload_json from department_tasks where id=?',(done,))['payload_json']),{'locked':True})

 def test_stale_scoring_cache_rebuilds_without_losing_decision_or_history(self):
  sp=self.insert_sp(selected_codes_json='["one"]');items,_=service.recommendations(self.con,sp);old=db.one(self.con,'select * from recommendations');stored=db.jload(old['filters_json']);stored['signature']='former-candidate-c-ab'
  self.con.execute('update recommendations set filters_json=? where id=?',(db.js(stored),old['id']));self.con.execute("update recommendation_items set decision='shortlist' where id=?",(items[0]['id'],))
  fresh,meta=service.recommendations(self.con,sp);self.assertNotEqual(fresh[0]['id'],items[0]['id']);self.assertEqual(fresh[0]['decision'],'shortlist');self.assertEqual(meta['algorithm'],'v3-demand-c-ab-2');self.assertEqual(db.one(self.con,"select selected_codes_json from subprojects where id='s'")['selected_codes_json'],'["one"]');self.assertTrue(db.one(self.con,'select id from recommendations where id=?',(old['id'],)))

 def test_selected_label_name_corrects_wrong_b_id(self):
  out=self.output();basis=next(b for b in out['subprojects'][0]['abc_basis'] if b['id']=='b');basis['label']='清新';basis['reason']='客户期望清新感'
  result=understand.validate(self.con,understand.snapshot(self.con,'p'),out,require_label_names=True);item=result['subprojects'][0]
  self.assertEqual(item['b'],['b2']);self.assertEqual(next(b for b in item['abc_basis'] if b['label']=='清新')['id'],'b2');self.assertEqual(item['label_identity_corrections'][0]['old_id'],'b')
 def test_ambiguous_c_name_is_not_silently_resolved(self):
  self.con.execute("insert into c_nodes values('c-duplicate','空间香氛','气质','','酒店','气质/酒店','另一个维度')")
  out=self.output();item=out['subprojects'][0];item['target_cs']=['cx'];basis=next(b for b in item['abc_basis'] if b['id']=='c');basis.update(id='cx',label='酒店')
  with self.assertRaisesRegex(ValueError,'ABC推断缺少'):understand.validate(self.con,understand.snapshot(self.con,'p'),out,require_label_names=True)
 def test_new_generation_requires_label_id_pairs(self):
  out=self.output();out['subprojects'][0]['abc_basis'][0].pop('label')
  with self.assertRaisesRegex(ValueError,'ABC推断缺少'):understand.validate(self.con,understand.snapshot(self.con,'p'),out,require_label_names=True)

 def seed_name_catalog(self):
  for code,brand,name in [('garden','Maison Demo','Garden Mist／花园晨雾'),('summer','Maison Demo',"Éclat d’Été 夏日之光"),('sea','Other House','Wood Sage & Sea Salt（鼠尾草海盐）')]:
   self.con.execute('insert into library_items(code,name,new_class,price,brand_tags_json) values(?,?,?,?,?)',(code,name,'个人香氛',100,db.js([brand])))
   self.con.execute('insert into formula_product_labels values(?,?,?,?,?)',(code,brand,name,'名称明确同款','fixture'))
  self.con.commit()
 def test_non_number_chinese_english_diacritic_and_spelling_aliases(self):
  self.seed_name_catalog();index=identity.Index(self.con)
  for brand,query,code in [('Maison Demo','花园晨雾','garden'),('Maison Demo','Garden Mist','garden'),('Maison Demo','Éclat d’Été','summer'),('Maison Demo',"Eclat d'Ete",'summer'),('Maison Demo','夏日之光','summer'),('Other House','鼠尾草海盐','sea'),('Other House','Wood Sage and Sea Salt','sea')]:
   with self.subTest(query=query):
    r=index.resolve(brand,query);self.assertEqual(r['status'],'matched');self.assertEqual(r['options'][0]['codes'],[code])
 def test_product_editions_are_not_stripped_as_translation_aliases(self):
  for text in ('Garden Mist（EDP）','Garden Mist（浓香精）','Garden Mist（高浓度）','Another 13／檀香33'):
   self.assertEqual(identity.bilingual_names(text),[])
  self.seed_name_catalog();index=identity.Index(self.con);self.assertEqual(index.resolve('Maison Demo','Garden Mist',version='EDP')['status'],'unmatched');self.assertNotEqual(identity.product_key('Edition 1.3'),identity.product_key('Edition 13'))
 def test_numeric_shorthand_requires_brand_and_unique_complete_number(self):
  self.con.executemany('insert into formula_product_labels values(?,?,?,?,?)',[('one','Le Labo','Another 13','名称明确同款','fixture'),('two','Le Labo','Another 113','名称明确同款','fixture'),('three','Other','Perfume 13','名称明确同款','fixture')]);index=identity.Index(self.con)
  self.assertEqual(index.resolve('Le Labo','13')['options'][0]['codes'],['one']);self.assertEqual(index.resolve('Le Labo','3')['status'],'unmatched')
  rows,_=reco.find_product(self.con,self.sp(target_products_json=db.js([{'product':'13'}])));self.assertEqual(rows,[])
  self.con.execute("insert into formula_product_labels values('two','Le Labo','Rose 13','名称明确同款','fixture')");index=identity.Index(self.con);self.assertEqual(index.resolve('Le Labo','13')['status'],'ambiguous')
  rows,meta=reco.find_product(self.con,self.sp(target_products_json=db.js([{'brand':'Le Labo','product':'13'}])));self.assertEqual(rows,[]);self.assertEqual(meta['resolutions'][0]['status'],'ambiguous')
 def test_custom_aliases_work_for_arbitrary_names_and_brand_aliases(self):
  self.seed_name_catalog();before=self.con.execute('select count(*) from formula_product_labels').fetchone()[0]
  for body in [{'kind':'product','brand':'Maison Demo','product':'Garden Mist','alias':'晨雾'},{'kind':'product','brand':'Maison Demo','product':'Garden Mist','alias':'客户叫法甲'},{'kind':'brand','brand':'Maison Demo','alias':'示例香坊'},{'kind':'brand','brand':'Maison Demo','alias':'MD'}]:self.assertEqual(self.request('/api/library/aliases','POST',body)[0],200)
  index=identity.Index(self.con)
  for brand,query in [('示例香坊','晨雾'),('MD','客户叫法甲'),('Maison Demo','晨雾')]:self.assertEqual(index.resolve(brand,query)['options'][0]['codes'],['garden'])
  self.assertEqual(self.con.execute('select count(*) from formula_product_labels').fetchone()[0],before);self.assertTrue(db.rows(self.con,"select * from decisions where entity='identity_alias'"))
 def test_ambiguous_custom_alias_does_not_merge_distinct_products(self):
  self.seed_name_catalog()
  for product in ('Garden Mist','Éclat d’Été 夏日之光'):
   identity.register_alias(self.con,{'brand':'Maison Demo','product':product,'alias':'清爽款'})
  index=identity.Index(self.con);r=index.resolve('Maison Demo','清爽款');self.assertEqual(r['status'],'ambiguous');self.assertEqual(len(r['options']),2)
  rows,meta=reco.find_product(self.con,self.sp(new_class='个人香氛',target_products_json=db.js([{'brand':'Maison Demo','product':'清爽款'}])));self.assertEqual(rows,[]);self.assertEqual(meta['resolutions'][0]['status'],'ambiguous')
  self.assertEqual(index.resolve('Maison Demo','Garden Mist')['options'][0]['codes'],['garden'])
 def test_catalogue_api_and_structured_search(self):
  self.seed_name_catalog();status,data=self.request('/api/library/catalog?brand=Maison%20Demo');self.assertEqual(status,200);self.assertEqual(len(data['products']),2)
  status,data=self.request('/api/library/search?brand=Maison%20Demo&product=Garden%20Mist');self.assertEqual(status,200);self.assertEqual([r['code'] for r in data['items']],['garden'])
 def test_known_identity_filtered_out_is_not_reported_as_absent(self):
  self.seed_name_catalog();sp=self.sp(new_class='个人香氛',price_target=50,price_elasticity=0,target_products_json=db.js([{'brand':'Maison Demo','product':'Garden Mist'}]));rows,meta=reco.find_product(self.con,sp)
  self.assertEqual(rows,[]);self.assertEqual(meta['identity_total'],1);self.assertEqual(meta['excluded_identity_records'][0]['reason'],'超过当前价格上限');self.assertIn('库中已有',meta['message'])
  sp['price_target']=None;sp['new_class']='空间香氛';rows,meta=reco.find_product(self.con,sp);self.assertEqual(rows,[]);self.assertEqual(meta['excluded_identity_records'][0]['reason'],'品类不适用')
 def test_alias_changes_invalidate_cached_resolution_and_delete_is_audited(self):
  self.seed_name_catalog();sp=self.insert_sp(task_type='find_product',new_class='个人香氛',target_products_json=db.js([{'brand':'Maison Demo','product':'晨雾'}]));self.assertEqual(service.recommendations(self.con,sp)[0],[])
  aid=identity.register_alias(self.con,{'brand':'Maison Demo','product':'Garden Mist','alias':'晨雾'});self.con.commit();rows,_=service.recommendations(self.con,sp);self.assertEqual([r['code'] for r in rows],['garden'])
  self.con.commit();self.assertEqual(self.request('/api/library/aliases/'+aid,'DELETE')[0],200);self.assertEqual(service.recommendations(self.con,sp)[0],[]);self.assertTrue(db.one(self.con,"select id from decisions where entity='identity_alias' and field='deleted'"))
 def test_reference_only_label_is_not_a_confirmed_catalogue_product(self):
  self.seed_name_catalog();self.con.execute("insert into formula_product_labels values('other','Maison Demo','Secret Garden','近似参考','fixture')");index=identity.Index(self.con)
  self.assertEqual(index.resolve('Maison Demo','Secret Garden')['status'],'unmatched');self.assertNotIn('Secret Garden',[p['product'] for p in index.catalog('Maison Demo')['products']])

 def test_existing_brand_normalization_source_is_reused(self):
  self.con.execute("insert into formula_product_labels values('one','Le Labo','Another 13','名称明确同款','fixture')");index=identity.Index(self.con)
  self.assertTrue(identity.same_brand('Jo Malone','祖玛珑 Jo Malone London'));self.assertTrue(identity.same_brand('香水实验室','Le Labo'))
  for name in ('13','13号','No.13','N°13'):
   self.assertEqual(index.resolve('香水实验室',name)['options'][0]['codes'],['one'])
 def test_brand_alias_cannot_merge_two_brands(self):
  self.seed_name_catalog();self.assertEqual(self.request('/api/library/aliases','POST',{'kind':'brand','brand':'Maison Demo','alias':'MD'})[0],200)
  self.assertEqual(self.request('/api/library/aliases','POST',{'kind':'brand','brand':'Other House','alias':'MD'})[0],400)
  self.assertEqual(self.request('/api/library/aliases','POST',{'kind':'brand','brand':'Other House','alias':'Maison Demo'})[0],400)
  self.assertFalse(identity.same_brand('Maison Demo','Other House'))
 def test_complete_product_name_takes_priority_over_brand_prefix_split(self):
  self.seed_name_catalog();self.con.execute("insert into formula_product_labels values('garden','Maison Demo','Maison Demo Mist／示例晨雾','名称明确同款','fixture')");index=identity.Index(self.con)
  rows,total=index.search('Maison Demo Mist');self.assertEqual(total,1);self.assertEqual(rows[0]['code'],'garden')

if __name__=='__main__':unittest.main(verbosity=2)
