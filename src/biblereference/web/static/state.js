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
  version: 'dra', // the preferred edition: the first column
  pinned: [], // the versions you keep open beside it
  vrs: 'eng',
  naming: 'modern',
  covering: false,
  theme: 'auto',
};

const LISTS = new Set(['with']);
const FLAGS = new Set(['covering', 'restricted']);

/** What each screen's address is allowed to carry. Anything else is dropped on the way. */
const OWNED = {
  reader: ['vrs', 'naming', 'version', 'with', 'covering'],
  numbering: ['vrs', 'naming'],
  search: ['q', 'composed'],
  library: ['lang', 'family', 'restricted'],
};

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
  // A hand-edited or half-written store must not reach a screen as the wrong shape:
  // `[...'dra']` is three one-letter corpus names, silently ignored by the server.
  merged.with = Array.isArray(params.with)
    ? params.with
    : Array.isArray(saved.pinned)
      ? saved.pinned
      : [];
  merged.path = path;
  return Object.freeze(merged);
}

/**
 * How far the book on screen runs, so `j` stops at its last chapter rather than navigating
 * to a refusal. Set by the reader, which is the only screen that knows; read by the
 * keyboard, which is in the router. Here because it belongs to neither.
 */
export const chapters = { book: '', count: 0 };

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
  let movedPath = 'path' in patch ? patch.path : path;
  // A parameter belongs to the screen that understands it. `q` following you from the
  // search box through every chapter you then read was not a link to the passage; it was a
  // link to the passage plus somebody's old quotation.
  const next = movedPath === path ? { ...params } : keptFor(movedPath, params);

  for (const [key, value] of Object.entries(patch)) {
    if (key === 'path') continue;
    if (value === null || value === undefined) delete next[key];
    else if (LISTS.has(key)) next[key] = value.join(',');
    // `false` is written, not dropped. Deleting it lets localStorage supply `true` again,
    // so a link would show the recipient something the sender was not looking at — and
    // unticking a box whose value was never in the URL did nothing at all.
    else if (typeof value === 'boolean') next[key] = value ? '1' : '0';
    else next[key] = String(value);
  }

  remember(patch);
  // `with` is the address's name for it and `pinned` is storage's, so a link that pins
  // nothing stays distinguishable from "use my saved pins". Mirrored only when this write
  // is the reader's own -- a link someone sent should not overwrite your saved set.
  if (patch.with && movedPath.startsWith('/reader')) remember({ pinned: patch.with });

  const search = new URLSearchParams(next).toString();
  const url = `#${movedPath}${search ? `?${search}` : ''}`;
  if (url === window.location.hash) {
    // The address cannot change, but something else may have: `remember` has just run, and
    // a control whose value the URL never carried would otherwise sit visibly toggled with
    // nothing redrawn behind it.
    announce();
    return;
  }
  if (push) {
    // Setting the hash fires `hashchange`, which routes. Announcing as well would render
    // twice for one click -- and the second render aborts the first's request through the
    // shared controller, so the loading state cleared while the real answer was in flight.
    window.location.hash = url;
    return;
  }
  history.replaceState(null, '', url);
  announce();
}

/** Which of the current parameters the destination screen has any use for. */
function keptFor(path, params) {
  const wanted = OWNED[path.split('/')[1]] ?? [];
  return Object.fromEntries(Object.entries(params).filter(([name]) => wanted.includes(name)));
}

/** The theme now: what you chose, or `auto` to follow the system. */
export function theme() {
  return remembered().theme;
}

/**
 * Show a theme, and remember it only if it was chosen.
 *
 * The `remember` is conditional because `start()` calls this on every load to apply what
 * was saved, and writing it back each time would turn a link carrying `?theme=dark` into a
 * permanent change to the recipient's settings.
 */
export function applyTheme(chosen, { save = false } = {}) {
  if (chosen === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', chosen);
  if (save) remember({ theme: chosen });
}
