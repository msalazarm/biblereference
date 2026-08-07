// What is chosen, and where each choice lives.
//
// Two stores, and the division is the whole design:
//
//   THE ADDRESS holds what makes a view linkable -- which passage, which system, which
//   versions are open beside it. Paste the URL to somebody and they see what you see.
//
//   localStorage holds what is chosen once and meant to persist -- your preferred version,
//   the naming tradition you read in, the theme, the reading size. These are properties of
//   the reader, not of the passage, and putting them in every link would mean sending
//   somebody your font size.
//
// **The address wins where it says anything; localStorage supplies the default where it is
// silent.** So a link that names a version shows that version even if you prefer another,
// and your preference comes back the moment you navigate somewhere the link did not
// specify.

const PREFIX = 'br.';

/** Defaults, and by their presence here the complete list of remembered keys. */
const REMEMBERED = {
  version: 'dra', // the preferred edition: the one that reads at full size
  pinned: [], // versions kept open in the compare column
  vrs: 'eng',
  naming: 'modern',
  covering: false,
  scale: 1,
  theme: 'auto',
  showRefused: false,
};

const LISTS = new Set(['pinned', 'with']);
const FLAGS = new Set(['covering', 'showRefused']);

function remembered() {
  const out = { ...REMEMBERED };
  for (const key of Object.keys(REMEMBERED)) {
    const raw = localStorage.getItem(PREFIX + key);
    if (raw === null) continue;
    try {
      out[key] = JSON.parse(raw);
    } catch {
      // A hand-edited or half-written value. The default is a better answer than a crash.
    }
  }
  return out;
}

function remember(patch) {
  for (const [key, value] of Object.entries(patch)) {
    if (!(key in REMEMBERED)) continue;
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  }
}

/** `#/reader/JHN/3:16?vrs=vul&v=dra` -> `{path: '/reader/JHN/3:16', params: {...}}` */
export function location_() {
  const raw = window.location.hash.replace(/^#/, '') || '/reader/JHN/3';
  const cut = raw.indexOf('?');
  const path = cut === -1 ? raw : raw.slice(0, cut);
  const params = new URLSearchParams(cut === -1 ? '' : raw.slice(cut + 1));
  const out = {};
  for (const [name, value] of params) {
    out[name] = LISTS.has(name) ? value.split(',').filter(Boolean) : value;
  }
  return { path: path || '/reader/JHN/3', params: out };
}

/**
 * Everything a screen needs, as one frozen object.
 *
 * Frozen because screens are pure functions of it: a screen that mutated what it was given
 * would be changing what the next render reads, which is exactly the class of bug a
 * framework's immutability rules exist to prevent and which is cheap to prevent here.
 */
export function read() {
  const { path, params } = location_();
  const saved = remembered();
  const merged = { ...saved, ...params };
  for (const key of FLAGS) {
    if (typeof merged[key] === 'string') merged[key] = merged[key] === '1' || merged[key] === 'true';
  }
  if (typeof merged.scale === 'string') merged.scale = Number(merged.scale) || 1;
  merged.with = params.with ?? saved.pinned ?? [];
  merged.path = path;
  return Object.freeze(merged);
}

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function announce() {
  for (const fn of listeners) fn(read());
}

/**
 * Change something.
 *
 * `push` decides what the Back button means. Changing the passage pushes -- Back should go
 * to the passage before. Changing a control replaces -- Back should not walk you through
 * every checkbox you toggled on the way here.
 */
export function write(patch, { push = false } = {}) {
  const { path, params } = location_();
  const next = { ...params };
  let movedPath = path;

  for (const [key, value] of Object.entries(patch)) {
    if (key === 'path') {
      movedPath = value;
      continue;
    }
    if (value === null || value === undefined) delete next[key];
    else if (LISTS.has(key)) next[key] = value.join(',');
    else if (typeof value === 'boolean') {
      if (value) next[key] = '1';
      else delete next[key];
    } else next[key] = String(value);
  }

  remember(patch);
  if (patch.with) remember({ pinned: patch.with });

  const search = new URLSearchParams(next).toString();
  const url = `#${movedPath}${search ? `?${search}` : ''}`;
  if (url === window.location.hash) return;
  if (push) window.location.hash = url;
  else history.replaceState(null, '', url);
  announce();
}

/** Apply the saved theme before the stylesheet paints. Also called by the toggle. */
export function applyTheme(theme) {
  const chosen = theme ?? remembered().theme;
  if (chosen === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', chosen);
  if (theme) remember({ theme });
}

export function applyScale(scale) {
  document.documentElement.style.setProperty('--reading-scale', String(scale ?? 1));
}
