/* Headless UI smoke test.
   Boots the real frontend scripts against the real API using a minimal DOM shim,
   then renders every route and fails on any thrown error or empty page.

   Usage:  node tests/smoke_ui.js [baseUrl]      (server must be running)
*/
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BASE = process.argv[2] || 'http://localhost:8000';
const ROOT = path.resolve(__dirname, '..');

/* ------------------------------------------------------------- DOM shim */
class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...c) { c.forEach((x) => x && this.set.add(x)); this.sync(); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); this.sync(); }
  contains(c) { return this.set.has(c) || String(this.el.className).split(/\s+/).includes(c); }
  toggle(c) { this.contains(c) ? this.remove(c) : this.add(c); return this.contains(c); }
  sync() { const extra = String(this.el.className || '').split(/\s+/).filter(Boolean).filter((x) => !this.set.has(x)); this.el.className = [...new Set([...extra, ...this.set])].join(' '); }
}

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.attributes = {};
    this.dataset = {};
    this.style = { setProperty() {}, removeProperty() {} };
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.selected = false;
    this.parentNode = null;
    this.classList = new ClassList(this);
    this._html = '';
  }
  get children() { return this.childNodes.filter((n) => n instanceof Element); }
  get firstChild() { return this.childNodes[0] || null; }
  set innerHTML(value) { this._html = String(value); this.childNodes = []; }
  get innerHTML() { return this._html; }
  appendChild(node) { if (!node) return node; node.parentNode = this; this.childNodes.push(node); return node; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(typeof n === 'string' ? new TextNode(n) : n)); }
  prepend(...nodes) { nodes.reverse().forEach((n) => { n.parentNode = this; this.childNodes.unshift(n); }); }
  removeChild(node) { this.childNodes = this.childNodes.filter((n) => n !== node); return node; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this.className = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  dispatch(type, event) { (this.listeners[type] || []).forEach((fn) => fn.call(this, event || { target: this })); }
  click() { this.dispatch('click'); }
  focus() {}
  querySelector(selector) {
    const want = selector.trim().toLowerCase();
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child instanceof Element) {
          if (child.tagName.toLowerCase() === want || child.classList.contains(want.replace('.', ''))) return child;
          const found = walk(child);
          if (found) return found;
        }
      }
      return null;
    };
    return walk(this);
  }
  querySelectorAll() { return []; }
  scrollIntoView() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
}
class TextNode {
  constructor(text) { this.nodeValue = String(text); this.textContent = String(text); this.childNodes = []; }
}

const registry = {};
const document = {
  title: '',
  body: new Element('body'),
  createElement: (tag) => new Element(tag),
  createElementNS: (ns, tag) => new Element(tag),
  createTextNode: (text) => new TextNode(text),
  getElementById: (id) => registry[id] || (registry[id] = new Element('div')),
  addEventListener() {}, removeEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  documentElement: new Element('html'),
};

const resolve = (input) => (typeof input === 'string' && input.startsWith('/') ? BASE + input : input);
const store = {};
const localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const window = {
  document, localStorage,
  location: { hash: '', href: BASE },
  addEventListener() {}, removeEventListener() {},
  scrollTo() {}, print() {},
  URL, URLSearchParams, setTimeout, clearTimeout, console,
  fetch: (input, init) => fetch(resolve(input), init),
  Blob: class Blob { constructor(parts) { this.parts = parts; } },
};

/* --------------------------------------------------------------- sandbox */
const sandbox = {
  window, document, localStorage, console,
  fetch: (input, init) => fetch(resolve(input), init),
  setTimeout, clearTimeout, URL, URLSearchParams,
  Blob: window.Blob,
  history: { replaceState() {} },
  location: window.location,
  Node: Element,
  navigator: { userAgent: 'node-smoke' },
  alert: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const file of ['core.js', 'pages.js', 'scheduling.js', 'reports.js']) {
  const code = fs.readFileSync(path.join(ROOT, 'static/js', file), 'utf8');
  vm.runInContext(code, sandbox, { filename: file });
  // in a browser window === globalThis, so mirror the exported globals
  sandbox.App = sandbox.window.App;
  sandbox.h = sandbox.window.h;
}

const App = sandbox.window.App;
if (!App) {
  console.error('FAIL base42: App was not exported');
  process.exit(1);
}

/* ------------------------------------------------------------------- run */
const ROUTES = [
  ['dashboard', {}], ['schools', {}], ['departments', {}], ['student-groups', {}],
  ['examinations', {}], ['rooms', {}], ['invigilators', {}], ['availability', {}],
  ['time-slots', {}], ['policies', {}], ['generator', {}], ['timetable', {}],
  ['conflicts', {}], ['fairness', {}], ['comparison', {}], ['reports', {}],
  ['notifications', {}], ['audit', {}], ['users', {}], ['settings', {}], ['calendar', {}],
  ['my-duties', {}],
];

(async () => {
  const login = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@examflow.ai', password: 'Admin@123' }),
  }).then((r) => r.json());

  App.state.token = login.token;
  App.state.user = login.user;
  App.state.meta = await App.api('/api/meta');
  App.refreshUnread = async () => {};

  let failures = 0;
  for (const [id, params] of ROUTES) {
    const def = App.routes[id];
    if (!def) { console.log(`MISSING route ${id}`); failures += 1; continue; }
    const view = new Element('main');
    try {
      await def.render(view, params);
      await new Promise((r) => setTimeout(r, 60));
      const nodes = view.childNodes.length;
      if (!nodes) { console.log(`EMPTY   ${id} (rendered no content)`); failures += 1; }
      else console.log(`ok      ${id} (${nodes} blocks)`);
    } catch (err) {
      failures += 1;
      console.log(`ERROR   ${id}: ${err && err.message}`);
      if (process.env.VERBOSE) console.log(err.stack);
    }
  }

  /* algorithm comparison sanity via API */
  try {
    const cmp = await App.api('/api/comparison');
    console.log(`\ncomparison: first-fit penalty ${cmp.baseline.soft_constraint_penalty} → AI ${cmp.candidate.soft_constraint_penalty}`);
    console.log(`fairness SD: first-fit ${cmp.baseline.workload_standard_deviation} → AI ${cmp.candidate.workload_standard_deviation}`);
  } catch (err) {
    console.log(`comparison unavailable: ${err.message}`);
  }

  console.log(failures ? `\n${failures} route(s) failed` : '\nAll routes rendered');
  process.exit(failures ? 1 : 0);
})();
