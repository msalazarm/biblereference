// Where a quotation came from, and which translation it was quoted in.
//
// The second half is the part worth showing. A match names not just the passage but every
// edition whose wording agrees, with how closely -- so a patristic quotation that matches
// the Douay at 0.94 and the King James at 0.71 is telling you which English Bible the
// author was reading. And where the document's date is known, an edition whose wording did
// not exist yet is marked: a 4th-century text cannot have been quoting the RSV.

import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { write } from './state.js';

function percent(value) {
  return `${Math.round(value * 100)}%`;
}

function bar(label, value, kind) {
  return el(
    'div',
    { class: 'measure' },
    el('span', { class: 'measure-label' }, label),
    el(
      'span',
      { class: 'measure-track' },
      el('span', { class: `measure-fill ${kind}`, style: `inline-size:${value * 100}%` }),
    ),
    el('span', { class: 'measure-value' }, percent(value)),
  );
}

function translations(match) {
  return el(
    'ul',
    { class: 'translations' },
    match.translations.map((one) =>
      el(
        'li',
        { class: one.translated && match.anachronistic ? 'is-anachronistic' : null },
        el('b', {}, one.label),
        el('code', {}, one.corpus),
        el('span', { class: 'meta' }, percent(one.similarity)),
        one.translated
          ? el('span', { class: 'meta' }, one.translated)
          : el('span', { class: 'meta' }, 'ancient'),
      ),
    ),
  );
}

function result(match) {
  const [book, rest] = match.passage.split(' ');
  return el(
    'article',
    { class: 'panel result' },
    el(
      'header',
      { class: 'result-head' },
      el(
        'a',
        { href: `#/reader/${book}/${rest}` },
        el('h3', {}, match.pretty),
      ),
      el('code', {}, match.vrs),
      match.identified ? el('span', { class: 'badge badge-open' }, 'identified') : null,
      match.decisive ? el('span', { class: 'badge badge-open' }, 'decisive') : null,
      match.ambiguous ? el('span', { class: 'badge badge-restricted' }, 'ambiguous') : null,
      match.anachronistic
        ? el('span', { class: 'badge badge-unrecorded' }, 'anachronistic')
        : null,
    ),
    match.quoted ? el('blockquote', {}, match.quoted) : null,
    bar('similarity', match.similarity, 'is-accent'),
    bar('coverage', match.coverage, 'is-agree'),
    match.alternates?.length
      ? el(
          'p',
          { class: 'hint' },
          'It could also be ',
          match.alternates.map((one, index) => [
            index ? ', ' : null,
            el('a', { href: `#/reader/${one.split(' ')[0]}/${one.split(' ')[1]}` }, one),
          ]),
          '.',
        )
      : null,
    el('h4', {}, 'Editions whose wording agrees'),
    translations(match),
  );
}

export async function render(state, match, signal) {
  const query = state.q ?? '';
  document.title = query ? `${query} — search` : 'search — biblereference';

  fill(
    slot('rail'),
    el(
      'div',
      { class: 'panel' },
      el(
        'p',
        { class: 'hint' },
        'Paste a quotation. It is matched against every edition here, and the answer names ' +
          'both the passage and which translation the wording came from.',
      ),
      el('div', { class: 'field' },
        el('label', { for: 'composed' }, 'Written in the year'),
        el('input', {
          id: 'composed',
          type: 'text',
          inputmode: 'numeric',
          placeholder: 'e.g. 397',
          value: state.composed ?? '',
          onchange: (event) => write({ composed: event.target.value || null }),
        }),
        el(
          'p',
          { class: 'hint' },
          'Where given, an edition whose wording did not exist yet is marked anachronistic.',
        ),
      ),
    ),
  );

  if (!query) {
    fill(slot('reading'), notice('Type a quotation in the box above, or a reference.', 'hint'));
    fill(slot('compare'));
    return;
  }

  fill(slot('reading'), el('p', { class: 'hint' }, 'searching…'));
  const payload = await api.search(
    query,
    { limit: 8, composed: state.composed || null },
    signal,
  );

  fill(
    slot('reading'),
    el(
      'div',
      { class: 'passage-head' },
      el('h1', {}, 'Search'),
      el('span', { class: 'meta' }, `${payload.matches.length} candidate passages`),
    ),
    el('blockquote', { class: 'asked' }, query),
    payload.matches.length
      ? payload.matches.map(result)
      : notice(
          'Nothing here matches that closely. A quotation needs a run of words in common ' +
            'with an edition this library holds — a paraphrase will not be found, and that ' +
            'is deliberate.',
          'hint',
        ),
  );

  fill(
    slot('compare'),
    el('h2', { class: 'column-head' }, 'The library that answered'),
    el(
      'div',
      { class: 'panel' },
      el('p', { class: 'meta' }, 'versification'),
      el('code', {}, payload.library.versification),
      el('p', { class: 'meta' }, 'library digest'),
      el('code', {}, payload.library.digest),
      el(
        'p',
        { class: 'hint' },
        'Carried on the result itself: a mapping correction is an edit to a data file ' +
          'rather than a version bump, so a caller recording only a version would not ' +
          'notice one.',
      ),
    ),
  );
}
