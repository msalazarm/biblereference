# The versification families, derived

Every audit in this project used to begin by trusting the seven systems the vendored data
declares, filing each corpus under one, and checking the mappings from there. The filing
step was never verified and it was wrong often enough to invalidate the results — an
eleven-hour sweep spent itself measuring its own witnesses. This document records what
happens when the families are derived from the editions instead.

Reproduce with `biblereference families` (add `--json` for the whole derivation).

## The rule, and what it costs

A corpus belongs to a family only when its structure is **exact** to every other member:
same verse count in every chapter both hold complete. That is stricter than the vendored
data, and the first thing it finds is that the single declared English family is **eleven
separate numberings**.

**The signature is taken over complete chapters only** — verses 1..*n* with no gaps. Judging
on the highest *printed* verse instead measures how much an edition left out rather than how
it numbers; it scored a Scripture portion at 42% agreement and read as a catastrophic
misfile when the edition was simply a selection.

## There is no canonical partition

This is the part worth stating plainly, because it constrains what any answer here can
claim. Compatibility — agreeing on every chapter two corpora share — is reflexive and
symmetric but **not transitive**, so it induces no equivalence classes.

The counterexample is concrete. The King James and the Revised Version differ on exactly two
chapters: **2 Esdras 7** (70 verses against 140 — the famous missing fragment) and
**Sirach 23**. Every Protestant-canon Bible has neither book, so it agrees perfectly with
both and chains them together.

Three constructions that would be canonical were tried and all fail:

| construction | result |
|---|---|
| signature refinement | splits `kjv` from `kjvcpb`, which agree on all 1,356 chapters they share — neither's coverage contains the other's |
| maximal cliques | 29 of 55 corpora land in more than one, and the largest cliques have no member unique to them |
| chain growth in random order | 15–20 families depending on order; matched the coverage-ordered answer **1 time in 200** |

So the derivation states a rule rather than pretending to discover a partition: **families
are grown in descending order of coverage**, so complete Bibles found them and partial
editions join. Under that rule the answer is deterministic — shuffling corpora of *equal*
coverage reproduced the identical partition in 200 of 200 trials, which is pinned by
`tests/test_families.py`. Alongside it, a canonical compatibility report says which families
each corpus could belong to, independent of any ordering. Where that list holds more than
one name, the partition made a choice and the choice is visible.

## The twenty families

| family | members | chapters | declared as |
|---|---|---|---|
| `web` | `web`, `webbe`, `webc`, `webp`, `webpb`, `webu`, `wmb`, `wmbb` | 1382 | eng |
| `lsv` | `lsv`, `oebcw`, `oebus`, `ulb` | 1189 | eng |
| `kjv` | `kjv`, `kjvcpb` | 1362 | eng |
| `wyc2017` | `wyc2017`, `wyc2018` | 1345 | eng |
| `ojb` | `ojb`, `oke` | 1189 | org |
| `lxx2012` | `lxx2012`, `lxx2012uk` | 1043 | lxx |
| `lxxup` | `brenton`, `lxxup` | 1027 | lxx |
| `asvbt` | `asvbt` | 1382 | eng |
| `dra` | `dra` | 1334 | vul |
| `latvuc` | `latvuc` | 1334 | vul |
| `rv` | `rv` | 1331 | eng |
| `novavulgata` | `novavulgata` | 1300 | nvl |
| `gnv` | `gnv` | 1189 | eng |
| `fbv` | `fbv` | 1174 | eng |
| `net` | `net` | 1174 | eng |
| `swete` | `swete` | 1021 | lxx |
| `t4t` | `t4t` | 1020 | eng |
| `wlc` | `wlc` | 929 | org |
| `noy` | `noy` | 737 | eng |
| `wycliffe` | `wycliffe` | 274 | eng |

**35 of 55 corpora are determined** — compatible with exactly one family. No corpus is
assigned to a family it is not compatible with, which `tests/test_families.py` enforces.

## What the declared data got wrong

Four pairs filed under one system are not one numbering, and each had already cost the
project something:

- **`wlc` and `ojb`**, both `org`. The Leningrad Codex is exact to `org` on all 929
  chapters; the OJB is off on ten. Using the OJB as the `org` witness produced thirteen
  findings that dissolved when `wlc` replaced it.
- **`swete` and `brenton`**, both `lxx`. They disagree on 83 chapters, and where they do,
  `lxx` follows Brenton 66 times to 9. Swete is a Greek critical edition following the Greek
  chapter divisions and belongs to no shipped system.
- **`dra` and `latvuc`**, both `vul`. Fourteen chapters apart; `vul` backs the Latin on
  eleven of them.
- **`kjv` and `rv`**, both `eng`, and the pair that proves compatibility is not transitive.

## Which corpora remain undetermined

Sixteen are exact to more than one family, always because those families differ only in
books the corpus does not carry. This is a real limit, not a defect in the method — nothing
in the text can settle it, because the deciding text is absent.

| corpus | chapters | exact to |
|---|---|---|
| `jps`, `lee` | 929, 928 | `asvbt`, `fbv`, `kjv`, `lsv`, `net`, `noy`, `rv`, `web`, `wyc2017` |
| `ourb` | 540 | `asvbt`, `fbv`, `kjv`, `lsv`, `net`, `rv`, `web` |
| `asv`, `bbe`, `bsb`, `dby`, `kjv2006`, `msb`, `webster`, `ylt` | 1174–1189 | `kjv`, `rv` |
| `tnt` | 257 | `kjv`, `rv`, `wycliffe` |
| `emtv`, `f35` | 256–257 | `web`, `wycliffe` |
| `tcent` | 256 | `asvbt`, `wycliffe` |
| `n1904` | 245 | `novavulgata`, `wycliffe` |

The New Testament is 260 chapters and every family here numbers it alike, so a New
Testament edition genuinely agrees with everything. `n1904` is the clearest case: a Greek
New Testament, declared `org`, and unfalsifiable by structure.

Four more hold too few complete chapters to place at all: `e2t`, `glw`, `niv`,
`swete-daniel`.

## Limits

- **`rsc` and `rso` have no corpus.** No family can be derived for them and no textual check
  can reach them; only the structural invariants in `tests/test_alignment.py` apply.
- **A derived family is a claim about the editions held here**, not about the tradition. Two
  corpora agreeing everywhere may still differ in a book neither carries.
- **Equal verse counts do not prove equal verse content.** Two editions can agree on every
  chapter length and still divide a chapter's text differently. Confirming that is a
  separate, textual step.

## Are the families textually real?

Structure is a necessary condition, not a sufficient one: two editions can agree on every
chapter length and still divide a chapter's text differently, which is a worse fault because
nothing structural can see it. So every pair of members of every multi-member family was
compared verse by verse, scoring the mapped position against offsets −2…+2.

**Thirty-one of the thirty-nine pairs are verse-for-verse identical in placement.** The other
eight flag between 13 and 241 verses out of tens of thousands — and every one of them spreads
its flags roughly evenly across all four offsets:

| pair | flagged | offsets |
|---|---|---|
| `lsv` vs `ulb` | 241 of 31,051 | −1:78 −2:56 +1:61 +2:46 |
| `lsv` vs `oebcw` | 195 of 13,870 | −1:69 −2:42 +1:57 +2:27 |
| `ojb` vs `oke` | 63 of 5,841 | −1:25 −2:15 +1:15 +2:8 |
| `brenton` vs `lxxup` | 15 of 28,000 | −1:5 +1:8 +2:2 |

That symmetry is the whole finding. A real displacement piles onto **one** offset — the
Jonah and Bel faults did, for their entire length. Flags scattered in both directions are two
different *translations* of the same verse, where a neighbour occasionally scores higher in
a repetitive passage. Every multi-member family is textually confirmed.

## No corpus follows `lxx` or `vul`

Measured across every corpus against every shipped system, comparing the full verse range
(first verse as well as last, since a Vulgate psalm may be numbered 10–19 rather than 1–10):

| system | corpora exact to it |
|---|---|
| `org` | `wlc` (929 ch), `n1904` (245, New Testament only) |
| `eng` | `lsv` (1189), `ulb` (1170), `jps` (929), `lee` (928), and three more |
| `nvl` | `novavulgata` (1300) |
| `lxx` | **none** — only `n1904`, New Testament only and therefore vacuous |
| `vul` | **none** — the Clementine is off on 7 chapters, the Douay on 15 |
| `rsc`, `rso` | no corpora exist at all |

This is the finding that explains the history. Every audit of `lxx` and `vul` was measuring
the gap between the system and the nearest edition rather than the mapping, and no amount of
care in the comparison could have fixed that.

It also breaks the obvious repair. Picking, per system, the one corpus that *is* that system
does not work: `org` has an exact witness only in Hebrew and Greek, `eng` only in English,
`nvl` only in Latin — so no two faithful witnesses share a language, and a same-language test
could not run on any pair.

**Restricting rather than discarding is what works.** A witness wrong on ten chapters is
right on the other 1,179, and a comparison confined to chapters where *both* sides are
faithful is sound even though neither corpus is faithful throughout. See
`audit.faithful_chapters`. The usable domains are large:

| pair | witnesses | chapters both are faithful on |
|---|---|---|
| `eng`/`vul` | `web`/`dra` | 1,294 |
| `org`/`vul` | `ojb`/`dra` | 1,172 |
| `org`/`eng` | `ojb`/`web` | 1,170 |
| `eng`/`lxx` | `web`/`brenton` | 959 |
| `lxx`/`vul` | `brenton`/`dra` | 920 |

## Deriving the mappings, and what they disagree about

With the witnesses chosen per *pair* — same language first, faithful-chapter restriction on
top — each family pair's mapping was derived from the text alone by monotonic alignment and
then diffed against the vendored data. Isolated disagreements are noise; a **run** of
consecutive verses all displaced the same way is what a versification fault looks like.

| pair | witnesses | agree | rate | runs of 3+ |
|---|---|---|---|---|
| `org`→`eng` | `ojb`/`web` | 30,509 | **99.993%** | **0** |
| `vul`→`nvl` | `latvuc`/`novavulgata` | 31,982 | 99.760% | 12 |
| `org`→`vul` | `ojb`/`dra` | 30,079 | 99.058% | 3 |
| `eng`→`vul` | `web`/`dra` | 32,217 | 98.910% | 11 |
| `eng`→`lxx` | `web`/`brenton` | 23,127 | 98.859% | 25 |
| `org`→`lxx` | `ojb`/`brenton` | 18,840 | 98.747% | 21 |
| `lxx`→`vul` | `brenton`/`dra` | 20,650 | 98.667% | 27 |

**`org`→`eng` is clean.** Not one run of three consecutive displaced verses across 30,509
comparisons. Its two isolated differences are both superscription artifacts of the
instrument, which cannot emit a verse 0 (`PSA 42:1 → PSA 42:0` is a title slot).

### Two instrument limits, stated so they are not read as findings

- **Cross-book mappings.** The Vulgate's Daniel absorbs Susanna, Bel and the Song of the
  Three, which `org` holds as separate books, and a per-book alignment cannot express that.
  250 of the `org`→`vul` differences are this and the data is right in every one:
  `vul DAN 3:24 → S3Y 1:1`, `DAN 13:1 → SUS 1:1`, `DAN 14:1 → BEL 1:2`.
- **Transpositions.** Monotonic alignment cannot represent a swap, so the genuine Greek
  transposition at `EXO 21:16`/`21:17` is reported as two disagreements in both directions.

### The candidates, ranked by how many independent pairs see them

Books where the Greek is *known* to reorder — 3 Kingdoms (`1KI` 7, 20, 21), Jeremiah
(`JER` 27), Greek Exodus — produce runs that are textual rather than mapping faults. What
survives that filter, and appears in more than one independent pair:

| passage | seen in | displacement |
|---|---|---|
| `JDT 6` | `eng`→`vul`, `lxx`→`vul`, `vul`→`nvl` | +4, then +2 |
| `EXO 39:19-38` | all seven pairs, including Latin-against-Latin | −1, −2 |
| `LEV 8:20-30` | `org`→`lxx`, `eng`→`lxx`, `lxx`→`vul` | ±1 |
| `NEH 7` | `eng`→`vul`, `vul`→`nvl` | +1 |
| `NUM 26` | `eng`→`lxx`, `lxx`→`vul` | ±4 |
| `SIR 6:20-34`, `SIR 14:16-23` | `eng`→`vul` | +1 |

`LEV 8:20-29`, `SIR 6:23-29` and `EXO 39:29-31` were also flagged by the earlier
model-and-similarity sweep, which used different witnesses and a different instrument. Two
independent methods agreeing on the same passages is the strongest signal available here,
and these are the queue for adjudication.

## Adjudication: putting the candidates to the models

Each run from Phase C is a hypothesis, not a finding. The models were asked to choose
between the two candidates — **the control is the rival, not an arbitrary neighbour**, which
is strictly stronger than the earlier sweep's design because the alternative being tested is
the one that actually competes. Only a discriminating pair of answers counts, and a rejection
must be certified by the inverse framing before it is allowed to stand.

Calibration first, on mappings verified by hand: **5 of 5 correct**, 5 of 6 informative.

Of 780 verses in runs of 3 or more: **246 say the derived alignment is right, 74 say the
vendored data is right**, 452 uninformative, 2 uncertified. A 41% informative rate is low,
which is why only the discriminating answers are counted at all.

The split is coherent rather than uniform, and that is the evidence that it is measuring
something. Exodus 39 comes out **derived** on all three Latin-side pairs and **vendored** on
both Greek-side pairs — exactly right, because the Greek Exodus genuinely reorders the
tabernacle account while the Latin has a plain off-by-one.

### Confirmed by hand as well as by the models

| passage | evidence | finding |
|---|---|---|
| `EXO 39:27+`, Latin side | `org`→`vul` 13–1, `eng`→`vul` 9–0, `vul`→`nvl` 5–0 | **off by one.** `vul 39:28` *"cingulum vero de bysso retorta, hyacintho, purpura, ac vermiculo"* is `nvl 39:29` *"cingulum vero de bysso retorta, hyacintho, purpura ac cocco"*, not `39:28` *"et tiaram et ornatum mitrarum"* |
| `LEV 8:20-30` | `lxx`→`vul` 10–0, `eng`→`lxx` 8–0, `org`→`lxx` 8–0 | **off by one.** `eng 8:22` *"He presented the other ram, the ram of consecration"* is `lxx 8:21` *"Moses brought the second ram, the ram of consecration"* |
| `JDT` (whole book) | `eng`→`vul` +4 in ch. 6, seen by 3 pairs | **no mapping exists at all.** Not one entry for Judith in any system, yet `vul` numbers its chapters [12, 18, 15, 17, 29…] against `eng` [16, 28, 10, 15, 24…]. Jerome translated Judith from a different recension and every verse converts by identity |

### Strong model evidence, not yet read by hand

`DAG 6` (26–0), `1KI 7` (23–0, 19–0, 18–0 across three pairs), `SIR 6:20-34` (9–0),
`NEH 7` (5–0), `BAR 6` (6–0), `NUM 26`, `NUM 27`, `NUM 15`, `EZK 7`, `LEV 15`.

`DAG 6` and `BAR 6` need care: both were *already corrected* in an earlier pass, so the model
may be reporting that those corrections went too far or not far enough.

### Where the vendored data is vindicated

`JER 25`, `JER 27`, `JER 29`, `JER 35` and `1KI 20` all come out **vendored**. These are the
books where the Septuagint reorders bodily, which monotonic alignment cannot represent — the
data is right and the derivation is the thing that is wrong. `PSA 13` likewise: 0–2 vendored,
a superscription the instrument cannot express.
