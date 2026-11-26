import copy,unittest
import test_v3
from app import db,model,workflow,modification,service,contracts,understand,prompt_store,business

class Changes(unittest.TestCase):
 setUp=test_v3.Regression.setUp
 tearDown=test_v3.Regression.tearDown
 sp=test_v3.Regression.sp
 insert_sp=test_v3.Regression.insert_sp
 request=test_v3.Regression.request
 def draft(self,code='one',parent=None):
  sp=self.insert_sp(task_type='modify',base_formula_code=code,parent_subproject_id=parent)
  modification.save(self.con,sp,{'base_formula_code':code,'modification':'降低成本，保持主体气味；提交两版试样。'})
  return db.one(self.con,'select * from subprojects where id=?',(sp['id'],))
 def test_draft_has_base_change_and_no_recommendation(self):
  sp=self.draft();st=modification.state(self.con,sp);self.assertTrue(st['ready']);self.assertFalse(st['locked'])
  task=db.one(self.con,'select * from department_tasks where id=?',(st['task_id'],));self.assertEqual(task['status'],'draft')
  self.assertEqual(service.recommendations(self.con,sp)[0],[]);self.assertEqual(db.rows(self.con,'select * from recommendations'),[])
  with self.assertRaises(ValueError):workflow.choose(self.con,sp,['two'])
  with self.assertRaises(ValueError):workflow.update(self.con,task['id'],{'status':'doing'})
  with self.assertRaises(ValueError):workflow.update(self.con,task['id'],{'status':'todo'})
 def test_dispatch_locks_base_and_preserves_started_requirements(self):
  sp=self.draft();tid=modification.dispatch(self.con,sp,{});sp=db.one(self.con,'select * from subprojects where id=?',(sp['id'],))
  self.assertTrue(modification.state(self.con,sp)['locked'])
  with self.assertRaises(ValueError):modification.save(self.con,sp,{'base_formula_code':'two'})
  self.con.commit();status,body=self.request('/api/subprojects/'+sp['id'],'PATCH',{'base_formula_code':'two'});self.assertEqual(status,400,body)
  workflow.update(self.con,tid,{'status':'doing'})
  with self.assertRaises(ValueError):modification.save(self.con,sp,{'modification':'另一版要求'})
  self.assertEqual(db.one(self.con,'select status from department_tasks where id=?',(tid,))['status'],'doing')
 def test_invalid_base_cannot_dispatch_and_http_is_atomic(self):
  sp=self.draft('absent');self.con.commit();before=db.one(self.con,'select version from briefs where subproject_id=?',(sp['id'],))['version']
  status,body=self.request('/api/subprojects/'+sp['id']+'/workflow','POST',{'action':'dispatch_modification','modification':'新要求'})
  self.assertEqual(status,400,body);self.assertEqual(db.one(self.con,'select version from briefs where subproject_id=?',(sp['id'],))['version'],before)
 def test_real_shipment_prototype_can_be_base_without_library_insert(self):
  parent=self.insert_sp(id='parent');tid=workflow.ensure(self.con,parent,'寄样');self.con.execute("update department_tasks set status='done',payload_json=? where id=?",(db.js({'shipped_codes':['prototype-R2']}),tid))
  sp=self.draft('prototype-R2','parent');self.assertTrue(modification.state(self.con,sp)['base_verified']);modification.dispatch(self.con,sp,{})
  self.assertFalse(db.one(self.con,'select code from library_items where code=?',('prototype-R2',)))
 def test_multiple_parent_codes_not_implicitly_selected(self):
  self.insert_sp(id='parent',selected_codes_json=db.js(['one','two']));sp=self.insert_sp(task_type='modify',parent_subproject_id='parent');workflow.start(self.con,sp)
  sp=db.one(self.con,'select * from subprojects where id=?',(sp['id'],));self.assertFalse(sp['base_formula_code']);self.assertEqual(len(modification.state(self.con,sp)['base_options']),2)
 def test_typed_explicit_local_identity_can_bind_but_title_cannot(self):
  sp=self.insert_sp(task_type='modify');bd=model.brief({'product':{'name':'one'},'modification':'降低成本'});db.save_brief(self.con,'p',bd,sp['id']);self.con.execute("update artifacts set text='one需要降低成本' where id='art'");workflow.start(self.con,sp)
  self.assertEqual(db.one(self.con,'select base_formula_code from subprojects where id=?',(sp['id'],))['base_formula_code'],'one')
 def test_tag_objects_normalize_before_hashing_and_unknown_shapes_fail(self):
  value={'subprojects':[{'key':'new','a1':[{'id':'a1','label':'茶'}],'a2':[],'a3':[],'b':[],'target_cs':[]}],'coverage':[{'subproject_keys':[{'key':'new'}]}]};contracts.normalize(value)
  self.assertEqual(value['subprojects'][0]['a1'],['a1']);self.assertEqual(value['coverage'][0]['subproject_keys'],['new']);self.assertTrue(value['contract_corrections'])
  with self.assertRaisesRegex(ValueError,'文本标识'):contracts.normalize({'a1':[{'label':'茶'}]})
  with self.assertRaises(ValueError):understand.refs_valid([{'artifact_id':{}}],{})
 def test_quote_whitespace_and_split_keep_original_and_counts(self):
  arts={'art':{'id':'art','text':'第一项要求。\n中间另有说明。\n第二项要求。','filename':'test','text_meta_json':'[]'}}
  refs=[{'artifact_id':'art','quote':'第一项 要求。；第二项 要求。'}];understand.refs_valid(refs,arts)
  self.assertEqual(len(refs),2);self.assertTrue(all(r['correction']=='split' and r['model_quote']=='第一项 要求。；第二项 要求。' for r in refs));self.assertIn('whitespace',refs[0]['corrections'])
  stats=contracts.reference_stats({'source_refs':refs});self.assertEqual(stats['occurrences'],2);self.assertEqual(stats['unique_spans'],2)
 def test_prompt_revision_and_preflight_do_not_weaken_contract(self):
  self.assertEqual(len(prompt_store.revision()),64);self.assertIn('label',prompt_store.system('repair_mapping'));self.assertNotIn('TF白麝',prompt_store.system('understand_project'))
  self.insert_sp();snap=understand.snapshot(self.con,'p');snap['subprojects']*=80;self.assertTrue(business.preflight(snap,{})['compact']);self.assertTrue(business.budget(snap,{})['max_tokens']>0)
