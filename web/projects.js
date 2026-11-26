const get = (id) => document.getElementById(id);
function el(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (className) node.className = className;
  return node;
}
function button(title, action, css = "quiet") {
  const node = el("button", title, css);
  node.type = "button"; node.onclick = action;
  return node;
}
async function api(url, payload) {
  const config = payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
  };
  const response = await fetch(url, config);
  const value = await response.json();
  if (!response.ok) throw Error(value.error || "操作未完成");
  return value;
}
function text(value) { return Array.isArray(value) ? value.join("；") : value ?? ""; }
function formField(title, value, update, kind = "text", options = null) {
  const wrap = el("label", title);
  const input = el(options ? "select" : kind === "area" ? "textarea" : "input");
  if (options) options.forEach(([key, label]) => input.add(new Option(label, key)));
  else if (kind !== "area") input.type = kind;
  input.value = text(value);
  input.onchange = () => update(input.value);
  if (!options) input.oninput = () => update(input.value);
  wrap.append(input);
  return wrap;
}
function link(label, href) {
  const node = el("a", label, "action-link");
  node.href = href;
  return node;
}

const actionNames = {
  select: "选定库香", duplicate: "启动仿香", create: "启动创香", modify: "启动改香", resend: "复寄原样",
  retry: "重派该步骤", confirm_analysis: "确认分析并调香", accept_trial: "评香通过",
  reject_trial: "退回调香", send_warehouse: "派发入库", warehouse_existing: "记录库香替代",
  record_warehouse: "确认入库回执", prepare_sample: "准备样品", record_sample: "确认样品回执",
  shipment_checks: "派发客户二查", record_shipment_checks: "确认检查回执",
  initial_shipment: "派发初寄", formal_shipment: "派发正式寄样", record_shipment: "记录实际寄样",
  pause: "暂存", resume: "恢复"
};
const stages = {chosen: "待交付", analysis: "分析", perfumery: "调香／评香",
  warehouse_review: "入库检查", warehouse: "入库", sample: "备样",
  shipment_review: "客户二查", shipment: "寄样", complete: "完成"};
const intentNames = {new: "新增", continue: "续荐", modify: "承袭改香", resend: "复寄"};
const entryNames = {recommend_simple: "常规推荐", recommend_brand: "品牌推荐", find_product: "精确找香",
  with_sample: "对香", modify: "改香", invent: "主动开发", resend: "复寄"};
const conditionNames = {scent: "香气方向", avoid: "排斥项", product: "指定产品", brand: "品牌", edition: "版本",
  substrate: "基质", dose_text: "加香量", quantity_text: "样品量", sample_form: "寄样形态", price_text: "价格原话",
  deadline_text: "交期", base_code: "原香编号", sample_reference: "参照样", changes: "改动", retained: "保留",
  markets: "地区", requirements: "检查／客户要求", count_min: "最低款数", price_min: "下限", price_max: "最高价",
  price_target: "参考价", count_max: "最多款数", launch_tier: "上市层级", delivery_scope: "交付范围",
  composition_text: "香型结构比例"};
let bootstrap, dictionaries, data, draft, modalTask;
const requested = new URLSearchParams(location.search);

function project() { return Number(get("project-select").value); }
function feedback(value) { get("feedback").textContent = value || ""; }
function fillProjects() {
  get("project-select").replaceChildren(new Option("选择项目", ""), ...bootstrap.projects.map(x => new Option(x.name, x.id)));
}
function setDraft(item) {
  draft = item;
  renderDraft();
}
function renderSources() {
  const used = new Set(data.drafts.filter(x => x.status === "confirmed").flatMap(x => x.source_ids));
  const rows = data.sources.map(source => {
    const item = el("article", null, "flow-source");
    const option = el("label", null, "check");
    const tick = el("input"); tick.type = "checkbox"; tick.value = source.id;
    tick.checked = !used.has(source.id); tick.name = "selected-source";
    option.append(tick, source.name);
    item.append(option);
    const detail = el("details"); detail.append(el("summary", source.extracted.segments.length + " 处已读取"));
    for (const w of source.extracted.warnings) detail.append(el("p", w, "risk"));
    for (const segment of source.extracted.segments) {
      detail.append(el("p", segment.locator + (segment.kind === "visual" ? " · 视觉转写" : ""), "small muted"),
        el("pre", segment.text, "source-preview"));
    }
    item.append(detail);
    return item;
  });
  get("source-list").replaceChildren(...rows);
}
function renderDraft() {
  get("confirm").hidden = !draft?.result.directions.length;
  const base = get("draft-shared"), questions = get("draft-issues");
  const container = get("directions");
  base.replaceChildren(); questions.replaceChildren(); container.replaceChildren();
  if (!draft) {
    get("draft-meta").textContent = "选择资料拆解，也可以手填。";
    return;
  }
  get("draft-meta").textContent = [draft.model, draft.elapsed ?? draft.seconds ? (draft.elapsed ?? draft.seconds) + " 秒" : ""]
    .filter(Boolean).join(" · ");
  const summary = draft.result;
  base.append(formField("项目摘要", summary.summary, v => summary.summary = v, "area"));
  const shared = summary.shared ||= {};
  const sharedFields = el("div", null, "flow-fields");
  for (const [key, label, kind] of [["customer","客户"],["deadline_text","总体交期"],["delivery_note","供样说明"],
       ["total_min","组合最低款数","number"],["total_max","组合最多款数","number"]]) {
    sharedFields.append(formField(label, shared[key], v => shared[key] = v, kind));
  }
  base.append(sharedFields);
  for (const question of summary.open_questions || []) questions.append(el("p", question, "small risk"));
  summary.directions.forEach((direction, index) => {
    const card = el("article", null, "flow-card");
    const header = el("div", null, "section-line");
    header.append(el("h3", direction.title || "新方向"), button("移除", () => {summary.directions.splice(index, 1); renderDraft()}));
    card.append(header);
    const fields = el("div", null, "flow-fields");
    const d = direction.conditions ||= {};
    fields.append(formField("方向名称", direction.title, v => direction.title = v),
      formField("需求入口", direction.entry, v => direction.entry = v, "text", Object.entries(entryNames)),
      formField("轮次关系", direction.intent, v => direction.intent = v, "text", Object.entries(intentNames)),
      formField("香气方向", d.scent, v => d.scent = v, "area"),
      formField("应用品类", d.application_id, v => d.application_id = v, "text",
        [["", "待定"], ...Object.entries(bootstrap.categories)]),
      formField("审查品类", d.review_category_id, v => d.review_category_id = v, "text",
        [["", "待定"], ...dictionaries.review_categories.map(x => [x.id, x.name])]));
    const more = el("details");
    more.open = Boolean(direction.source_shipment_id || ["modify", "resend"].includes(direction.entry));
    more.append(el("summary", "交付条件与原文依据"));
    const extra = el("div", null, "flow-fields");
    extra.append(formField("承袭旧方向", direction.previous_goal_id, v => direction.previous_goal_id = v,
      "text", [["", "待确认"], ...data.rounds.flatMap(r => r.goals.map(g => [g.id, "第 " + r.number + " 轮 · " + g.spec.title]))]),
      formField("关联实发记录", direction.source_shipment_id, v => direction.source_shipment_id = v,
        "text", [["", "待确认"], ...data.shipments.map(s => [s.id, s.details.fragrance_code + " · " + s.details.sample_id])]),
      formField("终点", d.fulfillment || "ship", v => d.fulfillment = v, "text", [["ship","寄样"],["warehouse","入库"]]));
    for (const [key, label] of Object.entries(conditionNames)) {
      if (key === "scent") continue;
      const kind = key.startsWith("price_") && key !== "price_text" || key.startsWith("count_") ? "number" : "text";
      extra.append(formField(label, d[key], v => d[key] = ["requirements", "markets"].includes(key) ?
        v.split(/[；;、]+/).filter(Boolean) : v, kind));
    }
    for (const ref of direction.basis || []) more.append(el("p", (ref.locator || "原文") + " · " + ref.quote, "small muted"));
    more.append(extra); card.append(fields, more); container.append(card);
  });
}
function renderShipments() {
  const items = data.shipments.map(h => el("p", [h.kind === "initial" ? "初寄" : h.kind === "resend" ? "复寄" : "正式寄样",
    h.details.fragrance_code, h.details.sample_id, h.details.quantity, h.details.tracking].join(" · "), "small"));
  get("shipments").replaceChildren(...(items.length ? items : [el("p", "暂无模拟实发", "muted")]));
}
function renderRounds() {
  const nodes = data.rounds.map(round => {
    const box = el("section", null, "flow-round");
    box.append(el("h3", ["第 " + round.number + " 轮", round.complete ? "已完成" : "进行中", round.completed_choices + " 款已完成"].join(" · ")));
    if (round.shared.summary) box.append(el("p", round.shared.summary, "small muted"));
    for (const goal of round.goals) {
      const spec = goal.spec, c = spec.conditions;
      const card = el("article", null, "flow-card");
      card.append(el("h3", spec.title), el("p", [entryNames[spec.entry], intentNames[spec.intent],
        bootstrap.categories[c.application_id], c.price_text, c.count_min ? c.count_min + " 款起" : "",
        goal.complete ? "已完成" : ""].filter(Boolean).join(" · "), "small muted"));
      if (c.scent) card.append(el("p", c.scent, "small"));
      const buttons = el("div", null, "row flow-buttons");
      if (spec.strategies.includes("select")) buttons.append(link("进入选香", "/?project=" + project() + "&goal=" + goal.id));
      for (const strategy of spec.strategies.filter(v => v !== "select")) buttons.append(
        button(actionNames[strategy], () => startPlan(goal, strategy)));
      const reroute = {modify: ["with_sample", "原配方不可用 · 转对香"],
        recommend_simple: ["recommend_brand", "转品牌推荐"]}[spec.entry];
      if (reroute && !goal.slots.length) buttons.append(button(reroute[1], async (e) =>
        perform(e.target, async () => {
          await api("/api/flow/reroute", {project_id: project(), goal_id: goal.id, entry: reroute[0]});
          await load();
        })));
      card.append(buttons);
      for (const slot of goal.slots) {
        const unit = el("section", null, "flow-slot");
        const phase = [actionNames[slot.strategy], slot.context.fragrance_code || slot.context.base_code,
           stages[slot.state], slot.context.paused ? "已暂存" : "",
           slot.context.iteration > 1 ? "试作 " + slot.context.iteration : ""].filter(Boolean);
        unit.append(el("strong", phase.join(" · ")));
        for (const task of slot.tasks) unit.append(el("p", bootstrap.departments[task.department] + " · " +
          (task.result === null ? "待回执" : task.result ? "通过" : "退回"), "small muted"));
        const choices = el("div", null, "row flow-buttons");
        for (const name of slot.actions) choices.append(button(actionNames[name], () => openStep(slot, name, c)));
        unit.append(choices); card.append(unit);
      }
      box.append(card);
    }
    return box;
  });
  get("rounds").replaceChildren(...(nodes.length ? nodes : [el("p", "确认需求草案后开始。", "muted")]));
}
async function load(id = project(), resetDraft = false) {
  get("project-main").hidden = !id;
  if (!id) { get("project-summary").textContent = ""; return; }
  data = await api("/api/workflow", {project_id: id});
  const url = new URL(location.href); url.searchParams.set("project", id); history.replaceState(null, "", url);
  get("project-summary").textContent = data.project.name + (data.complete ? " · 已完成" : "");
  if (resetDraft) setDraft(data.drafts.find(d => d.status === "draft"));
  renderSources(); renderRounds(); renderShipments();
}
async function perform(buttonElement, operation) {
  buttonElement.disabled = true;
  feedback();
  try { await operation(); } catch (error) { feedback(error.message); }
  finally { buttonElement.disabled = false; }
}
function openModal(title, fields, submit) {
  get("step-title").textContent = title;
  const payload = {};
  get("step-fields").replaceChildren(...fields.map(([key, label, value, type]) => {
    payload[key] = value;
    const field = formField(label, value, v => payload[key] = v, type);
    return field;
  }));
  modalTask = () => submit(payload);
  get("step-status").textContent = "";
  get("step-dialog").showModal();
}
function startPlan(goal, strategy) {
  const c = goal.spec.conditions;
  const fields = [["note", "评香说明", c.changes || c.scent || "", "area"]];
  if (strategy === "duplicate") fields.unshift(["sample_reference", "参照实物或分析样", c.sample_reference]);
  if (strategy === "modify") fields.unshift(["base_code", "原香编号", c.base_code],
    ["base_version", "可调用版本（模拟可填 MOCK 版本）", c.base_version]);
  openModal(actionNames[strategy], fields, payload => api("/api/flow/plan", {
    ...payload, strategy, project_id: project(), goal_id: goal.id
  }));
}
function openStep(slot, action, c) {
  const fields = [["note", "说明", "", "area"]];
  if (action === "prepare_sample") fields.unshift(["sample_form", "样品形态", c.sample_form],
    ["quantity", "数量及单位", c.quantity_text]);
  openModal(actionNames[action], fields, payload => api("/api/flow/advance", {
    ...payload, action, project_id: project(), slot_id: slot.id, revision: slot.stage_revision
  }));
}
function fileContent(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]);
    reader.onerror = () => reject(Error("文件读取失败 " + file.name));
    reader.readAsDataURL(file);
  });
}
async function init() {
  [bootstrap, dictionaries] = await Promise.all([api("/api/bootstrap"), api("/api/dictionaries")]);
  fillProjects();
  get("project-select").value = requested.get("project") || bootstrap.projects[0]?.id || "";
  await load(project(), true);
  get("project-select").onchange = () => load(project(), true).catch(e => feedback(e.message));
  get("refresh").onclick = (e) => perform(e.target, () => load());
  get("add-project").onclick = () => get("new-dialog").showModal();
  get("new-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const item = await api("/api/projects", {name: get("new-name").value, brief: get("new-brief").value});
      bootstrap.projects.unshift(item); fillProjects(); get("project-select").value = item.id;
      get("new-dialog").close(); get("new-form").reset(); await load(item.id, true);
    } catch (error) { get("new-status").textContent = error.message; }
  };
  get("add-text").onclick = (e) => perform(e.target, async () => {
    await api("/api/sources", {project_id: project(), name: "本轮文字.txt", text: get("source-text").value});
    get("source-text").value = ""; await load();
  });
  get("add-files").onclick = (e) => perform(e.target, async () => {
    const files = [...get("source-files").files];
    let imported = 0;
    for (const f of files) {
      if (f.size > 30 * 1024 * 1024) throw Error("单文件超过 30 MB " + f.name);
      feedback("正在读取 " + f.name);
      await api("/api/sources", {project_id: project(), name: f.name, vision: get("visual").checked,
        base64: await fileContent(f)});
      imported += 1;
    }
    get("source-files").value = ""; await load(); feedback("已读取 " + imported + " 份资料");
  });
  get("parse").onclick = (e) => perform(e.target, async () => {
    const source_ids = [...document.querySelectorAll("[name=selected-source]:checked")].map(x => Number(x.value));
    feedback("正在拆解本轮资料…");
    const result = await api("/api/briefs/analyze", {project_id: project(), source_ids});
    await load(); setDraft(result); feedback("");
  });
  get("add-direction").onclick = () => {
    draft ||= {result: {shared: {}, directions: [], open_questions: []}};
    draft.result.directions.push({title: "", entry: "recommend_simple", intent: "new", conditions: {}, basis: []});
    renderDraft();
  };
  get("confirm").onclick = (e) => perform(e.target, async () => {
    const result = await api("/api/briefs/confirm", {project_id: project(), draft_id: draft.id, result: draft.result});
    await load(project(), true); feedback("已建立第 " + result.number + " 轮");
  });
  get("step-form").onsubmit = async (e) => {
    e.preventDefault(); e.submitter.disabled = true;
    try { await modalTask(); get("step-dialog").close(); await load(); }
    catch (error) { get("step-status").textContent = error.message; }
    finally { e.submitter.disabled = false; }
  };
  for (const ctrl of document.querySelectorAll("[data-close]")) ctrl.onclick = () => get(ctrl.dataset.close).close();
}
init().catch(e => feedback(e.message));
