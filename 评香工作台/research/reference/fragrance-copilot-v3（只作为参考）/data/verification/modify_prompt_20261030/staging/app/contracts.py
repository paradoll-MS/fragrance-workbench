"""Validate wire types before hash-based semantic validation; retain correction traces."""
def normalize(result):
    changes=result.setdefault('contract_corrections',[])
    tag_fields={'a1','a2','a3','b','target_cs'}
    scalar={'id','key','artifact_id','source_id','parent_subproject_id','category_k_code','base_formula_code','task_type','title'}
    def atom(value,path,keys):
        if isinstance(value,str):return value
        if isinstance(value,dict):
            for key in keys:
                if isinstance(value.get(key),str) and value[key]:
                    changes.append({'path':path,'method':'explicit_identifier','original':value.copy(),'value':value[key]});return value[key]
        raise ValueError('模型字段 '+path+' 必须是文本标识，不能用对象或标签名称代替编号')
    def walk(value,path='result'):
        if isinstance(value,list):
            for i,child in enumerate(value):walk(child,path+'['+str(i)+']')
        elif isinstance(value,dict):
            for key,child in list(value.items()):
                if key.startswith('_') or key=='contract_corrections':continue
                at=path+'.'+key
                if key in tag_fields or key in ('subproject_keys','applies_to_keys'):
                    if not isinstance(child,list):raise ValueError('模型字段 '+at+' 必须是标识数组')
                    value[key]=[atom(x,at+'['+str(i)+']',('id','value') if key in tag_fields else ('key','id','value')) for i,x in enumerate(child)]
                elif key in scalar and child is not None:value[key]=atom(child,at,('id','value') if key!='key' else ('key','value'))
                elif key in ('source_refs','artifact_annotations','subprojects','abc_basis','target_products','coverage','customer_requirements','requirement_register'):
                    if not isinstance(child,list) or any(not isinstance(x,dict) for x in child):raise ValueError('模型字段 '+at+' 必须是对象数组')
                    walk(child,at)
                else:walk(child,at)
    walk(result)
    return result


def reference_stats(result):
    occurrences=0
    counts={'none':0,'whitespace':0,'split':0,'typo_anchor':0,'source_handle':0};unique=set()
    def walk(value,key=''):
        nonlocal occurrences
        if isinstance(value,list):
            for child in value:walk(child,key)
        elif isinstance(value,dict):
            if key in ('source_refs','evidence') and value.get('artifact_id'):
                occurrences+=1
                methods=value.get('corrections') or [value.get('correction','none')]
                for method in set(methods):counts[method]=counts.get(method,0)+1
                unique.add((value.get('artifact_id'),value.get('source_start'),value.get('source_end'),value.get('quote')))
            for k,v in value.items():
                if not k.startswith('_') and k not in ('contract_corrections','reference_corrections'):walk(v,k if k=='source_refs' or key=='evidence' or k=='evidence' else '')
    walk(result)
    return {'methods':counts,'occurrences':occurrences,'unique_spans':len(unique),'note':'重复引用不代表独立证据；原文定位成功不代表语义判断正确。'}
