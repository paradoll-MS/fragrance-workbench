from pathlib import Path
import sys,json,time,copy
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));from app import db,llm,model,understand,business
out=root/'data/verification/semantic_policy';out.mkdir(parents=True,exist_ok=True);c=db.connect();r=db.one(c,'select * from generation_runs where id=?',('g_98d393ced37d4fc4',));s=json.loads(r['input_json'])
for a in s['artifacts']:
 ocr=json.loads((out/(a['id']+'_ocr.json')).read_text(encoding='utf-8'));a['text']=ocr['text'];a['text_meta_json']=db.js([{'locator':'图片原文','text':a['text']}])
contract=model.brief();contract['planning']=dict(launch_tier='',development_target='',commercialization_target='',launch_timing='',priority_reason='');payload=json.dumps({'ontology':business.ontology(c),'canonical_brief_contract':contract,'context':understand.inference_context(s)},ensure_ascii=False,separators=(',',':'));system=(root/'spec/business_rules.md').read_text(encoding='utf-8')+'\n'+(root/'prompts/understand_project.md').read_text(encoding='utf-8');llm.begin(s['project']['id'],'understand_policy_verification');start=time.perf_counter();result=llm.chat_json([{'role':'system','content':system},{'role':'user','content':payload}],**business.budget(s,llm.config()),temperature=0.1);elapsed=time.perf_counter()-start
(out/'ouyin_fresh_output.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
try:
 valid=understand.validate(c,s,result);terms={x['id']:x['label'] for x in db.rows(c,'select id,label from terms')};items=[{'title':x['title'],'a':{k:[terms[t] for t in x.get(k,[])] for k in ('a1','a2','a3')},'extra':x['brief']['customer_requirements'],'scent':x['brief']['scent']} for x in valid['subprojects']];report={'elapsed':round(elapsed,2),'input_chars':len(payload),'passed':True,'items':items}
except Exception as e:report={'elapsed':round(elapsed,2),'input_chars':len(payload),'passed':False,'error':str(e)}
(out/'ouyin_fresh_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');c.close();print(json.dumps({k:v for k,v in report.items() if k!='items'},ensure_ascii=True),flush=True)
