const PROJECT_ID = Number(params().get("id") || 0);
let VIEW = null;
let META = null;

const STAGE_KIND = { planned: "plain", developing: "warn", checking: "plain", shipping: "plain", complete: "ok" };

function refresh() {
  return get("/api/projects/" + PROJECT_ID).then(data => { VIEW = data; render(); });
}

async function advance(slot, action, payload) {
  const result = await post(`/api/projects/${PROJECT_ID}/slots/${slot.id}/advance`,
    { action, payload: payload || {}, revision: slot.revision });
  if (result.blocked) {
    const first = (result.issues || [])[0];
    throw new Error(first ? `${first.label}：${(first.missing || []).join("、") || first.next_action}` : "这一步还不能执行");
  }
  if (result.notice) toast(result.notice);
  await refresh();
}

function actionButton(slot, action, handler) {
  const button = h("button", { class: "btn small", text: action.label });
  button.addEventListener("click", () => run(button, async () => {
    if (handler) await handler();
    else await advance(slot, action.action, {});
  }));
  return button;
}

function slotActions(slot, goal) {
  const enabled = slot.actions.filter(item => item.enabled);
  const blocked = slot.actions.filter(item => !item.enabled);
  const row = h("div", { class: "row" });
  for (const action of enabled) {
    if (action.action === "pick") continue;
    row.append(actionButton(slot, action, handlerFor(slot, action.action, goal)));
  }
  const hints = blocked.map(item => {
    const issue = (item.issues || [])[0] || {};
    const why = (issue.missing || []).join("、") || issue.next_action || "条件未满足";
    return h("div", { class: "muted small", text: `${item.label}：${why}` });
  });
  return h("div", { class: "stack" }, row, ...hints);
}

function handlerFor(slot, action, goal) {
  if (action === "build_checks") return () => buildCheckDialog(slot, goal);
  if (action === "dispatch_checks") return () => advance(slot, "dispatch_checks", {});
  if (action.startsWith("release_")) return () => releaseDialog(slot, action);
  if (action === "prepare_sample") return () => sampleDialog(slot);
  if (action === "confirm_gc") return () => noteDialog(slot, "确认 GC 报告", "报告编号", slot.job && slot.job.gc_report, true, "confirm_gc");
  if (action === "accept_trial") return () => noteDialog(slot, "验收试作", "评语（可留空）", "", false, "accept_trial");
  if (action === "reject_trial") return () => noteDialog(slot, "退回调香", "下一次的意见", "", true, "reject_trial");
  if (action === "pause") return () => noteDialog(slot, "暂存目标位", "暂存原因（可留空）", "", false, "pause");
  return null;
}

function noteDialog(slot, title, label, value, required, action) {
  const input = textInput(value, label);
  const confirm = h("button", { class: "btn primary", text: "确认" });
  const box = dialog(title, [field(label, input)], [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), confirm]);
  confirm.addEventListener("click", () => run(confirm, async () => {
    if (required && !input.value.trim()) throw new Error("请填写" + label);
    box.close();
    await advance(slot, action, { note: input.value, report: input.value });
  }));
}

function buildCheckDialog(slot, goal) {
  const fields = (goal && goal.fields) || {};
  const options = [{ value: "", label: "先按通用与市场要求" }]
    .concat((META.review_categories || []).map(item => ({ value: item.id, label: item.name })));
  const category = selectInput(options, fields.review_category_id || "");
  const markets = textInput((fields.markets || []).join("、"), "例如：中国、日本");
  const note = h("div", { class: "muted small", text: "审查品类决定默认检查项；不确定时留空，只生成通用、市场与客户要求。" });
  const confirm = h("button", { class: "btn primary", text: "生成清单" });
  const box = dialog("生成检查清单", [field("审查品类", category), field("目标市场", markets), note],
    [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), confirm]);
  confirm.addEventListener("click", () => run(confirm, async () => {
    box.close();
    await advance(slot, "build_checks", {
      review_category: category.value,
      markets: markets.value.split(/[、,，;；\s]+/).filter(Boolean),
    });
  }));
}

function releaseDialog(slot, action) {
  const checks = slot.checks || { counts: {}, total: 0, releases: [] };
  const deferred = checks.total - (checks.counts.passed || 0) - (checks.counts.failed || 0);
  const note = textInput("", "暂缓说明或放行备注");
  const body = [
    h("div", { class: "muted small", text: `本期 ${checks.total} 条要求，已通过 ${checks.counts.passed || 0} 条，不符合 ${checks.counts.failed || 0} 条，其余 ${deferred} 条。` }),
    field("备注", note),
  ];
  const confirm = h("button", { class: "btn primary", text: "放行" });
  const box = dialog(META_RELEASE[action] || "放行", body, [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), confirm]);
  confirm.addEventListener("click", () => run(confirm, async () => {
    box.close();
    await advance(slot, action, { note: note.value, actor: "评香" });
  }));
}

const META_RELEASE = { release_warehouse: "入库放行", release_initial: "初寄样放行", release_formal: "正式寄样放行" };

function sampleDialog(slot) {
  const form = textInput(slot.payload.sample_form || "", "例如：10 ml 喷雾样");
  const quantity = textInput(slot.payload.quantity || "", "例如：10");
  const unit = textInput(slot.payload.unit || "ml", "ml / g");
  const confirm = h("button", { class: "btn primary", text: "预留" });
  const box = dialog("准备样品", [field("形态", form), h("div", { class: "grid2" }, field("数量", quantity), field("单位", unit))],
    [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), confirm]);
  confirm.addEventListener("click", () => run(confirm, async () => {
    box.close();
    await advance(slot, "prepare_sample", { form: form.value, quantity: quantity.value, unit: unit.value });
  }));
}

function statusChip(status) {
  const kind = status === "passed" ? "ok" : status === "failed" ? "bad"
    : status === "unverified" || status === "pending" ? "warn" : "";
  const labels = { passed: "通过", failed: "不符合", unverified: "待核销", pending: "已派发", needs_review: "待核对", not_applicable: "不适用" };
  return chip(labels[status] || status, kind);
}

function checkBlock(slot) {
  const checks = slot.checks;
  if (!checks) return h("div", { class: "muted small", text: "还没有检查清单。" });
  const counts = checks.counts || {};
  const line = h("div", { class: "row" },
    h("span", { class: "small", text: `检查清单 v${checks.revision} · ${checks.scope_label} · ${checks.total} 条` }),
    counts.passed ? chip("通过 " + counts.passed, "ok") : null,
    counts.pending ? chip("已派发 " + counts.pending) : null,
    counts.unverified ? chip("待核销 " + counts.unverified, "warn") : null,
    counts.failed ? chip("不符合 " + counts.failed, "bad") : null);
  const detail = h("div", { class: "tree" });
  let open = false;
  const toggle = h("button", { class: "btn ghost small", text: "展开清单" });
  toggle.addEventListener("click", () => {
    open = !open;
    toggle.textContent = open ? "收起清单" : "展开清单";
    if (!open) { detail.replaceChildren(); return; }
    for (const group of checks.departments) {
      detail.append(h("div", { class: "row" }, h("span", { class: "small", text: group.label }), chip(group.requirements.length + " 条")));
      for (const item of group.requirements) {
        detail.append(h("div", { class: "row top", style: { padding: "4px 0", borderBottom: "1px solid var(--line)" } },
          h("div", { style: { flex: "1" } },
            h("div", { text: item.metric_name + (item.subitem ? " / " + item.subitem : "") }),
            item.criteria ? h("div", { class: "muted small", text: item.criteria }) : null,
            item.note ? h("div", { class: "muted small", text: "回执：" + item.note }) : null),
          statusChip(item.status)));
      }
    }
  });
  const releases = (checks.releases || []).map(item => chip(`${item.action_label} · ${item.verdict === "passed" ? "通过" : "未通过"}`,
    item.verdict === "passed" ? "ok" : "bad"));
  return h("div", { class: "stack" }, line, h("div", { class: "row" }, toggle, ...releases), detail);
}

function jobBlock(slot) {
  const job = slot.job;
  if (!job) return null;
  const trial = job.trial;
  return h("div", { class: "card soft" },
    h("div", { class: "row" },
      chip(job.dev_type_label, "plain"),
      h("span", { class: "small", text: "第 " + job.iteration + " 次" }),
      job.gc_report ? chip("GC " + job.gc_report) : chip("GC 未到", "warn")),
    trial ? h("div", { class: "small", text: `试作 ${trial.fragrance_id} · ${trial.formula_version}${trial.notes ? " · " + trial.notes : ""}` }) : null,
    job.approved_trial_id ? chip("试作已验收", "ok") : null);
}

function taskList(slot) {
  if (!slot.tasks.length) return null;
  const items = slot.tasks.map(task => h("div", { class: "row between" },
    h("span", { class: "small", text: `${task.department_label} · ${task.type_label}` }),
    h("span", { class: "row" },
      h("span", { class: "muted small mono", text: task.external_id || "" }),
      chip(task.status === "done" ? "已回执" : task.status === "sent" ? "等待回执" : "已退回",
        task.status === "done" ? "ok" : task.status === "sent" ? "warn" : "bad"))));
  return h("div", { class: "stack" }, h("div", { class: "muted small", text: "部门任务" }), ...items);
}

function shipmentList(slot) {
  if (!slot.shipments.length) return null;
  return h("div", { class: "stack" }, h("div", { class: "muted small", text: "寄样记录" }),
    ...slot.shipments.map(item => h("div", { class: "small" },
      `${item.kind_label} · ${item.fragrance_id} · ${item.formula_version} · ${item.sample_form || ""} ${item.quantity || ""}${item.unit || ""} · ${fmtDate(item.shipped_at)}`)));
}

function slotBlock(slot, goal) {
  const head = h("div", { class: "slot-head" },
    h("span", { class: "id", text: slot.strategy_label }),
    chip(slot.stage_label, STAGE_KIND[slot.stage] || ""),
    slot.fragrance_id
      ? h("span", { class: "mono", text: slot.fragrance_id + (slot.formula_version ? " · " + slot.formula_version : "") })
      : h("span", { class: "muted small", text: "香精未定" }),
    slot.paused ? chip("已暂存", "warn") : null);
  const children = [head];
  if (slot.child_subproject_id) {
    children.push(h("div", { class: "small muted" }, "开发在子项 #" + slot.child_subproject_id + " 进行，完成后自动回到这里。"));
  } else {
    children.push(jobBlock(slot), slotActions(slot, goal), checkBlock(slot), taskList(slot), shipmentList(slot));
    if (slot.issues.length) {
      children.push(...slot.issues.map(item => h("div", { class: "issue" },
        h("div", { text: item.label }),
        h("div", { class: "why", text: (item.missing || []).join("、") + (item.next_action ? " · " + item.next_action : "") }))));
    }
  }
  return h("div", { class: "card" }, ...children.filter(Boolean));
}

function planForm(goal, strategy, box) {
  box.replaceChildren();
  const inputs = {};
  const rows = [];
  if (strategy === "select") {
    rows.push(h("div", { class: "muted small" }, h("a", { href: `/select.html?project=${PROJECT_ID}&goal=${goal.id}`, text: "打开选香，选定一款后自动回到这里" })));
  }
  if (strategy === "duplicate") {
    inputs.sample_reference = textInput("", "分析样编号或来源");
    rows.push(field("分析样", inputs.sample_reference));
  }
  if (strategy === "modify") {
    inputs.base_version = textInput("", "例如 V2");
    rows.push(field("原配方版本", inputs.base_version));
  }
  if (strategy === "create" || strategy === "modify" || strategy === "duplicate") {
    inputs.note = textInput("", "给调香的要求（可留空）");
    rows.push(field("补充要求", inputs.note));
  }
  if (!rows.length) return;
  const confirm = h("button", { class: "btn primary small", text: "确认" });
  const cancel = h("button", { class: "btn small", text: "取消", onclick: () => box.replaceChildren() });
  box.append(...rows, h("div", { class: "row" }, confirm, cancel));
  confirm.addEventListener("click", () => run(confirm, async () => {
    const payload = {};
    for (const [key, input] of Object.entries(inputs)) if (input.value.trim()) payload[key] = input.value.trim();
    const result = await post(`/api/projects/${PROJECT_ID}/goals/${goal.id}/plan`, { strategy, payload });
    if (result.created) toast("方案已建立");
    await refresh();
  }));
}

function strategyArea(goal) {
  if (goal.slots.length) return null;
  const row = h("div", { class: "row" });
  const box = h("div", { style: { marginTop: "8px" } });
  for (const item of goal.strategies.filter(option => option.allowed)) {
    const button = h("button", { class: "btn small", text: item.label });
    button.addEventListener("click", () => planForm(goal, item.value, box));
    row.append(button);
  }
  return h("div", { class: "stack" }, row, box);
}

function briefBlock(goal) {
  const fields = goal.fields || {};
  const requirements = Array.isArray(fields.requirements) ? fields.requirements : [];
  const compliance = requirements.filter(item => item.kind === "regulatory" || item.kind === "other");
  const cells = [];
  const cell = (label, value, kind = "") => {
    if (value === undefined || value === null || !String(value).trim()) return;
    cells.push(h("div", { class: "brief-cell " + kind },
      h("span", { class: "brief-label", text: label }),
      h("div", { class: "brief-value", text: String(value) })));
  };
  cell("香气要求", fields.scent_text || fields.scent, "wide scent");
  cell("人群", fields.target_audience);
  cell("市场", Array.isArray(fields.markets) ? fields.markets.join("、") : fields.markets);
  cell("添加量", fields.dose_text);
  cell("价格", fields.price_text);
  const extras = [];
  if (fields.stability_note) extras.push("表稳：" + fields.stability_note);
  if (fields.flash_point) extras.push("闪点：" + fields.flash_point);
  const targeting = fields.targeting || {};
  const tags = Array.isArray(targeting.items) ? targeting.items : [];
  const unmapped = Array.isArray(targeting.unmapped) ? targeting.unmapped : [];
  return h("div", { class: "brief" },
    cells.length ? h("div", { class: "brief-grid" }, ...cells) : h("div", { class: "small muted", text: "需求字段还没填全，可以手补。" }),
    extras.length ? h("div", { class: "row" }, ...extras.map(text => chip(text, "plain"))) : null,
    compliance.length ? h("details", { class: "brief-more" },
      h("summary", { text: `合规与客户要求 ${compliance.length} 条` }),
      h("div", { class: "stack" }, ...compliance.slice(0, 12).map(item => h("div", { class: "small", text: item.text }))),
      compliance.length > 12 ? h("div", { class: "small muted", text: `另有 ${compliance.length - 12} 条，见检查清单` }) : null) : null,
    tags.length ? h("div", { class: "targeting" },
      h("div", { class: "row" },
        h("span", { class: "brief-label", text: "标签" }),
        ...tags.map(item => h("span", { class: "chip tag", title: item.basis || "", text: item.name })),
        targeting.method ? h("span", { class: "small muted", text: targeting.method }) : null),
      unmapped.length ? h("div", { class: "small muted", text: "未映射：" + unmapped.slice(0, 4).join("；") }) : null
    ) : h("div", { class: "small muted", text: targeting.method ? `标签：${targeting.method}` : "标签：首次检索时按品类、人群、市场与香气要求生成。" })
  );
}

function fieldsLine(goal) {
  const fields = goal.fields || {};
  const chips = [];
  const push = (label, value) => { if (value !== undefined && value !== null && String(value).trim()) chips.push(chip(label + " " + value, "plain")); };
  push("剂型", fields.substrate);
  push("样品", fields.sample_form);
  push("数量", fields.count_min || fields.count_max ? `${fields.count_min || ""}–${fields.count_max || ""}` : "");
  push("交期", fields.deadline_text);
  return chips.length ? h("div", { class: "row" }, ...chips) : null;
}

function goalBlock(goal) {
  return h("div", { class: "card goal" },
    h("div", { class: "row between" },
      h("div", { class: "row" }, h("h3", { text: goal.label }), chip(goal.entry_label, "plain")),
      h("div", { class: "row" },
        chip(goal.endpoint_label),
        goal.status === "complete" ? chip("已完成", "ok") : null)),
    briefBlock(goal),
    fieldsLine(goal),
    strategyArea(goal),
    ...goal.slots.map(slot => slotBlock(slot, goal)));
}

function subprojectBlock(subproject) {
  const rounds = subproject.rounds.map(round => h("div", { class: "section" },
    h("div", { class: "row" },
      h("span", { class: "small muted", text: `第 ${round.no} 轮 · ${round.kind_label}` }),
      round.status === "complete" ? chip("轮次完成", "ok") : null,
      round.summary ? h("span", { class: "muted small", text: round.summary }) : null),
    ...round.goals.map(goalBlock)));
  return h("div", { class: "card", style: { padding: "18px 20px" } },
    h("div", { class: "row between" },
      h("div", { class: "row" },
        h("h2", { text: subproject.title, style: { margin: "0", fontSize: "16px" } }),
        chip(subproject.requirement_label, "plain"),
        chip(subproject.final_endpoint_label)),
      h("div", { class: "row" },
        subproject.is_development ? chip("开发子项", "warn") : null,
        chip(subproject.status === "completed" ? "已完成" : "进行中", subproject.status === "completed" ? "ok" : ""))),
    ...rounds);
}

function issuesBlock() {
  const items = VIEW.progress.issues || [];
  if (!items.length) return null;
  return h("div", { class: "section" },
    h("div", { class: "head" }, h("h2", { text: "待处理" })),
    ...items.map(item => h("div", { class: "issue" },
      h("div", { text: item.label + "（" + (item.scope === "project" ? "项目" : "目标位 #" + item.scope_id) + "）" }))));
}

function render() {
  const app = $("#app");
  app.replaceChildren();
  app.append(nav("projects"));
  const project = VIEW.project;
  const progress = VIEW.progress;
  const importButton = h("button", { class: "btn", text: "导入资料" });
  const addButton = h("button", { class: "btn", text: "追加方向" });
  importButton.addEventListener("click", () => run(importButton, importDialog));
  addButton.addEventListener("click", () => run(addButton, () => draftDialog({ directions: [], shared: {}, open_questions: [] }, "追加方向")));

  app.append(...[
    h("div", { class: "row between" },
      h("div", {},
        h("h1", { text: project.name }),
        h("div", { class: "row" },
          chip(META_KINDS[project.kind] || project.kind, "plain"),
          project.customer ? h("span", { class: "muted small", text: project.customer }) : null,
          h("span", { class: "muted small", text: `${progress.slot_done}/${progress.slot_count} 目标位完成` }))),
      h("div", { class: "row" }, importButton, addButton)),
    issuesBlock(),
    h("div", { class: "section" },
      h("div", { class: "head" }, h("h2", { text: "交付方向" })),
      VIEW.subprojects.filter(item => !item.is_development).length
        ? VIEW.subprojects.filter(item => !item.is_development).map(subprojectBlock)
        : h("div", { class: "card soft" }, h("div", { text: "还没有交付方向。" }),
            h("div", { class: "muted small", text: "导入客户资料，或手填一个方向。" }))),
    VIEW.subprojects.some(item => item.is_development)
      ? h("div", { class: "section" },
          h("div", { class: "head" }, h("h2", { text: "开发子项" })),
          ...VIEW.subprojects.filter(item => item.is_development).map(subprojectBlock))
      : null,
    modelCallsBlock(),
  ].filter(Boolean));
}

const META_KINDS = { customer: "客户委托", internal_upgrade: "内部升级", invent: "主动开发" };
const CALL_LABELS = { parse: "拆解资料", targeting: "打标签", vision: "图片转写" };
const CALL_STATUS = { ok: "完成", error: "失败", invalid_json: "返回非 JSON", incomplete: "未完成" };

function modelCallsBlock() {
  const box = h("div", { class: "stack" }, h("div", { class: "muted small", text: "读取中" }));
  const section = h("div", { class: "section" },
    h("div", { class: "head" },
      h("h2", { text: "模型调用" }),
      h("span", { class: "muted small", text: "每一次请求的产出要求、输入和返回" })),
    box);
  get(`/api/projects/${PROJECT_ID}/llm-calls`).then(data => {
    const calls = data.calls || [];
    if (!calls.length) {
      box.replaceChildren(h("div", { class: "card soft" },
        h("div", { text: "还没有模型调用。" }),
        h("div", { class: "muted small", text: "导入资料并拆解、或首次按目标选香后，这里会留下每次请求。" })));
      return;
    }
    box.replaceChildren(...calls.map(call => {
      const state = CALL_STATUS[call.status] || call.status || "";
      const line = h("div", { class: "row between" },
        h("div", { class: "row" },
          h("span", { class: "call-purpose", text: CALL_LABELS[call.purpose] || call.purpose }),
          h("span", { class: "mono small", text: call.model }),
          h("span", { class: `chip ${call.status === "ok" ? "ok" : "bad"}`, text: state })),
        h("span", { class: "muted small", text: `${call.seconds}s · ${call.created_at}` }));
      const open = h("button", { class: "btn small", text: "看请求" });
      open.addEventListener("click", () => run(open, () => llmDialog(call.id)));
      return h("div", { class: "call-row" }, line,
        h("div", { class: "row between" },
          h("span", { class: "small muted", text: call.error || `请求 ${call.request_chars} 字 · 返回 ${call.response_chars} 字` }),
          open));
    }));
  }).catch(error => box.replaceChildren(h("div", { class: "issue bad" }, h("div", { text: error.message }))));
  return section;
}

async function llmDialog(callId) {
  const data = await get(`/api/llm-calls/${callId}`);
  const messages = ((data.request || {}).messages) || [];
  const asText = content => typeof content === "string" ? content : JSON.stringify(content, null, 2);
  const system = messages.filter(item => item.role === "system").map(item => asText(item.content)).join("\n\n");
  const user = messages.filter(item => item.role === "user").map(item => asText(item.content)).join("\n\n");
  const response = String(data.response || "");
  let pretty = response;
  try { pretty = JSON.stringify(JSON.parse(response), null, 2); } catch (error) { /* 保留原文 */ }
  const box = dialog(CALL_LABELS[data.purpose] || data.purpose || "模型调用", [
    h("div", { class: "row" },
      h("span", { class: "mono small", text: data.model }),
      h("span", { class: "chip " + (data.status === "ok" ? "ok" : "bad"), text: CALL_STATUS[data.status] || data.status }),
      h("span", { class: "muted small", text: `${data.seconds}s · ${data.created_at}` })),
    system ? h("div", { class: "call-part" },
      h("div", { class: "brief-label", text: "产出要求（system）" }),
      h("pre", { class: "code", text: system })) : null,
    user ? h("div", { class: "call-part" },
      h("div", { class: "brief-label", text: "输入（user）" }),
      h("pre", { class: "code", text: user })) : null,
    h("div", { class: "call-part" },
      h("div", { class: "brief-label", text: data.error ? "错误" : "返回" }),
      h("pre", { class: "code", text: data.error || pretty || "（空）" })),
  ], [h("button", { class: "btn", text: "关闭", onclick: () => box.close() })]);
}

async function importDialog() {
  const text = h("textarea", { placeholder: "把客户原话、邮件、需求描述粘贴在这里" });
  const fileInput = h("input", { type: "file", multiple: true, accept: ".txt,.md,.csv,.pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp" });
  const vision = h("input", { type: "checkbox" });
  const status = h("div", { class: "muted small" });
  const read = h("button", { class: "btn primary", text: "读取并拆解" });
  const body = [
    field("文字资料", text),
    h("div", { class: "drop" }, h("div", { text: "或选择文件（可多选）" }), fileInput),
    h("label", { class: "row small" }, vision, h("span", { text: "图片用视觉模型转写（会产生模型调用）" })),
    status,
  ];
  const box = dialog("导入资料", body, [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), read]);
  read.addEventListener("click", () => run(read, async () => {
    const ids = [];
    const files = Array.from(fileInput.files || []);
    for (const [index, file] of files.entries()) {
      status.textContent = `读取文件 ${index + 1}/${files.length}：${file.name}`;
      const data = await readFile(file);
      const saved = await post(`/api/projects/${PROJECT_ID}/sources`,
        { name: file.name, base64: data, vision: vision.checked && /\.(png|jpe?g|webp)$/i.test(file.name) });
      ids.push(saved.source_id);
    }
    if (text.value.trim()) {
      const saved = await post(`/api/projects/${PROJECT_ID}/sources`, { name: "粘贴的文字.txt", text: text.value });
      ids.push(saved.source_id);
    }
    if (!ids.length) throw new Error("请粘贴文字或选择文件");
    status.textContent = "拆解中，可能要几十秒…";
    const analyzed = await post(`/api/projects/${PROJECT_ID}/analyze`, { source_ids: ids });
    box.close();
    draftDialog(analyzed.draft, "确认需求方向", analyzed.draft_id);
  }));
}

function directionEditor(direction, index, onRemove) {
  const title = textInput(direction.title || "", "方向标题，例如：洗护香精两款");
  const entries = META.entries.map(item => ({ value: item.value, label: item.label }));
  const entry = selectInput(entries, direction.entry || "recommend_simple");
  const conditions = direction.conditions || {};
  const markets = textInput((conditions.markets || []).join("、"), "市场，例如：中国、日本");
  const dose = textInput(conditions.dose_text || "", "用量，例如：0.5%");
  const substrate = textInput(conditions.substrate || "", "基质，例如：洗发水");
  const sampleForm = textInput(conditions.sample_form || "", "样品形态，例如：10 ml");
  const price = textInput(conditions.price_text || "", "价格，例如：300 以内");
  const quotes = (direction.basis || []).slice(0, 3).map(item =>
    h("div", { class: "muted small", text: "原文：" + item.quote }));
  const card = h("div", { class: "card" },
    h("div", { class: "row between" },
      h("span", { class: "muted small", text: "方向 " + (index + 1) }),
      h("button", { class: "btn ghost small", text: "删除", onclick: () => onRemove(card) })),
    field("标题", title),
    h("div", { class: "grid2" }, field("入口", entry), field("市场", markets)),
    h("div", { class: "grid3" }, field("基质", substrate), field("用量", dose), field("样品", sampleForm)),
    field("价格", price),
    ...quotes);
  card.read = () => ({
    title: title.value.trim(),
    entry: entry.value,
    conditions: {
      ...conditions,
      markets: markets.value.split(/[、,，;；\s]+/).filter(Boolean),
      dose_text: dose.value.trim(),
      substrate: substrate.value.trim(),
      sample_form: sampleForm.value.trim(),
      price_text: price.value.trim(),
    },
  });
  return card;
}

function draftDialog(draft, title, draftId) {
  const cards = [];
  const list = h("div", { class: "stack" });
  const add = () => {
    const card = directionEditor({}, cards.length, (node) => {
      cards.splice(cards.indexOf(card), 1);
      node.remove();
    });
    cards.push(card);
    list.append(card);
  };
  for (const direction of draft.directions || []) {
    const card = directionEditor(direction, cards.length, (node) => {
      cards.splice(cards.indexOf(card), 1);
      node.remove();
    });
    cards.push(card);
    list.append(card);
  }
  const shared = draft.shared || {};
  const customer = textInput(shared.customer || "", "客户");
  const brief = textInput(shared.brief_goal || "", "本轮要解决什么");
  const deadline = textInput(shared.deadline_text || "", "交期原话");
  const sample = textInput(shared.sample_form || "", "样品形态");
  const questions = (draft.open_questions || []).map(item => h("div", { class: "muted small", text: "· " + item }));
  const body = [
    draft.summary ? h("div", { class: "small", text: draft.summary }) : null,
    questions.length ? h("div", { class: "issue" }, h("div", { class: "small", text: "需要留意" }), ...questions) : null,
    h("div", { class: "grid2" }, field("客户", customer), field("本轮目标", brief)),
    h("div", { class: "grid2" }, field("交期", deadline), field("样品形态", sample)),
    h("div", { class: "row between" }, h("span", { class: "muted small", text: "方向" }),
      h("button", { class: "btn small", text: "加一个方向", onclick: add })),
    list,
  ];
  const confirm = h("button", { class: "btn primary", text: "确认建项" });
  const box = dialog(title, body, [h("button", { class: "btn", text: "取消", onclick: () => box.close() }), confirm]);
  confirm.addEventListener("click", () => run(confirm, async () => {
    const directions = cards.map(card => card.read()).filter(item => item.title);
    if (!directions.length) throw new Error("至少保留一个方向标题");
    const edits = {
      summary: draft.summary || "",
      shared: { ...shared, customer: customer.value, brief_goal: brief.value, deadline_text: deadline.value, sample_form: sample.value },
      directions,
      open_questions: draft.open_questions || [],
    };
    let target = draftId;
    if (!target) {
      const created = await post(`/api/projects/${PROJECT_ID}/draft`, { directions });
      target = created.draft_id;
    }
    await post(`/api/projects/${PROJECT_ID}/draft/${target}/confirm`, { edits });
    box.close();
    toast(`已建立 ${directions.length} 个方向`);
    await refresh();
  }));
}

async function main() {
  if (!PROJECT_ID) { location.href = "/index.html"; return; }
  META = await boot();
  await refresh();
}

main().catch(error => {
  const app = $("#app");
  app.replaceChildren(nav("projects"), h("div", { class: "card" }, h("div", { text: error.message })));
});
