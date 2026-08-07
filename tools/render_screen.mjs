// Run a screen against a live server and print what it built, with no browser.
//
//     venv/bin/biblereference serve --port 8124 &
//     node tools/render_screen.mjs http://127.0.0.1:8124 reader JHN 3
//
// There is no headless browser here and there is not going to be one: it would be the
// project's first dependency that cannot be vendored, for a check that can be had another
// way. What the screens actually need from a browser is small and boring -- create an
// element, set an attribute, append a child, query by selector -- so this supplies exactly
// that, loads the real module, and prints the tree it produced.
//
// It answers the question a regex cannot: does the reader, given what this server really
// says, produce the verses in the right order with the right language and direction on
// them. Appearance still wants eyes; correctness does not.

import { readFileSync } from 'node:fs';

// --------------------------------------------------------------------------------------
// The smallest DOM that the screens actually use
// --------------------------------------------------------------------------------------

class Node_ {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.dataset = {};
    this.children = [];
    this.className = '';
    this.style = { setProperty() {} };
    this.listeners = {};
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  getAttribute(name) {
    return this.attrs[name] ?? null;
  }
  removeAttribute(name) {
    delete this.attrs[name];
  }
  toggleAttribute(name) {
    if (name in this.attrs) delete this.attrs[name];
    else this.attrs[name] = '';
  }
  addEventListener(name, fn) {
    (this.listeners[name] ??= []).push(fn);
  }
  append(...kids) {
    this.children.push(...kids);
  }
  replaceChildren(...kids) {
    this.children = kids;
  }
  get classList() {
    return { add() {}, remove() {}, toggle() {} };
  }
  querySelectorAll() {
    return [];
  }
  get textContent() {
    return this.children.map((c) => (c instanceof Node_ ? c.textContent : String(c.text ?? c))).join('');
  }
}

class Text_ {
  constructor(text) {
    this.text = String(text);
  }
  get textContent() {
    return this.text;
  }
}

const slots = new Map();
for (const name of ['rail', 'reading', 'compare']) slots.set(name, new Node_('section'));

globalThis.Node = Node_;
globalThis.HTMLElement = Node_;
globalThis.document = {
  createElement: (tag) => new Node_(tag),
  createTextNode: (text) => new Text_(text),
  createDocumentFragment: () => new Node_('#fragment'),
  documentElement: new Node_('html'),
  body: new Node_('body'),
  addEventListener() {},
  querySelectorAll: () => [],
  querySelector(selector) {
    const match = /\[data-slot="(.+)"\]/.exec(selector);
    return match ? slots.get(match[1]) : new Node_('div');
  },
};
globalThis.localStorage = {
  store: new Map(),
  getItem(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  },
  setItem(key, value) {
    this.store.set(key, value);
  },
};

const [base, screen, book, chapter, query] = process.argv.slice(2);
const where =
  screen === 'library'
    ? `#/library${query ? `?${query}` : ''}`
    : `#/${screen}/${book}/${chapter}${query ? `?${query}` : ''}`;
globalThis.window = { location: { hash: where }, addEventListener() {} };
globalThis.history = { replaceState() {} };

// Relative URLs, resolved against the server being tested. This is also a check in itself:
// anything absolute here would not be relative, and the page would not work behind a
// tunnel or on a machine with no DNS.
const real = globalThis.fetch;
globalThis.fetch = (url, options) => real(url.startsWith('http') ? url : base + url, options);

// --------------------------------------------------------------------------------------
// Print what it built
// --------------------------------------------------------------------------------------

function show(node, depth = 0, out = []) {
  if (node instanceof Text_) {
    const text = node.text.trim();
    if (text) out.push('  '.repeat(depth) + JSON.stringify(text.slice(0, 88)));
    return out;
  }
  if (!(node instanceof Node_)) return out;
  const bits = [node.tag];
  if (node.className) bits.push(`.${node.className.split(' ').join('.')}`);
  for (const [k, v] of Object.entries(node.attrs)) bits.push(` ${k}=${v}`);
  for (const [k, v] of Object.entries(node.dataset)) bits.push(` data-${k}=${v.slice(0, 60)}`);
  out.push('  '.repeat(depth) + bits.join(''));
  for (const kid of node.children) show(kid, depth + 1, out);
  return out;
}

const modules = { reader: './reader.js', numbering: './numbering.js', library: './library.js' };
const module_ = await import(new URL(modules[screen], `file://${process.cwd()}/src/biblereference/web/static/`));
const { read } = await import(new URL('./state.js', `file://${process.cwd()}/src/biblereference/web/static/`));

const state = read();
const patterns = {
  reader: /^\/reader\/([A-Z0-9]{3})(?:\/(.+))?$/,
  numbering: /^\/numbering\/([A-Z0-9]{3})(?:\/(.+))?$/,
  library: /^\/library$/,
};
await module_.render(state, patterns[screen].exec(state.path) ?? [], undefined);

for (const name of ['rail', 'reading', 'compare']) {
  console.log(`\n===== ${name} =====`);
  console.log(show(slots.get(name)).join('\n'));
}
