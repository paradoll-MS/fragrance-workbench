"""Stable source-span handles: cite original evidence without regenerating long quotations."""
import re
from functools import lru_cache
from . import db

@lru_cache(maxsize=8)
def _index(key):
    result={};serial=0
    for aid,text,meta_json in key:
        metas=db.jload(meta_json,[]);located=[]
        for m in metas:
            part=m.get('text') or '';at=text.find(part) if part else -1
            if at>=0:located.append((at,at+len(part),m.get('locator') or '原文'))
        for block in re.finditer(r'\S[\s\S]*?(?=\n[ \t]*\n|\Z)',text):
            start,end=block.span();serial+=1;locator=next((loc for a,b,loc in located if start<b and end>a),'原文')
            result['S'+str(serial)]={'artifact_id':aid,'locator':locator,'source_start':start,'source_end':end}
    return result

def index(artifacts):
    values=artifacts.values() if isinstance(artifacts,dict) else artifacts
    return _index(tuple((a['id'],a.get('text') or '',a.get('text_meta_json') or '[]') for a in values))

def compact(value,lookup,artifacts):
    if isinstance(value,list):return [compact(x,lookup,artifacts) for x in value]
    if not isinstance(value,dict):return value
    aid=value.get('artifact_id')
    if aid in artifacts and ('quote' in value or 'source_start' in value):
        source=artifacts[aid].get('text') or '';quote=value.get('quote') or '';start=value.get('source_start');end=value.get('source_end')
        if start is None and quote:
            start=source.find(quote);end=start+len(quote)
        if start is not None and start>=0:
            match=next((sid for sid,ref in lookup.items() if ref['artifact_id']==aid and start>=ref['source_start'] and end<=ref['source_end']),None)
            if match:return {'source_id':match}
    return {k:compact(v,lookup,artifacts) for k,v in value.items()}
