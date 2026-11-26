import json
from app import config
from app.domain import brief as bm
from app.intelligence import parse, targeting
from app.workflow.service import Workbench
import tests.test_brief as T

wb = Workbench(database=config.DATA/'debug-brief.sqlite3')
r = parse.shape(T.RAW, [{"id":"s1","locator":"p1","kind":"text","text":T.SOURCE}], wb.catalog.categories, [o["id"] for o in wb.rules.category_options()])
print('dirs', len(r['directions']))
d = r['directions'][0]
print('brief keys', d['brief'].keys())
print('app', d['brief'].get('application_id'), d['conditions'].get('application_id'))
f = bm.merge(r['shared'], d['brief'], d['conditions'].get('application_id'))
print('fields app', f.get('application_id'), 'scent', f.get('scent_text'))
cands = wb.catalog.c_candidates(f.get('application_id') or '')
print('cands', len(cands), cands[0]['c_id'] if cands else None)
ch = cands[0]['c_id']

def fake(model, messages, limit, timeout=40):
    return {"c_ids":[ch], "items":[{"c_id":ch,"basis":"蓝甘菊品牌香为主调","confidence":0.8}], "used_conditions":[], "unmapped":[]}
targeting.json_object = fake
res = targeting.tag_direction(f, 'recommend_brand', wb.catalog, wb.config)
print(json.dumps(res, ensure_ascii=False)[:800])
