// The reading screen: a book, a chapter, your version at full size, the rest beside it.
//
// The feature this exists for is the hover. Every verse the server sends carries `covers`
// -- the set of pivot verses whose text it holds -- and two verses correspond exactly when
// those sets intersect. So hovering the Douay's Matthew 17:14 lights up *two* Greek verses,
// because that one Latin verse carries both. No per-pair table, no guessing from verse
// numbers: the pivot the whole library is built around already says it.

import { el, fill, notice, slot } from './dom.js';
import * as api from './api.js';
import { read, write } from './state.js';

let inventory = null; // /api/books, which changes only with the numbering or the naming
let inventoryKey = '';

async function booksFor(state, signal) {
  const key = `${state.vrs}/${state.naming}`;
  if (inventoryKey !== key) {
    inventory = await api.books({ vrs: state.vrs, naming: state.naming }, signal);
    inventoryKey = key;
  }
  return inventory;
}

// --------------------------------------------------------------------------------------
// The rail
// --------------------------------------------------------------------------------------

function bookPicker(state, catalogue, book) {
  const byCode = new Map(catalogue.books.map((b) => [b.book, b]));
  const groups = catalogue.groups
    .filter((group) => group.books.length)
    .map((group) =>
      el(
        'optgroup',
        { label: group.label },
        group.books.map((code) =>
          el(
            'option',
            { value: code, selected: code === book },
            byCode.get(code).title,
            // Said in the dropdown itself, because it changes what the chapter grid means:
            // the shape came from the editions rather than from the numbering system.
            byCode.get(code).from === 'corpora' ? ' ·' : null,
          ),
        ),
      ),
    );
  return el(
    'div',
    { class: 'field' },
    el('label', { for: 'book' }, 'Book'),
    el(
      'select',
      {
        id: 'book',
        onchange: (event) => write({ path: `/reader/${event.target.value}/1` }, { push: true }),
      },
      groups,
    ),
  );
}

function chapterGrid(state, entry, chapter) {
  if (!entry || entry.chapters < 1) return null;
  const cells = [];
  for (let n = 1; n <= entry.chapters; n += 1) {
    cells.push(
      el(
        'button',
        {
          class: n === chapter ? 'chapter is-on' : 'chapter',
          type: 'button',
          'aria-current': n === chapter ? 'true' : null,
          title: `${entry.verses[n - 1] ?? '?'} verses`,
          onclick: () => write({ path: `/reader/${entry.book}/${n}` }, { push: true }),
        },
        n,
      ),
    );
  }
  return el(
    'div',
    { class: 'field' },
    el('label', {}, entry.chapters === 1 ? 'One chapter' : `${entry.chapters} chapters`),
    el('div', { class: 'chapters' }, cells),
  );
}

function versionPicker(state, versions) {
  const carrying = versions.filter((v) => v.carries);
  return el(
    'div',
    { class: 'field' },
    el('label', { for: 'version' }, 'Read in'),
    el(
      'select',
      {
        id: 'version',
        onchange: (event) => write({ version: event.target.value }),
      },
      carrying.length
        ? carrying.map((v) =>
            el('option', { value: v.corpus, selected: v.corpus === state.version }, v.label),
          )
        : el('option', { value: '' }, 'nothing here carries this'),
    ),
    el(
      'p',
      { class: 'hint' },
      `${carrying.length} of ${versions.length} versions carry this passage`,
    ),
  );
}

function controls(state) {
  return el(
    'div',
    { class: 'field' },
    el('label', {}, 'Numbering'),
    el(
      'select',
      { onchange: (event) => write({ vrs: event.target.value }) },
      ['org', 'eng', 'lxx', 'vul', 'nvl'].map((s) =>
        el('option', { value: s, selected: s === state.vrs }, s),
      ),
    ),
    el('label', { style: 'margin-top:.5rem' }, 'Book names'),
    el(
      'select',
      { onchange: (event) => write({ naming: event.target.value }) },
      [
        ['modern', 'Modern'],
        ['dr', 'Douay-Rheims'],
        ['lxx', 'Septuagint'],
        ['de', 'German'],
      ].map(([value, label]) => el('option', { value, selected: value === state.naming }, label)),
    ),
    el(
      'label',
      { class: 'check', style: 'margin-top:.6rem' },
      el('input', {
        type: 'checkbox',
        checked: state.covering,
        onchange: (event) => write({ covering: event.target.checked }),
      }),
      'covering',
    ),
    el(
      'p',
      { class: 'hint' },
      'Covering answers with every verse needed to carry all of this one’s text, rather ' +
        'than the single verse it most corresponds to.',
    ),
  );
}

// --------------------------------------------------------------------------------------
// The text
// --------------------------------------------------------------------------------------

/** Light every verse in every column whose `covers` set meets this one's. */
function link(covers) {
  const wanted = new Set(covers);
  for (const node of document.querySelectorAll('.verse[data-covers]')) {
    const theirs = node.dataset.covers ? node.dataset.covers.split('|') : [];
    node.classList.toggle('is-linked', theirs.some((one) => wanted.has(one)));
  }
}

function unlink() {
  for (const node of document.querySelectorAll('.verse.is-linked')) {
    node.classList.remove('is-linked');
  }
}

function verses(version) {
  return version.verses.map((verse) =>
    el(
      'span',
      {
        class: 'verse',
        lang: version.language,
        dir: version.dir,
        dataset: { covers: verse.covers.join('|'), ref: verse.ref },
        onmouseenter: () => link(verse.covers),
        onmouseleave: unlink,
      },
      el('span', { class: 'n' }, verse.n === 0 ? '·' : verse.n, verse.sub),
      verse.text,
    ),
  );
}

/** The one line under a version's name that says how completely it answered. */
function shortfall(version) {
  if (version.refused) return notice(version.refused);
  if (version.absent) return el('p', { class: 'hint' }, 'this edition does not have the book');
  if (version.missing) {
    return el(
      'p',
      { class: 'hint gap' },
      `${version.missing} of ${version.asked} verses are not printed in this edition`,
    );
  }
  return null;
}

function reading(state, version) {
  if (!version) {
    return notice('Choose a version in the rail, or none of them carries this passage.');
  }
  return el(
    'article',
    { class: 'reading' },
    el(
      'header',
      { class: 'version-head' },
      el('h2', {}, version.label),
      el('code', {}, version.corpus),
      el('span', { class: 'meta' }, version.language, ' · ', version.ref ?? ''),
    ),
    shortfall(version),
    version.verses ? el('div', {}, verses(version)) : null,
  );
}

function beside(state, versions, families) {
  const open = new Set(state.with);
  const groups = [];
  for (const [family, rows] of families) {
    const carrying = rows.filter((v) => v.carries || v.loaded);
    if (!carrying.length) continue;
    groups.push(
      el(
        'details',
        { class: 'family', open: carrying.some((v) => open.has(v.corpus)) },
        el(
          'summary',
          {},
          family,
          el('span', { class: 'meta' }, `${carrying.length} carry it`),
        ),
        carrying.map((v) =>
          el(
            'div',
            { class: v.loaded ? 'version is-open' : 'version' },
            el(
              'button',
              {
                type: 'button',
                class: 'version-toggle',
                'aria-expanded': v.loaded ? 'true' : 'false',
                onclick: () => {
                  const next = new Set(state.with);
                  if (next.has(v.corpus)) next.delete(v.corpus);
                  else next.add(v.corpus);
                  write({ with: [...next] });
                },
              },
              el('b', {}, v.label),
              el('span', { class: 'meta' }, v.language, ' · ', v.versification),
            ),
            v.loaded
              ? el(
                  'div',
                  { class: 'compare-text' },
                  el('div', { class: 'meta' }, v.ref),
                  shortfall(v),
                  el('div', {}, verses(v)),
                )
              : shortfall(v),
          ),
        ),
      ),
    );
  }
  return groups.length ? groups : notice('No other version carries this passage.');
}

// --------------------------------------------------------------------------------------
// Putting it together
// --------------------------------------------------------------------------------------

export async function render(state, match, signal) {
  const [, book, rest] = match;
  const chapter = (rest ?? '1').split(':')[0];
  const verse = (rest ?? '').split(':')[1] ?? '';

  const catalogue = await booksFor(state, signal);
  const entry = catalogue.books.find((b) => b.book === book);

  // Ask for the preferred version plus whatever is pinned open. Everything else comes back
  // as a stub, which is what keeps Psalm 119 from being 740 KB.
  const wanted = [...new Set([state.version, ...state.with].filter(Boolean))];
  const payload = await api.reader(
    {
      book,
      chapter,
      verse,
      vrs: state.vrs,
      naming: state.naming,
      covering: state.covering,
      corpus: wanted,
    },
    signal,
  );

  const versions = payload.versions;
  const preferred = versions.find((v) => v.corpus === state.version && v.loaded);
  const families = new Map();
  for (const version of versions) {
    if (version.corpus === state.version) continue;
    if (!families.has(version.versification)) families.set(version.versification, []);
    families.get(version.versification).push(version);
  }

  document.title = `${payload.asked.ref} — biblereference`;

  fill(
    slot('rail'),
    el(
      'div',
      { class: 'panel' },
      bookPicker(state, catalogue, book),
      chapterGrid(state, entry, Number(chapter)),
    ),
    el('div', { class: 'panel' }, versionPicker(state, versions), controls(state)),
    el(
      'div',
      { class: 'panel' },
      el(
        'a',
        { href: `#/numbering/${book}/${rest ?? '1'}?vrs=${state.vrs}` },
        'How every system numbers this →',
      ),
    ),
  );

  fill(
    slot('reading'),
    el(
      'div',
      { class: 'passage-head' },
      el('h1', {}, payload.asked.ref),
      el('span', { class: 'meta' }, 'written in ', el('code', {}, state.vrs)),
    ),
    reading(state, preferred),
  );

  fill(
    slot('compare'),
    el('h2', { class: 'column-head' }, 'Beside it'),
    beside(state, versions, families),
  );
}
