"""Reconcile saved generated briefs after schema normalization changes; preserve all history."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,model,workflow,understand
from app.server import Handler
pid=sys.argv[1];c=db.connect();p=db.one(c,'select * from projects where id=?',(pid,));run=db.one(c,"select * from generation_runs where project_id=? and status='succeeded' order by rowid desc limit 1",(pid,))
if not run:raise RuntimeError('No successful generated output')
output=json.loads(run['output_json']);shared=(output.get('result') or {}).get('shared_brief') or {};changed=[]
for sp in db.rows(c,'select * from subprojects where project_id=?',(pid,)):
 if sp['status'] in model.TERMINAL:continue
 r=db.one(c,'select * from briefs where subproject_id=? order by version desc limit 1',(sp['id'],))
 if not r:continue
 before=json.loads(r['data_json']);after=model.brief(model.inherit(shared,before));after=model.preserve_manual(before,after)
 if after==before:continue
 after['handoff']=model.handoff(p,sp,after);db.save_brief(c,pid,after,sp['id'],actor='schema_normalization')
 c.execute('update subprojects set planning_json=?,customer_requirements_json=?,updated_at=? where id=?',(db.js(after.get('planning',{})),db.js(after.get('customer_requirements',[])),db.now(),sp['id']))
 db.audit(c,'subproject',sp['id'],'schema_normalization',before,after,actor='system')
 Handler.refresh_pending(c,db.one(c,'select * from subprojects where id=?',(sp['id'],)))
 changed.append(sp['id'])
output['applied_fingerprint']=understand.input_hash(understand.snapshot(c,pid));output['schema_normalized_at']=db.now()
c.execute('update generation_runs set output_json=? where id=?',(db.js(output),run['id']))
c.commit();c.close();print('normalized',len(changed))
