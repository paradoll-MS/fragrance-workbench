"""Persistence of deterministic recommendation snapshots and endpoint check freshness."""
from __future__ import annotations
from . import db, model, reco, identity


def rec_signature(sp,con=None):
    return model.fingerprint({'resolver_version':'20261030-product-catalog-2-demand-c-ab-2','builtin_aliases':identity.BUILTIN_ALIAS_SIGNATURE,'identity_aliases':identity.load_aliases(con),**{k: sp.get(k) for k in ('task_type','new_class','target_c','target_cs_json','a1_json','a2_json','a3_json','b_json','hard_filters_json','price_target','price_elasticity','brand_filter','brand_requirements_json','wants_hot','wants_new','target_products_json')}})


def recommendations(con, sp, force=False):
    if sp['task_type']=='modify':return [],{'mode':'modification','total':0,'message':'改香按锁定对象和修改要求推进，不生成推荐候选。'}
    if sp['task_type'] not in ('recommend_simple', 'recommend_brand', 'find_product', 'match_sample', 'create', 'modify'):
        return [], {}
    last = db.one(con, 'select * from recommendations where subproject_id=? order by rowid desc limit 1', (sp['id'],))
    signature = rec_signature(sp,con)
    if last:
        stored = db.jload(last.get('filters_json'), {})
        if stored.get('signature') == signature and not force:
            items = []
            for r in db.rows(con, 'select * from recommendation_items where recommendation_id=? order by rank', (last['id'],)):
                item = db.jload(r.get('snapshot_json'), {})
                items.append({**item, 'id':r['id'], 'decision':r['decision'], 'note':r['note']})
            return items, stored.get('meta', {})
    for_reference = sp['task_type'] in ('create', 'modify')
    items, meta = reco.recommend(con, {**sp, 'task_type':'recommend_brand'} if for_reference else sp)
    if for_reference: meta['mode'] = 'reference'
    rid = db.uid('r_')
    snapshot = dict(signature=signature, conditions={k:sp.get(k) for k in ('task_type','new_class','a1_json','a2_json','a3_json','b_json','target_cs_json','price_target','price_elasticity','brand_requirements_json')}, meta=meta)
    con.execute('insert into recommendations values(?,?,?,?,?)', (rid, sp['id'], db.js(snapshot), meta.get('algorithm', 'v3'), db.now()))
    for i, x in enumerate(items, 1):
        old = db.one(con, '''select i.decision,i.note from recommendation_items i join recommendations r on r.id=i.recommendation_id
                           where r.subproject_id=? and i.code=? order by i.rowid desc limit 1''', (sp['id'], x['code'])) or {}
        iid = db.uid('ri_')
        con.execute('''insert into recommendation_items(id,recommendation_id,code,rank,ab_score,ab_hits_json,price_gap,reason,c_json,c_score,snapshot_json,decision,note)
                       values(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (iid, rid, x['code'], i, x.get('ab_score',0), db.js(x.get('ab_hits',[])), x.get('price_gap'), x.get('reason',''),
                     db.js({'all':x.get('c_all',[]),'matches':[]}), x.get('c_score',0), db.js(x), old.get('decision'), old.get('note')))
        x.update(id=iid, decision=old.get('decision'), note=old.get('note'))
    return items, meta


def endpoint_checks(con, sp, defaults):
    r = db.one(con, 'select data_json from briefs where subproject_id=? order by version desc limit 1', (sp['id'],))
    bd = model.brief(db.jload(r['data_json'], {}) if r else {})
    d = defaults
    rows = []
    for code, label, detail in [('IFRA','IFRA 用途与浓度',d.get('ifra')), ('ALLERGEN','过敏原信息',d.get('allergen')), ('SDS','SDS / COA',d.get('sds_coa'))]:
        if detail: rows.append(('法规',code,label,'default',str(detail)))
    for region, detail in d.get('regulatory_by_region',{}).items():
        rows.append(('法规','REGION:'+region,'市场法规：'+region,'default',str(detail)))
    p_labels = dict(P1='强度',P2='爆发',P3='扩散',P4='特征保持',P5='平衡',P6='层次',P7='留香',P8='均匀性',P9='再释放',P10='遮盖',P11='舒适')
    s_labels = dict(S1='基质相容',S2='温度稳定',S3='光照稳定',S4='燃烧 / 闪点',S5='包材相容',S6='批次一致',S7='供货周期')
    for codes, section, labels in [(d.get('performance_codes',[]),'表现力',p_labels),(d.get('stability_codes',[]),'稳定性',s_labels)]:
        for code in codes: rows.append((section,code,labels.get(code,code),'default',labels.get(code,code)))
    comp = bd['compliance']
    for text in comp.get('regulatory',[]):
        if text: rows.append(('法规','CUSTOM:'+model.fingerprint(str(text))[:12],str(text)[:100],'customer',str(text)))
    for key, label in [('allergen','客户过敏原要求'),('flash_point','客户闪点要求'),('stability','客户稳定性要求'),('color','客户颜色要求'),('substrate_test','客户基料测试要求'),('halal','客户清真要求')]:
        if comp.get(key): rows.append(('客户要求','CUSTOM:'+key,label,'customer',str(comp[key])))
    existing_text = {r[4] for r in rows if r[3] == 'customer'}
    for req in bd.get('customer_requirements', []):
        if req.get('text') and req['text'] not in existing_text:
            rows.append(('客户额外要求', 'EXTRA:'+model.fingerprint(req['text'])[:12], req['text'][:100], 'customer', req['text']))
    keep = {r[1] for r in rows}
    existing = db.rows(con, 'select * from endpoint_checks where subproject_id=?', (sp['id'],))
    for r in existing:
        if r['code'] not in keep: con.execute('delete from endpoint_checks where subproject_id=? and code=?', (sp['id'],r['code']))
    for section, code, label, source, detail in rows:
        old = next((r for r in existing if r['code'] == code), None)
        unchanged = old and old.get('detail') == detail
        con.execute('''insert into endpoint_checks(subproject_id,section,code,label,status,source,detail,note,updated_at) values(?,?,?,?,?,?,?,?,?)
                       on conflict(subproject_id,code) do update set section=excluded.section,label=excluded.label,status=excluded.status,source=excluded.source,detail=excluded.detail,note=excluded.note,updated_at=excluded.updated_at''',
                    (sp['id'],section,code,label,old['status'] if unchanged else 'pending',source,detail,old['note'] if unchanged else '',old['updated_at'] if unchanged else db.now()))
    return db.rows(con, "select * from endpoint_checks where subproject_id=? order by source='customer' desc,section,code", (sp['id'],))
