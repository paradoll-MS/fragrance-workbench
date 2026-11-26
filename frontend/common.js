const $ = (selector, root = document) => root.querySelector(selector);

function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "value") node.value = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(9)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

async function api(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  let data = {};
  try { data = await response.json(); } catch { /* 空响应按失败处理 */ }
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

const get = path => api("GET", path);
const post = (path, body) => api("POST", path, body || {});
const patch = (path, body) => api("PATCH", path, body || {});

let BOOT = null;
async function boot() {
  if (!BOOT) BOOT = await get("/api/bootstrap");
  return BOOT;
}

let toastNode = null;
function toast(message) {
  if (!toastNode) {
    toastNode = h("div", { class: "toast" });
    document.body.append(toastNode);
  }
  toastNode.textContent = message;
  toastNode.classList.add("show");
  clearTimeout(toastNode.timer);
  toastNode.timer = setTimeout(() => toastNode.classList.remove("show"), 2200);
}

async function run(button, task) {
  const label = button.textContent;
  button.disabled = true;
  try {
    return await task();
  } catch (error) {
    toast(error.message);
    return null;
  } finally {
    button.disabled = false;
    if (button.textContent !== label) button.textContent = label;
  }
}

function chip(text, kind = "") {
  return h("span", { class: "chip " + kind, text });
}

function field(label, input) {
  return h("div", { class: "field" }, h("label", { text: label }), input);
}

function textInput(value, placeholder = "") {
  return h("input", { type: "text", value: value || "", placeholder });
}

function selectInput(options, value, onChange) {
  const node = h("select");
  for (const option of options) {
    node.append(h("option", { value: option.value, text: option.label }));
  }
  node.value = value;
  if (onChange) node.addEventListener("change", () => onChange(node.value));
  return node;
}

function nav(active) {
  return h("div", { class: "bar" },
    h("span", { class: "brand", text: "评香工作台" }),
    h("span", { class: "grow" }),
    h("nav", {},
      h("a", { href: "/index.html", class: active === "projects" ? "on" : "", text: "项目" }),
      h("a", { href: "/select.html", class: active === "select" ? "on" : "", text: "选香" }),
      h("a", { href: "/mock.html", class: active === "mock" ? "on" : "", text: "模拟中台" })),
  );
}

function dialog(title, bodyNodes, footNodes) {
  const node = h("dialog");
  const close = () => { node.close(); node.remove(); };
  node.append(
    h("div", { class: "dlg-head" }, h("h3", { text: title })),
    h("div", { class: "dlg-body" }, bodyNodes.flat(9).filter(Boolean)),
    h("div", { class: "dlg-foot" }, footNodes.flat(9).filter(Boolean)),
  );
  document.body.append(node);
  node.addEventListener("close", () => node.remove());
  node.showModal();
  return { node, close };
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",").pop());
    reader.onerror = () => reject(new Error("读取文件失败：" + file.name));
    reader.readAsDataURL(file);
  });
}

function fmtDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = number => String(number).padStart(2, "0");
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function tagNames(ids, terms) {
  return (ids || []).map(id => (terms[id] ? terms[id].name : id)).filter(Boolean);
}

function params() {
  return new URLSearchParams(location.search);
}
