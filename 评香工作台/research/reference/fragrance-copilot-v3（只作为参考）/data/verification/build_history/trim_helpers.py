import ast
from pathlib import Path
p=Path('fragrance-copilot-v3/app/legacy.py')
source=p.read_text(encoding='utf-8-sig');lines=source.splitlines();tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
keep={'log_message','_send','_json_body','_err','_ok','do_OPTIONS','do_GET','do_POST','do_PUT','do_PATCH','do_DELETE','library_search','projects_list','_drop_subproject','artifact_delete','artifact_get','artifact_file','artifact_classify','_norm_defaults','_resolve_category','fetch_link','usage'}
parts=[]
for node in cls.body:
 if isinstance(node,ast.FunctionDef) and node.name in keep:
  start=min([node.lineno]+[d.lineno for d in node.decorator_list])-1
  parts.append('\n'.join(lines[start:node.end_lineno]))
header='''"""Retained V2 HTTP/read helpers. Generation and task behavior live in V3 modules."""
from __future__ import annotations
import json
import re
import mimetypes
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from . import db
ROOT = Path(__file__).resolve().parents[1]

def project_or_404(con,pid):
    p = db.one(con,'select * from projects where id=?',(pid,))
    if not p: raise KeyError('项目不存在')
    return p

class Handler(BaseHTTPRequestHandler):
    def api(self,method,path,q):
        if method=='GET' and path=='/api/library/search': return self.library_search(q)
        if method=='GET' and path=='/api/categories':
            con=db.connect(); rows=db.rows(con,'select * from category_map order by k_code');con.close()
            return self._ok({'items':rows})
        if method=='GET' and path=='/api/library/meta':
            con=db.connect(); count=db.one(con,'select count(*) n from library_items')['n'];con.close()
            return self._ok({'formulas':count})
        if method=='POST' and path=='/api/category/resolve':
            b=self._json_body(); con=db.connect(); row=self._resolve_category(con,b.get('l3'));con.close()
            return self._ok({'item':row})
        return self._err('接口不存在',404)
'''
p.write_text(header+'\n\n'.join(parts)+'\n',encoding='utf-8')
