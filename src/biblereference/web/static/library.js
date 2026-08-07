// Everything this machine holds, and what may be done with it.
//
// The licence column is the one to get right. Twenty-five of the sixty-six are restricted
// and four of those are CC BY-SA, which permits commercial use and still obliges you -- so
// there is no single "free/not free" flag that would be true. And one corpus has no
// recorded licence at all, which is shown *more* loudly than a restrictive one: a blank
// cell reads as "no restrictions" and means the opposite.
//
// The second panel is the interesting one. A corpus declares a versification in its
// metadata; `/api/families` says which one its chapter divisions actually resemble. Where
// those disagree is worth knowing, and it is how the whole family model was checked.

import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { write } from './state.js';

function licence(row) {
  const terms = row.licence;
  if (terms.unrecorded) {
    return el(
      'span',
      { class: 'badge badge-unrecorded', title: terms.describe },
      'no licence recorded',
    );
  }
  return el(
    'span',
    {
      class: terms.restricted ? 'badge badge-restricted' : 'badge badge-open',
      title: terms.describe,
    },
    terms.name,
  );
}

function row(entry) {
  return el(
    'tr',
    {},
    el(
      'th',
      {},
      entry.label,
      el('code', {}, entry.corpus),
      entry.attribution ? el('span', { class: 'meta' }, entry.attribution) : null,
    ),
    el('td', {}, el('span', { lang: entry.language }, entry.language)),
    el('td', {}, el('code', {}, entry.versification)),
    el('td', { class: 'num' }, entry.verses.toLocaleString()),
    el('td', { class: 'num' }, entry.books),
    el(
      'td',
      {},
      entry.ancient ? el('span', { class: 'meta' }, 'ancient') : String(entry.translated),
    ),
    el('td', {}, licence(entry)),
  );
}

function filters(state, payload) {
  const languages = Object.keys(payload.totals.languages);
  const families = Object.keys(payload.totals.families);
  return el(
    'div',
    { class: 'panel' },
    el(
      'div',
      { class: 'field' },
      el('label', { for: 'lang' }, 'Language'),
      el(
        'select',
        { id: 'lang', onchange: (event) => write({ lang: event.target.value || null }) },
        el('option', { value: '' }, `all (${payload.totals.corpora})`),
        languages.map((code) =>
          el(
            'option',
            { value: code, selected: code === state.lang },
            `${code} (${payload.totals.languages[code]})`,
          ),
        ),
      ),
    ),
    el(
      'div',
      { class: 'field' },
      el('label', { for: 'family' }, 'Numbering'),
      el(
        'select',
        { id: 'family', onchange: (event) => write({ family: event.target.value || null }) },
        el('option', { value: '' }, 'all'),
        families.map((code) =>
          el(
            'option',
            { value: code, selected: code === state.family },
            `${code} (${payload.totals.families[code]})`,
          ),
        ),
      ),
    ),
    el(
      'label',
      { class: 'check' },
      el('input', {
        type: 'checkbox',
        checked: state.restricted === '1',
        onchange: (event) => write({ restricted: event.target.checked ? '1' : null }),
      }),
      'needs attention before reuse',
    ),
  );
}

async function derived(signal) {
  const payload = await api.families({}, signal);
  const declared = new Map();
  for (const family of payload.families) {
    for (const member of family.members) declared.set(member, family.name);
  }
  return el(
    'div',
    { class: 'panel' },
    el('h3', {}, 'Families, from where the chapters end'),
    el(
      'p',
      { class: 'hint' },
      'Derived by comparing verse counts chapter by chapter, not read from the metadata. ' +
        'A corpus declaring one system and dividing like another is what this is for.',
    ),
    el(
      'ul',
      { class: 'families' },
      payload.families.map((family) =>
        el(
          'li',
          {},
          el('code', {}, family.name),
          el('span', { class: 'meta' }, `${family.members.length} members`),
          el('span', { class: 'meta' }, `declares ${family.declared.join(', ')}`),
        ),
      ),
    ),
    payload.unplaced.length
      ? el(
          'p',
          { class: 'hint' },
          `${payload.unplaced.length} corpora could not be placed: they overlap no family ` +
            'by enough chapters to say.',
        )
      : null,
  );
}

export async function render(state, match, signal) {
  document.title = 'library — biblereference';
  const payload = await api.catalogue({}, signal);

  let rows = payload.corpora;
  if (state.lang) rows = rows.filter((r) => r.language === state.lang);
  if (state.family) rows = rows.filter((r) => r.versification === state.family);
  if (state.restricted === '1') {
    rows = rows.filter((r) => r.licence.restricted || r.licence.unrecorded);
  }

  fill(slot('rail'), filters(state, payload));

  const totals = payload.totals;
  fill(
    slot('reading'),
    el(
      'div',
      { class: 'passage-head' },
      el('h1', {}, 'The library'),
      el(
        'span',
        { class: 'meta' },
        `${totals.corpora} editions · ${totals.verses.toLocaleString()} verses · ` +
          `${Object.keys(totals.languages).length} languages`,
      ),
    ),
    el(
      'p',
      { class: 'hint' },
      `${totals.restricted} carry a licence that restricts reuse. `,
      totals.unrecorded
        ? el(
            'b',
            { class: 'gap' },
            `${totals.unrecorded} has no recorded licence at all, which is stricter still — ` +
              'nobody has established the terms.',
          )
        : null,
    ),
    rows.length
      ? el(
          'div',
          { class: 'scroll-x' },
          el(
            'table',
            { class: 'catalogue' },
            el(
              'thead',
              {},
              el(
                'tr',
                {},
                el('th', {}, 'edition'),
                el('th', {}, 'lang'),
                el('th', {}, 'numbers'),
                el('th', { class: 'num' }, 'verses'),
                el('th', { class: 'num' }, 'books'),
                el('th', {}, 'wording'),
                el('th', {}, 'licence'),
              ),
            ),
            el('tbody', {}, rows.map(row)),
          ),
        )
      : notice('Nothing here matches those filters.', 'hint'),
  );

  fill(slot('compare'), el('h2', { class: 'column-head' }, 'How they group'), el('p', { class: 'hint' }, 'deriving…'));
  fill(slot('compare'), el('h2', { class: 'column-head' }, 'How they group'), await derived(signal));
}
