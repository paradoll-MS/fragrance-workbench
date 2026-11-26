"""Business policy and lossless, compact model dictionaries."""
from . import db

TERM_FIELDS=('id','domain','layer','label','definition')
C_FIELDS=('id','new_class','dimension','parent_id','label','path','description')
CATEGORY_FIELDS=('k_code','level1','level2','level3','norm_class','new_class','aliases_json','identity_json','norm_status','new_status')

def ontology(con):
    terms=db.rows(con,'select id,domain,layer,label,definition from terms')
    nodes=db.rows(con,'select * from c_nodes');by_id={r['id']:r for r in nodes}
    groups={};overrides={}
    for n in nodes:
        lineage=[];at=n;seen=set()
        while at and at['id'] not in seen:
            seen.add(at['id']);lineage.insert(0,at['label']);at=by_id.get(at.get('parent_id'))
        path=' / '.join([n['new_class'],n['dimension']]+lineage)
        if path!=n['path']:overrides[n['id']]=n['path']
        groups.setdefault(n['new_class'],[]).append([n[k] for k in ('id','dimension','parent_id','label','description')])
    return {'format':'column_tables_v1','terms':{'columns':list(TERM_FIELDS),'rows':[[r[k] for k in TERM_FIELDS] for r in terms]},
            'c_nodes':{'columns':['id','dimension','parent_id','label','description'],'by_class':groups,'path_rule':'new_class / dimension / ancestor labels / label','path_overrides':overrides},
            'categories':{'columns':list(CATEGORY_FIELDS),'rows':[[r[k] for k in CATEGORY_FIELDS] for r in db.rows(con,'select * from category_map')]}}

def expand(value):
    terms=[dict(zip(value['terms']['columns'],r)) for r in value['terms']['rows']]
    nodes=[dict(zip(value['c_nodes']['columns'],r),new_class=cl) for cl,rows in value['c_nodes']['by_class'].items() for r in rows];by_id={r['id']:r for r in nodes}
    for n in nodes:
        lineage=[];at=n;seen=set()
        while at and at['id'] not in seen:
            seen.add(at['id']);lineage.insert(0,at['label']);at=by_id.get(at.get('parent_id'))
        n['path']=value['c_nodes']['path_overrides'].get(n['id'],' / '.join([n['new_class'],n['dimension']]+lineage))
    return {'terms':terms,'c_nodes':nodes,'categories':[dict(zip(value['categories']['columns'],r)) for r in value['categories']['rows']]}

def budget(snapshot,config):
    small=len(snapshot['artifacts'])<=4 and len(snapshot['subprojects'])<=4 and sum(len(a.get('text') or '') for a in snapshot['artifacts'])<=6000
    thinking=bool(config.get('understanding_thinking',False))
    return {'reasoning_effort':(config.get('understanding_reasoning_effort') or 'high') if thinking else None,
            'thinking':thinking,
            'max_tokens':int(config.get('understanding_max_tokens') or (24000 if small else 48000)),
            'timeout':180 if small else 420}
