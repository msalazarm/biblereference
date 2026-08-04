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
