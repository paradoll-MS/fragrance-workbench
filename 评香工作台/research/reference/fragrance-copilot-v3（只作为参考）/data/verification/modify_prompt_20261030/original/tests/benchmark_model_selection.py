from pathlib import Path
import sys,json,time,concurrent.futures,copy
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));from app import db,llm,model,understand,business
label=sys.argv[1] if len(sys.argv)>1 else 'baseline';assert label.replace('_','').isalnum();folder=root/'data/verification/model_selection'/label;folder.mkdir(parents=True,exist_ok=True);c=db.connect();r=db.one(c,'select * from generation_runs where id=?',('g_513e26b639c74432',));s=json.loads(r['input_json']);contract=model.brief();contract['planning']=dict(launch_tier='',development_target='',commercialization_target='',launch_timing='',priority_reason='');payload=json.dumps({'ontology':business.ontology(c),'canonical_brief_contract':contract,'context':understand.inference_context(s)},ensure_ascii=False,separators=(',',':'));system=(root/'spec/business_rules.md').read_text(encoding='utf-8')+'\n'+(root/'prompts/understand_project.md').read_text(encoding='utf-8');c.close()
def test(model_name):
 llm.begin(s['project']['id'],'model_selection_verification');start=time.perf_counter();report={'model':model_name,'thinking':False,'input_chars':len(payload)}
 try:
  result=llm.chat_json([{'role':'system','content':system},{'role':'user','content':payload}],model=model_name,provider_name='deepseek',thinking=False,max_tokens=24000,timeout=180,temperature=0.1);report['elapsed']=round(time.perf_counter()-start,2);(folder/(model_name+'_output.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');con=db.connect()
  try:
   validated=understand.validate(con,s,result);report.update(contract_passed=True,subprojects=[{'title':i['title'],'type':i['task_type'],'extra':i['brief']['customer_requirements']} for i in validated['subprojects']])
  except Exception as error:report.update(contract_passed=False,error=str(error))
  finally:con.close()
 except Exception as error:report.update(elapsed=round(time.perf_counter()-start,2),contract_passed=False,error=str(error))
 (folder/(model_name+'_report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='subprojects'},ensure_ascii=True),flush=True);return report
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(test,['deepseek-v4-pro','deepseek-flash']))
