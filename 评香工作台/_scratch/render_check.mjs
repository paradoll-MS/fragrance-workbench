// Minimal DOM so the browser code can be executed in Node to catch runtime errors.
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const BASE = process.env.BASE || "http://127.0.0.1:18762";

class Node {
  constructor() {
    this.childNodes = [];
    this.parent = null;
    this._listeners = {};
  }
  get textContent() { return this.childNodes.map(node => node.textContent).join(""); }
  set textContent(value) { this.childNodes = [new Text(String(value))]; }
}

class Text extends Node {
  constructor(text) { super(); this._text = text; }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); }
}

function walk(node, visit) {
  for (const child of node.childNodes) {
    if (child instanceof Element) {
      visit(child);
      walk(child, visit);
    }
  }
}

function matches(node, selector) {
  if (selector.startsWith("#")) return node.attributes.id === selector.slice(1);
  if (selector.startsWith(".")) return node.classList.contains(selector.slice(1));
  return node.tag === selector.toUpperCase();
}

function select(root, selector, all) {
  const found = [];
  walk(root, node => { if (matches(node, selector)) found.push(node); });
  return all ? found : found[0] || null;
}

class Element extends Node {
  constructor(tag) {
    super();
    this.tag = tag.toUpperCase();
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.value = "";
    this.checked = false;
    this.files = [];
    this.disabled = false;
    this.open = false;
    this._className = "";
    const self = this;
    this.classList = {
      add(name) { self._className = (self._className + " " + name).trim(); },
      remove(name) { self._className = self._className.split(/\s+/).filter(item => item && item !== name).join(" "); },
      contains(name) { return self._className.split(/\s+/).includes(name); },
      toggle(name) { this.contains(name) ? this.remove(name) : this.add(name); },
    };
  }
  get className() { return this._className; }
  set className(value) { this._className = String(value || ""); }
  append(...kids) {
    for (const kid of kids) {
      const node = kid instanceof Node ? kid : new Text(String(kid));
      node.parent = this;
      this.childNodes.push(node);
    }
  }
  appendChild(kid) { this.append(kid); return kid; }
  replaceChildren(...kids) { this.childNodes = []; this.append(...kids); }
  remove() {
    if (!this.parent) return;
    const index = this.parent.childNodes.indexOf(this);
    if (index >= 0) this.parent.childNodes.splice(index, 1);
    this.parent = null;
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
    if (name === "value") this.value = value;
    if (name === "id") this.id = value;
  }
  getAttribute(name) { return this.attributes[name]; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  dispatch(type) { for (const fn of this._listeners[type] || []) fn({ target: this, preventDefault() {} }); }
  querySelector(selector) { return select(this, selector, false); }
  querySelectorAll(selector) { return select(this, selector, true); }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch("close"); }
  focus() {}
  click() { this.dispatch("click"); }
}

const body = new Element("body");
const app = new Element("div");
app.setAttribute("id", "app");
body.append(app);

const document = {
  body,
  createElement: tag => new Element(tag),
  createTextNode: text => new Text(String(text)),
  querySelector: selector => select(body, selector, false),
  querySelectorAll: selector => select(body, selector, true),
  getElementById: id => select(body, "#" + id, false),
};

const search = process.argv[3] || "";
const globalScope = {
  Node, Element, Text, document, console,
  location: { search, href: BASE + (process.argv[4] || "/"), assign() {} },
  URLSearchParams, setTimeout, clearTimeout, setInterval, clearInterval,
  fetch: (input, init) => fetch(input.startsWith("http") ? input : BASE + input, init),
  FileReader: class {},
  alert() {}, confirm: () => true,
  window: {},
};
globalScope.window = globalScope;
globalScope.globalThis = globalScope;

const context = vm.createContext(globalScope);
const files = ["frontend/common.js", ...(process.argv[2] || "").split("+").filter(Boolean).map(name => "frontend/" + name)];
for (const file of files) {
  const code = fs.readFileSync(path.join(ROOT, file), "utf8");
  vm.runInContext(code, context, { filename: file });
}

await new Promise(resolve => setTimeout(resolve, 4000));
const text = body.textContent.replace(/\s+/g, " ");
console.log("TEXT", text.slice(0, 1200));
console.log("LEN", text.length);
if (/请求失败|Cannot read|undefined is not|is not a function/.test(text)) {
  console.log("SUSPECT", text.match(/.{0,60}(请求失败|Cannot read|is not a function).{0,60}/)?.[0]);
  process.exitCode = 1;
}
