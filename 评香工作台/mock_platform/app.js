let META = null;
let PLATFORM = null;

const TYPE_LABELS = { analysis: "分析", perfumery: "调香", check: "检查", warehouse: "入库", shipment: "寄样" };

async function load() {
  PLATFORM = await get("/api/platform");
  render();
}

async function setDefault(department, value) {
  await post("/api/platform/default", { department, result: value });
  await load();
}

async function receipt(task, passed, extra) {
  const payload = { ...(extra || {}) };
  if (task.spec && task.spec.requirement_ids && task.type === "check") {
    const results = task.spec.requirement_ids.map(id => ({ requirement_id: id, passed }));
    payload.results = results;
  }
  await post("/api/platform/receipt", { task_id: task.id, passed, payload });
  toast(passed ? "已回执通过" : "已回执退回");
  await load();
}

function extraFields(task) {
  if (task.type === "analysis") {
    return [field("GC 报告编号", textInput("", "例如 GC-2026-041"))];
  }
  if (task.type === "perfumery") {
    return [
      h("div", { class: "grid2" },
        field("试作香精编号", textInput("", "可留空，自动生成")),
        field("配方版本", textInput("", "例如 V1"))),
      field("说明", textInput("", "给评香看的要点")),
    ];
  }
  if (task.type === "shipment") {
    return [field("快递单号", textInput("", "可留空"))];
  }
  return [];
}

function taskCard(task) {
  const inputs = extraFields(task);
  const pass = h("button", { class: "btn primary small", text: "回执通过" });
  const fail = h("button", { class: "btn small", text: "回执退回" });
  const collect = () => {
    const payload = {};
    for (const node of inputs) {
      const input = node.querySelector("input");
      if (!input || !input.value.trim()) continue;
      if (node.textContent.startsWith("GC")) payload.document = input.value.trim();
      else if (node.textContent.startsWith("试作")) payload.trial_fragrance_id = input.value.trim();
      else if (node.textContent.startsWith("配方")) payload.formula_version = input.value.trim();
      else if (node.textContent.startsWith("快递")) payload.tracking = input.value.trim();
      else payload.note = input.value.trim();
    }
    return payload;
  };
  pass.addEventListener("click", () => run(pass, () => receipt(task, true, collect())));
  fail.addEventListener("click", () => run(fail, () => receipt(task, false, collect())));

  const spec = task.spec || {};
  const details = [];
  if (spec.fragrance_id) details.push("香精 " + spec.fragrance_id);
  if (spec.formula_version) details.push("版本 " + spec.formula_version);
  if (task.type === "check") {
    details.push(`${(spec.requirement_ids || []).length} 条要求`);
    const names = (spec.requirements || []).slice(0, 6).map(item =>
      `${item.metric_name || item.metric_id}${item.subitem ? "/" + item.subitem : ""}`);
    if (names.length) details.push(names.join("、") + ((spec.requirements || []).length > 6 ? " …" : ""));
  }
  if (spec.sample_reference) details.push("样 " + spec.sample_reference);
  if (spec.kind) details.push(spec.kind === "initial" ? "初寄样" : "正式寄样");
  return h("div", { class: "card" },
    h("div", { class: "row between" },
      h("div", { class: "row" },
        chip(TYPE_LABELS[task.type] || task.type, "plain"),
        h("span", { text: task.department_label }),
        task.external_id ? h("span", { class: "mono muted small", text: task.external_id }) : null),
      h("a", { class: "small", href: "/project.html?id=" + task.project_id, text: "打开项目" })),
    h("div", { class: "muted small", text: details.join(" · ") }),
    ...inputs,
    h("div", { class: "row", style: { marginTop: "8px" } }, pass, fail));
}

function render() {
  const app = $("#app");
  app.replaceChildren();
  app.append(nav("mock"),
    h("h1", { text: "模拟中台" }),
    h("div", { class: "sub", text: "部门回执、默认回执与报价都在这里；真实中台接入后由适配层替换。" }));

  const defaults = PLATFORM.defaults || {};
  const rows = PLATFORM.departments.map(item => {
    const select = selectInput([
      { value: "", label: "无默认，等人工回执" },
      { value: "1", label: "自动回执通过" },
      { value: "0", label: "自动回执退回" },
    ], defaults[item.value] === 1 ? "1" : defaults[item.value] === 0 ? "0" : "");
    select.addEventListener("change", () => run(select, () => setDefault(item.value, select.value === "" ? "" : select.value === "1")));
    return h("div", { class: "row between item" }, h("span", { text: item.label }), select);
  });
  app.append(h("div", { class: "section" },
    h("div", { class: "head" }, h("h2", { text: "默认回执" })),
    h("div", { class: "muted small", text: "设置后，新派发给该部门的任务会立即按默认结果回执。" }),
    h("div", { class: "list" }, ...rows)));

  const tasks = PLATFORM.tasks || [];
  app.append(h("div", { class: "section" },
    h("div", { class: "head" }, h("h2", { text: "待处理任务" }), chip(tasks.length + " 条")),
    tasks.length ? h("div", {}, ...tasks.map(taskCard))
      : h("div", { class: "card soft" }, h("div", { text: "没有等待回执的任务。" }))));

  const receipts = PLATFORM.receipts || [];
  if (receipts.length) {
    app.append(h("div", { class: "section" },
      h("div", { class: "head" }, h("h2", { text: "最近回执" })),
      h("div", { class: "row" }, ...receipts.map(item => chip("任务 #" + item.task_id + " · " + item.department, "plain")))));
  }
}

async function main() {
  META = await boot();
  await load();
}

main().catch(error => toast(error.message));
