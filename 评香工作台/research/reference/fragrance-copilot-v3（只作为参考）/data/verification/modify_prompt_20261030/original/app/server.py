"""V3 HTTP API. Legacy supplies read-only library lookup, QA and usage helpers."""
from __future__ import annotations
import base64
import binascii
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
import re
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote, quote
from . import db, llm, model, parse, reco, service, understand, workflow, identity
from .legacy import Handler as LegacyHandler

MAX_REQUEST_BYTES=72*1024*1024
LOG=logging.getLogger('copilot.server')

def configure_logging():
    logger=logging.getLogger('copilot')
    if logger.handlers:return
    db.DATA.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(db.DATA/'copilot.log',maxBytes=2*1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger.addHandler(handler);logger.setLevel(logging.INFO);logger.propagate=False

def decode_upload(value):
    if not isinstance(value,str):raise ValueError('文件内容须为base64字符串')
    encoded=value.split(',')[-1]
    if len(encoded)>4*((50*1024*1024+2)//3):raise ValueError('单文件请控制在50MB以内')
    try:return base64.b64decode(encoded,validate=True)
    except (binascii.Error,ValueError):raise ValueError('文件内容不是合法base64') from None

@contextmanager
def session():
    con = db.connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()

def require(con, table, identity):
    row = db.one(con, f'select * from {table} where id=?', (identity,))
    if not row: raise KeyError('记录不存在')
    return row

class Handler(LegacyHandler):
    server_version = 'FragranceCopilotV3/1.0'

    def _json_body(self):
        size=int(self.headers.get('Content-Length') or 0)
        if size<0:raise ValueError('请求长度无效')
        if size>MAX_REQUEST_BYTES:raise ValueError('单次请求过大，文件请控制在50MB以内')
        return super()._json_body()

    def route(self, method):
        u = urlsplit(self.path)
        try:
            if u.path.startswith('/api/'):
                return self.api(method, unquote(u.path), {k:v[-1] for k,v in parse_qs(u.query).items()})
            path = (db.ROOT/'web'/unquote(u.path).lstrip('/')).resolve() if u.path != '/' else db.ROOT/'web/index.html'
            if not path.is_relative_to((db.ROOT/'web').resolve()) or not path.is_file():
                return self._err('页面不存在',404)
            return self._send(200,path.read_bytes(),mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        except KeyError as e: self._err(str(e),404)
        except ValueError as e: self._err(str(e),400)
        except Exception as e:
            LOG.exception('request_failed method=%s path=%s',method,u.path)
            self._err(f'{type(e).__name__}: {e}',500)

    def api(self, method, path, q):
        if path=='/api/library/catalog' and method=='GET':
            with session() as con:return self._ok(identity.Index(con).catalog(q.get('brand','')))
        if path=='/api/library/aliases':
            if method=='GET':
                with session() as con:return self._ok({'items':identity.load_aliases(con)})
            if method=='POST':
                body=self._json_body()
                with session() as con:aid=identity.register_alias(con,body)
                return self._ok({'id':aid})
        alias_match=re.fullmatch(r'/api/library/aliases/([^/]+)',path)
        if alias_match and method=='DELETE':
            with session() as con:
                prior=require(con,'identity_aliases',alias_match[1]);con.execute('delete from identity_aliases where id=?',(prior['id'],))
                db.audit(con,'identity_alias',prior['id'],'deleted',prior,None,reason='移除应用层别名配置，不改原库')
            return self._ok()
        if path == '/api/health':
            return self._ok({'app':'fragrance-copilot-v3','db':db.DB_PATH.exists(),'library_write_enabled':False})
        if path == '/api/projects':
            if method == 'GET': return self.projects_list()
            if method == 'POST': return self.project_create()
        if path == '/api/ontology' and method == 'GET':
            with session() as con:
                return self._ok({'terms':db.rows(con,'select * from terms order by domain,layer,label'),
                                 'c_nodes':db.rows(con,'select * from c_nodes order by new_class,path'),
                                 'categories':db.rows(con,'select * from category_map order by k_code')})
        m = re.fullmatch(r'/api/projects/([^/]+)(?:/(.*))?',path)
        if m:
            pid, action = m.groups()
            if action is None:
                if method == 'GET': return self.project_detail(pid)
                if method == 'DELETE': return self.project_delete(pid)
            if action == 'artifacts':
                if method == 'POST': return self.artifact_create(pid)
                if method == 'GET':
                    with session() as con: return self._ok({'items':db.rows(con,'select * from artifacts where project_id=? order by created_at,id',(pid,))})
            if action in ('generate','brief/suggest','split') and method == 'POST':
                b = self._json_body()
                return self._ok({'run':understand.start(pid,bool(b.get('force')))})
            if action == 'generation' and method == 'GET':
                with session() as con:
                    r = db.one(con,'select * from generation_runs where project_id=? order by rowid desc limit 1',(pid,))
                    return self._ok({'run':understand.public(r) if r else None})
            if action == 'brief':
                if method == 'GET': return self.brief_get(pid)
                if method in ('PUT','PATCH'): return self.brief_save(pid)
            if action == 'story' and method == 'GET': return self.story_get(pid)
            if action == 'subprojects' and method == 'POST': return self.subproject_create(pid)
            if action == 'qa' and method == 'POST': return self.qa(pid)
            if action == 'usage' and method == 'GET': return self.usage(pid)
        m = re.fullmatch(r'/api/artifacts/([^/]+)(?:/(file|reparse|enrich|classify))?',path)
        if m:
            aid, action = m.groups()
            if method == 'GET' and action == 'file': return self.artifact_file(aid)
            if method == 'GET' and not action: return self.artifact_get(aid)
            if method in ('PATCH','PUT') and not action: return self.artifact_patch(aid)
            if method == 'DELETE' and not action: return self.artifact_delete(aid)
            if method == 'POST' and action in ('reparse','enrich'): return self.artifact_reparse(aid)
            if method == 'POST' and action == 'classify': return self.artifact_classify(aid)
        m = re.fullmatch(r'/api/subprojects/([^/]+)(?:/(.*))?',path)
        if m:
            sid, action = m.groups()
            if not action:
                if method == 'GET': return self.subproject_detail(sid)
                if method in ('PUT','PATCH'): return self.subproject_save(sid)
                if method == 'DELETE': return self.subproject_delete(sid)
            if action == 'recommend' and method == 'POST': return self.recommend(sid)
            if action == 'abc-map' and method == 'GET': return self.abc_map(sid)
            if action == 'brief' and method in ('PUT','PATCH'): return self.brief_save(None,sid)
            if action in ('convert','follow-up') and method == 'POST': return self.follow_up(sid)
            if action == 'workflow' and method == 'POST': return self.advance(sid)
            if action == 'samples' and method == 'POST': return self.sample_create(sid)
            if action == 'endpoint' and method == 'POST': return self.endpoint(sid)
            if action == 'endpoint-checks' and method == 'POST': return self.endpoint_checks_save(sid)
        m = re.fullmatch(r'/api/tasks/([^/]+)(?:/(files))?',path)
        if m:
            tid, action = m.groups()
            if action == 'files' and method == 'POST': return self.task_upload(tid)
            if not action and method in ('PATCH','PUT'):
                b = self._json_body()
                with session() as con: workflow.update(con,tid,b)
                return self._ok()
        m = re.fullmatch(r'/api/task-files/([^/]+)',path)
        if m and method == 'GET':
            with session() as con: f = require(con,'task_files',m[1])
            return self._send(200,(db.UPLOADS/f['stored_name']).read_bytes(),f['mime'] or 'application/octet-stream',{'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f['filename'])})
        m = re.fullmatch(r'/api/recommendation-items/([^/]+)',path)
        if m and method in ('PATCH','PUT'): return self.rec_item_patch(m[1])
        if path in ('/api/library/meta','/api/library/search','/api/categories','/api/category/resolve'):
            return super().api(method,path,q)
        return self._err('接口不存在',404)

    def project_create(self):
        b = self._json_body()
        if not str(b.get('name','')).strip(): raise ValueError('请填写项目名称')
        pid = db.uid('p_')
        with session() as con:
            con.execute('insert into projects(id,name,customer,brand,sales,evaluator,grade,status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?)',
                        (pid,b['name'],b.get('customer',''),b.get('brand',''),b.get('sales',''),b.get('evaluator','评香'),b.get('grade',''),'draft',db.now(),db.now()))
            db.audit(con,'project',pid,'created',None,{'name':b['name']})
        self._ok({'id':pid})

    def project_detail(self,pid):
        with session() as con:
            p = require(con,'projects',pid)
            r = db.one(con,'select * from generation_runs where project_id=? order by rowid desc limit 1',(pid,))
            brief = db.one(con,"select * from briefs where project_id=? and coalesce(subproject_id,'')='' order by version desc limit 1",(pid,))
            self._ok({'project':p,'subprojects':db.rows(con,'select * from subprojects where project_id=? order by created_at,id',(pid,)),
                      'artifacts':db.rows(con,'select * from artifacts where project_id=? order by created_at,id',(pid,)),
                      'brief':model.brief(db.jload(brief['data_json'],{}) if brief else {}), 'run':understand.public(r) if r else None})

    def project_delete(self,pid):
        with session() as con:
            require(con,'projects',pid)
            if db.one(con,"select id from generation_runs where project_id=? and status in ('queued','running')",(pid,)):
                raise ValueError('项目正在生成，完成后再删除')
            for s in db.rows(con,'select id from subprojects where project_id=?',(pid,)): self._drop_subproject(con,s['id'])
            for t in ('artifacts','briefs','stories','generation_runs','brief_history'): con.execute(f'delete from {t} where project_id=?',(pid,))
            con.execute('delete from projects where id=?',(pid,))
        self._ok()

    @staticmethod
    def _drop_subproject(con,sid):
        con.execute('delete from task_files where task_id in (select id from department_tasks where subproject_id=?)',(sid,))
        con.execute('delete from brief_history where subproject_id=?',(sid,))
        con.execute('update subprojects set parent_subproject_id=null where parent_subproject_id=?',(sid,))
        LegacyHandler._drop_subproject(con,sid)

    def subproject_delete(self,sid):
        with session() as con:
            require(con,'subprojects',sid)
            if db.one(con,'select id from subprojects where parent_subproject_id=?',(sid,)): raise ValueError('该子项目被后续任务引用，请保留历史')
            self._drop_subproject(con,sid)
        self._ok()

    def _auto_classify(self,aid,pid):
        with session() as con: a = require(con,'artifacts',aid)
        llm.begin(pid,'parse_annotation_v3')
        sys = (db.ROOT/'prompts/classify_artifact.md').read_text(encoding='utf-8')
        d = llm.chat_json([{'role':'system','content':sys},{'role':'user','content':db.js({'filename':a['filename'],'user_note':a['note'],'text':a['text']})}],max_tokens=1000,timeout=60)
        with session() as con:
            con.execute('update artifacts set source_type=?,role=?,annotation_json=?,updated_at=? where id=?',
                        (d.get('source_type') or '其他',d.get('role') or '其他',db.js(dict(d,phase='parse')),db.now(),aid))
        return d

    def parsed(self,pid,path,name,mime):
        ex = parse.extract(path,name,mime)
        pieces = [ex.get('text') or '']; meta = ex.get('meta') or []; errors = []
        if ex.get('images'):
            for image in ex['images']:
                try:
                    llm.begin(pid,'parse_pdf_vision_v3')
                    text = llm.vision_describe(image['data'],image.get('mime') or 'image/jpeg')
                    if not text.strip(): raise ValueError('视觉识别返回空内容')
                    loc = image.get('locator') or image.get('name') or '扫描页'
                    pieces.append(f'【扫描页视觉识别 / {loc}】\n{text}'); meta.append({'locator':loc,'text':text})
                except Exception as e: errors.append(str(e))
        elif mime.startswith(('image/','audio/')):
            try:
                llm.begin(pid,'parse_multimodal_v3')
                text = llm.vision_describe(path.read_bytes(),mime) if mime.startswith('image/') else llm.asr_transcribe(path.read_bytes(),mime)
                if not text.strip(): raise ValueError('识别返回空内容')
                pieces.append('【视觉识别 / 转写辅助文本】\n'+text); meta.append({'locator':'图片 / 音频','text':text})
            except Exception as e: errors.append(str(e))
        text = '\n\n'.join(x for x in pieces if x.strip())
        error = '；'.join(errors) or (ex.get('error') if not text else '') or ''
        if ex.get('incomplete'): error = (error+'；'+str(ex.get('error') or '部分内容未解析')).strip('；')
        return text,meta,'parsed' if text.strip() and not error else 'needs_text',error

    def artifact_create(self,pid):
        b = self._json_body()
        with session() as con: require(con,'projects',pid)
        name = str(b.get('filename') or '粘贴资料.txt')
        kind = b.get('kind','paste'); mime = b.get('mime') or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        stored = ''; text = str(b.get('text') or ''); meta = []; error = ''; status = 'parsed'
        if b.get('data_base64'):
            raw = decode_upload(b['data_base64'])
            if len(raw)>50*1024*1024: raise ValueError('单文件请控制在50MB以内')
            stored = db.uid('f_')+'_'+re.sub(r'[^\w.\-\u4e00-\u9fff]+','_',name)[:120]
            f = db.UPLOADS/stored; f.write_bytes(raw)
            text,meta,status,error = self.parsed(pid,f,name,mime)
        elif kind == 'link':
            url = str(b.get('url') or '')
            if urlsplit(url).scheme not in ('http','https'): raise ValueError('请使用http或https链接')
            text = self.fetch_link(url); meta = [{'locator':'来源链接','text':url}]
            if not text: status,error = 'needs_text','未抓取到链接正文，请补充可读取的文本'
        elif not text.strip(): raise ValueError('资料内容为空')
        aid = db.uid('a_')
        with session() as con:
            con.execute('''insert into artifacts(id,project_id,filename,stored_name,mime,text,text_meta_json,source_type,role,note,status,parse_error,created_at,updated_at)
                           values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (aid,pid,name,stored,mime,text,db.js(meta),'其他','',b.get('note',''),status,error,db.now(),db.now()))
            db.audit(con,'artifact',aid,'created',None,{'project_id':pid,'filename':name,'kind':kind,'status':status})
        warning = ''
        if text.strip():
            try: self._auto_classify(aid,pid)
            except Exception as e:
                warning = '初步标注未完成：'+str(e)
                with session() as con: con.execute('update artifacts set annotation_json=? where id=?', (db.js({'phase':'parse','error':warning}),aid))
        self._ok({'id':aid,'status':status,'error':error,'annotation_warning':warning})

    def artifact_patch(self,aid):
        b = self._json_body()
        with session() as con:
            a = require(con,'artifacts',aid)
            for k in ('note','source_type','role','text','filename'):
                if k in b:
                    if not isinstance(b[k],str): raise ValueError('资料字段必须是文本')
                    con.execute(f'update artifacts set {k}=?,updated_at=? where id=?',(b[k],db.now(),aid))
                    db.audit(con,'artifact',aid,k,a.get(k),b[k])
            if 'text' in b: con.execute("update artifacts set status=?,parse_error='' where id=?",('parsed' if b['text'].strip() else 'needs_text',aid))
        self._ok()

    def artifact_reparse(self,aid):
        with session() as con: a = require(con,'artifacts',aid)
        if not a.get('stored_name'): raise ValueError('该资料没有上传原件，可直接补充文本')
        text,meta,status,error = self.parsed(a['project_id'],db.UPLOADS/a['stored_name'],a['filename'],a['mime'] or mimetypes.guess_type(a['filename'])[0] or '')
        with session() as con: con.execute('update artifacts set text=?,text_meta_json=?,status=?,parse_error=?,updated_at=? where id=?',(text,db.js(meta),status,error,db.now(),aid))
        self._ok({'status':status,'error':error,'length':len(text)})
    def brief_get(self,pid):
        with session() as con:
            require(con,'projects',pid)
            r = db.one(con,"select * from briefs where project_id=? and coalesce(subproject_id,'')='' order by version desc limit 1",(pid,))
            self._ok({'brief':model.brief(db.jload(r['data_json'],{}) if r else {}),'version':r['version'] if r else 0})

    def brief_save(self,pid,sid=None):
        b = self._json_body(); bd = model.brief(b.get('brief',b))
        with session() as con:
            sp = require(con,'subprojects',sid) if sid else None
            pid = sp['project_id'] if sp else pid
            require(con,'projects',pid)
            old_row = db.one(con, "select data_json from briefs where project_id=? and coalesce(subproject_id,'')=? order by version desc limit 1", (pid, sid or ''))
            old_bd = model.brief(db.jload(old_row['data_json'], {}) if old_row else {})
            if sp:
                if any(v not in (None,'',[],{}) and v!=old_bd['project'].get(k) for k,v in bd['project'].items()):
                    raise ValueError('客户、联系人和总体对接信息请在项目简报修改')
                root_row=db.one(con,"select data_json from briefs where project_id=? and coalesce(subproject_id,'')=''",(pid,))
                bd['project']=model.project_context(require(con,'projects',pid),db.jload((root_row or {}).get('data_json'),{}).get('project',{}))
            bd = model.track_manual(old_bd, bd)
            if sp: bd['manual_overrides']={k:v for k,v in bd['manual_overrides'].items() if not k.startswith('project.')}
            if sp and sp['status'] in model.TERMINAL: raise ValueError('已结束子项目请通过关联后续子项目补充')
            bd['commercial']['target_price'] = model.number(bd['commercial'].get('target_price'),'目标价')
            if sp:
                cat = self._resolve_category(con,bd['product'].get('category_l3'))
                if bd['product'].get('category_l3') and not cat: raise ValueError('请从标准品类中选择三级品类')
                changes = {'price_target':bd['commercial']['target_price'],'base_formula_code':bd['scent'].get('old_formula') or sp.get('base_formula_code') or ''}
                if cat: changes.update(category_l1=cat['level1'],category_l2=cat['level2'],category_l3=cat['level3'],norm_class=cat['norm_class'],new_class=cat['new_class'])
                self.write_sub(con,sp,changes)
                sp = require(con,'subprojects',sid); bd['handoff'] = model.handoff(require(con,'projects',pid),sp,bd)
            bid = db.save_brief(con,pid,bd,sid,actor='evaluator')
            if sid:
                con.execute('update subprojects set customer_requirements_json=? where id=?', (db.js(bd.get('customer_requirements', [])), sid))
            else:
                p = bd['project']
                for key in ('name','customer','brand','sales','evaluator','grade'):
                    if p.get(key): con.execute(f'update projects set {key}=? where id=?', (p[key], pid))
                con.execute('update projects set customer_info_json=?,coordination_json=? where id=?',
                            (db.js({'customer':p.get('customer',''), 'brand':p.get('brand',''), 'profile':p.get('customer_profile',''), 'contacts':p.get('contacts',[])}),
                             db.js({'overall_deadline':p.get('overall_deadline') or bd['deliverables'].get('deadline',''),
                                    'sample_due':bd['commercial'].get('sample_due',''), 'recipient':bd['deliverables'].get('recipient',''),
                                    'sales':p.get('sales',''), 'evaluator':p.get('evaluator',''), 'notes':p.get('coordination_notes',''),
                                    'events':p.get('coordination_events',[])}), pid))
                # Propagate shared facts only while a child still holds the previous shared value.
                for child in db.rows(con, 'select * from subprojects where project_id=?', (pid,)):
                    if child['status'] in model.TERMINAL: continue
                    child_row = db.one(con, 'select data_json from briefs where subproject_id=? order by version desc limit 1', (child['id'],))
                    if not child_row: continue
                    cb = model.brief(db.jload(child_row['data_json'], {}))
                    for group in model.GROUPS:
                        for key, value in bd[group].items():
                            if value != old_bd[group].get(key) and cb[group].get(key) == old_bd[group].get(key) and group+'.'+key not in cb['manual_overrides']:
                                cb[group][key] = value
                    changes = {}
                    if cb['commercial']['target_price'] != child.get('price_target'):
                        changes['price_target'] = model.number(cb['commercial']['target_price'], '目标价')
                    if cb['product']['category_l3'] != child.get('category_l3'):
                        cat = self._resolve_category(con, cb['product']['category_l3'])
                        if cat: changes.update(category_l1=cat['level1'],category_l2=cat['level2'],category_l3=cat['level3'],norm_class=cat['norm_class'],new_class=cat['new_class'])
                    if changes:
                        self.write_sub(con, child, changes)
                        child = require(con, 'subprojects', child['id'])
                    cb['handoff'] = model.handoff(require(con,'projects',pid),child,cb)
                    db.save_brief(con,pid,cb,child['id'],actor='inherited')
                    self.refresh_pending(con,child)
            db.audit(con,'subproject' if sid else 'project',sid or pid,'brief',None,bd)
            if sp: self.refresh_pending(con,sp)
        self._ok({'id':bid})

    def story_get(self,pid):
        with session() as con:
            require(con,'projects',pid)
            r = db.one(con,'select * from stories where project_id=? order by updated_at desc limit 1',(pid,))
            self._ok({'story':db.jload(r['sections_json'],{}) if r else {},'artifacts':db.rows(con,'select id,filename,created_at,note from artifacts where project_id=? order by created_at,id',(pid,)),
                      'decisions':db.rows(con,"select * from decisions where entity_id=? or entity_id in (select id from subprojects where project_id=?) order by id desc limit 100",(pid,pid))})

    def subproject_detail(self,sid):
        with session() as con:
            sp = require(con,'subprojects',sid)
            row = db.one(con,'select * from briefs where subproject_id=? order by version desc limit 1',(sid,))
            bd = model.brief(db.jload(row['data_json'],{}) if row else {})
            if not row:
                pb = db.one(con,"select data_json from briefs where project_id=? and coalesce(subproject_id,'')='' order by version desc limit 1",(sp['project_id'],))
                if pb: bd = model.brief(db.jload(pb['data_json'],{}))
                bd['product'].update(category_l1=sp.get('category_l1') or '',category_l2=sp.get('category_l2') or '',category_l3=sp.get('category_l3') or '')
                bd['commercial']['target_price'] = sp.get('price_target')
                bd['handoff'] = model.handoff(require(con,'projects',sp['project_id']),sp,bd)
            defaults = self._norm_defaults(sp.get('norm_class'),bd['compliance'].get('markets') or bd['commercial'].get('markets'))
            checks = service.endpoint_checks(con,sp,defaults)
            last = db.one(con,'select * from recommendations where subproject_id=? order by rowid desc limit 1',(sid,))
            items = []
            for r in db.rows(con,'select * from recommendation_items where recommendation_id=? order by rank',((last or {}).get('id',''),)):
                snap = db.jload(r.get('snapshot_json'),{})
                items.append({**snap,'id':r['id'],'decision':r['decision'],'note':r['note']})
            saved = db.jload((last or {}).get('filters_json'),{})
            origin_run=db.one(con,'select * from generation_runs where id=?',(db.jload(sp.get('context_json'),{}).get('run_id',''),))
            self._ok({'subproject':sp,'sub_brief':bd,'items':items,'meta':saved.get('meta',{}),
                      'semantic_review_required':bool(origin_run and understand.public(origin_run)['policy_stale']),
                      'recommendation_stale':bool(not last or saved.get('signature') != service.rec_signature(sp,con)),
                      'tasks':db.rows(con,'select * from department_tasks where subproject_id=? order by created_at,rowid',(sid,)),
                      'samples':db.rows(con,'select * from external_samples where subproject_id=?',(sid,)),
                      'task_files':db.rows(con,'select f.* from task_files f join department_tasks t on t.id=f.task_id where t.subproject_id=?',(sid,)),
                      'defaults':defaults,'endpoint_checks':checks,'hard_filters':reco.filters(sp)})

    @staticmethod
    def write_sub(con,sp,changes):
        if 'new_class' in changes and changes['new_class'] != sp.get('new_class'):
            changes.update(target_c='',target_cs_json='[]')
            f = reco.filters(sp); f['categories'] = [changes['new_class']] if changes['new_class'] else []
            f['tags'] = [{**g,'ids':[tid for tid in g['ids'] if not db.one(con,'select id from c_nodes where id=?',(tid,))]} for g in f.get('tags',[])]
            f['tags'] = [g for g in f['tags'] if g['ids']]; changes['hard_filters_json'] = db.js(f)
        changes['updated_at'] = db.now()
        con.execute(f"update subprojects set {','.join(k+'=?' for k in changes)} where id=?",(*changes.values(),sp['id']))
        db.audit(con,'subproject',sp['id'],'fields',{k:sp.get(k) for k in changes},changes)

    @staticmethod
    def refresh_pending(con,sp):
        ctx = workflow.context(con,sp)
        for t in db.rows(con,"select * from department_tasks where subproject_id=? and status='todo'",(sp['id'],)):
            payload = db.jload(t.get('payload_json'),{}); payload.update(ctx)
            payload['analysis_files'] = db.rows(con,'select f.id,f.filename,f.task_id from task_files f join department_tasks t on t.id=f.task_id where t.subproject_id=?',(sp['id'],))
            con.execute('update department_tasks set payload_json=?,detail=? where id=?',(db.js(payload),ctx['handoff'],t['id']))
        workflow.start(con,sp)

    def subproject_save(self,sid):
        b = self._json_body()
        with session() as con:
            sp = require(con,'subprojects',sid)
            if sp['status'] in model.TERMINAL: raise ValueError('已结束子项目保留历史，请创建关联后续子项目')
            if 'status' in b or 'endpoint' in b: raise ValueError('请通过任务流程或终点接口推进状态')
            if 'task_type' in b and b['task_type'] != sp['task_type']: raise ValueError('任务类型变化请创建关联后续子项目')
            vals = {k:b[k] for k in ('title','base_formula_code','direction') if k in b}
            if 'price_target' in b: vals['price_target'] = model.number(b['price_target'],'目标价')
            if 'price_elasticity' in b: vals['price_elasticity'] = model.number(b['price_elasticity'],'价格弹性',False,0,200)
            if 'category_l3' in b:
                cat = self._resolve_category(con,b['category_l3'])
                if not cat: raise ValueError('请选择标准三级品类')
                vals.update(category_l1=cat['level1'],category_l2=cat['level2'],category_l3=cat['level3'],norm_class=cat['norm_class'],new_class=cat['new_class'])
            terms = {t['id']:t for t in db.rows(con,'select * from terms')}
            c_nodes = {t['id']:t for t in db.rows(con,'select * from c_nodes')}
            for key in ('a1','a2','a3','b','target_cs'):
                if key not in b: continue
                if not isinstance(b[key],list): raise ValueError('标签必须是数组')
                ids = list(dict.fromkeys(b[key]))
                for tid in ids:
                    if key == 'target_cs':
                        if tid not in c_nodes or c_nodes[tid]['new_class'] != vals.get('new_class',sp['new_class']): raise ValueError('C标签不属于该内部品类')
                    elif tid not in terms or (terms[tid]['domain'] != 'B' if key == 'b' else terms[tid]['layer'] != key.upper()): raise ValueError('标签层级无效')
                vals[key+'_json'] = db.js(ids)
                if key == 'target_cs': vals['target_c'] = ids[0] if ids else ''
            for key in ('target_products','brand_requirements'):
                if key in b:
                    if not isinstance(b[key],list) or any(not isinstance(x,dict) for x in b[key]): raise ValueError('产品/品牌要求必须是对象数组')
                    vals[key+'_json'] = db.js(b[key])
            if 'brand_requirements' in b:
                for req in b['brand_requirements']:
                    if req.get('kind') not in ('brand','dupe') or not str(req.get('value') or '').strip(): raise ValueError('品牌要求无效')
            if 'hard_filters' in b:
                f = b['hard_filters']
                if not isinstance(f,dict) or not isinstance(f.get('tags',[]),list): raise ValueError('硬筛配置无效')
                classes = {c['new_class'] for c in db.rows(con,'select distinct new_class from library_items') if c['new_class']}
                if not isinstance(f.get('categories',[]),list) or set(f.get('categories',[]))-classes: raise ValueError('内部品类无效')
                for g in f.get('tags',[]):
                    if not isinstance(g,dict) or not isinstance(g.get('ids'),list) or g.get('mode') not in ('any','all'): raise ValueError('硬筛标签组无效')
                    if set(g['ids'])-set(terms)-set(c_nodes): raise ValueError('硬筛包含不存在的标签')
                for flag in ('category_enabled','price_enabled','brand_enabled','hot_enabled','new_enabled'):
                    if not isinstance(f.get(flag,False),bool): raise ValueError('硬筛开关必须是布尔值')
                vals['hard_filters_json'] = db.js(f)
            if 'reset_filters' in b:
                if not isinstance(b['reset_filters'],bool):raise ValueError('恢复默认筛选参数无效')
                if b['reset_filters']:
                    if 'hard_filters' in b:raise ValueError('恢复默认与自定义筛选不能同时提交')
                    vals['hard_filters_json']=db.js(reco.default_filters({**sp,**vals}))
            self.write_sub(con,sp,vals); sp = require(con,'subprojects',sid)
            r = db.one(con,'select data_json from briefs where subproject_id=? order by version desc limit 1',(sid,))
            bd = model.brief(db.jload(r['data_json'],{}) if r else {})
            bd['product'].update(category_l1=sp['category_l1'],category_l2=sp['category_l2'],category_l3=sp['category_l3'],new_class=sp['new_class'])
            bd['commercial']['target_price'] = sp['price_target']; bd['scent']['old_formula'] = sp.get('base_formula_code') or ''
            bd['scent']['directions'] = [sp['direction']] if sp.get('direction') else []
            bd['handoff'] = model.handoff(require(con,'projects',sp['project_id']),sp,bd)
            bd = model.track_manual(model.brief(db.jload(r['data_json'],{}) if r else {}), bd)
            db.save_brief(con,sp['project_id'],bd,sid,actor='evaluator'); self.refresh_pending(con,sp)
        self._ok()

    def subproject_create(self,pid,parent=None,payload=None):
        b = payload if payload is not None else self._json_body()
        if b.get('task_type') not in model.TYPES: raise ValueError('主类型无效')
        if not str(b.get('title') or '').strip(): raise ValueError('请填写标题')
        if b['task_type'] == 'find_product' and not any(p.get('product') for p in b.get('target_products', [])):
            raise ValueError('找香任务需要具体产品名称')
        sid = db.uid('s_')
        with session() as con:
            p = require(con,'projects',pid); cat = self._resolve_category(con,b.get('category_l3')) or {}
            bd = model.brief(b.get('brief') or {}); price = model.number(b.get('price_target',bd['commercial'].get('target_price')),'目标价')
            root_row=db.one(con,"select data_json from briefs where project_id=? and coalesce(subproject_id,'')=''",(pid,))
            bd['project']=model.project_context(p,db.jload((root_row or {}).get('data_json'),{}).get('project',{}))
            vals = dict(id=sid,project_id=pid,title=b['title'],task_type=b['task_type'],status='briefed',parent_subproject_id=parent,
                        category_l1=cat.get('level1',''),category_l2=cat.get('level2',''),category_l3=cat.get('level3',''),norm_class=cat.get('norm_class',''),new_class=cat.get('new_class',''),
                        a1_json='[]',a2_json='[]',a3_json='[]',target_products_json=db.js(b.get('target_products',[])),base_formula_code=b.get('base_formula_code',''),price_target=price,price_elasticity=20,created_at=db.now(),updated_at=db.now())
            con.execute(f"insert into subprojects({','.join(vals)}) values({','.join('?' for _ in vals)})",tuple(vals.values()))
            bd['product'].update(category_l1=vals['category_l1'],category_l2=vals['category_l2'],category_l3=vals['category_l3']); bd['commercial']['target_price'] = price
            bd['handoff'] = model.handoff(p,vals,bd); bid = db.save_brief(con,pid,bd,sid,actor='evaluator')
            con.execute('update subprojects set customer_requirements_json=? where id=?', (db.js(bd.get('customer_requirements', [])), sid))
            con.execute('update subprojects set planning_json=? where id=?',(db.js(bd.get('planning',{})),sid))
            con.execute('update subprojects set brief_id=? where id=?',(bid,sid)); workflow.start(con,require(con,'subprojects',sid))
        self._ok({'id':sid})

    def follow_up(self,sid):
        b = self._json_body()
        with session() as con:
            sp = require(con,'subprojects',sid); r = db.one(con,'select data_json from briefs where subproject_id=? order by version desc limit 1',(sid,))
            bd = model.brief(db.jload(r['data_json'],{}) if r else {})
        bd['modification'] = b.get('modification') or ''
        if b.get('task_type') == 'modify' and not bd['modification'].strip(): raise ValueError('请填写改动要求')
        return self.subproject_create(sp['project_id'],sid,dict(title=b.get('title') or sp['title']+' · 后续',task_type=b.get('task_type','modify'),category_l3=sp['category_l3'],price_target=sp['price_target'],base_formula_code=b.get('base_formula_code') or '',target_products=db.jload(sp['target_products_json'],[]),brief=bd))
    def abc_map(self,sid):
        with session() as con:
            sp = require(con,'subprojects',sid); term = {t['id']:dict(t,path=t['label']) for t in db.rows(con,'select * from terms')}; cn = {t['id']:t for t in db.rows(con,'select * from c_nodes')}
            self._ok({**{key:[term.get(tid,{'id':tid,'label':tid}) for tid in db.jload(sp.get(key+'_json'),[])] for key in ('a1','a2','a3','b')},
                      'c_list':[cn.get(tid,{'id':tid,'label':tid}) for tid in reco.target_cs(sp)],'basis':db.jload(sp.get('abc_basis_json'),{}),'hard_filters':reco.filters(sp)})

    def recommend(self,sid):
        with session() as con:
            sp = require(con,'subprojects',sid)
            if sp['task_type'] not in model.TYPES: raise ValueError('此类型不运行自动推荐')
            items,meta = service.recommendations(con,sp); workflow.start(con,sp)
            if sp['task_type'] in ('recommend_brand','recommend_simple','find_product') and sp['status'] not in model.TERMINAL and sp['status'] != 'tasks': con.execute("update subprojects set status='recommended',updated_at=? where id=?",(db.now(),sid))
        self._ok({'items':items,'meta':meta})

    def rec_item_patch(self,iid):
        b = self._json_body()
        if b.get('decision') not in ('shortlist','eliminated','pending'): raise ValueError('候选决定无效')
        with session() as con:
            old = require(con,'recommendation_items',iid)
            con.execute('update recommendation_items set decision=?,note=? where id=?',(b['decision'],b.get('note',old['note']),iid))
            db.audit(con,'recommendation_item',iid,'decision',old['decision'],b['decision'])
        self._ok()

    def advance(self,sid):
        b = self._json_body()
        with session() as con:
            sp = require(con,'subprojects',sid)
            if sp['status'] in model.TERMINAL: raise ValueError('已结束子项目请新建关联后续')
            if b.get('action') == 'select': workflow.choose(con,sp,b.get('codes',[]))
            elif b.get('action') == 'analysis': workflow.request_analysis(con,sp)
            else: raise ValueError('流程动作无效')
        self._ok()

    def task_upload(self,tid):
        b = self._json_body(); name = str(b.get('filename') or '分析报告')
        raw = decode_upload(b.get('data_base64') or '')
        if not raw or len(raw)>50*1024*1024: raise ValueError('文件为空或超过50MB')
        stored = db.uid('tf_')+'_'+re.sub(r'[^\w.\-\u4e00-\u9fff]+','_',name)[:120]
        with session() as con:
            t = require(con,'department_tasks',tid)
            if t['type'] == '入库': raise ValueError('本版入库已禁用')
            (db.UPLOADS/stored).write_bytes(raw); fid = db.uid('tf_')
            con.execute('insert into task_files values(?,?,?,?,?,?)',(fid,tid,name,stored,b.get('mime') or mimetypes.guess_type(name)[0] or 'application/octet-stream',db.now()))
            self.refresh_pending(con,require(con,'subprojects',t['subproject_id']))
        self._ok({'id':fid})

    def sample_create(self,sid):
        b = self._json_body()
        sample_id=db.uid('es_')
        if not str(b.get('product') or '').strip(): raise ValueError('请填写实物样品名称')
        with session() as con:
            sp = require(con,'subprojects',sid)
            con.execute('''insert into external_samples(id,project_id,subproject_id,received_at,received_by,source,brand,product,version,description,analysis_status,matched_formula_ids_json,result,notes)
                           values(?,?,?,?,?,?,?,?,?,?,'none','[]','pending',?)''',
                        (sample_id,sp['project_id'],sid,b.get('received_at') or db.now(),b.get('received_by',''),'客户',b.get('brand',''),b['product'],b.get('version',''),b.get('description',''),b.get('notes','')))
            db.audit(con,'sample',sample_id,'created',None,{'subproject_id':sid,'product':b['product']})
            workflow.start(con,sp)
        self._ok()

    def endpoint_checks_save(self,sid):
        b = self._json_body()
        with session() as con:
            require(con,'subprojects',sid)
            for c in b.get('checks',[]):
                if c.get('status') not in ('pending','confirmed','na'): raise ValueError('检查状态无效')
                if c['status'] == 'na' and not str(c.get('note') or '').strip(): raise ValueError('不适用时请说明原因')
                old = db.one(con,'select * from endpoint_checks where subproject_id=? and code=?',(sid,c.get('code')))
                if not old: raise ValueError('检查项不存在')
                con.execute('update endpoint_checks set status=?,note=?,updated_at=? where subproject_id=? and code=?',(c['status'],c.get('note',''),db.now(),sid,c['code']))
                db.audit(con,'subproject',sid,'check:'+c['code'],old['status'],c['status'],reason=c.get('note',''))
        self._ok()

    def qa(self,pid):
        b = self._json_body(); question = str(b.get('q') or '').strip()
        if not question: raise ValueError('请填写问题')
        with session() as con: context = understand.snapshot(con, pid)
        payload = db.js({'question':question, 'project_context':context})
        if len(payload) > understand.MAX_CONTEXT_CHARS: raise ValueError('项目上下文过大，请先缩小提问范围')
        llm.begin(pid,'qa')
        d = llm.chat_json([{'role':'system','content':(db.ROOT/'prompts/qa.md').read_text(encoding='utf-8')},
                           {'role':'user','content':payload}],max_tokens=3000,timeout=120)
        citations = d.get('citations') or []
        arts = {a['id']:a for a in context['artifacts']}
        understand.refs_valid(citations, arts)
        self._ok({'answer':d.get('answer') or '资料中尚未找到答案','citations':citations})

    def endpoint(self,sid):
        b = self._json_body(); kind = b.get('endpoint')
        if kind == 'library_intake': raise ValueError('本版入库操作已禁用，香精库不会写入')
        if kind not in ('sample_initial','sample_final'): raise ValueError('终点无效')
        with session() as con:
            sp = require(con,'subprojects',sid); tasks = db.rows(con,'select * from department_tasks where subproject_id=?',(sid,))
            done = {t['type'] for t in tasks if t['status']=='done'}
            if '寄样' not in done: raise ValueError('先完成打样与寄样任务')
            if sp['task_type']=='match_sample' and not db.one(con,'select id from external_samples where subproject_id=?',(sid,)): raise ValueError('先登记实物收样')
            r = db.one(con,'select data_json from briefs where subproject_id=? order by version desc limit 1',(sid,)); bd = model.brief(db.jload(r['data_json'],{}) if r else {})
            defaults = self._norm_defaults(sp.get('norm_class'),bd['compliance'].get('markets') or bd['commercial'].get('markets')); checks = service.endpoint_checks(con,sp,defaults)
            blockers = []
            if kind=='sample_final':
                if not sp.get('norm_class') or not defaults: blockers.append('规范类与默认指标尚未确定')
                blockers += [k+'任务未完成' for k in ('法规','质量') if k not in done]
                blockers += [c['label']+'尚未核对' for c in checks if c['status']=='pending']
            elif not str(b.get('reason') or '').strip(): raise ValueError('初样放行请填写评香确认说明')
            if blockers: return self._ok({'completed':False,'blockers':blockers})
            if sp.get('status')=='sample_final' and kind=='sample_initial': raise ValueError('已完成终样不能退回初样')
            con.execute('update subprojects set status=?,endpoint=?,updated_at=? where id=?',(kind,kind,db.now(),sid))
            db.audit(con,'subproject',sid,'endpoint',sp.get('endpoint'),kind,reason=b.get('reason',''))
        self._ok({'completed':True,'blockers':[]})

def main():
    configure_logging()
    with session() as con:
        con.execute("update generation_runs set status='failed',stage='服务重启，需重新生成',error='上次运行被服务重启中断',updated_at=? where status in ('queued','running')",(db.now(),))
    host = os.environ.get('V3_HOST','127.0.0.1'); port = int(os.environ.get('V3_PORT','8768'))
    print(f'fragrance-copilot-v3 http://{host}:{port}',flush=True)
    LOG.info('server_start host=%s port=%s library_write_enabled=false',host,port)
    ThreadingHTTPServer((host,port),Handler).serve_forever()

if __name__=='__main__': main()
