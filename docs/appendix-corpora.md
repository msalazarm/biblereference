# The appendix books, and what it would take to hold them

*2026-08-22. Marco asked for Enoch, Jubilees, the Odes of Solomon and 4 Ezra in their own
languages, and for the appendix generally to be complete. This is what was found, what is
obtainable, and what stands in the way. Nothing here is imported yet, and the last section
says why.*

---

## What the library holds today

Fourteen appendix books, and the shape of the holding is lopsided:

```
1ES en:13 grc:3 syc:1     2ES en:7  ← no Latin, and Latin is the primary witness
3MA en:8  grc:3 syc:1     4MA en:8  grc:3 syc:1
MAN chu:1 en:13 syc:2     ODA grc:3 syc:1      ← the biblical Odae, not Solomon's
PS2 en:5  syc:1           PSS en:1  grc:3 syc:1
BLT/DNT/JDB/SST/TBS grc:2                       EZA syc:1
ENO, JUB, JSA: registered book codes, zero verses
```

**The library holds no Latin appendix book of any kind** — no 1ES, 2ES, MAN, PS2, PSS or ODA
in `la`.

---

## Two of these are not gaps at all

**`S3Y` is complete and unreachable by name.** The Prayer of Azariah is held in seven corpora
— it is simply printed inside Daniel 3, exactly as the Greek prints it. `swete-daniel DAN 3:52`
is *Εὐλογητὸς εἶ, Κύριε ὁ θεὸς τῶν πατέρων ἡμῶν*, the *Benedictus es*. `canon.py:668` already
declares `"S3Y": "Daniel 3:24-90"` — but that is a *title* map, not a resolution bridge, and
`lxx.json` declares no `S3Y` because in the Greek scheme it is not a book. Nothing is missing
except the bridge that would resolve a citation of S3Y into Daniel 3 for grc, la, chu, cop and
syc.

**`PS2` is a book-code fault costing three languages.** Psalm 151 is held **nine times** — as
`PSA 151` in `rahlfs`, `rahlfs-cc`, `swete`, `sahot` (Coptic), `chuelz` (Slavonic) and four
English LXX translations. `resolve_book("Psalm 151")` returns `PS2`, which reaches English and
Syriac only. The Greek, Coptic and Slavonic Psalm 151 are invisible by name. The two sets are
disjoint, so this is a clean split rather than a duplication.

A second, separate fault sits beside it: all four schemes declare `PS2` as one chapter of
seven verses, and `peshitta-alt` stores `PS2` chapters 2-5 — 58 verses — outside that bound.

**`JSA` is probably a phantom.** Joshua A is Rahlfs' Alexandrinus column, printed against
Vaticanus for the place-name lists in Joshua 15/18/19 — not a freestanding book. `lxx.json`
nonetheless declares it as a full 24-chapter Joshua, which is the Paratext standard cloning
the shape of `JOS`. Swete's own versification file carries **zero** `Jsa` references.

---

## 1 Enoch — the text is already on this machine

`~/.local/share/biblereference/sources/swete/2026-08-05/` carries **`1En`, 353 verse
references, 247 of them non-empty**, and `corpora/swete.py` skips it.

Measured from the file: chapters 1-32 (4 an empty stub), **89 at 49 verses**, **97 at 5**, and
33-88 and 90-96 present as one-verse stubs. `1En.1:1` = *ΛΟΓΟΣ εὐλογίας Ἑνώχ*; `1En.1:9` is
the verse Jude quotes.

The skip reason said *"outside every canon this library resolves against"*. That stopped being
true — `ENO` is a registered `_APPENDIX` code and `org` declares it. **The live blocker is
narrower: `lxx.json` declares no `ENO`, and Swete is an `lxx` corpus**, so there is nothing to
map it onto. The reason in the file now says that instead.

`org`'s declaration is no help as it stands: 42 chapters, with counts that are a placeholder
rather than a description — chapter 4 at 88 verses, where the text has one.

### Other languages, all verified by fetching

| language | edition | verses | licence, as the file states it |
|---|---|---|---|
| **Ge'ez** | Beta maṣāḥǝft `LIT1340EnochE.xml`, division `EOTCed` | **108 ch / 1,058 v** | `<licence target="creativecommons.org/licenses/by-sa/4.0/">` in the file's own header |
| **Greek** | First1K, Swete vol. 3 (Panopolitanus) | 246 v, ch 1-89 | CC BY-SA 4.0 in `publicationStmt` |
| **Greek** | First1K, Flemming–Radermacher GCS 5 | 235 v, ch 1-32 | CC BY-SA 4.0 |
| **Latin** | First1K, the fragment | 13 v, ch 106 | CC BY-SA 4.0 |
| Aramaic | ETCBC/DSS Text-Fabric | 158 fragments, 869 lines | CC BY-NC 4.0 in every `.tf` header |

All four First1K files parse through this library's own `cts_verses` unmodified — including
the GCS one, where a naive subtype reader returns zero because its verse divisions are
`subtype="section"`. Ours walks nesting.

The Aramaic is **not** verse-addressable: it is `scroll▪fragment▪line`, with no Enoch
chapter:verse anywhere in it. It cannot populate `ENO c:v` and should not be offered as
though it could.

**One source was rejected for cause.** A GitHub repository advertising complete Ge'ez
scripture *"in Ethiopic script"* is, for Enoch and 31 other books including Genesis and
Isaiah, **Latin transliteration with no Ethiopic characters at all**; its per-chapter verse
counts are byte-identical to Beta maṣāḥǝft's across all 108 chapters; it names no source
edition and asserts a personal copyright over the result; and the repository was created and
fully pushed within seven minutes.

---

## 4 Ezra — the cheapest fix was checked and is not available

`latvuc` is eBible's `latVUC`. Its archived zip holds **73 USFM files, no MAN, no 1ES, no
2ES**, and eBible's own catalogue declares `DCbooks 7` — Tobit through 2 Maccabees. The
Clementine Text Project never transcribed the appendix. `novavulgata.py`'s book table is 73
books with no appendix slugs either. **So the Latin appendix is genuinely absent, not merely
unimported.**

**But `vul.json` already expects it.** It declares `2ES` at 16 chapters and 942 verses, with
chapter 7 at 139. Measured against two candidate Latin texts:

* the Clementine appendix on Latin Wikisource matches `vul.json` in **15 of 16 chapters**,
  including the three where `vul` deliberately differs from `eng` because the Latin merges
  what the English splits. Its one gap is chapter 7 at 69 — short by exactly the 70 verses of
  Bensly's missing fragment, 7:36-105;
* the OCP Latin covers chapters 3-14 at 713 of 713, matching chapter for chapter.

**The two together sum to 942 — `vul.json`'s declared total.** The same check on the rest of
the appendix: Latin 3 Esdras matches `vul.json`'s `1ES` in all nine chapters, and the Latin
*Oratio Manasse* is 15 verses, which is what `vul.json` declares for `MAN`.

An independent transcription reproducing this library's own derived versification, quirks
included, is about as good a validation as this kind of data admits.

---

## Why nothing is imported yet

Every text above needs the same thing first, and it is not a fetch: **a versification
declaration that describes the book rather than standing in for one.**

* `ENO` is declared in `org` at 42 chapters with placeholder counts, and not declared in
  `lxx` at all — which is the scheme Swete's Enoch would arrive in.
* `JUB` is declared at 34 chapters. Jubilees has 50.
* `JSA` is declared as a 24-chapter Joshua for a text that is not a book.

Adding or correcting a book in a shipped versification scheme changes how every conversion
resolves, and a mistake there is silent. That is a decision to take deliberately and with
the Ge'ez and Swete shapes in front of you — both of which are recorded above — and not one
to slip in beside a corpus import at four in the morning.

**Infrastructure note, 2026-08-22.** Both local search servers were restarted on the current
library and now advertise `search_options` and accept `gate_first`. **The box at 10.0.0.182 is
a different machine** — this one is 10.0.0.170 — and refuses ssh from here, so it still runs an
older build; churchfathers' sweeps should use `127.0.0.1:8000` until someone with access
updates it. The Greek corpus sweep was restarted clean under `gate_first`, setting 30,797
findings aside into `citation_superseded`, so the language is one measurement rather than two.

**The order that follows from this:**

1. `PS2` → `PSA 151`, and the `S3Y` → Daniel 3 bridge. Both are mapping faults over text
   already held, and both make existing witnesses reachable without fetching anything.
2. `ENO` declared in `lxx` from Swete's own shape, then flip one line in `swete.py`. Greek
   Enoch is already on disk.
3. Ge'ez Enoch from Beta maṣāḥǝft — the only complete text, cleanly licensed.
4. Latin 4 Esdras, where the frame is already declared and independently validated.
5. Jubilees and the Odes of Solomon, which need new book codes as well as new text.
