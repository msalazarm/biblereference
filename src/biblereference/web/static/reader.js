// The reading screen: a book, a chapter, and every version you have opened, side by side.
//
// The table is the whole point. Two verses of two editions belong on one row when they
// carry the same text, and the server says which by keying every row on the pivot verse --
// so the Douay's Matthew 17:14 and the Greek's 17:15 sit together, and every Douay verse
// after them sits one row behind its own number. No amount of aligning by verse number
// could do that, and verse number is exactly what disagrees on the passages worth
// comparing.
//
// Rows carry indices into each version's `verses` array rather than text, so a verse that
// answers to three rows crosses the wire once.

import * as api from './api.js';
import { el, fill, notice, slot } from './dom.js';
import { chapters, write } from './state.js';

/** Past this many columns the page is worth a word of warning. */
const BUSY = 6;

/** And past this it is refused: Psalm 119 at thirteen columns is ~19,000 cells. */
const TOO_MANY = 12;

let inventory = null; // /api/books, which changes only with the numbering or the naming
let inventoryKey = '';

async function booksFor(vrs, naming, signal) {
  const key = `${vrs}/${naming}`;
  if (inventoryKey !== key) {
    inventory = await api.books({ vrs, naming }, signal);
    inventoryKey = key;
  }
  return inventory;
}

// --------------------------------------------------------------------------------------
// The rail
// --------------------------------------------------------------------------------------

function bookPicker(catalogue, book) {
  const byCode = new Map(catalogue.books.map((b) => [b.book, b]));
  return el(
    'div',
    { class: 'field' },
    el('label', { for: 'book' }, 'Book'),
    el(
      'select',
      {
        id: 'book',
        dataset: { keep: 'book' },
        onchange: (event) => write({ path: `/reader/${event.target.value}/1` }, { push: true }),
      },
      catalogue.groups
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
                // Said in the dropdown, because choosing it changes the numbering: this
                // book's shape comes from the editions that hold it, not from the system.
                byCode.get(code).from === 'corpora' ? ' ·' : null,
              ),
            ),
          ),
        ),
    ),
    catalogue.books.some((b) => b.from === 'corpora')
      ? el(
          'p',
          { class: 'hint' },
          '· is a book this numbering does not have. Choosing one switches to a ' +
            'numbering that does.',
        )
      : null,
  );
}

function chapterGrid(entry, chapter) {
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

/** Whether a version can show anything here: it holds the book, or it loaded through one. */
function usable(version) {
  return version.carries || version.loaded || version.refused;
}

function versionPicker(state, versions) {
  const offered = versions.filter(usable);
  const known = new Set(offered.map((v) => v.corpus));
  // A version pinned somewhere else and useless here still needs to be unpinnable.
  const stranded = state.with.filter((corpus) => !known.has(corpus));
  return el(
    'div',
    { class: 'field' },
    el('label', { for: 'version' }, 'Read in'),
    el(
      'select',
      {
        id: 'version',
        dataset: { keep: 'version' },
        onchange: (event) => write({ version: event.target.value }),
      },
      offered.length
        ? offered.map((v) =>
            el(
              'option',
              { value: v.corpus, selected: v.corpus === state.version },
              v.label,
              v.held ? null : ' — not here',
            ),
          )
        : el('option', { value: '' }, 'nothing here carries this'),
    ),
    stranded.length
      ? el(
          'p',
          { class: 'hint' },
          `${stranded.length} pinned version(s) have nothing here. `,
          el(
            'button',
            {
              type: 'button',
              class: 'linkish',
              onclick: () => write({ with: state.with.filter((c) => known.has(c)) }),
            },
            'Drop them',
          ),
        )
      : null,
  );
}

/** The compare picker: which versions get a column. */
function columns(state, versions) {
  const open = new Set(state.with);
  const families = new Map();
  for (const version of versions) {
    if (version.corpus === state.version || !usable(version)) continue;
    if (!families.has(version.versification)) families.set(version.versification, []);
    families.get(version.versification).push(version);
  }
  if (!families.size) {
    return el('p', { class: 'hint' }, 'No other version has this passage.');
  }

  const total = open.size + 1;
  return el(
    'div',
    { class: 'field' },
    el('label', {}, 'Compare with'),
    total > BUSY
      ? el(
          'p',
          { class: total > TOO_MANY ? 'hint gap' : 'hint' },
          `${total} columns open.`,
          total > TOO_MANY ? ' That is more than this page will draw at once.' : null,
        )
      : null,
    el(
      'div',
      { class: 'columns-pick' },
      [...families].map(([family, rows]) =>
        el(
          'fieldset',
          { class: 'family' },
          el(
            'legend',
            {},
            family,
            el(
              'span',
              { class: 'meta' },
              `${rows.length} · ${[...new Set(rows.map((v) => v.language))].join(' ')}`,
            ),
          ),
          rows.map((v) => {
            const id = `with-${v.corpus}`;
            const blocked = !open.has(v.corpus) && total >= TOO_MANY;
            return el(
              'div',
              { class: 'pick' },
              el('input', {
                type: 'checkbox',
                id,
                dataset: { keep: id },
                checked: open.has(v.corpus),
                disabled: blocked,
                onchange: () => {
                  const next = new Set(state.with);
                  if (next.has(v.corpus)) next.delete(v.corpus);
                  else next.add(v.corpus);
                  write({ with: [...next] });
                },
              }),
              el(
                'label',
                { for: id, title: v.refused || `${v.label} — ${v.language}` },
                el('span', { class: 'pick-name' }, v.label),
                // The language only where it is not the family's usual one, and a warning
                // where the edition has nothing here. Anything else is width the edition's
                // name needs more.
                v.held ? null : el('span', { class: 'meta gap' }, 'empty'),
              ),
            );
          }),
        ),
      ),
    ),
  );
}

function controls(state, systems) {
  return el(
    'div',
    { class: 'field' },
    el('label', { for: 'vrs' }, 'Numbering'),
    el(
      'select',
      {
        id: 'vrs',
        dataset: { keep: 'vrs' },
        onchange: (event) => write({ vrs: event.target.value }),
      },
      systems.map((s) => el('option', { value: s, selected: s === state.vrs }, s)),
    ),
    el('label', { for: 'naming' }, 'Book names'),
    el(
      'select',
      {
        id: 'naming',
        dataset: { keep: 'naming' },
        onchange: (event) => write({ naming: event.target.value }),
      },
      [
        ['modern', 'Modern'],
        ['dr', 'Douay-Rheims'],
        ['lxx', 'Septuagint'],
        ['de', 'German'],
      ].map(([value, label]) => el('option', { value, selected: value === state.naming }, label)),
    ),
    el(
      'label',
      { class: 'check', for: 'covering' },
      el('input', {
        type: 'checkbox',
        id: 'covering',
        dataset: { keep: 'covering' },
        checked: state.covering,
        onchange: (event) => write({ covering: event.target.checked }),
      }),
      'covering',
    ),
    el(
      'p',
      { class: 'hint' },
      'Covering shows every verse needed to carry all of a verse’s text, rather than the ' +
        'single verse it most corresponds to. It changes which verses appear, never which ' +
        'row they appear on.',
    ),
  );
}

// --------------------------------------------------------------------------------------
// The table
// --------------------------------------------------------------------------------------

/**
 * Which rows each verse appears in.
 *
 * A verse carrying two pivot verses is drawn in both rows — the Douay's Matthew 17:14 is
 * genuinely the answer to two Greek verses, and blanking the second would deny it. This
 * says so, and lets hovering one copy light the other.
 */
function repeats(rows) {
  const where = new Map();
  for (const row of rows) {
    for (const [corpus, indices] of Object.entries(row.at ?? {})) {
      for (const index of indices) {
        const key = `${corpus}:${index}`;
        if (!where.has(key)) where.set(key, []);
        where.get(key).push(row.key);
      }
    }
  }
  return where;
}

function verse(version, held, rows, here) {
  const shared = rows.length > 1;
  // Drawn in every row it answers to, but only the first is the primary reading: the rest
  // are the same words seen again, and setting them at the same weight makes a long verse
  // look like two different ones.
  const echo = shared && rows[0] !== here;
  return el(
    'span',
    {
      class: ['verse', shared ? 'is-shared' : null, echo ? 'is-echo' : null]
        .filter(Boolean)
        .join(' '),
      lang: version.language,
      dir: version.dir,
      dataset: shared ? { ref: held.ref, rows: rows.join('|') } : { ref: held.ref },
      title: shared ? `one verse carrying ${rows.length} of the original` : null,
    },
    el('span', { class: 'n' }, held.n === 0 ? '·' : held.n, held.sub),
    held.text,
  );
}

/** The one line under a version's name saying how completely it answered. */
function shortfall(version) {
  if (version.refused) return el('p', { class: 'hint gap' }, version.refused);
  if (version.absent) return el('p', { class: 'hint' }, 'not in this edition');
  if (version.missing) {
    return el(
      'p',
      { class: 'hint gap' },
      `${version.missing} of ${version.asked} verses are not printed here`,
    );
  }
  return null;
}

function head(open) {
  return el(
    'thead',
    {},
    el(
      'tr',
      {},
      el('th', { class: 'key-head', scope: 'col' }, 'verse'),
      open.map((v) =>
        el(
          'th',
          { scope: 'col', lang: v.language },
          el('span', { class: 'version-name' }, v.label),
          el('span', { class: 'meta' }, v.language, ' · ', v.versification),
          shortfall(v),
        ),
      ),
    ),
  );
}

function body(payload, open) {
  const byCorpus = new Map(open.map((v) => [v.corpus, v]));
  const where = repeats(payload.rows);
  let outside = null; // the caption for a run of rows outside the asked passage

  const rows = [];
  for (const row of payload.rows) {
    if (!row.in_span && outside !== row.key.split(':')[0]) {
      outside = row.key.split(':')[0];
      rows.push(
        el(
          'tr',
          { class: 'row-aside' },
          el(
            'td',
            { colspan: open.length + 1 },
            'These verses sit elsewhere in the original numbering — ',
            el('b', {}, outside),
            '. An edition that moves a passage bodily is shown where its text belongs.',
          ),
        ),
      );
    }
    if (row.in_span) outside = null;

    const label = row.label;
    rows.push(
      el(
        'tr',
        {
          class: [
            row.in_span ? null : 'is-outside',
            row.aligned ? null : 'is-unlinked',
            row.at && Object.keys(row.at).length ? null : 'is-empty',
          ]
            .filter(Boolean)
            .join(' '),
          dataset: { key: row.key },
        },
        el(
          'th',
          { scope: 'row', class: 'key', title: label.refused || row.key },
          el('span', { class: 'key-ref' }, label.ref),
          label.pivot ? el('span', { class: 'key-pivot' }, label.pivot) : null,
          label.vrs ? el('span', { class: 'key-pivot' }, label.vrs) : null,
        ),
        open.map((v) => {
          const indices = (row.at && row.at[v.corpus]) || [];
          return el(
            'td',
            { class: indices.length ? null : 'is-blank' },
            indices.map((index) =>
              verse(
                byCorpus.get(v.corpus),
                v.verses[index],
                where.get(`${v.corpus}:${index}`) ?? [],
                row.key,
              ),
            ),
          );
        }),
      ),
    );
  }
  return el('tbody', {}, rows);
}

function table(payload, open) {
  if (!open.length) {
    return notice('Choose a version to read in, from the rail.');
  }
  if (!payload.rows.length) {
    return notice('No open version prints this passage.');
  }
  return el(
    'div',
    { class: 'compare-scroll scroll-x' },
    el(
      'table',
      { class: 'compare' },
      el(
        'colgroup',
        {},
        el('col', { class: 'key-col' }),
        open.map(() => el('col', { class: open.length === 1 ? 'sole-col' : 'text-col' })),
      ),
      head(open),
      body(payload, open),
    ),
  );
}

// --------------------------------------------------------------------------------------
// Putting it together
// --------------------------------------------------------------------------------------

export async function render(state, match, signal) {
  const [, book, rest] = match;
  const chapter = (rest ?? '1').split(':')[0];
  const verses = (rest ?? '').split(':')[1] ?? '';

  let catalogue = await booksFor(state.vrs, state.naming, signal);
  let entry = catalogue.books.find((b) => b.book === book);

  // A book this numbering does not have. Rather than refusing — which is what asking for
  // it used to do, for a fifth of the library under the Nova Vulgata — move to a numbering
  // that does, and say so above the text.
  let switched = null;
  if (entry && entry.from === 'corpora') {
    const target = (entry.in ?? [])[0];
    if (target && target !== state.vrs) {
      switched = { from: state.vrs, to: target, title: entry.title };
      catalogue = await booksFor(target, state.naming, signal);
      entry = catalogue.books.find((b) => b.book === book) ?? entry;
    }
  }
  const vrs = switched ? switched.to : state.vrs;

  // The preferred version plus whatever is open. Everything else comes back as a stub,
  // which is what keeps Psalm 119 across every version from being 1.5 MB.
  const wanted = [...new Set([state.version, ...state.with].filter(Boolean))].slice(0, TOO_MANY);
  const payload = await api.reader(
    {
      book,
      chapter,
      verse: verses,
      vrs,
      naming: state.naming,
      covering: state.covering,
      corpus: wanted,
      rows: 1,
    },
    signal,
  );

  const versions = payload.versions;
  const byCorpus = new Map(versions.map((v) => [v.corpus, v]));
  // Column order: the version you read in first, then the rest as you opened them.
  const open = [state.version, ...state.with]
    .filter((corpus, index, all) => corpus && all.indexOf(corpus) === index)
    .map((corpus) => byCorpus.get(corpus))
    .filter((v) => v && v.loaded);

  document.title = `${payload.asked.ref} — biblereference`;
  // So `j` stops at the last chapter instead of navigating to a refusal.
  chapters.book = book;
  chapters.count = entry ? entry.chapters : 0;

  fill(
    slot('rail'),
    el('div', { class: 'panel' }, bookPicker(catalogue, book), chapterGrid(entry, Number(chapter))),
    el(
      'div',
      { class: 'panel' },
      versionPicker(state, versions),
      columns(state, versions),
      controls({ ...state, vrs }, catalogue.systems ?? [vrs]),
    ),
    el(
      'div',
      { class: 'panel' },
      el(
        'a',
        { href: `#/numbering/${book}/${rest ?? '1'}?vrs=${vrs}` },
        'How every system numbers this →',
      ),
    ),
  );

  const alignment = payload.asked.alignment ?? {};
  fill(
    slot('reading'),
    el(
      'div',
      { class: 'passage-head' },
      el('h1', {}, payload.asked.ref),
      el('span', { class: 'meta' }, 'written in ', el('code', {}, vrs)),
    ),
    switched
      ? el(
          'p',
          { class: 'note-gap' },
          `${switched.title} is not a book of `,
          el('code', {}, switched.from),
          '. Showing it in ',
          el('code', {}, switched.to),
          ' numbering instead.',
        )
      : null,
    alignment.note
      ? el(
          'p',
          { class: 'note-gap' },
          el('b', {}, 'These columns are lined up by verse number, not by correspondence. '),
          alignment.note,
        )
      : null,
    open.length > TOO_MANY - 1
      ? el('p', { class: 'hint gap' }, `Showing the first ${TOO_MANY} versions.`)
      : null,
    table(payload, open),
  );

  linkShared(slot('reading'));

  // The reader uses the full width; the third slot belongs to the other screens.
  fill(slot('compare'));
}

/**
 * Hovering a verse that answers to several rows lights the others.
 *
 * Everything else is CSS — `tbody tr:hover` covers 99.7% of verses, because a row *is* the
 * correspondence and needs no script to say so. This is the remainder: one delegated pair
 * of listeners for the thirty verses in the library that carry more than one.
 *
 * The version this replaces bound two listeners to every verse and queried every verse in
 * the document on each one, which was 186,000 class toggles to drag down one column of
 * Psalm 119.
 */
function linkShared(node) {
  node.addEventListener('mouseover', (event) => {
    const shared = event.target.closest?.('[data-rows]');
    if (!shared) return;
    for (const key of shared.dataset.rows.split('|')) {
      node.querySelector(`tr[data-key="${CSS.escape(key)}"]`)?.classList.add('is-linked');
    }
  });
  node.addEventListener('mouseout', () => {
    for (const row of node.querySelectorAll('tr.is-linked')) row.classList.remove('is-linked');
  });
}
