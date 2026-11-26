"""Deterministic V3 recall and scoring. No model calls or library mutations."""
from __future__ import annotations
import re
import unicodedata
from . import db, identity


def values(sp, key):
    return db.jload(sp.get(key + '_json'), []) or []


def target_cs(sp):
    return values(sp, 'target_cs') or ([sp['target_c']] if sp.get('target_c') else [])


def scope(con, tid):
    found, todo = {tid}, [tid]
    while todo:
        parent = todo.pop()
        for r in db.rows(con, 'select id from c_nodes where parent_id=?', (parent,)):
            if r['id'] not in found:
                found.add(r['id']); todo.append(r['id'])
    return found


def default_filters(sp):
    a1 = values(sp, 'a1')
    a23 = values(sp, 'a2') + values(sp, 'a3')
    groups = ([{'key': 'A1', 'ids': a1, 'mode': 'any'}] if a1 else
              [{'key': 'A23', 'ids': a23, 'mode': 'any'}] if a23 else [])
    return {'category_enabled': True, 'categories': [sp['new_class']] if sp.get('new_class') else [],
            'price_enabled': True, 'tags': groups,
            'brand_enabled': bool(sp.get('brand_filter') or values(sp, 'brand_requirements')) if sp.get('task_type') == 'recommend_simple' else False,
            'hot_enabled': bool(sp.get('wants_hot')) if sp.get('task_type') == 'recommend_simple' else False,
            'new_enabled': bool(sp.get('wants_new')) if sp.get('task_type') == 'recommend_simple' else False}


def filters(sp):
    saved = db.jload(sp.get('hard_filters_json'), None)
    return saved if isinstance(saved, dict) else default_filters(sp)


def normal(s):
    text = unicodedata.normalize('NFKD', str(s).casefold())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'[\s\W_]+', '', text)


def brand_matches(row, requirements,aliases=None):
    brands = values(row, 'brand_tags')
    for req in requirements:
        if req.get('kind') == 'dupe':
            if row.get('is_brand_dupe'):
                return True
        elif req.get('kind') == 'brand':
            want = req.get('value')
            if want and any(identity.same_brand(want,b,aliases) for b in brands):
                return True
    return not requirements


def requirements(sp):
    reqs = values(sp, 'brand_requirements')
    if not reqs and sp.get('brand_filter'):
        reqs = [{'kind': 'brand', 'value': v.strip()} for v in re.split('[,，;；]', sp['brand_filter']) if v.strip()]
    # Keep the leaf of each requested branch, preserving independent branches (OR).
    return [r for r in reqs if not any(r != s and r.get('path') and s.get('path') and
            len(s['path']) > len(r['path']) and s['path'][:len(r['path'])] == r['path'] for s in reqs)]


def recommend(con, sp):
    if sp['task_type'] == 'find_product':
        return find_product(con, sp)
    if sp['task_type'] not in ('recommend_brand', 'recommend_simple', 'match_sample'):
        return [], {'message': '此类型在任务流程中推进', 'total': 0}
    if sp['task_type']=='recommend_brand' and not any(values(sp,k) for k in ('a1','a2','a3','b','target_cs')):
        return [], {'total':0,'needs_abc_review':True,'message':'尚无可用于语义推荐的ABC标签，请完成映射或由评香确认；可用香精库检索浏览原始记录。','algorithm':'v3-abc-pending'}
    f = filters(sp)
    if f.get('category_enabled') and not f.get('categories'):
        raise ValueError('先选择内部品类，或取消品类硬筛')
    price = sp.get('price_target')
    maximum = float(price) * (1 + float(sp.get('price_elasticity') if sp.get('price_elasticity') is not None else 20) / 100) if price is not None else None
    all_tags = {}
    for t in db.rows(con, "select code,tag_id,domain,layer,label,path from library_tags where scope='main'"):
        all_tags.setdefault(t['code'], {})[t['tag_id']] = t
    # A/B JSON columns are also authoritative in older library snapshots.
    term_map = {t['id']: t for t in db.rows(con, 'select * from terms')}
    c_map = {t['id']: t for t in db.rows(con, 'select * from c_nodes')}
    c_ab = {}
    for t in db.rows(con, 'select * from c_ab'):
        c_ab.setdefault(t['c_id'], {})[t['term_id']] = t
    want_ab = set(values(sp, 'a1') + values(sp, 'a2') + values(sp, 'a3') + values(sp, 'b'))
    want_cs = target_cs(sp)
    demand_c_ab={}
    for cid in want_cs:
        for tid,t in c_ab.get(cid,{}).items():
            demand_c_ab.setdefault(tid,{'id':tid,'label':t['label'],'domain':t['domain'],'via_demand_cs':[]})['via_demand_cs'].append(cid)
    scopes = {x: scope(con, x) for x in set(want_cs + [i for g in f.get('tags', []) for i in g['ids'] if i in c_map])}
    locked = {i for g in f.get('tags', []) for i in g['ids']}
    reqs = requirements(sp)
    aliases=identity.load_aliases(con)
    rejected = dict(category=0, price=0, tags=0, brand=0, hot=0, new=0)
    out = []
    for row in db.rows(con, 'select * from library_items order by code'):
        tags = dict(all_tags.get(row['code'], {}))
        for tid in values(row, 'a1_ids') + values(row, 'a2_ids') + values(row, 'a3_ids') + values(row, 'c_ids'):
            if tid not in tags:
                t = term_map.get(tid) or c_map.get(tid) or {}
                tags[tid] = dict(tag_id=tid, label=t.get('label', tid), domain=t.get('domain', 'C'), layer=t.get('layer', 'C'))
        have = set(tags)
        cids = {tid for tid in have if tags[tid]['domain'] == 'C'}
        # The chosen main class and explicit co-classes are both recorded applicability.
        classes = {row.get('new_class')} | set(values(row, 'co_classes'))
        reason = None
        if f.get('category_enabled') and not classes.intersection(f.get('categories', [])):
            reason = 'category'
        elif f.get('price_enabled') and maximum is not None and (row['price'] is None or row['price'] > maximum):
            reason = 'price'
        else:
            for group in f.get('tags', []):
                matches = [bool(have & scopes.get(i, {i})) for i in group['ids']]
                if matches and not (all(matches) if group.get('mode') == 'all' else any(matches)):
                    reason = 'tags'; break
        if not reason and f.get('brand_enabled') and not brand_matches(row, reqs,aliases): reason = 'brand'
        if not reason and f.get('hot_enabled') and not row.get('is_hot'): reason = 'hot'
        if not reason and f.get('new_enabled') and not row.get('is_new'): reason = 'new'
        if reason:
            rejected[reason] += 1; continue
        direct_ab = sorted((have & want_ab) - locked)
        direct_c = [tc for tc in want_cs if tc not in locked and cids & scopes[tc]]
        # Demand C supplies the associated AB targets. Only the candidate's own
        # recorded A/B can match them; never infer candidate AB from candidate C.
        mapped = {tid:t for tid,t in demand_c_ab.items() if tid in have}
        hits = [{'id': tid, 'label': tags[tid]['label'], 'domain': tags[tid]['domain'], 'source': 'direct'} for tid in direct_ab]
        direct_a = sum(h['domain'] == 'A' for h in hits)
        direct_b = sum(h['domain'] == 'B' for h in hits)
        cs = 3 * len(direct_c)
        mapped_hits = list(mapped.values())
        total = len(hits) + cs + len(mapped_hits)
        out.append({**row, 'abc': list(tags.values()), 'a_score': direct_a, 'b_score': direct_b,
                    'c_score': cs, 'mapped_score': len(mapped_hits), 'ab_score': len(hits) + len(mapped_hits),
                    'score': total, 'ab_hits': hits, 'mapped_hits': mapped_hits, 'c_hits': direct_c,
                    'c_all': [dict(id=cid, label=tags[cid]['label'], path=tags[cid].get('path', '')) for cid in sorted(cids)],
                    'price_gap': row['price'] - price if row['price'] is not None and price is not None else None,
                    'reason': f'直接 A {direct_a} + B {direct_b} + C {cs}；需求 C 关联 AB 命中候选 A/B {len(mapped_hits)}；总分 {total}'})
    out.sort(key=lambda x: (-x['score'], -x['c_score'], x['price'] is None, x['price'] or 0, -(x.get('usage_count') or 0), x['code']))
    return out[:100], {'total': len(out), 'shown': min(100, len(out)), 'max_price': maximum if f.get('price_enabled') else None,
                       'filters': f, 'rejected': rejected, 'algorithm': 'v3-demand-c-ab-2','demand_c_ab':list(demand_c_ab.values()),
                       'price_note': '未提供目标价，价格不限制' if price is None else '',
                       'mode': 'tag_search' if sp['task_type'] == 'match_sample' else 'recommend',
                       'score_rule': '直接 A×1 + B×1 + C×3（硬筛标签除外）+ 需求C关联AB命中候选A/B×1（按AB去重）'}


def find_product(con, sp):
    index=identity.Index(con);found={};identity_codes=set();unresolved=[];resolutions=[];excluded={}
    f=filters(sp);categories=f.get('categories') or ([sp['new_class']] if sp.get('new_class') else [])
    price=sp.get('price_target');maximum=float(price)*(1+float(sp.get('price_elasticity') if sp.get('price_elasticity') is not None else 20)/100) if price is not None and f.get('price_enabled') else None
    for request in values(sp,'target_products'):
        brand,product,version=(str(request.get(k) or '').strip() for k in ('brand','product','version'))
        if not product:continue
        if brand:resolution=index.resolve(brand,product,version)
        else:
            roots=set()
            for g in index.groups.values():roots.update(index.resolve(g['brand'],product,version,allow_number=False)['roots'])
            resolution={'status':'matched' if len(roots)==1 else 'ambiguous' if roots else 'unmatched','mode':'name_or_alias','brand':brand,'query':product,'version':version,'roots':roots,'options':[{'brand':index.groups[r]['brand'],'product':index.groups[r]['product'],'codes':sorted(index.groups[r]['codes'])} for r in sorted(roots)]}
        resolutions.append({k:v for k,v in resolution.items() if k!='roots'})
        if resolution['status']!='matched':
            if version:unresolved.append(request)
            continue
        for root in resolution['roots']:
            group=index.groups[root]
            for code in sorted(group['codes']):
                row=index.by_code[code];identity_codes.add(code)
                classes={row.get('new_class')}|set(values(row,'co_classes'))
                reason=None
                if f.get('category_enabled') and categories and not classes.intersection(categories):reason='品类不适用'
                elif maximum is not None and row.get('price') is None:reason='价格待确认'
                elif maximum is not None and row['price']>maximum:reason='超过当前价格上限'
                if reason:
                    excluded[code]={'code':code,'name':row['name'],'price':row.get('price'),'reason':reason};continue
                labels=[r for r in group['records'] if r['code']==code]
                label=min(labels,key=lambda r:({'名称明确同款':0,'仿香对象':1,'同款指认':2}.get(r['relation'],3),r['product']))
                found[code]={**row,'score':0,'ab_score':0,'c_score':0,'abc':[],'product_identity':label,
                             'product_resolution':{k:v for k,v in resolution.items() if k!='roots'},
                             'reason':'品牌—产品身份匹配：'+group['brand']+' · '+group['product']+('（品牌内编号简称）' if resolution['mode']=='brand_number' else '')}
    rows=list(found.values());rows.sort(key=lambda r:(r.get('price') is None,r.get('price') or 0,r['code']))
    ambiguous=[r for r in resolutions if r['status']=='ambiguous'];missing=[r for r in resolutions if r['status']=='unmatched']
    message=''
    if not rows:
        if ambiguous:message='名称对应多个产品，请确认规范产品；没有自动猜选。'
        elif identity_codes:message='库中已有产品身份记录，但当前品类 / 价格条件下没有可用候选；请查看排除原因。'
        elif unresolved:message='未确认指定版本的产品身份；未用其它版本代替。'
        else:message='尚未解析到库内产品身份；可按品牌和产品目录查找或补充名称别名。'
    return rows[:100],{'total':len(rows),'shown':min(100,len(rows)),'identity_total':len(identity_codes),'max_price':maximum,
                       'algorithm':'v3-structured-product-catalog-2','resolutions':resolutions,'excluded_identity_records':list(excluded.values()),
                       'unverified_versions':unresolved,'unresolved_products':missing,'message':message}
