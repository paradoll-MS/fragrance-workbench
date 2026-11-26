from pathlib import Path
import json,hashlib,sqlite3
root=Path(__file__).resolve().parents[1];tables=['library_items','library_tags','c_nodes','c_ab','formula_product_labels','category_map','terms','term_aliases'];report={}
for table in tables:
 results=[]
 for folder in ['fragrance-copilot-v2','fragrance-copilot-v3']:
  path=root.parent/folder/'data/app.sqlite3';c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);h=hashlib.sha256();count=0
  for row in c.execute('select * from '+table+' order by rowid'):
   h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n');count+=1
  c.close();results.append({'count':count,'sha256':h.hexdigest()})
 report[table]={'unchanged':results[0]==results[1],'v2':results[0],'v3':results[1]}
(root/'data/verification/library_integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('library tables unchanged',all(x['unchanged'] for x in report.values()))
print([(k,x['v3']['count'],x['unchanged']) for k,x in report.items()])
