"""Revalidate a stored failed output after a contract fix, with original inputs unchanged."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,understand
rid=sys.argv[1];c=db.connect();old=db.one(c,'select * from generation_runs where id=?',(rid,));s=json.loads(old['input_json']);draft=json.loads(old['output_json'])['rejected_output'];pid=old['project_id'];newid=db.uid('g_')
if understand.input_hash(understand.snapshot(c,pid))!=old['fingerprint']:raise RuntimeError('项目已发生变化，不能复用旧输出')
c.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',(newid,pid,'running','重验已保存输出与ABC依据',old['fingerprint'],old['input_json'],None,'',db.now(),db.now()));c.commit();c.close()
try:
 c=db.connect()
 try:result=understand.validate(c,s,draft)
 except ValueError as e:
  if str(e)!='ABC推断缺少语义依据':raise
  c.close();print('repairing',newid,flush=True);draft=understand.repair_abc(s,draft,str(e));c=db.connect();result=understand.validate(c,s,draft)
 c.execute('BEGIN IMMEDIATE')
 if understand.input_hash(understand.snapshot(c,pid))!=old['fingerprint']:raise RuntimeError('项目在重验期间已变化')
 change=understand.apply(c,s,result,newid);change['result']=result;change['revalidated_from']=rid;change['applied_fingerprint']=understand.input_hash(understand.snapshot(c,pid));c.execute("update generation_runs set status='succeeded',stage='理解完成',output_json=?,updated_at=? where id=?",(db.js(change),db.now(),newid));c.commit();print('succeeded',newid,len(change['created']),flush=True)
except Exception as e:
 try:c.rollback();c.close()
 except Exception:pass
 c=db.connect();c.execute("update generation_runs set status='failed',stage='未更新项目',error=?,output_json=?,updated_at=? where id=?",(str(e),db.js({'rejected_output':draft}),db.now(),newid));c.commit();print('failed',str(e).encode('unicode_escape').decode(),flush=True);raise
finally:c.close()
