# biblereference

A Markdown preprocessor for theological writing. You tag scripture references; it emits a
new Markdown file with the actual verse text substituted in — English, plus the Hebrew,
Septuagint Greek, or New Testament Greek behind it.

The point is citation integrity. Hand-copying verses is where errors get in: a mistyped
verse number, a quotation that has drifted from the source, a Masoretic reading silently
standing in for a Septuagint one. Here you tag the reference and the library guarantees
the text.

The Catholic canon is in scope throughout — Tobit, Judith, Wisdom, Sirach, Baruch, the
Letter of Jeremiah, 1–2 Maccabees, and the Greek additions to Esther and Daniel are books,
not an appendix.

## Getting started

```bash
pip install -e .
biblereference sync      # fetch, build and index everything: ~160 MB down, ~600 MB built
biblereference render treatise.md -o treatise.out.md
```

`sync` is the only command a new install needs, and it is the one to run again later: every
step skips what it already has, so an interrupted run resumes where it stopped. Its parts
are still available separately — `fetch` archives the raw files, `build` indexes them into
the database, `index` builds the search index over that.

Any of the fifty local English translations can be the one you quote —
`--english BSB`, or `Config(default_english="BSB")`. The **Berean Standard Bible** is the
strongest public-domain choice: modern English, dedicated to the public domain in 2023, so
no quota applies however much you quote, and it tracks the NIV closely enough to stand in
for it. `--english ASV` remains the default.

`biblereference verify treatise.md` checks every citation and writes nothing — the one to
put in a pre-commit hook. `biblereference doctor` says what is cached, what is built, and
which chapters cannot be converted between numbering systems; `doctor --verify` re-hashes
every archived file against the manifest. `biblereference render --appendix` adds the
passage register.

`biblereference compare latvuc novavulgata` reports how far the two Latin Bibles have
drifted apart, book by book — aligned through the pivot, since they are not numbered
alike, and compared on words so that commas and the j/i spelling shift are not counted as
substance.

## Finding the citation

The inverse of everything above: give it words, get back the verse.

```console
$ biblereference search "I can do all things through Christ who gives me strength"
Philippians 4:13 (100%) -- bsb, msb (indistinguishable here)

$ biblereference scan sermon.txt
{"passage": "JHN 3:16", "similarity": 1.0, "identified": true, "span": [118, 258], …}
```

`search` takes a string; `scan` reads a whole document and emits one JSON record per
quotation, with the character span it occupies, so a transcript can be fed straight into an
analysis pipeline. Both work on half-remembered wording — the matching is on folded word
tokens with Porter stemming behind it, so *loving* still finds *loved*.

Three things it is careful about, because the point of it is counting what gets quoted:

- **It says when it cannot name the translation.** NIV, ESV, NASB and NKJV are most of
  American preaching and none may be lawfully bulk-downloaded. A quotation from one of them
  matches its passage well and matches no held translation closely, and that is reported as
  what it is rather than credited to whichever public-domain text sits nearest.
- **It reports ties as ties.** Many of the fifty-odd English translations render a given
  verse identically; where they do, naming one is invention.
- **It would rather miss than guess.** A match has to be both close and *contiguous* — six
  unbroken words at minimum. Ordinary religious language passes the first test regularly
  and the second almost never, which is what keeps a distribution built from this honest.

## Naming the translation

The thirteen best-selling English Bibles since 1901 are what people actually quote, and
eleven of them are under live copyright — no publisher-sanctioned channel permits a
complete local copy of any. So they are reached the way everything else here is reached:
a chapter at a time, once ever.

`resolve` asks only about passages the search has already found and cannot attribute to one
of those thirteen:

```bash
biblereference scan sermon.txt > found.jsonl          # fast, offline, no network
biblereference resolve found.jsonl --resolve-budget 50 > attributed.jsonl
```

Splitting it in two is the point: the scan runs over thousands of transcripts offline, and
only the passages that need an answer cost a request. `search --resolve` and
`scan --resolve` do it inline for one-offs.

A worked example. A sermon quoting *we all like sheep have gone astray* is found as
Isaiah 53:6 and attributed to the Berean Standard Bible tied with eight World English
variants — true, and not an answer, since none of those is on the list. Resolution checks
the KJV and ASV from disk for nothing, then asks once:

```
resolve: Isaiah 53:6 -> NIV
1 attributed, 0 still unattributed; 1 chapter request(s) spent of 3
```

The whole of Isaiah 53 is now stored, so the next sermon quoting any of it resolves in
0.2 seconds with the network off. That is why it fetches chapters rather than verses: one
request costs the site the same either way.

Three guards, because this is the part that could run away:

- `--resolve-budget N` is a ceiling, not a hint. Thirteen versions at BibleGateway's
  published 15-second crawl delay is over three minutes a passage, and a long sermon holds
  dozens. At the ceiling the run stops and says so.
- Versions are tried in likelihood order and **stop at the first decisive match**, so the
  usual cost is one or two requests rather than thirteen.
- `--offline` resolves only from what is already stored.

The Message is the known gap. It is a paraphrase far enough from the underlying text that
no public-domain translation aligns with it, so a Message quotation is usually never found
in the first place — and resolution can only name the translation for a passage already
found.

## Reading one passage, in a language you name

The other direction from search: you already have the reference, and you want the text.

```bash
$ biblereference passage 'PSA 79:5' --vrs vul --language la
latvuc  PSA 79:5  (vul)
Domine Deus virtutum, quousque irasceris super orationem servi tui?

$ biblereference passage 'PSA 79:5' --vrs nvl --language la
novavulgata  PSA 79:5  (nvl)
Usquequo, Domine? Irasceris in finem? Accendetur velut ignis zelus tuus?
```

Two different psalms, because `vul` and `nvl` number the Psalter differently. `--vrs` is
required for that reason: there is no numbering it would be safe to assume.

```python
from biblereference import PassageReader
from biblereference.store import DataHome

with PassageReader(DataHome()) as reader:  # open once; reuse
    found = reader.resolve("DAN 10:11", vrs="vul", language="grc")

found.corpus  # 'swete-daniel'  -- which text answered
found.reference  # (DAN 10:11,)    -- the number to check it by
found.text  # 'καὶ εἶπεν πρὸς μέ Δανιήλ, ἀνὴρ ἐπιθυμιῶν…'
```

**It will not cross language.** Candidates come only from corpora in the language asked
for, so a Greek question is never answered with an English verse — a failure mode that
cost one consumer 275 confirmed findings before this existed. Where nothing can answer,
`found` is falsy and `found.reason` says which kind of nothing: `book-not-held`,
`verse-not-held`, `out-of-range`, `unconvertible`, `no-corpus`.

Corpora needing no conversion are tried first, since a text numbered as the reference is
numbered cannot be renumbered wrongly; `PREFERRED` orders the rest, and `corpora=[…]`
overrides both. The answer always names the corpus that gave it, because "the model was
shown Swete" and "the model was shown the Old Greek" are different pieces of evidence —
for Daniel 10:11 they are different texts.

## Usage

```python
from biblereference import Config, Renderer

r = Renderer(Config(default_english="ASV"))
r.render_file("treatise.md", "treatise.out.md")
```

Three tag forms. The short one keeps a sentence readable and quotes English only:

```markdown
As it says in {{Luke 2:42}}, the child was already about his Father's business.
```

The bracketed form carries a few options; a fenced ` ```passage ` block takes YAML when
they outgrow a line:

```markdown
[passage="Isa 7:14" original="hebrew,lxx"]
```

````markdown
```passage
ref: Dan 3:24-90
vrs: vul
original: [lxx]
```
````

`original=` takes `auto` (Hebrew for the Hebrew canon, Greek for the New Testament, the
Septuagint for the deuterocanon), or any of `hebrew`, `lxx`, `greek`, `theodotion`,
`latin`, `nova`, `none`, or a list. Latin is never automatic: the Vulgate is a
translation, and setting it beside the originals is a choice about what you are arguing.

## Appendices

`Config(appendix=True)` adds **Appendix Y**, every passage the work cites, merged and
printed whole — cite 1 Timothy 2:7, then 2:4, then 2:1-6 and the register shows
1 Timothy 2:1-7 once, in every language available, with a line saying where to find it in
other numbering and naming traditions.

**Appendix Z** is on by default: the copyright notices assembled from what was actually
quoted, plus a check against each publisher's stated limit. The units differ — the
National Council of Churches permits 500 *verses*, the Confraternity of Christian Doctrine
5,000 *words* — and over the limit the note says so and recommends the Berean Standard
Bible, which went public domain in 2023. `--strict` makes it a failing exit code.

## Texts

Fetched once and then archived. Most are public domain or ask only for a credit line; a
few are not, and `doctor` says which — see [What the licences oblige](#what-the-licences-oblige).

| | Source | Note |
|---|---|---|
| Hebrew | Westminster Leningrad Codex, via [OSHB](https://github.com/openscriptures/morphhb) | text public domain; morphology CC BY 4.0 |
| Septuagint | [Swete 1930](https://github.com/eliranwong/LXX-Swete-1930) | the whole deuterocanon; Theodotion for Daniel, Susanna and Bel |
| Greek NT | [Nestle 1904](https://github.com/biblicalhumanities/Nestle1904) | public domain |
| English | 50 translations from [eBible.org](https://ebible.org) — Berean Standard, ASV, KJV, NET, Young's, Geneva 1599, Brenton's Septuagint… | every one flagged redistributable there: 32 public domain, 18 by the holder's permission |
| English | ASV, KJV and more via [pythonbible](https://github.com/avendesora/pythonbible) | public domain; the fallback where a translation is not built |
| English deuterocanon | [WEB Catholic Edition](https://ebible.org/find/details.php?id=eng-web-c) | translated from the Greek, so numbered like the Greek |
| English of the Vulgate | [Douay-Rheims 1899](https://ebible.org/find/details.php?id=engDRA) | for citations written in Vulgate numbering |
| Latin | [Clementine Vulgate](https://ebible.org/find/details.php?id=latVUC) | Jerome as the Church received him; public domain |
| Latin | [Nova Vulgata](https://www.vatican.va/archive/bible/nova_vulgata/documents/nova-vulgata_index_lt.html) | the official text since 1979, complete and in its own numbering; © Libreria Editrice Vaticana |
| Latin | Castellio 1551, via [Corpus Corporum](https://mlat.uzh.ch) | translated from the originals owing nothing to Jerome; Genesis and the Gospels only |
| **Syriac** | Peshitta Old Testament (ETCBC) and New Testament, via [PTA](https://github.com/PatristicTextArchive/pta_data) | a complete Syriac Bible; the Old Testament is **CC BY-NC** |
| Septuagint | [Rahlfs 1935](https://github.com/PatristicTextArchive/pta_data), twice — PTA and Corpus Corporum | the standard critical text, in two independent transcriptions that agree on 96% of verses |
| Greek NT | [SBLGNT](https://github.com/PatristicTextArchive/pta_data) and [Westcott–Hort](https://github.com/PerseusDL/canonical-greekLit) | three Greek New Testaments now, so a variant is visible rather than merely arguable |
| **Old Latin** | Codices Vercellensis and Veronensis, via [Corpus Corporum](https://mlat.uzh.ch) | the gospels *before* Jerome, from the two of Migne's four manuscripts that carry verse numbers; the holes in them are kept rather than closed |
| **Coptic** | Mark 1 in Sahidic, via [First1KGreek](https://github.com/OpenGreekAndLatin/First1KGreek) | 45 verses; the seed of a language, not a coverage |
| English of the LXX | Ottley's Isaiah 1904, via First1KGreek | the Septuagint *as one manuscript has it*, which Brenton is not |
| Versification | [Copenhagen Alliance](https://github.com/Copenhagen-Alliance/versification-specification) | org / eng / lxx / vul maps |

NA28 and the BHS apparatus are under copyright and cannot be included. What you get instead
are the public-domain and freely-licensed critical editions above: Nestle 1904 (61 words
from NA28 across the whole New Testament), the SBL Greek New Testament, Westcott–Hort, the
Leningrad Codex that BHS itself prints, and both Swete's Vaticanus-based Septuagint and
Rahlfs. Defensible, and no longer only the diplomatic editions — but still not NA28.

### What the licences oblige

Most of the library is public domain or asks only for a credit line, which the renderer
already prints. Six corpora are not, and `biblereference doctor` says which:

    3 corpus/corpora may not be used commercially.
    4 carry share-alike terms; keep derived work separable.

The licence is read **per file**, never per repository, because it genuinely varies inside
one: the Patristic Text Archive publishes the Peshitta Old Testament under CC BY-NC and the
New Testament beside it under CC BY. Where a file's declared licence is not the edition's
own terms — its Greek New Testament says CC BY 4.0 and the text is the SBLGNT, whose terms
are not CC BY — the stricter of the two governs, because the other direction tells you that
you may do something you may not.

## Copyrighted translations

Set `default_english` (or a tag's `en=`) to `NRSVCE`, `NABRE`, `RSV2CE`, `RSVCE`, `GNTCE`,
`NCB`, `NASB` or `NASB1995` and they are fetched a chapter at a time from BibleGateway.
Naming one is the opt-in; nothing reaches the network otherwise.

These are the translations that cannot be held offline, so this is the only way to cite
them — and chapters cached this way join the search index like any other, meaning coverage
grows as you use them. They are never swept in bulk.

**Whole chapters, once.** Citing a single verse pulls the chapter around it — one request
costs the site the same either way, and the rest of that chapter is very likely what you
cite next. Every verse of it is then kept twice over: the page in `sources/`, the parsed
verses in the same database as every other corpus. So a chapter is requested **once, ever**,
and later citations from anywhere in it are free. A citation spanning several chapters is
batched into a single request (up to `max_chapters`, default 5).

Requests are serial with a 15-second gap, which is what BibleGateway's `robots.txt`
publishes as its `Crawl-delay`. Keep it that way: their terms do not contemplate systematic
downloading, and staying small is how this stays within them. Fetching a whole chapter at a
time is what makes the wait affordable — you pay it once per chapter, ever.

The text remains under its publisher's copyright, and the renderer emits their notice
automatically. Drafting privately is one thing; a published treatise quoting at length
needs permission above the publisher's stated limit. The public-domain path — ASV with the
WEB Catholic Edition, or the Douay-Rheims throughout — has no such ceiling.

Set `Config(online=False)` to guarantee no network use, or `offline=True` to serve only
what is already archived.

## What it refuses to do

Where the data cannot support an honest answer, resolution fails and says why rather than
producing a plausible wrong verse:

- The Vulgate's Sirach, Tobit and Judith come from source texts differing from the Greek
  by whole clauses (Vulgate Sirach runs 1605 verses to the Greek's 1401), and no mapping
  exists. Cite them in Vulgate numbering and quote them from the Douay-Rheims.
- Greek Sirach manuscripts transpose 30:25–33:16a with 33:16b–36:13a, so those chapters
  refuse conversion — and only those. Sirach 24 converts fine.
- The Septuagint's own interleaved Esther numbering is unusable upstream, and no fetched
  corpus carries the additions in Greek. The A–F letter chapters resolve against the
  Douay-Rheims instead; see `esther_additions.json`.
- The Nova Vulgata numbers seventy-one chapters differently from the original-language
  frame, so those cannot be cross-referenced to it. The text is stored complete and is
  citable in its own numbering (`vrs=nvl`) — the edition is not bent to fit another.

Every such refusal, and every correction applied to the upstream versification data, is
recorded with its reasoning in
`src/biblereference/versification/data/corrections.json`.

## Running it as a server

`biblereference serve` puts the whole library behind HTTP: a reader to browse it with, a
JSON API, and a job queue for the walks that take minutes. Standard library only — no
framework, no build step, no extra dependency, and nothing fetched from the network at run
time.

```bash
venv/bin/biblereference serve                  # http://localhost:8000, local only
```

### Setting it up on a fresh Ubuntu box

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone <your-remote> biblereference && cd biblereference
python3 -m venv venv && venv/bin/pip install -e .

venv/bin/biblereference sync         # ~160 MB down, ~600 MB built, once
venv/bin/biblereference serve --host 0.0.0.0 --token "$(openssl rand -hex 24)"
```

`sync` is the long step and the only one that needs the network. If you already have the
corpus on another machine, copy `$data_home/sources/` across and run `biblereference build`
instead — it rebuilds an identical database offline, and `doctor --verify` re-hashes every
file against the manifest so a truncated copy is caught.

To keep it running after you log out:

```bash
sudo tee /etc/systemd/system/biblereference.service >/dev/null <<EOF
[Unit]
Description=biblereference server
After=network.target

[Service]
User=$USER
WorkingDirectory=$PWD
Environment=BIBLEREFERENCE_TOKEN=$(openssl rand -hex 24)
ExecStart=$PWD/venv/bin/biblereference serve --host 0.0.0.0
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now biblereference
systemctl status biblereference          # the token is in the unit file
```

**It binds to `127.0.0.1` unless you say otherwise, and it warns if you open it to the
network without a token.** There is no user model and no rate limiting: anyone who can
reach the port can run jobs on that machine. Put it on a trusted network or behind a
tunnel, not on the open internet.

The token works three ways, and the third is what makes the reader usable. A header is
what a script sends; `?token=` is how you arrive from a link; and arriving that way sets a
`SameSite=Strict; HttpOnly` cookie, because a `<link>` cannot carry an `Authorization`
header and a page whose own stylesheet 401'd would look broken rather than unauthorised.
`curl "$BR/api/search?token=…"` is unaffected.

`--data-home` applies to the job workers as well as to the reads: they are spawned and
build their own `DataHome` from the environment, so the environment is what carries it.

### The reader

`GET /` is four screens, routed on the URL fragment — which the browser never sends, so a
deep link needs nothing configured at either end.

**Read** — pick a book from a dropdown grouped into the four parts of the canon, a chapter
from a grid, the version you read in, and any number of versions to set beside it. They
appear as **aligned columns**: one row per verse of the passage, every version's answer to
it on that row.

> **The rows are keyed on the pivot verse, not on verse numbers**, because verse numbers are
> exactly what disagrees on the passages worth comparing. The Douay's Matthew 17:14 carries
> what the Greek numbers 14 *and* 15, so it occupies both rows — marked ↕, the second muted —
> and every Douay verse after it sits one row behind its own number. Hovering a row is the
> correspondence; nothing has to be guessed from numbering.

Four things the table will not pretend about. A verse two editions both print but the pivot
divides differently gets **both** verses in one cell, stacked. A verse **no** open version
prints still gets its row, rather than the table silently renumbering. Where an edition
carries a passage somewhere else entirely — the Septuagint moves the tabernacle account from
Exodus 36 to 39 — those rows are kept and captioned rather than dropped. And where a chapter
cannot be converted at all (Acts 19 in the English numbering; most of the Vulgate's Sirach),
a banner says so in the versification's own words, because columns lined up by shared
numbering look exactly like columns lined up by correspondence.

**Numbering** — `#/numbering/MAT/17:14?vrs=vul`. Exact beside covering, differing rows
highlighted, and a third column saying **why**: the refusal in its own words where a system
has no place for the verse, or the recorded reason where the mapping was corrected by hand.
The five worth starting with are `Matt 17:14` in `vul`, `Bar 6:43` in `eng`, `1Sam 20:42`
in `eng`, `Mal 3:22` in `org` and `Matt 5:4` in `vul` — each is a different way for two
traditions to disagree, and each now explains itself.

**Search** — paste a quotation. The answer names the passage *and* which edition's wording
it matches, so a patristic quotation agreeing with the Douay at 94% and the King James at
71% tells you which Bible the author had. Give the year the document was written and any
edition whose wording postdates it is struck through.

**Library** — the sixty-six editions as a filterable table: language, numbering, verses,
the year the wording appeared, and what its licence obliges. Beside it, the families
derived from where the chapter divisions actually fall, which is not always what a corpus
declares.

Type either a reference or a quotation in the one box; the server decides which it is. If
you type something that means different books in different traditions — "1 Kings" is
1 Samuel to a Douay reader — it asks rather than guessing.

`/` needs JavaScript. **`GET /plain` does the same in one round trip without it**, and is
linked from the header and the footer.

#### Fonts

None are fetched — this works with the network off, and the good Hebrew, Syriac and Coptic
faces are not ours to redistribute. The page names deep local stacks per language instead.
Worth installing if you read in them:

| | |
|---|---|
| Hebrew | *SBL Hebrew* (the Leningrad Codex carries niqqud **and** te'amim; most stacks collide them) |
| Syriac | *Noto Sans Syriac*, or *Estrangelo Edessa* |
| Greek | *Gentium Plus* or *New Athena Unicode* — polytonic, so a stack without it renders every breathing as tofu |
| Coptic | *Antinoou* |

### The API

```bash
export BR=http://bigbox.local:8000 TOKEN=...
curl -H "Authorization: Bearer $TOKEN" "$BR/api/health"
```

| | |
|---|---|
| `GET /api/health` | corpora count, versification fingerprint, cores, jobs running |
| `GET /api/corpora` | every built corpus, with language and versification |
| `GET /api/library` | every corpus in full: books, canon, date, licence, totals |
| `GET /api/families` | versification families derived from where the chapter ends fall |
| `GET /api/books` | `?vrs=eng&naming=dr` — every book, grouped, with its chapter shape |
| `GET /api/reader` | `?book=&chapter=&corpus=&covering=` — a chapter across versions, plus `rows`: one per verse of the passage, keyed on the pivot, each cell an index into that version's verses |
| `GET /api/parse` | `?q=` — is this a reference or is it prose? **always 200**; it is a predicate |
| `GET /api/alignment` | `?ref=&vrs=&to=` — exact beside covering, and why each is what it is |
| `GET /api/corrections` | `?system=&book=&chapter=&verse=&kind=` — the recorded reasons, browsable |
| `GET /api/convert` | `?ref=Matt+17:14&from=vul&covering=1` — that reference in every system |
| `GET /api/passage` | `?ref=&vrs=eng&covering=1` — the text in every corpus, or `&corpus=dra` for one |
| `POST /api/search` | body is the quotation; returns the passage and which translation it came from |
| `POST /api/scan` | body is a *document*; finds the quotations inside it and where each one sits |

`/api/reader` loads only the versions you name and answers for the rest from a cached
inventory with no queries at all. That is not an optimisation: Psalm 119 in every version
holding it is 1.5 MB, so the reader warns past six columns and refuses past twelve. Its
`rows` carry *indices* rather than text, so a verse answering to three rows crosses the wire
once.

Two hundred corrections to the upstream versification data each carry a written reason, and
until recently the loader consumed them and threw them away. `/api/corrections` and the
`why` column of `/api/alignment` are where they surface.

`search` must be handed a quotation; `scan` finds them. Its spans are character offsets
into the body exactly as posted, so a caller can point back at its own text.

Both take `Searcher`'s scoring parameters and filters over the wire — `quotation`,
`coverage`, `identified`, `min_query`, `min_run`, and `languages` / `corpora` / `families`,
repeatable or comma-separated:

```bash
curl -X POST --data-binary @passage.txt \
  "$BR/api/scan?languages=grc&coverage=0.5&min_run=scaled:4"
```

`min_run=scaled:4` is `ScaledRun(4)` — `max(4, min(6, n // 2))`, proportional with a floor.
A plain integer keeps the fixed behaviour, and is *not* an approximation of the scaled
form: it is looser for every query over eight words.

**A parameter that cannot be honoured is refused, never ignored.** An unknown name, an
unreadable value, a fraction outside 0–1, a language this machine does not hold: all 400.
Silently ignoring one is how a caller comes to believe it configured something it did not,
and the answer looks like a genuine absence of matches with nothing to tell them apart.

Every `search`, `scan` and job response carries the library that produced it:

```json
"library": {"versification": "5c51d940…", "digest": "17a03466…", "code": "0.1.0"}
```

A mapping correction is an edit to a JSON file, not a version bump, so a caller recording
only a version would not notice one.

The whole-corpus walks take minutes and would time out on a held-open socket, so they are
submitted as jobs and polled. They run in separate processes, which is what the extra cores
buy you: several at once, and none of them sharing a SQLite connection with the server.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" "$BR/api/jobs?task=coverage"
# {"id": "coverage-1", "state": "running", ...}

curl -H "Authorization: Bearer $TOKEN" "$BR/api/jobs/coverage-1"
# {"state": "done", "seconds": 71.5, "result": {...}}
```

`task=coverage` walks all 155,578 conversions; `task=audit` checks every family pair
against its witnesses (`&book=JON` for one book); `task=compare` diffs two editions
(`&left=latvuc&right=novavulgata`). All take `&covering=1`. `GET /api/jobs` lists
everything submitted since the server started.

`task=scan` is the one that repays the cores. Post a JSON array of `{"id", "text"}` and it
is spread across the pool rather than run as one call, with progress in the poll response
because a job of that size is otherwise a black box:

```bash
curl -X POST -H "Content-Type: application/json" --data @corpus.json \
  "$BR/api/jobs?task=scan&languages=grc&coverage=0.5"
# {"id": "scan-1", "total": 43815}
# {"state": "running", "done": 8123, "total": 43815}
# {"state": "done", "result": {"found": {"<id>": [...]}, "failed": {}}}
```

Results are keyed by the id you gave each document, so a partial failure cannot shift
them. One unreadable document is named in `failed` and the rest still arrive — forty
thousand passages is too many to resubmit because one was malformed. Measured on 60
documents over 12 cores: 159s one at a time, 24s as a batch, byte-identical results.

### Where the cores actually go

Scanning is pure-Python string comparison and holds the GIL throughout, so work done on a
request thread gets one core's worth of throughput however many requests arrive at once.
Every search and scan therefore runs in a worker process, not on the serving thread. Eight
concurrent scans now finish in 1.36× the time of one rather than eight times it.

**One pool, and `--cores` is the only number** — every request draws on the same workers,
whether it is a search, a scan or a batch job. It was two pools for a while, which sounds
prudent and is not: two pools that cannot lend to each other strand whichever is idle. An
operator who said `--workers 28` on a 32-thread machine got four, because that flag sized
the pool he was not using; and when the split was evened up he got half the machine, and
both arms of his throughput measurement plateaued at the same number — which looked like a
shared bottleneck and was two halves of equal size.

What the split was protecting is real: a batch occupies every worker for hours and a reader
must not wait behind it. That is kept by bounding the batch *chunk* instead, so a request
arriving mid-sweep waits behind at most one chunk per worker — seconds — rather than behind
the sweep. `--workers` and `--interactive-workers` are still accepted and now both mean
`--cores`.

## Data home

Everything fetched is archived under `$data_home` (default: platform data dir), raw bytes
and all, alongside a manifest recording URL, checksum, and license:

```
$data_home/sources/     raw downloads, kept forever, dated      ~150 MB
$data_home/db/          built SQLite index and search index     ~600 MB
```

Back up that one directory and you own your corpus, independent of whether any upstream
repository still exists. Only `sources/` needs backing up: `db/` is derived, and
`biblereference build` reconstructs it from the archive without touching the network.
Copying `sources/` to another machine and rebuilding there gives an identical database —
verified, not assumed, and `doctor --verify` re-hashes every archived file against the
manifest so a truncated copy is caught before it becomes a wrong verse.

Point `$BIBLEREFERENCE_HOME` at a synced or backed-up directory to carry the corpus
between machines.

### Making a second machine identical to the first

```bash
biblereference mirror http://bigbox.local:8000        # --token if the server has one
```

Copies the other machine's whole archive, verifies every file against the checksum *that*
machine recorded before writing it, then rebuilds and reindexes. 155 MB and about four
minutes, most of it the rebuild.

Use this rather than `sync` whenever two machines must match. `sync` cannot promise it:
it downloads from a dozen upstreams and upstream is free to publish something different
between one machine's run and the other's. That is not hypothetical — two machines here,
synced two days apart, disagreed about `asvbt` and `tcent` because eBible had republished
both in between. Mirroring is the only way to be sure.

It is safe to interrupt and re-run: a file already held with the right checksum is never
fetched again, and one that has gone bad on disk is replaced. It will also adopt a
`sources/` directory you copied by other means — rsync, a USB disk — recognising the files
by hash and recording them rather than transferring them again.

Transfers are keyed on content rather than on where a file sits. Archive paths carry the
date a file was fetched, so two machines that synced on different days hold *everything*
under a different path while almost all of the bytes are identical — mirroring by path
alone moved 155 MB to change two files the first time this ran. Anything already held
under any path is copied from disk instead, which took the same job to 4.1 MB and half a
second.

Disk is what it does spend. The archive is append-only, so a mirror landing on new dates
adds a second copy rather than replacing the first; the old files stay, which is what
keeps any earlier build reproducible.

Only `sources/` crosses the wire. The database is derived, so rebuilding locally is both
quicker than moving 600 MB and a stronger check: if the same bytes build into a different
database, that is worth knowing rather than papering over.

### Are two machines holding the same library?

`biblereference doctor` ends with a digest. Run it on both and compare the last line:

```
library digest -- run this on both machines and compare the last line:
  sources        5ea7ec38362680fd  57 registered source(s)
  texts          1e78d328b31bb0a5  1,518,339 verses built from them
  versification  845aefeb77339b2c  vendored data and corrections
  code           0.1.0
= library        31adb664f7d33a2ffe95e9b798808ff5d5c4bae64f17a07c3a17ff7d730feb92
```

Four parts, because when two machines disagree the useful question is immediately *which*
part disagrees. `sources` is a hash of the checksums the manifest already recorded, so
nothing is re-read from disk. `texts` walks the verse table — about three seconds for a
full sync — and catches what the sources cannot: a half-finished build or a corrupted
page.

Three things it deliberately ignores, because otherwise machines that are identical *as
far as syncing goes* would disagree:

- **When a source was fetched, and how often.** The manifest records a dated path and a
  timestamp per download; only the newest checksum per source is hashed.
- **Sources the code no longer registers.** An archive is never deleted, so a machine that
  once fetched something since dropped from the list keeps it forever. Counting it would
  mean that machine could never again match a fresh install.
- **Chapters `resolve` fetched from a publisher's site.** Real content, in no manifest, and
  per-machine by nature — it accumulates wherever the resolving is run.

The last two are reported underneath as asides, so you can see them without their moving
the number.

Over the API: `GET /api/digest`. When two machines *do* disagree, `GET /api/sources` gives
the per-source checksums, which is how you find the file responsible rather than guessing.

## License

MIT for the code. The texts carry their own terms — see `source_meta` in the built
database, and the attribution block the renderer emits.
