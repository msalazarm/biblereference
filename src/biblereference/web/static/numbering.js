// How every system numbers one verse — exact beside covering, and why.
//
// The two columns are identical for almost every verse in the library, and that is the
// point: where they differ is where one edition merges what another divides. The third
// column is the new one. A refusal explains itself, because every VersificationError in
// this library is written as a sentence for a person; a *mapping* does not, and what fills
// it there are the two hundred reasons somebody wrote down after reading the verses.

import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { write } from './state.js';

function cell(answer, differs) {
  if (answer.refused) return el('td', { class: 'gap' }, answer.refused);
  return el(
    'td',
    { class: differs ? 'differs' : null },
    answer.ref,
    answer.verses > 1 ? el('span', { class: 'meta' }, `${answer.verses} verses`) : null,
  );
}

function why(reasons) {
  if (!reasons.length) return el('td', { class: 'meta' }, '—');
  return el(
    'td',
    {},
    reasons.map((reason) =>
      el(
        'details',
        { class: 'reason' },
        el(
          'summary',
          {},
          el('code', {}, `${reason.system} ${reason.kind}`),
          ' ',
          reason.key,
        ),
        el('p', {}, reason.reason),
      ),
    ),
  );
}

export async function render(state, match, signal) {
  const [, book, rest] = match;
  const ref = `${book} ${rest ?? '1'}`;
  const payload = await api.alignment(
    { ref, vrs: state.vrs, naming: state.naming },
    signal,
  );

  document.title = `${payload.asked.ref} — numbering`;

  fill(
    slot('rail'),
    el(
      'div',
      { class: 'panel' },
      el('div', { class: 'field' }, el('label', {}, 'Written in'),
        el(
          'select',
          { onchange: (event) => write({ vrs: event.target.value }) },
          ['org', 'eng', 'lxx', 'vul', 'nvl'].map((s) =>
            el('option', { value: s, selected: s === state.vrs }, s),
          ),
        ),
      ),
      el(
        'p',
        { class: 'hint' },
        'Highlighted rows are where the exact answer and the covering one differ — where ' +
          'one edition carries in a single verse what another divides in two.',
      ),
    ),
    el(
      'div',
      { class: 'panel' },
      el('a', { href: `#/reader/${book}/${rest ?? '1'}` }, '← Read this passage'),
    ),
  );

  fill(
    slot('reading'),
    el(
      'div',
      { class: 'passage-head' },
      el('h1', {}, payload.asked.ref),
      el('span', { class: 'meta' }, 'written in ', el('code', {}, payload.asked.vrs)),
    ),
    el(
      'div',
      { class: 'scroll-x' },
      el(
        'table',
        { class: 'numbering' },
        el(
          'thead',
          {},
          el(
            'tr',
            {},
            el('th', {}, 'system'),
            el('th', {}, 'exact', el('small', {}, 'which verse it is')),
            el('th', {}, 'covering', el('small', {}, 'every verse it needs')),
            el('th', {}, 'why', el('small', {}, 'refusals, and recorded corrections')),
          ),
        ),
        el(
          'tbody',
          {},
          payload.systems.map((row) =>
            el(
              'tr',
              { class: row.differs ? 'differs' : null },
              el('th', {}, row.label),
              cell(row.exact, false),
              cell(row.covering, row.differs),
              why(row.why),
            ),
          ),
        ),
      ),
    ),
  );

  const kinds = new Set(payload.systems.flatMap((row) => row.why.map((w) => w.kind)));
  fill(
    slot('compare'),
    el('h2', { class: 'column-head' }, 'About this passage'),
    kinds.size
      ? el(
          'div',
          { class: 'panel' },
          el('p', {}, 'The mappings here were corrected by hand. Kinds involved:'),
          el('ul', {}, [...kinds].sort().map((kind) => el('li', {}, el('code', {}, kind)))),
          el(
            'a',
            { href: `#/numbering/${book}/${rest ?? '1'}` },
            '',
          ),
        )
      : notice('Nothing here was corrected — every system maps this verse as upstream had it.', 'hint'),
  );
}
