// Making elements, without a framework and without innerHTML.
//
// Every string that reaches the page goes in as a text node. Verse text is Hebrew, Syriac,
// Greek and Latin from sixty-six editions, and one of them containing a `<` would silently
// eat the rest of the verse if this built markup out of strings -- so it never does.

/**
 * `el('span', {class: 'verse', lang: 'hbo'}, 'בראשית')`
 *
 * Attributes go on as attributes, except `class`/`dataset`/`on*`, which are what they
 * look like. A null or undefined child is skipped, so `cond && el(...)` is usable inline.
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (name.startsWith('on') && typeof value === 'function') {
      node.addEventListener(name.slice(2).toLowerCase(), value);
    } else if (name === 'class') {
      node.className = value;
    } else if (value === true) {
      node.setAttribute(name, '');
    } else {
      node.setAttribute(name, value);
    }
  }
  add(node, children);
  return node;
}

function add(node, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) add(node, child);
    else node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

/** Replace a node's contents in one go, so the screen never shows a half-built state. */
export function fill(node, ...children) {
  const holder = document.createDocumentFragment();
  add(holder, children);
  node.replaceChildren(holder);
  return node;
}

/** A named region of the shell. */
export function slot(name) {
  return document.querySelector(`[data-slot="${name}"]`);
}

/** A short message in place of a screen: an error, or nothing found. */
export function notice(message, kind = 'note-gap') {
  return el('p', { class: kind }, message);
}
