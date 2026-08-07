// The router, the keyboard, and the search box in the header.
//
// Routing is on `location.hash`, which the browser never sends to the server. That means
// deep links need no catch-all route and the server's "anything else is a 404" rule stays
// literally true -- there is nothing to configure and nothing to get wrong when this is put
// behind a tunnel.

import { ApiError } from './api.js';
import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { applyTheme, chapters, read, subscribe, theme, write } from './state.js';
import * as reader from './reader.js';
import * as numbering from './numbering.js';
import * as search from './search.js';
import * as library from './library.js';

const ROUTES = [
  [/^\/reader\/([A-Z0-9]{3})(?:\/(.+))?$/, reader.render],
  [/^\/numbering\/([A-Z0-9]{3})(?:\/(.+))?$/, numbering.render],
  [/^\/search$/, search.render],
  [/^\/library$/, library.render],
];

// One controller per navigation. A chapter that takes a moment must not be able to land
// after you have moved on and paint itself over the screen you are now looking at.
let inflight = null;

/**
 * What had the keyboard, so it can have it back.
 *
 * Every control is destroyed by the render it causes -- `fill` replaces the rail wholesale
 * -- so tabbing to the covering checkbox and pressing Space left focus on `<body>`, and
 * the next Space scrolled the page. The controls carry a `data-keep` naming what they are
 * rather than which element they are, and the replacement with the same name gets it back.
 */
function held() {
  const active = document.activeElement;
  return active && active.dataset && active.dataset.keep ? active.dataset.keep : null;
}

function restore(keep) {
  if (!keep) return;
  const found = document.querySelector(`[data-keep="${CSS.escape(keep)}"]`);
  if (found && found !== document.activeElement) found.focus({ preventScroll: true });
}

async function route() {
  const state = read();
  const keep = held();
  for (const [pattern, screen] of ROUTES) {
    const match = pattern.exec(state.path);
    if (!match) continue;

    inflight?.abort();
    inflight = new AbortController();
    const current = inflight;
    document.body.dataset.screen = state.path.split('/')[1] ?? 'reader';
    document.body.classList.add('is-loading');
    try {
      await screen(state, match, current.signal);
      restore(keep);
    } catch (error) {
      if (error.name === 'AbortError' || current.signal.aborted) return;
      // The server writes its refusals as sentences for a person. Showing them is the whole
      // benefit of having written them that way.
      fill(slot('reading'), notice(error instanceof ApiError ? error.message : `${error}`));
      fill(slot('compare'));
    } finally {
      // Only the newest navigation may clear it; an aborted one must not say the page has
      // settled while its replacement is still fetching.
      if (inflight === current) document.body.classList.remove('is-loading');
    }
    return;
  }
  document.body.dataset.screen = 'none';
  fill(slot('reading'), notice(`No screen for ${state.path}`));
  fill(slot('rail'));
  fill(slot('compare'));
}

// --------------------------------------------------------------------------------------
// The one box
// --------------------------------------------------------------------------------------

// Its own controller: two quick submissions would otherwise race, and the slower answer
// would navigate you away from where the faster one had already taken you.
let asking = null;

async function submitted(event) {
  event.preventDefault();
  const box = document.querySelector('#q');
  const query = box.value.trim();
  if (!query) return;

  const state = read();
  asking?.abort();
  asking = new AbortController();
  const mine = asking;
  // Ask the server what it is rather than guessing here. It knows the book names of four
  // traditions and this does not.
  let verdict;
  try {
    verdict = await api.parse({ q: query, vrs: state.vrs, naming: state.naming }, mine.signal);
  } catch (error) {
    if (error.name === 'AbortError') return;
    verdict = { ok: false, kind: 'text' };
  }
  if (mine.signal.aborted) return;

  if (verdict.ok) {
    const tail = verdict.single ? `${verdict.chapter}:${verdict.verse}` : String(verdict.chapter);
    write({ path: `/reader/${verdict.book}/${tail}` }, { push: true });
    return;
  }
  if (verdict.kind === 'ambiguous') {
    fill(slot('reading'), ambiguity(verdict));
    fill(slot('compare'));
    return;
  }
  if (verdict.kind === 'unreachable') {
    fill(slot('reading'), notice(verdict.error));
    fill(slot('compare'));
    return;
  }
  write({ path: '/search', q: query }, { push: true });
}

/** "1 Kings" means 1 Samuel to a Douay reader. Ask, rather than guess. */
function ambiguity(verdict) {
  return el(
    'div',
    { class: 'panel' },
    el('p', {}, `“${verdict.q}” names different books in different traditions.`),
    el(
      'ul',
      { class: 'choices' },
      verdict.options.map((option) =>
        el(
          'li',
          {},
          el(
            'button',
            {
              type: 'button',
              onclick: () => write({ naming: option.naming, path: `/reader/${option.book}/1` }, { push: true }),
            },
            option.title,
            el('span', { class: 'meta' }, `read as ${option.naming}`),
          ),
        ),
      ),
    ),
  );
}

// --------------------------------------------------------------------------------------
// Keys
// --------------------------------------------------------------------------------------

function typing(target) {
  return target instanceof HTMLElement && target.matches('input, select, textarea');
}

function key(event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (typing(event.target)) {
    if (event.key === 'Escape') event.target.blur();
    return;
  }
  // Read the address rather than the whole state: this runs on every keystroke, and
  // `read()` touches localStorage six times.
  const path = (window.location.hash.replace(/^#/, '').split('?')[0] || '/reader/JHN/3');
  const match = /^\/reader\/([A-Z0-9]{3})(?:\/(.+))?$/.exec(path);
  switch (event.key) {
    case '/':
      event.preventDefault();
      document.querySelector('#q').focus();
      break;
    case 'j':
    case 'k': {
      if (!match) return;
      const chapter = Number((match[2] ?? '1').split(':')[0]);
      if (!Number.isFinite(chapter)) return; // Esther's lettered chapters
      const next = event.key === 'j' ? chapter + 1 : chapter - 1;
      const last = chapters.book === match[1] ? chapters.count : Infinity;
      if (next >= 1 && next <= last) {
        write({ path: `/reader/${match[1]}/${next}` }, { push: true });
      }
      break;
    }
    case '?':
      document.querySelector('#help').toggleAttribute('open');
      break;
    default:
      break;
  }
}

// --------------------------------------------------------------------------------------
// Start
// --------------------------------------------------------------------------------------

//: auto -> light -> dark -> auto. `auto` has to be reachable again: it is the only setting
//: that follows the reader's own machine, and a toggle that could only leave it is a
//: preference you can lose by accident.
const THEMES = ['auto', 'light', 'dark'];

function start() {
  applyTheme(theme());

  document.querySelector('#find').addEventListener('submit', submitted);
  const toggle = document.querySelector('#theme');
  const label = () => {
    const now = theme();
    toggle.setAttribute('aria-label', `Theme: ${now}. Click for the next.`);
    toggle.textContent = now === 'light' ? '☀' : now === 'dark' ? '☾' : '◐';
  };
  toggle.addEventListener('click', () => {
    const next = THEMES[(THEMES.indexOf(theme()) + 1) % THEMES.length];
    applyTheme(next, { save: true });
    label();
  });
  label();

  document.addEventListener('keydown', key);
  window.addEventListener('hashchange', route);
  subscribe(route);
  route();
}

// A token in the address is how somebody arrives from a link; the server has set a cookie
// by now, so leaving it in the bar only invites it into a screenshot.
if (new URLSearchParams(window.location.search).has('token')) {
  history.replaceState(null, '', window.location.pathname + window.location.hash);
}

start();
