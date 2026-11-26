"""Read-only library catalogue plus application-owned brand/product aliases.

Names are resolved within brand identity, before category/price eligibility.
No model calls, keyword task classification, or writes to the eight library tables.
"""
import re
import unicodedata
import json
import hashlib
from . import db

SHORT_BRANDS={'tomford':{'tf','汤姆福特'}}
IDENTITY_RELATIONS={'仿香对象','名称明确同款','同款指认','同款'}
VERSION_WORDS={'edp','edt','extrait','parfum','eaudeparfum','eaudetoilette','淡香精','浓香精','淡香水','古龙水','香精版','新版','旧版','限量版','男香','女香'}
BUILTIN_BRAND_GROUPS=json.loads((db.ROOT/'spec/brand_name_aliases.json').read_text(encoding='utf-8'))['groups']
BUILTIN_ALIAS_SIGNATURE=hashlib.sha256(db.js(BUILTIN_BRAND_GROUPS).encode()).hexdigest()


def normal(value):
    text=unicodedata.normalize('NFKD',str(value).casefold())
    return re.sub(r'[\s\W_]+','', ''.join(ch for ch in text if not unicodedata.combining(ch)))


def product_key(value):
    text=unicodedata.normalize('NFKC',str(value)).replace('&',' and ')
    text=re.sub(r'(?<=\d)号$','',text.strip())
    # Decimal/edition separators are significant; 1.3 and 13 are not the same.
    text=re.sub(r'(?<=\d)\.(?=\d)','decimal',text)
    text=re.sub(r'(?<=\d)-(?=\d)','edition',text)
    return normal(text)


def load_aliases(con=None):
    own=con is None
    if own:con=db.connect()
    try:return db.rows(con,'select * from identity_aliases order by id')
    finally:
        if own:con.close()


def _raw_brand_forms(value):
    forms={normal(value)}
    forms.update(normal(x) for x in re.findall(r"[A-Za-z][A-Za-z\s&.'-]*|[\u4e00-\u9fff]+",str(value)))
    forms.discard('')
    for key,values in SHORT_BRANDS.items():
        if forms & ({key}|values):forms|={key}|values
    return forms

_BUILTIN_LOOKUP={}
for _canonical,_names in BUILTIN_BRAND_GROUPS.items():
    _forms=set().union(*(_raw_brand_forms(n) for n in [_canonical]+_names))
    for _name in _forms:_BUILTIN_LOOKUP.setdefault(_name,[]).append(_forms)

def _base_brand_forms(value):
    known=_BUILTIN_LOOKUP.get(normal(value),[])
    return set(known[0]) if len(known)==1 else _raw_brand_forms(value)

def brand_forms(value,aliases=None):
    forms=_base_brand_forms(value)
    rows=aliases if aliases is not None else load_aliases()
    before=-1
    while before!=len(forms):
        before=len(forms)
        for row in rows:
            if row['kind']=='brand':
                pair=_base_brand_forms(row['brand'])|_raw_brand_forms(row['alias'])
                if forms & pair:forms|=pair
    return forms


def same_brand(a,b,aliases=None):
    aliases=load_aliases() if aliases is None else aliases
    return bool(brand_forms(a,aliases)&brand_forms(b,aliases))


def brand_key(value,aliases=None):
    forms=brand_forms(value,aliases)
    return min(forms,key=lambda x:(x not in SHORT_BRANDS,not bool(re.fullmatch('[a-z0-9]+',x)),len(x),x)) if forms else ''


def bilingual_names(value):
    """Parse the library's bilingual name notation, preserving edition qualifiers."""
    text=unicodedata.normalize('NFKC',value).strip()
    parts=[p.strip() for p in re.split(r'[/|]',text) if p.strip()]
    if len(parts)!=2:
        match=re.fullmatch(r'(.+?)\s*\(([^()]*)\)',text)
        if match:parts=[p.strip() for p in match.groups()]
        else:
            match=re.fullmatch(r'([^\u4e00-\u9fff]+?)\s+([\u4e00-\u9fff].*)',text)
            if not match:match=re.fullmatch(r'([\u4e00-\u9fff][^A-Za-z]*?)\s+([^\u4e00-\u9fff]+)',text)
            parts=list(match.groups()) if match else []
    if len(parts)!=2:return []
    chinese=[p for p in parts if re.search(r'[\u4e00-\u9fff]',p)]
    latin=[p for p in parts if any(ch.isalpha() for ch in p) and not re.search(r'[\u4e00-\u9fff]',p)]
    if len(chinese)!=1 or len(latin)!=1:return []
    if any(normal(p) in VERSION_WORDS or re.search(r'\d\s*(?:ml|毫升)(?![A-Za-z])',p,re.I) for p in parts):return []
    if any(re.search(r'浓度|版本|限量|限定|(?:新|旧|珍藏|浓香|淡香)版',p) for p in parts):return []
    editions=[set(re.findall(r'(?<![A-Za-z])(?:EDP|EDT|Extrait|Parfum)(?![A-Za-z])',p,re.I)) for p in parts]
    if {v.casefold() for v in editions[0]}!={v.casefold() for v in editions[1]}:return []
    numbers=[set(re.findall(r'\d+',p)) for p in parts]
    if all(numbers) and numbers[0]!=numbers[1]:return []
    return parts


class Index:
    def __init__(self,con):
        self.aliases=load_aliases(con)
        self.items=db.rows(con,'select * from library_items')
        self.labels=db.rows(con,'select * from formula_product_labels')
        self.by_code={r['code']:r for r in self.items};self.by_label={};self.parents={};self.names={};self.brands={}
        for r in self.items:
            for b in db.jload(r.get('brand_tags_json'),[])+[r.get('primary_brand') or '']:
                if b:self.brands.setdefault(r['code'],set()).update(brand_forms(b,self.aliases))
        for r in self.labels:
            self.by_label.setdefault(r['code'],[]).append(r)
            self.brands.setdefault(r['code'],set()).update(brand_forms(r['brand'],self.aliases))
            if r['relation'] not in IDENTITY_RELATIONS or r['code'] not in self.by_code:continue
            key=brand_key(r['brand'],self.aliases);p=(key,product_key(r['product']))
            self.root(p);self.names.setdefault(p,set()).add(r['product'])
            for name in bilingual_names(r['product']):
                part=(key,product_key(name));self.names.setdefault(part,set()).add(name);self.union(p,part)
        self.groups={};self.native={};self.custom={};self.numbers={}
        for r in self.labels:
            if r['relation'] not in IDENTITY_RELATIONS or r['code'] not in self.by_code:continue
            key=brand_key(r['brand'],self.aliases);root=self.root((key,product_key(r['product'])))
            group=self.groups.setdefault(root,{'brand':r['brand'],'names':set(),'records':[],'codes':set()})
            group['records'].append(r);group['codes'].add(r['code'])
        for (key,name),values in self.names.items():
            root=self.root((key,name));self.groups[root]['names'].update(values);self.native.setdefault((key,name),set()).add(root)
        for root,g in self.groups.items():
            g['product']=min(g['names'],key=lambda n:(bool(re.search(r'[\u4e00-\u9fff]',n)),len(n),n))
            for name in g['names']:
                digits=set(re.findall(r'\d+',unicodedata.normalize('NFKC',name)))
                tail=re.search(r'(\d+)\s*$',name)
                if tail and len(digits)==1:self.numbers.setdefault((root[0],tail[1]),set()).add(root)
        for row in self.aliases:
            if row['kind']!='product':continue
            key=brand_key(row['brand'],self.aliases);target=self.native.get((key,product_key(row['product'])),set())
            if len(target)==1:self.custom.setdefault((key,product_key(row['alias'])),set()).update(target)
        self.brand_aliases=set().union(*self.brands.values()) if self.brands else set()
        for row in self.aliases:
            if row['kind']=='brand':self.brand_aliases.update(brand_forms(row['alias'],self.aliases))

    def root(self,x):
        self.parents.setdefault(x,x)
        if self.parents[x]!=x:self.parents[x]=self.root(self.parents[x])
        return self.parents[x]

    def union(self,a,b):self.parents[self.root(b)]=self.root(a)

    def resolve(self,brand,query,version='',allow_number=True):
        key=brand_key(brand,self.aliases);q=product_key(query)
        roots=self.native.get((key,q),set()) or self.custom.get((key,q),set());mode='name_or_alias'
        number=re.fullmatch(r'(?:no[.\s]*|n[°º]\s*|#\s*)?(\d+)(?:号)?',unicodedata.normalize('NFKC',str(query)).strip(),re.I)
        if not roots and allow_number and brand and number:
            roots=self.numbers.get((key,number[1]),set());mode='brand_number'
        if version:
            extended=self.native.get((key,product_key(str(query)+' '+str(version))),set()) or self.custom.get((key,product_key(str(query)+' '+str(version))),set())
            if not extended:
                extended=set()
                for root in roots:
                    for name in self.groups[root]['names']:
                        extended.update(self.native.get((key,product_key(name+' '+str(version))),set()))
            roots=extended
        options=[{'brand':self.groups[r]['brand'],'product':self.groups[r]['product'],'aliases':sorted(self.groups[r]['names']),'codes':sorted(self.groups[r]['codes'])} for r in sorted(roots)]
        return {'status':'matched' if len(roots)==1 else 'ambiguous' if roots else 'unmatched','mode':mode,'brand':brand,'query':query,'version':version,'options':options,'roots':set(roots)}

    def product_match(self,label,query,brand='',version=''):
        if brand and not same_brand(brand,label['brand'],self.aliases):return False
        target=self.resolve(brand or label['brand'],query,version,allow_number=bool(brand))
        left=self.resolve(label['brand'],label['product'],allow_number=bool(brand))
        return target['status']=='matched' and left['status']=='matched' and target['roots']==left['roots']

    def catalog(self,brand=''):
        brands={};products=[]
        for root,g in self.groups.items():
            b=brands.setdefault(root[0],{'brand':g['brand'],'product_count':0,'codes':set()});b['product_count']+=1;b['codes'].update(g['codes'])
            if brand and same_brand(g['brand'],brand,self.aliases):
                custom=[r['alias'] for r in self.aliases if r['kind']=='product' and same_brand(r['brand'],g['brand'],self.aliases) and self.native.get((root[0],product_key(r['product'])))=={root}]
                products.append({'brand':g['brand'],'product':g['product'],'aliases':sorted(g['names']|set(custom)),'code_count':len(g['codes'])})
        return {'brands':sorted([{'brand':b['brand'],'product_count':b['product_count'],'code_count':len(b['codes'])} for b in brands.values()],key=lambda b:b['brand'].casefold()),'products':sorted(products,key=lambda p:p['product'].casefold())}

    def _split_brand(self,text):
        q=normal(text);a=next((a for a in sorted(self.brand_aliases,key=lambda a:(-len(a),a)) if len(a)>=2 and (q.startswith(a) or q.endswith(a))),None)
        if not a:return '',text
        if q.startswith(a):
            end=next(i for i in range(1,len(text)+1) if normal(text[:i])==a);return a,text[end:].strip()
        start=next(i for i in range(len(text)-1,-1,-1) if normal(text[i:])==a);return a,text[:start].strip()

    def search(self,query,limit=100,brand='',product=''):
        if not brand and not product:
            exact=next((r for r in self.items if r['code'].casefold()==query.strip().casefold()),None)
            if exact:return [{**exact,'matched_by':['编号'],'product_identities':self.by_label.get(exact['code'],[])}],1
        global_roots=set()
        if not brand and not product:
            for b in {g['brand'] for g in self.groups.values()}:global_roots.update(self.resolve(b,query,allow_number=False)['roots'])
        if not brand and not global_roots:brand,remainder=self._split_brand(query.strip())
        else:remainder=query.strip()
        wanted=product or remainder;resolution=self.resolve(brand,wanted) if brand and wanted else None
        groups=resolution['roots'] if resolution else global_roots
        if not brand and wanted:
            for b in {g['brand'] for g in self.groups.values()}:groups.update(self.resolve(b,wanted,allow_number=False)['roots'])
        codes=set().union(*(self.groups[r]['codes'] for r in groups)) if groups else set()
        q=product_key(wanted);result=[]
        for row in self.items:
            labels=self.by_label.get(row['code'],[]);score=0;matched=[]
            if not query and not brand and not product:score=1
            elif normal(query)==normal(row['code']) and not brand and not product:score=1000;matched=['编号']
            elif brand:
                if not brand_forms(brand,self.aliases)&self.brands.get(row['code'],set()):continue
                if not wanted:score=100;matched=['品牌']
                elif row['code'] in codes:score=500;matched=['品牌','名称有歧义，仅列候选' if resolution['status']=='ambiguous' else '产品名称 / 别名 / 编号']
                elif product or (resolution and resolution['status']=='matched'):continue
                elif q in product_key(row['name']) or any(q in product_key(l['product']) for l in labels):score=200;matched=['名称文字（含参考标注）']
            else:
                if q in normal(row['code']):score=350;matched=['编号']
                elif q==product_key(row['name']):score=300;matched=['名称']
                elif q in product_key(row['name']):score=200;matched=['名称']
                elif row['code'] in codes:score=250;matched=['产品身份别名（多产品同名需确认）' if len(groups)>1 else '产品身份别名']
                elif any(normal(wanted) in b for b in self.brands.get(row['code'],set())):score=100;matched=['品牌']
                elif any(q in product_key(l['product']) for l in labels):score=150;matched=['产品身份文字']
            if score:result.append({**row,'matched_by':matched,'product_identities':labels,'_rank':score})
        result.sort(key=lambda r:(-r['_rank'],-int(r.get('central') or 0),-int(r.get('is_hot') or 0),r['code']))
        for row in result:row.pop('_rank')
        return result[:limit],len(result)


def register_alias(con,body):
    kind=body.get('kind','product');brand=str(body.get('brand') or '').strip();product=str(body.get('product') or '').strip();alias=str(body.get('alias') or '').strip()
    if kind not in ('brand','product') or not brand or not alias or max(len(brand),len(product),len(alias))>200:raise ValueError('请填写有效的品牌、产品与别名')
    index=Index(con)
    if kind=='product':
        target=index.resolve(brand,product,allow_number=False)
        if target['status']!='matched':raise ValueError('请选择目录里唯一的规范产品后再登记别名')
        product=target['options'][0]['product'];brand=target['options'][0]['brand']
        native=index.native.get((brand_key(brand,index.aliases),product_key(alias)),set())
        if native and native!=target['roots']:raise ValueError('该名称已是另一产品的库内名称，不能覆盖')
    else:
        product=''
        matches=[b for b in index.catalog()['brands'] if same_brand(brand,b['brand'],index.aliases)]
        if len(matches)!=1:raise ValueError('请选择唯一的现有品牌')
        brand=matches[0]['brand']
        if any(same_brand(alias,b['brand'],index.aliases) and not same_brand(brand,b['brand'],index.aliases) for b in index.catalog()['brands']):raise ValueError('该别名已属于另一品牌，不能将两个品牌合并')
    existing=db.one(con,'select * from identity_aliases where kind=? and brand=? and product=? and alias=?',(kind,brand,product,alias))
    if existing:return existing['id']
    aid=db.uid('alias_');con.execute('insert into identity_aliases values(?,?,?,?,?,?,?)',(aid,kind,brand,product,alias,'user_confirmed',db.now()))
    db.audit(con,'identity_alias',aid,'created',None,{'kind':kind,'brand':brand,'product':product,'alias':alias},reason='应用层名称别名，不修改原始香精库')
    return aid
