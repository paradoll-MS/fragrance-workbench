from pathlib import Path
import sys,json
root=Path('fragrance-copilot-v3').resolve();sys.path.insert(0,str(root));from app import db,understand,model
c=db.connect();old=db.one(c,'select * from generation_runs where id=?',('g_513e26b639c74432',));s=json.loads(old['input_json']);pid=old['project_id'];current=understand.snapshot(c,pid)
if understand.input_hash(s)!=understand.input_hash(current):raise RuntimeError('资料或业务状态已变化，不能套用对照结果')
draft=json.loads((root/'data/verification/model_selection/compact_sources/deepseek-v4-pro_output.json').read_text(encoding='utf-8'));result=understand.validate(c,s,draft);terms={t['id']:t['label'] for t in db.rows(c,'select id,label from terms')};expected={'金钱':{'海水','金属','纸张'},'权力':{'焚香','烘焙谷物'},'天赋':{'墨水','茶叶','咖啡'},'名望':{'葡萄酒'}}
assert len(result['subprojects'])==4
for key,wanted in expected.items():
 item=next(x for x in result['subprojects'] if key in x['title'].split('·')[-1]);actual={terms[t] for t in item['a1']};assert wanted<=actual,(key,actual);assert item['task_type']=='recommend_brand';assert item['price_target']==2000
rid=db.uid('g_');c.execute('insert into generation_runs values(?,?,?,?,?,?,?,?,?,?)',(rid,pid,'running','应用已验证的完整结果',understand.input_hash(s),db.js(s),None,'',db.now(),db.now()));c.commit();c.execute('BEGIN IMMEDIATE')
if understand.input_hash(s)!=understand.input_hash(understand.snapshot(c,pid)):raise RuntimeError('应用期间项目变化')
change=understand.apply(c,s,result,rid);change.update(result=result,business_policy=model.BUSINESS_POLICY,recovered_from=old['id'],reused_verified_output='deepseek-v4-pro; thinking disabled; compact source handles',applied_fingerprint=understand.input_hash(understand.snapshot(c,pid)));c.execute("update generation_runs set status='succeeded',stage='理解完成',output_json=?,updated_at=? where id=?",(db.js(change),db.now(),rid));c.commit();c.close();print(json.dumps({'run_id':rid,'created':len(change['created']),'updated':len(change['updated'])}))
(root/'data/verification/model_selection/recovery.json').write_text(json.dumps({'run_id':rid,'recovered_from':old['id'],'created':change['created'],'updated':change['updated']},indent=2),encoding='utf-8')
