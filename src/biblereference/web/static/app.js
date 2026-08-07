// The router, the keyboard, and the search box in the header.
//
// Routing is on `location.hash`, which the browser never sends to the server. That means
// deep links need no catch-all route and the server's "anything else is a 404" rule stays
// literally true -- there is nothing to configure and nothing to get wrong when this is put
// behind a tunnel.

import { ApiError } from './api.js';
import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { applyScale, applyTheme, read, subscribe, write } from './state.js';
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

async function route() {
  const state = read();
  for (const [pattern, screen] of ROUTES) {
    const match = pattern.exec(state.path);
    if (!match) continue;

    inflight?.abort();
    inflight = new AbortController();
    const { signal } = inflight;
    document.body.dataset.screen = state.path.split('/')[1] ?? 'reader';
    document.body.classList.add('is-loading');
    try {
      await screen(state, match, signal);
    } catch (error) {
      if (error.name === 'AbortError') return;
      // The server writes its refusals as sentences for a person. Showing them is the whole
      // benefit of having written them that way.
      fill(
        slot('reading'),
        notice(error instanceof ApiError ? error.message : `${error}`),
      );
      fill(slot('compare'));
    } finally {
      document.body.classList.remove('is-loading');
    }
    return;
  }
  fill(slot('reading'), notice(`No screen for ${state.path}`));
}

// --------------------------------------------------------------------------------------
// The one box
// --------------------------------------------------------------------------------------

async function submitted(event) {
  event.preventDefault();
  const box = document.querySelector('#q');
  const query = box.value.trim();
  if (!query) return;

  const state = read();
  // Ask the server what it is rather than guessing here. It knows the book names of four
  // traditions and this does not.
  let verdict;
  try {
    verdict = await api.parse({ q: query, vrs: state.vrs, naming: state.naming });
  } catch {
    verdict = { ok: false, kind: 'text' };
  }

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
  const state = read();
  const match = /^\/reader\/([A-Z0-9]{3})(?:\/(.+))?$/.exec(state.path);
  switch (event.key) {
    case '/':
      event.preventDefault();
      document.querySelector('#q').focus();
      break;
    case 'j':
    case 'k': {
      if (!match) return;
      const chapter = Number((match[2] ?? '1').split(':')[0]);
      const next = event.key === 'j' ? chapter + 1 : chapter - 1;
      if (next >= 1) write({ path: `/reader/${match[1]}/${next}` }, { push: true });
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

function start() {
  const state = read();
  applyTheme(state.theme);
  applyScale(state.scale);

  document.querySelector('#find').addEventListener('submit', submitted);
  document.querySelector('#theme').addEventListener('click', () => {
    const now = document.documentElement.getAttribute('data-theme');
    applyTheme(now === 'dark' ? 'light' : 'dark');
  });
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
