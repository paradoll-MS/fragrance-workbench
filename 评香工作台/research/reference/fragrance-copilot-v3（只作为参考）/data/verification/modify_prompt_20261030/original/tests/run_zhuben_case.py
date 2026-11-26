"""Drive the supplied case in two separate rounds through the public V3 API."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64,json,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'data/verification/逐本/state.json'
BASE='http://127.0.0.1:8768'

def api(path,body=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json'},method='POST' if body is not None else 'GET')
 with urllib.request.urlopen(req,timeout=700) as r:
  d=json.load(r)
  if not d.get('ok'):raise RuntimeError(d)
  return d

phase=sys.argv[1] if len(sys.argv)>1 else 'round1'
s=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
if not s.get('project_id'):
 s['project_id']=api('/api/projects',{'name':'逐本 · v3 两轮验证','customer':'逐本','brand':'逐本'})['id']
 STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
pid=s['project_id']
existing={a['filename'] for a in api('/api/projects/'+pid)['artifacts']}
files=[f for f in (ROOT.parent/'案例/逐本').iterdir() if f.is_file() and (f.name.startswith('2026') if phase=='round2' else not f.name.startswith('2026'))]

def upload(f):
 if f.name in existing:return {'filename':f.name,'reused':True}
 print('uploading',f.name.encode('unicode_escape').decode(),flush=True)
 d=api('/api/projects/'+pid+'/artifacts',{'kind':'file','filename':f.name,'data_base64':base64.b64encode(f.read_bytes()).decode()})
 print('parsed',d['id'],d['status'],d.get('error'),d.get('annotation_warning'),flush=True)
 return {'filename':f.name,**d}
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(upload,files))
s[phase+'_artifacts']=results
s[phase+'_generation']=api('/api/projects/'+pid+'/generate',{'force':True})['run']
STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'project_id':pid,'phase':phase,'run':s[phase+'_generation']},ensure_ascii=False),flush=True)
