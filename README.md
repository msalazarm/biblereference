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

Public domain or freely licensed, fetched once and then archived:

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
| Versification | [Copenhagen Alliance](https://github.com/Copenhagen-Alliance/versification-specification) | org / eng / lxx / vul maps |

NA28, the BHS apparatus, and Rahlfs-Hanhart are under copyright and cannot be included.
What you get instead are the public-domain diplomatic editions above: Nestle 1904 (61 words
from NA28 across the whole New Testament), the Leningrad Codex that BHS itself prints, and
Swete's Vaticanus-based Septuagint. Defensible, but not the modern eclectic editions —
worth knowing before citing.

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

`tools/serve.py` puts the whole library behind HTTP, so the corpus and the slow work can
live on one machine and be used from another. Standard library only — no framework, no
extra dependency.

### Setting it up on a fresh Ubuntu box

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone <your-remote> biblereference && cd biblereference
python3 -m venv venv && venv/bin/pip install -e .

venv/bin/biblereference sync         # ~160 MB down, ~600 MB built, once
venv/bin/python tools/serve.py --host 0.0.0.0 --token "$(openssl rand -hex 24)"
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
ExecStart=$PWD/venv/bin/python tools/serve.py --host 0.0.0.0
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

### Using it

```bash
export BR=http://bigbox.local:8000 TOKEN=...
curl -H "Authorization: Bearer $TOKEN" "$BR/api/health"
```

`GET /` is the browsing page: type a reference, say which numbering you wrote it in, and
see how every system numbers it — exact beside covering, differences highlighted — then
the text of every corpus that carries it.

| | |
|---|---|
| `GET /api/health` | corpora count, versification fingerprint, cores, jobs running |
| `GET /api/corpora` | every built corpus, with language and versification |
| `GET /api/convert` | `?ref=Matt+17:14&from=vul&covering=1` — that reference in every system |
| `GET /api/passage` | `?ref=&vrs=eng&covering=1` — the text in every corpus, or `&corpus=dra` for one |
| `POST /api/search` | body is the quotation; returns the passage and which translation it came from |

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

### Are two machines holding the same library?

`biblereference doctor` ends with a digest. Run it on both and compare the last line:

```
library digest -- run this on both machines and compare the last line:
  sources        ab853964752816f7  57 source(s), newest fetch of each
  texts          edac3672be0ff8bb  1,396,953 verses
  versification  5c51d940ca700cbc  vendored data and corrections
  code           0.1.0
= library        d376bf27ac111b586cbc5c3d79e8b92ed6001872399bce7178a467070e2c8cc3
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
