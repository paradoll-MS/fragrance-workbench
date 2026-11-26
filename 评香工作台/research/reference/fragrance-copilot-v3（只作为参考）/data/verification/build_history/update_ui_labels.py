from pathlib import Path
p=Path('fragrance-copilot-v3/web/app.js');s=p.read_text(encoding='utf-8-sig')
s=s.replace("['find_product','recommend_simple','recommend_brand','match_sample'].includes(d.subproject.task_type)","Object.keys(types).includes(d.subproject.task_type)")
s=s.replace("const isRec=['find_product','recommend_brand','recommend_simple','match_sample'].includes(s.task_type)","const isRec=Object.keys(types).includes(s.task_type)")
s=s.replace('<h2>推荐候选</h2>',"<h2>${['create','modify'].includes(s.task_type)?'评香参考候选':s.task_type==='match_sample'?'标签检索候选':'推荐候选'}</h2>")
s=s.replace("button('选定香精并派发打样','select-codes','','primary')","button(['create','modify'].includes(s.task_type)?'保存参考香并附到调香任务':'选定香精并派发打样','select-codes','','primary')")
s=s.replace("toast('已派发打样');await openSub", "toast(['create','modify'].includes(state.sub.subproject.task_type)?'参考香已附到调香任务':'已派发打样');await openSub")
s=s.replace('<details><summary>完整需求与来源</summary>', '${requirementsHTML(d.sub_brief)}${planningHTML(d.sub_brief.planning)}<details><summary>完整需求与来源</summary>')
s=s.replace("coordination_notes:'项目对接约定'", "coordination_notes:'项目对接约定',coordination_events:'项目协调事项'")
s=s.replace('${esc(human(v))}</dd>', "${esc(k==='direction_notes'?Object.entries(v).map(([name,value])=>name+'：'+human(value)).join('；'):human(v))}</dd>")
s=s.replace("+requirementsHTML(b)+", "+requirementsHTML(b)+planningHTML(b.planning)+coordinationHTML(b.project?.coordination_events)+")
s+='''
function planningHTML(p){return p&&Object.keys(p).length?`<section class="brief-section"><h3>开发与上市计划</h3><dl>${Object.entries(p).filter(([k,v])=>human(v)).map(([k,v])=>`<div><dt>${esc(({launch_tier:'客户资源分层',development_target:'开发目标',commercialization_target:'商品化目标',launch_timing:'上市节奏',priority_reason:'优先依据'})[k]||'计划')}</dt><dd>${esc(human(v))}</dd></div>`).join('')}</dl></section>`:''}
function coordinationHTML(events){return events?.length?`<section class="brief-section"><h3>项目对接与协调</h3>${events.map(e=>`<div class="item"><strong>${esc(e.action||'协调事项')}</strong><p>${esc([e.owner,e.due_original,e.due_resolved,e.destination,e.quantity,e.purpose].filter(Boolean).join(' · '))}</p>${chip(({planned:'计划中',confirmed:'已确认',done:'已完成'})[e.status]||'待确认')}${refsHTML(e.source_refs)}</div>`).join('')}</section>`:''}
'''
p.write_text(s,encoding='utf-8')
