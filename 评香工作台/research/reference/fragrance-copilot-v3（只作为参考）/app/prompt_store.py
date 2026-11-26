"""Registry for active production instructions; case fixtures never enter prompts."""
import hashlib,json
from . import db
GENERATION=('understand_project','repair_mapping','repair_abc','repair_followup')
def system(name):
    manifest=json.loads((db.ROOT/'prompts/manifest.json').read_text(encoding='utf-8'))
    entry=manifest['active'][name]
    text=(db.ROOT/entry['file']).read_text(encoding='utf-8')
    return ((db.ROOT/'spec/business_rules.md').read_text(encoding='utf-8')+'\n' if entry.get('common_policy') else '')+text

def revision(scope='generation'):
    names=GENERATION if scope=='generation' else tuple(json.loads((db.ROOT/'prompts/manifest.json').read_text(encoding='utf-8'))['active'])
    return hashlib.sha256('\n'.join(name+'\n'+system(name) for name in names).encode()).hexdigest()
