"""V3 data contracts shared by understanding, editing, and task handoffs."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

TYPES = ('find_product', 'match_sample', 'recommend_simple', 'recommend_brand', 'modify', 'create')
BUSINESS_POLICY = '20261030-semantic-completeness-required-products'
SPECIAL_REQUIREMENT_KINDS = {'document','certificate','claim'}
A_EVIDENCE_ROLES = {'explicit_scent_target','main_accord'}
TERMINAL = {'sample_initial', 'sample_final', 'done', 'cancelled', 'library_intake'}
GROUPS = {
    'project': dict(name='', customer='', brand='', sales='', evaluator='', grade='', summary='',
                    customer_profile='', contacts=[], overall_deadline='', coordination_notes='', coordination_events=[]),
    'product': dict(name='', category_l1='', category_l2='', category_l3='', application='', form='',
                    usage='', substrate='', dosage='', target_audience=''),
    'scent': dict(theme='', core_position='', structure='', principles=[], directions=[], direction_notes={}, references=[], families=[],
                  top=[], middle=[], base=[], note_references=[], main_accord='', feelings=[], scenes=[], exclusions=[], intensity='', longevity='', diffusion=''),
    'commercial': dict(target_price=None, markets=[], channel='', annual_volume='', sample_due='', terminal_price=''),
    'compliance': dict(markets=[], regulatory=[], allergen='', halal='', flash_point='', stability='', color='', substrate_test=''),
    'deliverables': dict(type='', quantity='', recipient='', deadline='', notes=''),
}


def merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in patch.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def project_context(row, group=None):
    out=merge(GROUPS['project'],group or {})
    for key in ('name','customer','brand','sales','evaluator','grade'):
        if row.get(key): out[key]=row[key]
    return out


def inherit(shared, specific):
    """Model empty placeholders mean unspecified; explicit local values override shared facts."""
    out = copy.deepcopy(shared)
    for key, value in specific.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = inherit(out[key], value)
        elif value not in (None, '', [], {}):
            out[key] = copy.deepcopy(value)
        elif key not in out:
            out[key] = copy.deepcopy(value)
    return out


def followup_defaults(parent, current, superseded=()):
    """Carry stable product constraints, never obsolete scent recipes or prior-round due dates."""
    parent=brief(parent)
    stable = {k: copy.deepcopy(parent.get(k) or {}) for k in ('product','planning','compliance')}
    stable['commercial'] = {k:v for k,v in (parent.get('commercial') or {}).items() if k != 'sample_due'}
    out = inherit(stable, current)
    notes=(out.get('deliverables') or {}).get('notes','')
    if not (out.get('manual_overrides') or {}).get('deliverables.notes'):
        notes=notes.replace('先确认改香基准，内部香精编号补齐后执行调香。','承袭首轮实发记录，编号随源记录同步。')
        out.setdefault('deliverables',{})['notes']=notes
    ongoing = [dict(r,source_scope='inherited') for r in parent.get('customer_requirements',[])
               if r.get('category') in SPECIAL_REQUIREMENT_KINDS and r.get('text') not in superseded]
    out['customer_requirements'] = list({(r.get('text'),r.get('category')):r for r in ongoing + current.get('customer_requirements',[])}.values())
    register = [dict(r,source_scope='inherited') for r in parent.get('requirement_register',[]) if r.get('category') in ('substrate','compliance','performance','stability') and r.get('text') not in superseded]
    out['requirement_register'] = list({(r.get('text'),r.get('category')):r for r in register + current.get('requirement_register',[])}.values())
    return brief(out)


def brief(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('简报必须是对象')
    value = copy.deepcopy(value or {})
    aliases = {'product': {'product_name':'name', 'base':'substrate'},
               'scent': {'direction':'theme', 'formula':'structure'},
               'compliance': {'requirements':'regulatory'}}
    for group, fields in aliases.items():
        obj = value.get(group)
        if isinstance(obj, dict):
            for alias, canonical in fields.items():
                if alias in obj:
                    if not obj.get(canonical): obj[canonical] = obj[alias]
                    obj.pop(alias)
    commercial = value.get('commercial') or {}
    if isinstance(commercial, dict):
        for alias, group, key in [('target_audience','product','target_audience'),('positioning','scent','core_position'),('series_concept','scent','theme')]:
            if commercial.get(alias) and not value.setdefault(group, {}).get(key): value[group][key] = commercial[alias]
        if commercial.get('tier'):
            value.setdefault('planning', {}).setdefault('launch_tier', commercial['tier'])
        if commercial.get('role'):
            value.setdefault('planning', {}).setdefault('priority_reason', commercial['role'])
    deliverables = value.get('deliverables') or {}
    if isinstance(deliverables, dict):
        for alias in ('overall','common','stage_gates','stage'):
            if deliverables.get(alias):
                text = deliverables[alias]
                text = '\n'.join(str(x) for x in text) if isinstance(text,list) else str(text)
                deliverables['notes'] = '\n'.join(x for x in [deliverables.get('notes') or '',text] if x)
                deliverables.pop(alias)
        if not (value.get('planning') or {}).get('launch_tier'):
            # Normalize an explicitly labelled launch tier; do not infer it from votes or ABC tags.
            m = re.match(r'\s*([SABC])\s*级(?=首发|快速|快跟|低资源|香型库|储备|跟进|测试)',str(deliverables.get('notes') or ''))
            if m: value.setdefault('planning', {})['launch_tier'] = m.group(1)
    for key in GROUPS:
        if key in value and not isinstance(value[key], dict):
            raise ValueError(f'简报 {key} 必须是对象')
    out = merge(GROUPS, value)
    for group, fields in GROUPS.items():
        for field, default in fields.items():
            v = out[group].get(field)
            if isinstance(default, list) and not isinstance(v, list):
                out[group][field] = [] if v in (None, '') else [v]
            elif isinstance(default, dict) and not isinstance(v, dict):
                out[group][field] = {}
            elif isinstance(default, str) and v is None:
                out[group][field] = ''
    out.update(schema_version='3.0')
    out.setdefault('evidence', {})
    out.setdefault('open_questions', [])
    out.setdefault('customer_requirements', [])
    ordinary = out.setdefault('requirement_register', [])
    special = []
    for req in out['customer_requirements']:
        if req.get('category') in SPECIAL_REQUIREMENT_KINDS:
            special.append(req)
        else:
            ordinary.append({**req,'classification':'ordinary' if req.get('category') in ('scent','substrate','performance','stability','delivery') else 'needs_review'})
    out['customer_requirements']=special
    out['requirement_register']=list({(r.get('text'),r.get('category')):r for r in ordinary}.values())
    out.setdefault('manual_overrides', {})
    out.setdefault('planning', {})
    return out


def number(value, name, nullable=True, low=0, high=None):
    if nullable and value in ('', None):
        return None
    if isinstance(value, bool):
        raise ValueError(f'{name}必须是数值')
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name}必须是数值')
    if not math.isfinite(v) or v < low or (high is not None and v > high):
        raise ValueError(f'{name}超出允许范围')
    return v


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def track_manual(old, new):
    overrides = copy.deepcopy(old.get('manual_overrides') or {})
    for group in GROUPS:
        for key, value in new[group].items():
            if value != (old.get(group) or {}).get(key):
                overrides[group+'.'+key] = copy.deepcopy(value)
                new.setdefault('evidence', {})[group+'.'+key] = []
    for key in ('modification', 'customer_requirements', 'requirement_register', 'open_questions'):
        if new.get(key) != old.get(key): overrides[key] = copy.deepcopy(new.get(key))
    new['manual_overrides'] = overrides
    return new


def preserve_manual(old, new):
    for path, value in (old.get('manual_overrides') or {}).items():
        if '.' in path:
            group, key = path.split('.', 1)
            new.setdefault(group, {})[key] = copy.deepcopy(value)
        else:
            new[path] = copy.deepcopy(value)
    new['manual_overrides'] = copy.deepcopy(old.get('manual_overrides') or {})
    return new


def handoff(project, sp, bd):
    p, s, c, d = (bd[k] for k in ('product', 'scent', 'commercial', 'deliverables'))
    rows = [('项目', project.get('name')), ('客户 / 品牌', ' / '.join(filter(None, [project.get('customer'), project.get('brand')]))),
            ('目标', sp.get('title')), ('产品 / 品类', ' / '.join(filter(None, [p.get('name'), sp.get('category_l3')]))),
            ('基质 / 添加量', ' / '.join(filter(None, [p.get('substrate'), p.get('dosage')]))),
            ('人群', p.get('target_audience')), ('产品定位', s.get('core_position')), ('主韵',s.get('main_accord')), ('气味要求', s.get('theme')),
            ('改香基准', sp.get('base_formula_code') or sp.get('base_sample_reference')), ('改动要求', bd.get('modification')),
            ('目标价', f"{sp['price_target']:g} 元/kg" if sp.get('price_target') is not None else ''),
            ('市场', '、'.join(c.get('markets') or [])), ('交付', '；'.join(str(d[x]) for x in ('type','quantity', 'deadline', 'recipient', 'notes') if d.get(x)))]
    text = '\n'.join(f'{k}：{v}' for k, v in rows if v)
    requirements = bd.get('customer_requirements') or []
    if requirements:
        text += '\n客户额外要求：\n' + '\n'.join('• ' + str(r.get('text') or '') for r in requirements)
    return text
