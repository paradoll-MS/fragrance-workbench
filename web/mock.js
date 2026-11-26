const get = (id) => document.getElementById(id);
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const button = (text, action) => {
  const b = el("button", text, "quiet");
  b.type = "button";
  b.addEventListener("click", action);
  return b;
};
const api = async (url, body) => {
  const response = await fetch(url, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "操作暂未完成");
  return data;
};
let data, setup, termNames, productNames;
let dictionaries;

function paintWeights() {
  const mode = get("lab-mode").value;
  get("lab-weights").replaceChildren(...Object.entries(setup.mode_weights[mode]).map(([key, value]) => {
    const label = el("label", {alpha: "反向关联 α", beta: "正向关联 β"}[key] || key);
    const input = el("input");
    input.type = "number"; input.min = "0"; input.required = true;
    input.step = key.length > 2 ? "0.01" : "1"; input.max = key.length > 2 ? "1" : "100";
    input.value = value; input.dataset.weight = key;
    label.append(input);
    return label;
  }));
}

function paintLabTerms() {
  const selectedCategory = get("lab-category").value;
  const filter = get("lab-tag-search").value.trim().toLocaleLowerCase();
  const applicableTerms = setup.terms.filter((t) => t.level !== "C" || t.category === selectedCategory);
  for (const id of ["lab-positive", "lab-negative"]) {
    const select = get(id);
    const prior = new Set([...select.selectedOptions].map((o) => o.value));
    const visible = applicableTerms.filter((t) => prior.has(t.id) ||
      [t.id, t.path || t.name].some((text) => text.toLocaleLowerCase().includes(filter)));
    select.replaceChildren(...visible.map((t) => new Option(t.level + " · " + (t.path || t.name), t.id,
      false, prior.has(t.id))));
  }
}

function paintDictionaries() {
  const filter = get("dictionary-search").value.trim().toLocaleLowerCase();
  const kind = get("dictionary-mode").value;
  const entries = dictionaries[kind].filter((item) =>
    [item.id, item.name, item.brand, item.path].filter(Boolean).some((field) => field.toLocaleLowerCase().includes(filter)));
  get("dictionary-count").textContent = entries.length + " 条" + (entries.length > 30 ? "，显示前 30 条" : "");
  get("dictionary-items").replaceChildren(...entries.slice(0, 30).map((item) => {
    const box = el("article", null, "task-card");
    box.append(el("h3", [item.brand, item.path || item.name].filter(Boolean).join(" · ")),
               el("p", [item.id, item.level, setup.categories[item.category], setup.departments[item.department]]
                 .filter(Boolean).join(" · "), "muted"));
    if (item.tags?.length) box.append(el("p", item.tags.map((t) => termNames.get(t) || t).join("、"), "small"));
    if (item.record_hint) box.append(el("p", item.record_hint, "small"));
    if (item.defaults?.length) box.append(el("p", item.defaults.map((d) => d.metric_id).join("、"), "small"));
    return box;
  }));
}

async function trialLab(event) {
  event.preventDefault();
  const byRole = [["lab-positive", "preference"], ["lab-negative", "avoid"]];
  const groups = byRole.flatMap(([id, role]) => [...get(id).selectedOptions].map((o) => ({
    role, op: "ANY", tags: [o.value],
  })));
  const weights = Object.fromEntries([...get("lab-weights").querySelectorAll("input")].map((input) =>
    [input.dataset.weight, Number(input.value)]));
  get("lab-note").textContent = "正在试算…";
  try {
    const result = await api("/api/sandbox-search", {term: get("lab-term").value, weights,
      query: {mode: get("lab-mode").value, categories: [get("lab-category").value].filter(Boolean),
        max_price: get("lab-price").value, sort: get("lab-sort").value, groups}});
    get("lab-note").textContent = result.total + " 款" + (result.total > 40 ? "，显示前 40 款" : "");
    get("lab-results").replaceChildren(...result.results.map((item) => {
      const card = el("article", null, "task-card");
      card.append(el("h3", item.name + " · " + item.fragrance_id), el("p",
        [item.score == null ? null : item.score + " 分", item.price ? item.price + " 元/kg" : "价格待查",
          item.price_source === "mock" ? "模拟报价" : "库报价", item.reason].filter(Boolean).join(" · "), "small"));
      if (item.risks?.length) card.append(el("p", item.risks.join(" · "), "small risk"));
      const detail = el("details");
      detail.append(el("summary", "香精资料"),
        el("p", item.categories.map((id) => setup.categories[id]).join("、") || "应用品类待确认"),
        el("p", item.tags.map((id) => termNames.get(id) || id).join("、") || "待补标签"));
      if (item.products.length) detail.append(el("p", item.products.map((p) => p.name).join("、")));
      card.append(detail);
      return card;
    }));
  } catch (error) { get("lab-note").textContent = error.message; }
}

function render() {
  const department = get("department").value;
  get("mock-default").disabled = !department;
  get("mock-default").value = data.defaults[department] == null ? "" : String(data.defaults[department]);
  const tasks = data.tasks.filter((t) => !department || t.department === department);
  get("pass-all").disabled = !data.tasks.some((t) => t.result == null);
  const tasksNodes = tasks.map((t) => {
    const card = el("article", null, "task-card");
    const title = el("h3", setup.departments[t.department] + " · " + t.title);
    const state = t.result == null ? "待处理" : t.result ? "通过" : "退回";
    card.append(title, el("p", t.project_name + " · " + state, "muted"));
    if (t.spec.note) card.append(el("p", t.spec.note));
    if (t.spec.sample_form) card.append(el("p", t.spec.sample_form));
    if (t.spec.workflow) {
      const details = el("details");
      details.append(el("summary", "第 " + t.spec.round + " 轮 · 任务条件"));
      const fields = {scent: "香气方向", avoid: "排斥项", changes: "改动", retained: "保留", substrate: "基质",
        dose_text: "加香量", requirements: "客户要求", price_text: "价格", deadline_text: "交期"};
      for (const [key, label] of Object.entries(fields)) {
        if (t.spec.brief[key]) details.append(el("p", label + " · " + t.spec.brief[key], "small"));
      }
      if (t.spec.assay?.length) details.append(el("p", "审查项 " + t.spec.assay.map(x => x.metric_id).join("、"), "small"));
      if (t.spec.execution?.formula_version) details.append(el("p", t.spec.execution.formula_version, "small"));
      card.append(details);
    }
    if (t.consumed) card.append(el("p", "回执已用于推进项目", "small muted"));
    else {
      const options = el("div", null, "row");
      options.append(button("通过", () => answer(t.id, true)), button("退回", () => answer(t.id, false)));
      card.append(options);
    }
    return card;
  });
  get("tasks").replaceChildren(...(tasksNodes.length ? tasksNodes : [el("p", "暂无任务", "muted")]));
  const quotes = Object.entries(data.quotes).map(([id, value]) => id + " · " + value + " 元/kg");
  get("quotes").textContent = quotes.join("；") || "暂无模拟报价";
  const activity = data.feed.map((item) => {
    const card = el("article", null, "task-card");
    const payload = item.payload;
    card.append(el("h3", item.kind + (payload.key ? " · " + payload.key : "")));
    if (item.kind === "香精资产修改") {
      for (const [field, change] of Object.entries(payload.changes)) {
        if (Array.isArray(change.after)) {
          const lookup = field === "tags" ? termNames : field === "product_ids" ? productNames : new Map(Object.entries(setup.categories));
          const added = change.after.filter((x) => !change.before.includes(x)).map((x) => lookup.get(x) || x);
          const removed = change.before.filter((x) => !change.after.includes(x)).map((x) => lookup.get(x) || x);
          if (added.length) card.append(el("p", "添加 " + added.join("、"), "small"));
          if (removed.length) card.append(el("p", "移除 " + removed.join("、"), "small risk"));
        } else card.append(el("p", change.before + " → " + change.after, "small"));
      }
      card.append(el("p", "manual · " + item.created_at + " UTC", "muted"));
    } else {
      const details = el("details");
      details.append(el("summary", "查看事件"), el("pre", JSON.stringify(payload, null, 2)));
      card.append(details);
    }
    return card;
  });
  get("feed").replaceChildren(...(activity.length ? activity : [el("p", "暂无回流记录", "muted")]));
}

async function reload() {
  data = await api("/api/platform");
  render();
}

async function answer(id, passed) {
  try { await api("/api/task-result", {id, passed}); await reload(); }
  catch (error) { get("status").textContent = error.message; }
}

async function init() {
  setup = await api("/api/bootstrap");
  termNames = new Map(setup.terms.map((t) => [t.id, t.name]));
  productNames = new Map(setup.products.map((p) => [p.id, p.name]));
  get("department").append(...Object.entries(setup.departments).map(([k, v]) => new Option(v, k)));
  const extra = await api("/api/dictionaries");
  dictionaries = {...extra, terms: setup.terms, products: setup.products,
    categories: Object.entries(setup.categories).map(([id, name]) => ({id, name}))};
  get("lab-category").append(...dictionaries.categories.map((c) => new Option(c.name, c.id)));
  get("lab-mode").addEventListener("change", paintWeights);
  get("lab-category").addEventListener("change", paintLabTerms);
  get("lab-tag-search").addEventListener("input", paintLabTerms);
  get("lab-form").addEventListener("submit", trialLab);
  get("dictionary-search").addEventListener("input", paintDictionaries);
  get("dictionary-mode").addEventListener("change", paintDictionaries);
  paintWeights(); paintLabTerms(); paintDictionaries();
  get("department").addEventListener("change", render);
  get("mock-default").addEventListener("change", async () => {
    const choice = get("mock-default").value;
    try {
      await api("/api/mock-default", {department: get("department").value, result: choice === "" ? null : choice === "1"});
      await reload();
    } catch (error) { get("status").textContent = error.message; }
  });
  get("refresh").addEventListener("click", () => reload().catch((error) => { get("status").textContent = error.message; }));
  get("pass-all").addEventListener("click", () => answer(null, true));
  get("quote-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/quotes", {code: get("code").value, price: get("price").value});
      get("status").textContent = "已保存模拟报价";
      await reload();
    } catch (error) { get("status").textContent = error.message; }
  });
  await reload();
}
init().catch((error) => { get("status").textContent = error.message; });
