from pathlib import Path
import sys,time,json,concurrent.futures
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));from app import db,llm
out=root/'data/verification/semantic_policy';out.mkdir(parents=True,exist_ok=True)
c=db.connect();arts=db.rows(c,'select * from artifacts where project_id=?',('p_219042a6344c4d89',));c.close()
def recognize(a):
 llm.begin(a['project_id'],'parse_policy_verification');started=time.perf_counter();text=llm.vision_describe((db.UPLOADS/a['stored_name']).read_bytes(),a['mime']);result={'artifact_id':a['id'],'elapsed':round(time.perf_counter()-started,2),'characters':len(text),'text':text};(out/(a['id']+'_ocr.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return {k:v for k,v in result.items() if k!='text'}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for result in pool.map(recognize,arts):print(json.dumps(result),flush=True)
