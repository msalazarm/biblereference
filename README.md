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
which chapters cannot be converted between numbering systems.

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
`none`, or a list.

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
| Versification | [Copenhagen Alliance](https://github.com/Copenhagen-Alliance/versification-specification) | org / eng / lxx / vul maps |

NA28, the BHS apparatus, and Rahlfs-Hanhart are under copyright and cannot be included.
What you get instead are the public-domain diplomatic editions above: Nestle 1904 (61 words
from NA28 across the whole New Testament), the Leningrad Codex that BHS itself prints, and
Swete's Vaticanus-based Septuagint. Defensible, but not the modern eclectic editions —
worth knowing before citing.

Copyrighted English translations (NRSVCE, NABRE, RSV-2CE…) are reachable through an
opt-in online provider. That text stays under its publisher's copyright; private drafting
is one thing, publishing extensive quotation needs permission.

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
