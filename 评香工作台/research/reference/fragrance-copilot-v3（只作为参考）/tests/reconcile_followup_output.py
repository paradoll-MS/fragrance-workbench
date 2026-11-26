from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,understand
pid,rid=sys.argv[1:3];c=db.connect();old=db.one(c,'select * from generation_runs where id=?',(rid,));stored=json.loads(old['output_json']);draft=stored['result'];s=understand.snapshot(c,pid);fingerprint=understand.input_hash(s)
if fingerprint!=stored.get('applied_fingerprint'):raise ValueError('项目已变化，不能重放旧输出')
newid=db.uid('g_');c.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',(newid,pid,'running','跨轮结构一致性校验',fingerprint,db.js(s),None,'',db.now(),db.now()));c.commit();c.close();print('run',newid,flush=True)
try:
 try:
  c=db.connect();understand.validate(c,s,draft)
 except ValueError as issue:
  if str(issue)!='比例修改与气味结构或继承要求冲突，未覆盖旧结果':raise
  c.close();draft=understand.repair_followup(s,draft,str(issue));c=db.connect()
 result=understand.validate(c,s,draft);c.execute('BEGIN IMMEDIATE')
 if understand.input_hash(understand.snapshot(c,pid))!=fingerprint:raise ValueError('修复期间项目变化')
 change=understand.apply(c,s,result,newid);change['result']=result;change['revalidated_from']=rid;change['applied_fingerprint']=understand.input_hash(understand.snapshot(c,pid));c.execute("update generation_runs set status='succeeded',stage='理解完成',output_json=?,updated_at=? where id=?",(db.js(change),db.now(),newid));c.commit();print('succeeded',newid,len(change['created']),len(change['updated']),flush=True)
except Exception as issue:
 try:c.rollback();c.close()
 except Exception:pass
 c=db.connect();c.execute("update generation_runs set status='failed',stage='未更新项目',error=?,output_json=?,updated_at=? where id=?",(str(issue),db.js({'rejected_output':draft}),db.now(),newid));c.commit();print(str(issue).encode('unicode_escape').decode(),flush=True);raise
finally:c.close()
