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
biblereference fetch     # download the texts into your archive (~45 MB)
biblereference build     # index them; from here on, everything works offline
biblereference render treatise.md -o treatise.out.md
```

`biblereference verify treatise.md` checks every citation and writes nothing — the one to
put in a pre-commit hook. `biblereference doctor` says what is cached, what is built, and
which chapters cannot be converted between numbering systems. `biblereference render
--appendix` adds the passage register.

`biblereference compare latvuc novavulgata` reports how far the two Latin Bibles have
drifted apart, book by book — aligned through the pivot, since they are not numbered
alike, and compared on words so that commas and the j/i spelling shift are not counted as
substance.

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
| English | ASV, KJV and two dozen more via [pythonbible](https://github.com/avendesora/pythonbible) | public domain |
| English deuterocanon | [WEB Catholic Edition](https://ebible.org/find/details.php?id=eng-web-c) | translated from the Greek, so numbered like the Greek |
| English of the Vulgate | [Douay-Rheims 1899](https://ebible.org/find/details.php?id=engDRA) | for citations written in Vulgate numbering |
| Latin | [Clementine Vulgate](https://ebible.org/find/details.php?id=latVUC) | Jerome as the Church received him; public domain |
| Latin | [Nova Vulgata](https://www.vatican.va/archive/bible/nova_vulgata/documents/nova-vulgata_index_lt.html) | the 1979 revision; © Libreria Editrice Vaticana |
| Versification | [Copenhagen Alliance](https://github.com/Copenhagen-Alliance/versification-specification) | org / eng / lxx / vul maps |

NA28, the BHS apparatus, and Rahlfs-Hanhart are under copyright and cannot be included.
What you get instead are the public-domain diplomatic editions above: Nestle 1904 (61 words
from NA28 across the whole New Testament), the Leningrad Codex that BHS itself prints, and
Swete's Vaticanus-based Septuagint. Defensible, but not the modern eclectic editions —
worth knowing before citing.

## Copyrighted translations

Set `default_english` (or a tag's `en=`) to `NRSVCE`, `NABRE`, `RSV2CE`, `RSVCE`, `GNTCE`
or `NCB` and they are fetched a chapter at a time from BibleGateway. Naming one is the
opt-in; nothing reaches the network otherwise.

**Whole chapters, once.** Citing a single verse pulls the chapter around it — one request
costs the site the same either way, and the rest of that chapter is very likely what you
cite next. Every verse of it is then kept twice over: the page in `sources/`, the parsed
verses in the same database as every other corpus. So a chapter is requested **once, ever**,
and later citations from anywhere in it are free. A citation spanning several chapters is
batched into a single request (up to `max_chapters`, default 5).

Requests are serial with a 2-second gap. Keep it that way: BibleGateway's terms do not
contemplate systematic downloading, and staying small is how this stays within them.

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

Every such refusal, and every correction applied to the upstream versification data, is
recorded with its reasoning in
`src/biblereference/versification/data/corrections.json`.

## Data home

Everything fetched is archived under `$data_home` (default: platform data dir), raw bytes
and all, alongside a manifest recording URL, checksum, and license:

```
$data_home/sources/     raw downloads, kept forever, dated
$data_home/db/          built SQLite index, regenerable offline from sources/
```

Back up that one directory and you own your corpus, independent of whether any upstream
repository still exists.

## License

MIT for the code. The texts carry their own terms — see `source_meta` in the built
database, and the attribution block the renderer emits.
