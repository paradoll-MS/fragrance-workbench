from pathlib import Path
import sys,json,importlib.util
sys.path.insert(0,str(Path('fragrance-copilot-v3').resolve()))
from app import parse
out=Path('fragrance-copilot-v3/data/verification/逐本');out.mkdir(parents=True,exist_ok=True)
for f in Path('案例/逐本').iterdir():
 if not f.is_file():continue
 ex=parse.extract(f,f.name)
 (out/(f.stem+'.txt')).write_text(ex['text'],encoding='utf-8')
 (out/(f.stem+'.json')).write_text(json.dumps({k:v for k,v in ex.items() if k!='images'},ensure_ascii=False,indent=2),encoding='utf-8')
 print(f.name, 'chars',len(ex['text']),'pages',ex['page_count'],'status',ex['status'])
print('fitz',importlib.util.find_spec('fitz') is not None)
