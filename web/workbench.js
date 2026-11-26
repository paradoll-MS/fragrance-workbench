const get = (id) => document.getElementById(id);
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const choice = (value, name) => new Option(name, value);
const values = (id) => [...get(id).selectedOptions].map((o) => o.value).filter(Boolean);
const button = (text, action, className) => {
  const node = el("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
};
const api = async (path, body) => {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "操作暂未完成");
  return data;
};

const actions = {
  select: "选定香精", create: "创香", duplicate: "仿香", modify: "改香",
  checks: "派发检查", warehouse: "入库", sample: "备样",
  initial_shipment: "初寄样", formal_shipment: "正式寄样"
};
const productStates = {suggested: "推定", unverified: "待核", manual: "人工标签", confirmed: "已确认"};
const demandRoles = {required: "必须", preference: "偏好", avoid: "避开"};
let setup, terms, products, editing, currentAsset, currentMode, groups = [], page = 1, currentResult;
let flowGoal, newCombination;
let requestNo = 0, debounce;

function projectId() {
  return Number(get("project").value) || null;
}

function modeState() {
  const mode = get("mode").value;
  get("exact-panel").hidden = mode !== "find_product";
  get("directory-controls").hidden = mode === "find_product";
  get("brief-panel").hidden = mode === "find_product";
  get("sample-controls").hidden = mode !== "with_sample";
  if (currentMode !== mode) {
    currentMode = mode;
    currentResult = undefined;
    requestNo += 1;
    get("status").textContent = "";
    get("result-count").textContent = "";
    get("result-list").replaceChildren();
    get("pagination").hidden = true;
    get("alternatives").hidden = true;
    get("unmatched").hidden = true;
    get("diagnostics").hidden = true;
  }
}

function searchTerms(text, categories, max = 12) {
  const reference = text.trim().toLocaleLowerCase();
  if (!reference) return [];
  return setup.terms.filter((term) =>
    (term.level !== "C" || categories.includes(term.category)) &&
    [term.name, term.id, term.path || ""].some((value) => value.toLocaleLowerCase().includes(reference))
  ).sort((a, b) => Number(b.name.toLocaleLowerCase() === reference) -
                   Number(a.name.toLocaleLowerCase() === reference)).slice(0, max);
}

function conditionText(group) {
  return group.tags.map(id => terms.get(id)?.name || id).join(group.op === "ALL" ? " 和 " : " 或 ");
}

function updateDemand() {
  renderDemand();
  refreshSearch();
}

function renderDemand() {
  const summary = get("demand-summary");
  const editable = get("demand-editor").open;
  const rows = [];
  for (const [role, label] of Object.entries(demandRoles)) {
    const conditions = groups.filter(group => group.role === role && group.tags.length);
    if (!conditions.length) continue;
    const row = el("div", null, "demand-row");
    const chips = el("div", null, "chips");
    for (const group of conditions) {
      const description = conditionText(group);
      const style = "chip" + (role === "avoid" ? " avoid" : "");
      const chip = editable ? button(description + " ×", () => {
        groups = groups.filter(item => item !== group);
        updateDemand();
      }, style) : el("span", description, style);
      if (editable) chip.setAttribute("aria-label", "移除条件 " + description);
      chips.append(chip);
    }
    row.append(el("strong", label), chips);
    rows.push(row);
  }
  summary.hidden = !rows.length;
  summary.replaceChildren(...rows);
  renderCombinations();
  renderDemandOptions();
}

function renderDemandOptions() {
  const role = get("demand-role").value;
  const matches = searchTerms(get("demand-search").value, values("categories"));
  get("demand-options").replaceChildren(...matches.flatMap(term => {
    const existing = groups.find(group => group.tags.includes(term.id));
    if (existing && (existing.role === role || existing.tags.length > 1)) return [];
    return [button(term.path || term.name, () => {
      if (existing) {
        existing.role = role;
        if (role === "avoid") existing.strength = "normal";
      } else {
        groups.push({role, op: "ANY", tags: [term.id]});
      }
      get("demand-search").value = "";
      updateDemand();
      get("demand-search").focus();
    })];
  }));
}

function renderCombinations() {
  const nodes = groups.filter(group => group.tags.length > 1 || group === newCombination).map(group => {
    const wrap = el("div", null, "group");
    const options = el("div", null, "row");
    const role = el("select"); role.setAttribute("aria-label", "组合用途");
    role.append(choice("preference", "偏好"), choice("required", "必须"), choice("avoid", "避开（扣分）"));
    role.value = group.role;
    const op = el("select"); op.setAttribute("aria-label", "组合匹配关系");
    op.append(choice("ANY", "任一即可"), choice("ALL", "需要同时满足")); op.value = group.op;
    const strength = el("select"); strength.setAttribute("aria-label", "扣分强度");
    strength.append(choice("mild", "轻"), choice("normal", "普通"), choice("strong", "强"));
    strength.value = group.strength || "normal";
    strength.hidden = group.role !== "avoid";
    role.addEventListener("change", () => { group.role = role.value; updateDemand(); });
    op.addEventListener("change", () => { group.op = op.value; updateDemand(); });
    strength.addEventListener("change", () => { group.strength = strength.value; refreshSearch(); });
    options.append(role, op, strength, button("移除此条件", () => {
      groups = groups.filter(item => item !== group); updateDemand();
    }, "group-remove"));
    const chips = el("div", null, "chips");
    for (const tag of group.tags) {
      const t = terms.get(tag);
      chips.append(button((t ? t.name : tag) + " ×", () => {
        group.tags = group.tags.filter((item) => item !== tag); updateDemand();
      }, "chip " + (group.role === "avoid" ? "avoid" : "")));
    }
    const input = el("input"); input.placeholder = "为组合添加标签"; input.setAttribute("aria-label", "查找组合标签");
    const found = el("div", null, "picker");
    input.addEventListener("input", () => found.replaceChildren(...searchTerms(input.value, values("categories"))
      .filter((t) => !group.tags.includes(t.id)).map((t) => button([t.level, t.path || t.name].join(" · "), () => {
        group.tags.push(t.id); updateDemand();
      }))));
    wrap.append(options, chips, input, found);
    if (group.source) wrap.append(el("small", group.source, "muted"));
    return wrap;
  });
  get("groups").replaceChildren(...nodes);
}

function queryForm() {
  return {
    mode: get("mode").value,
    asset_search: get("asset-search").value,
    categories: values("categories"),
    confirmed_only: get("confirmed-only").checked,
    min_price: get("min-price").value,
    max_price: get("max-price").value,
    target_price: get("target-price").value,
    big_brand: get("big-brand").value,
    brand_ids: values("brand"),
    only_new: get("only-new").checked,
    only_hot: get("only-hot").checked,
    sort: get("sort").value,
    product_id: get("product").value,
    edition: get("edition").value.trim(),
    sample_note: get("mode").value === "with_sample" ? get("sample").value : null,
    similarity: get("mode").value === "with_sample" ? get("similarity").value || null : null,
    groups
  };
}

function cardNode(card, outside, clue = false) {
  const article = el("article", null, "result-card");
  const header = el("div", null, "result-head");
  const meta = el("div");
  meta.append(el("h3", card.name, "candidate-name"));
  const info = el("p", null, "candidate-note");
  info.append(el("span", card.fragrance_id, "candidate-code"));
  const price = card.price ? card.price + " 元/kg" : "价格待查";
  const category = card.category ? setup.categories[card.category] : "";
  const shown = [price, card.price_source === "mock" ? "模拟报价" : "库报价", category,
    card.category_evidence === "historical" ? "历史应用依据" : "", card.manual ? "人工编辑" : ""].filter(Boolean);
  info.append(el("span", shown.join(" · "))); meta.append(info);
  header.append(meta);
  if (card.score != null) header.append(el("span", card.score.toFixed(1) + " 分", "score"));
  article.append(header);
  if (card.risks?.length) article.append(el("p", card.risks.join(" · "), "candidate-note risk"));
  if (card.reason) article.append(el("p", card.reason, "candidate-note"));
  const associations = card.identity || card.products;
  if (associations?.length) {
    article.append(el("p", associations.slice(0, 3).map((label) =>
      [label.name, productStates[label.status], card.identity && !label.edition && label.status === "confirmed" ?
        "版本待定" : label.edition].filter(Boolean).join(" · ")).join("；"), "candidate-note muted"));
  }
  const details = el("details");
  details.append(el("summary", "标签与匹配依据"));
  function hitLine(label, hits) {
    if (hits?.length) {
      details.append(el("p", label + " " + hits.map((t) =>
        t.name + (t.via?.length ? "（" + t.via.map((v) => terms.get(v)?.name || v).join("、") + "）" : "")).join("、")));
    }
  }
  hitLine("直接命中", card.direct_hits);
  hitLine("关联支持", card.cross_hits);
  hitLine("未命中偏好", card.unmatched);
  hitLine("负向扣分", card.negative_hits);
  if (card.penalty) details.append(el("p", "扣分 " + card.penalty + " 分"));
  if (card.tags?.length) details.append(el("p", "自身标签 " + card.tags.map((tag) => terms.get(tag)?.name || tag).join("、")));
  if (card.branches?.length > 1) {
    details.append(el("p", card.branches.map((b) =>
      (setup.categories[b.category] || "未限定品类") + " " + (b.score ?? "目录浏览")).join(" · ")));
  }
  article.append(details);
  const bar = el("div", null, "result-actions");
  if (!outside) bar.append(button("处理此香", () => openAction(card)));
  if (clue) bar.append(button("启动仿香", () => openAction(null, "duplicate", card.name)));
  bar.append(button("编辑资产标签", () => openEdit(card)));
  article.append(bar);
  return article;
}

async function search(nextPage = 1, manual = false) {
  if (!setup) return;
  const number = ++requestNo;
  get("search").disabled = true;
  get("status").textContent = "正在检索…";
  try {
    const result = await api("/api/search", {query: queryForm(), project_id: projectId(), page: nextPage, manual});
    if (number !== requestNo) return;
    const prior = currentResult;
    currentResult = {...result, query_id: result.query_id || (nextPage > 1 ? prior?.query_id : null)};
    page = nextPage;
    get("result-count").textContent = result.total + (result.exact ? " 条精确关系" : " 款");
    get("status").textContent = result.total ? "" : result.unmatched_total ?
      "尚未找到有香气标签支持的候选" : "当前条件下无结果";
    const flags = Object.entries(result.diagnostics).filter(([name]) => name !== "编码待核对");
    get("diagnostics").hidden = !flags.length || result.total > 0;
    get("diagnostics").textContent = flags.map(([k, n]) => "放宽" + k + "可增加 " + n + " 款").join(" · ");
    get("result-list").replaceChildren(...result.results.map((c) => cardNode(c, false)));
    const outside = [...(result.clues || []).map((c) => cardNode(c, true, true)),
      ...result.alternatives.map((c) => cardNode(c, true))];
    get("alternatives").hidden = !outside.length;
    if (outside.length) {
      get("alternatives").open = !result.total;
      get("alternative-title").textContent = result.exact ? "身份线索及条件冲突" : "条件外候选";
      get("alternative-list").replaceChildren(...outside);
    }
    get("unmatched").hidden = !result.unmatched_total;
    if (result.unmatched_total) {
      get("unmatched-title").textContent = "符合硬筛但缺香气依据 " + result.unmatched_total + " 款（预览）";
      get("unmatched-list").replaceChildren(...result.unmatched_preview.map((c) => cardNode(c, false)));
    }
    const pages = Math.ceil(result.total / 30);
    get("pagination").hidden = pages <= 1;
    get("prev").disabled = page === 1;
    get("next").disabled = page >= pages;
    get("page-label").textContent = page + " / " + pages;
  } catch (error) {
    if (number === requestNo) get("status").textContent = error.message;
  } finally { get("search").disabled = false; }
}

function refreshSearch() {
  if (!currentResult) return;
  clearTimeout(debounce);
  debounce = setTimeout(() => search(1, true), 280);
}

function openEdit(card) {
  editing = {card, tags: new Set(card.tags), productIds: new Set(card.products.map((p) => p.product_id))};
  get("edit-feedback").textContent = "";
  get("edit-title").textContent = "编辑 " + card.fragrance_id;
  get("asset-name").value = card.name;
  get("asset-tag-search").value = "";
  get("asset-tags").replaceChildren();
  get("asset-product").value = "";
  editChips();
  get("edit-dialog").showModal();
}

function editChips() {
  get("asset-chips").replaceChildren(...[...editing.tags].map((t) => button((terms.get(t)?.name || t) + " ×", () => {
    editing.tags.delete(t); editChips();
  }, "chip")));
  get("asset-products").replaceChildren(...[...editing.productIds].map((p) => button((products.get(p)?.name || p) + " ×", () => {
    editing.productIds.delete(p); editChips();
  }, "chip")));
}

function openAction(card, action = "select", name = null) {
  if (!projectId()) {
    get("status").textContent = "请先选择或新建项目";
    get("new-project").focus();
    return;
  }
  currentAsset = card;
  if (flowGoal) {
    for (const option of get("action-type").options) {
      option.hidden = !flowGoal.spec.strategies.includes(option.value) || option.value === "select" && !card;
    }
    if (get("action-type").querySelector("option[value=" + action + "]")?.hidden) {
      action = [...get("action-type").options].find(o => !o.hidden)?.value;
    }
    if (!action) return;
  }
  get("action-asset").textContent = card ? card.name + " · " + card.fragrance_id : (name || "当前项目");
  get("action-type").value = action;
  get("action-note").value = flowGoal?.spec.conditions.changes ||
    (card ? "" : [get("sample").value, get("similarity").value].filter(Boolean).join(" · "));
  get("action-quantity").previousElementSibling.textContent = flowGoal ?
    "原配方版本（改香时）或分析样（仿香时）" : "寄样形态和数量";
  get("action-quantity").value = "";
  get("action-feedback").textContent = "";
  get("action-dialog").showModal();
}

async function progress() {
  get("project-progress").hidden = !projectId();
  if (!projectId()) return;
  try {
    const data = await api("/api/platform");
    const id = projectId();
    const project = setup.projects.find((p) => p.id === id);
    const nodes = project?.brief ? [el("p", project.brief, "muted")] : [];
    for (const task of data.tasks.filter((item) => item.project_id === id)) {
      const status = task.result == null ? "待处理" : task.result ? "通过" : "退回";
      nodes.push(el("p", [setup.departments[task.department], task.title, status].join(" · ")));
    }
    for (const item of data.feed.filter((r) => r.kind === "评香决定" && r.payload.project_id === id)) {
      nodes.push(el("p", [actions[item.payload.action], item.payload.name, item.payload.sample_form]
        .filter(Boolean).join(" · "), "small muted"));
    }
    get("progress-list").replaceChildren(...(nodes.length ? nodes : [el("p", "暂无处理动作", "muted")]));
  } catch (error) { get("progress-list").textContent = error.message; }
}

function setProjects() {
  const select = get("project"), value = select.value;
  select.replaceChildren(choice("", "浏览模式"), ...setup.projects.map((p) => choice(p.id, p.name)));
  select.value = value;
}

async function loadFlowGoal() {
  const params = new URLSearchParams(location.search);
  const project = Number(params.get("project")), id = Number(params.get("goal"));
  if (!project || !id) return;
  const context = await api("/api/workflow", {project_id: project});
  flowGoal = context.rounds.flatMap(r => r.goals).find(g => g.id === id);
  if (!flowGoal) throw Error("找不到该轮次方向");
  get("project").value = project;
  get("project").disabled = true;
  const spec = flowGoal.spec, c = spec.conditions;
  get("mode").value = spec.entry;
  if (!get("mode").value) get("mode").value = "recommend_simple";
  get("brief").value = [c.scent, c.avoid ? "排斥 " + c.avoid : ""].filter(Boolean).join("；");
  for (const option of get("categories").options) option.selected = option.value === c.application_id;
  get("min-price").value = c.price_min ?? "";
  get("max-price").value = c.price_max ?? "";
  get("target-price").value = c.price_target ?? "";
  get("product").value = c.catalog_product_id || "";
  get("brand").value = c.catalog_brand_id || "";
  get("edition").value = c.edition || "";
  get("sample").value = c.sample_reference || "";
  const back = el("a", "返回项目流程", "action-link");
  back.href = "/projects?project=" + project;
  get("flow-banner").append(context.project.name + " · " + spec.title + "　", back);
  get("flow-banner").hidden = false;
}

async function init() {
  setup = await api("/api/bootstrap");
  terms = new Map(setup.terms.map((t) => [t.id, t]));
  products = new Map(setup.products.map((p) => [p.id, p]));
  get("catalog-meta").textContent = setup.catalog_count.toLocaleString("zh-CN") + " 条库记录";
  get("categories").append(...Object.entries(setup.categories).map(([id, name]) => choice(id, name)));
  get("brand").append(...setup.brands.map((b) => choice(b.id, b.name)));
  for (const id of ["product", "asset-product"]) {
    get(id).append(choice("", id === "product" ? "请选择产品" : "添加产品标签"),
      ...setup.products.map((p) => choice(p.id, [p.brand, p.name].filter(Boolean).join(" · "))));
  }
  setProjects();
  await loadFlowGoal();
  modeState();
  get("mode").addEventListener("change", modeState);
  get("project").addEventListener("change", () => {
    const project = setup.projects.find((p) => p.id === projectId());
    if (project?.brief) get("brief").value = project.brief;
    progress(); if (currentResult) search();
  });
  get("new-project").addEventListener("click", () => get("project-dialog").showModal());
  get("refresh-progress").addEventListener("click", progress);
  get("direct-develop").addEventListener("click", () => openAction(null, "duplicate", "跳过检索直接开发"));
  get("search").addEventListener("click", () => search(1, true));
  get("prev").addEventListener("click", () => search(page - 1));
  get("next").addEventListener("click", () => search(page + 1));
  get("demand-editor").addEventListener("toggle", renderDemand);
  get("demand-search").addEventListener("input", renderDemandOptions);
  get("demand-role").addEventListener("change", renderDemandOptions);
  get("add-combination").addEventListener("click", () => {
    groups = groups.filter(group => group.tags.length);
    newCombination = {role: "preference", op: "ANY", tags: []};
    groups.push(newCombination);
    renderDemand();
    get("groups").lastElementChild.querySelector("input").focus();
  });
  for (const id of ["confirmed-only", "min-price", "max-price", "target-price", "big-brand",
                    "brand", "sort", "only-new", "only-hot", "product", "edition", "similarity", "asset-search"]) {
    get(id).addEventListener("change", refreshSearch);
  }
  get("categories").addEventListener("change", () => {
    const active = values("categories");
    groups = groups.map((g) => ({...g, tags: g.tags.filter((id) =>
      terms.get(id)?.level !== "C" || active.includes(terms.get(id).category))}));
    updateDemand();
  });
  get("mapping").addEventListener("click", async () => {
    const control = get("mapping"); control.disabled = true;
    get("mapping-note").textContent = "正在提取…";
    try {
      const result = await api("/api/targeting", {mode: get("mode").value, categories: values("categories"), text: get("brief").value});
      groups = result.groups;
      get("mapping-note").textContent = result.unmapped.filter(Boolean).join(" · ");
      updateDemand();
    } catch (error) { get("mapping-note").textContent = error.message; }
    finally { control.disabled = false; }
  });
  get("asset-tag-search").addEventListener("input", () => get("asset-tags").replaceChildren(
    ...searchTerms(get("asset-tag-search").value, [...editing.card.categories, ...editing.card.historical_categories])
      .filter((t) => !editing.tags.has(t.id)).map((t) => button(t.level + " · " + (t.path || t.name), () => {
        editing.tags.add(t.id); editChips();
      }))));
  get("asset-product").addEventListener("change", () => {
    const selected = get("asset-product").value;
    if (selected) editing.productIds.add(selected);
    get("asset-product").value = ""; editChips();
  });
  for (const [id, callback] of [
    ["edit", async () => {
      await api("/api/assets", {key: editing.card.key, name: get("asset-name").value,
                                tags: [...editing.tags], product_ids: [...editing.productIds]});
      get("edit-dialog").close(); search(page);
    }],
    ["project", async () => {
      const p = await api("/api/projects", {name: get("project-name").value, brief: get("project-brief").value});
      setup.projects.unshift(p); setProjects(); get("project").value = p.id;
      get("project-form").reset(); get("project-dialog").close(); get("brief").value = p.brief; progress();
      if (currentResult) search();
    }],
    ["action", async () => {
      if (flowGoal) {
        const strategy = get("action-type").value;
        const input = get("action-quantity").value;
        await api("/api/flow/plan", {project_id: projectId(), goal_id: flowGoal.id, strategy,
          query_id: currentResult?.query_id, asset_key: currentAsset?.key, note: get("action-note").value,
          base_version: strategy === "modify" ? input : undefined,
          sample_reference: ["duplicate", "select"].includes(strategy) ? input || get("sample").value : undefined});
        location.assign("/projects?project=" + projectId());
        return;
      }
      await api("/api/decisions", {project_id: projectId(), action: get("action-type").value,
        query_id: currentResult?.query_id, key: currentAsset?.key, name: get("action-asset").textContent,
        note: get("action-note").value, sample_form: get("action-quantity").value});
      get("action-dialog").close(); progress();
    }]
  ]) {
    get(id + "-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = event.submitter;
      if (submit) submit.disabled = true;
      get(id + "-feedback").textContent = "";
      try { await callback(); } catch (error) { get(id + "-feedback").textContent = error.message; }
      finally { if (submit) submit.disabled = false; }
    });
  }
  for (const close of document.querySelectorAll("[data-close]")) {
    close.addEventListener("click", () => get(close.dataset.close).close());
  }
}
init().catch((error) => { get("status").textContent = error.message; });
