const QUERY = params();
const PROJECT = Number(QUERY.get("project") || 0);
const GOAL = Number(QUERY.get("goal") || 0);
let META = null;
let LAST = null;
let PAGE = 1;

const MODE_LABELS = {
  recommend_simple: "常规推荐", recommend_brand: "品牌定位", with_sample: "对标样品",
};

function tagsLine(card) {
  const terms = META.terms || {};
  const names = (card.tags || []).map(id => terms[id]).filter(Boolean);
  const groups = {};
  for (const term of names) (groups[term.level] = groups[term.level] || []).push(term.name);
  return Object.entries(groups).map(([level, values]) =>
    h("span", { class: "row small" }, h("span", { class: "muted", text: level }), h("span", { text: values.join("、") })));
}

function productLine(card) {
  const products = card.products || card.exact_products || [];
  if (!products.length) return null;
  return h("div", { class: "muted small", text: "关联产品：" + products.slice(0, 3).map(item => item.name || item.product_name).join("；") });
}

async function pick(card) {
  if (!PROJECT || !GOAL) {
    toast("从项目目标位进入才能直接选定");
    return;
  }
  const result = await post(`/api/projects/${PROJECT}/goals/${GOAL}/plan`,
    { strategy: "select", payload: { asset_key: card.key, fragrance_id: card.fragrance_id } });
  if (result.created) toast("已选定 " + card.name);
  location.href = "/project.html?id=" + PROJECT;
}

function resultCard(card) {
  const button = h("button", { class: "btn small", text: "选这款" });
  button.addEventListener("click", () => run(button, () => pick(card)));
  return h("div", { class: "item" },
    h("div", { class: "row between" },
      h("div", { class: "row" },
        h("span", { class: "slot-head id", text: card.name }),
        h("span", { class: "mono muted", text: card.fragrance_id }),
        card.price ? h("span", { class: "small", text: "¥" + card.price }) : null,
        card.is_new ? chip("新", "plain") : null,
        card.is_hot ? chip("热", "plain") : null),
      button),
    card.reason ? h("div", { class: "small muted", text: card.reason }) : null,
    ...tagsLine(card),
    productLine(card),
    (card.risks || []).length ? h("div", { class: "small", style: { color: "var(--warn)" }, text: card.risks.join("；") }) : null);
}

function renderResults(data) {
  const list = $("#results");
  list.replaceChildren();
  const query = data.query || {};
  const summary = h("div", { class: "row" },
    chip(MODE_LABELS[query.mode] || query.mode || "推荐"),
    h("span", { class: "muted small", text: "共 " + data.total + " 款" }),
    data.unmatched_total ? h("span", { class: "muted small", text: "其中 " + data.unmatched_total + " 款缺少可比价格" }) : null);
  list.append(summary);
  if (!data.results.length) {
    list.append(h("div", { class: "card soft" },
      h("div", { text: "没有命中。" }),
      h("div", { class: "muted small", text: (query.hints || []).join("；") || "换个说法，或去掉过窄的限制。" })));
  }
  for (const card of data.results) list.append(resultCard(card));
  if (data.clues && data.clues.length) {
    list.append(h("div", { class: "section" }, h("div", { class: "head" }, h("h2", { text: "线索" })),
      ...data.clues.map(card => h("div", { class: "item" },
        h("div", { class: "row" }, h("span", { text: card.name }), h("span", { class: "mono muted", text: card.fragrance_id }),
          ...(card.risks || []).map(risk => chip(risk, "warn"))),
        productLine(card)))));
  }
  if (data.alternatives && data.alternatives.length) {
    list.append(h("div", { class: "section" }, h("div", { class: "head" }, h("h2", { text: "同类候选" })),
      h("div", { class: "row" }, ...data.alternatives.slice(0, 10).map(card => chip(card.name + " " + card.fragrance_id)))));
  }
  if (data.pages > 1) {
    const prev = h("button", { class: "btn small", text: "上一页" });
    const next = h("button", { class: "btn small", text: "下一页" });
    prev.disabled = data.page <= 1;
    next.disabled = data.page >= data.pages;
    prev.addEventListener("click", () => { PAGE = data.page - 1; search(); });
    next.addEventListener("click", () => { PAGE = data.page + 1; search(); });
    list.append(h("div", { class: "row", style: { marginTop: "12px" } }, prev,
      h("span", { class: "muted small", text: `${data.page} / ${data.pages}` }), next));
  }
}

async function search() {
  const text = $("#query").value.trim();
  if (!text && !GOAL) { toast("请输入要找的香型、产品或描述"); return; }
  const button = $("#go");
  await run(button, async () => {
    const data = await post("/api/search", {
      query: { text: text || undefined, mode: $("#mode").value || undefined },
      goal_id: GOAL || undefined,
      page: PAGE, project_id: PROJECT || undefined, limit: 30,
    });
    LAST = data;
    renderResults(data);
  });
}

async function main() {
  META = await boot();
  const app = $("#app");
  app.append(nav("select"));
  const input = h("input", { type: "text", id: "query", placeholder: "例如：白茶木质 300 以内 洗发；或 COCO 小姐" });
  const mode = h("select", { id: "mode" },
    h("option", { value: "", text: "自动判断" }),
    ...Object.entries(MODE_LABELS).map(([value, label]) => h("option", { value, text: label })));
  const go = h("button", { class: "btn primary", id: "go", text: "搜索" });
  go.addEventListener("click", search);
  input.addEventListener("keydown", event => { if (event.key === "Enter") search(); });
  app.append(
    h("h1", { text: GOAL ? "按需求选香" : "选香" }),
    h("div", { class: "sub", text: GOAL ? "用这个方向的人群、市场、香气原文与标签筛选；改动搜索词会覆盖标签条件。" : (PROJECT ? "选定后回到项目目标位。" : "从项目目标位进入时可以直接选定。") }),
    h("div", { class: "row", style: { margin: "14px 0 20px" } }, input, mode, go),
    h("div", { id: "results", class: "list" }));
  const preset = QUERY.get("q");
  if (preset) { input.value = preset; search(); }
  else if (GOAL) search();
}

main().catch(error => toast(error.message));
