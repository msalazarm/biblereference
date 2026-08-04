# Which corpus speaks for which family

A versification audit compares two systems by comparing two *texts* that claim to follow
them. That only works if each text actually does. This document records what happened when
that assumption was checked rather than assumed, because it did not hold, and several
conclusions in `versification-audit.md` rested on it.

The test is deterministic and needs no similarity scoring at all: take every chapter a
corpus holds **complete** (verses 1..n with no gaps) and compare its length against each
system's declared `maxVerses`. A corpus that follows a system agrees with it everywhere.

> Completeness matters. An earlier pass used each chapter's *highest printed verse*, which
> for an abridged corpus measures its excerpting rather than its versification — it scored
> the `nna` selection at 42% and read as a catastrophic misfile. `nna` held 1,366 verses
> across 26 books and only 12 complete chapters. It is a reader's selection, not a Bible,
> and it could not be judged this way at all.
>
> The four such editions have since been dropped from the corpus entirely — see
> `PORTIONS` in `biblereference.corpora.ebible`. What follows describes the corpus as it
> now stands.

## The rule that came out of it

**A translation is a witness to its own language's versification, not to its source
family's.** Every family here that has both a same-language witness and a translated one
shows the translated witness drifting toward English chapter divisions:

| family | same-language witness | agreement | translated witness | agreement |
|---|---|---|---|---|
| `org` | `wlc` (Hebrew) | **929/929** | `ojb` (English) | 1179/1189 |
| `vul` | `latvuc` (Latin) | 1327/1334 | `dra` (English) | 1319/1334 |
| `nvl` | `novavulgata` (Latin) | **1300/1300** | — | — |
| `lxx` | `swete` (Greek) | 900/1012 | `brenton` (English) | 977/1006 |

The `lxx` row inverts, and that is not an exception to the rule but a consequence of it:
our `lxx` system was *built from* the English tradition. Where Swete and Brenton disagree on
a chapter's length — 83 chapters — `lxx` sides with Brenton 66 times and with Swete 9.

## Swete is misfiled

`swete` is declared `lxx` and is not. It fits `rsc` better (92.3% against 88.9%), and its
disagreements with `lxx` are the well-known Greek-against-Hebrew chapter boundaries —
Deuteronomy 12, Numbers 6, Hosea 1, Joel 2, Zechariah 1 — where `rsc` inherits the Greek
divisions through Church Slavonic and `lxx` does not. All 47 of the chapters where `rsc` is
right and `lxx` is wrong are **protocanonical**; none are deuterocanonical, which is what
rules out a canon-scope explanation.

But `rsc` is not right either: 78 chapters still differ. Swete follows neither system.
Reassigning it would trade one wrong label for a less wrong one.

## The English family, by majority vote

Forty-six independent English corpora, each voting its own chapter lengths against declared
`eng`. Six chapters where the witnesses overrule the declaration:

| chapter | declared | witnesses say | tally |
|---|---|---|---|
| `BAR 1` | 21 | **22** | 10–0 |
| `SIR 41` | 23 | **24** | 10–0 |
| `TOB 5` | 21 | **22** | 8–0 |
| `TOB 10` | 13 | **12** | 8–2 |
| `3JN 1` | 15 | 14 | 27–9 |
| `REV 12` | 18 | 17 | 27–8 |

The first four are unanimous and sit in the deuterocanon — the same region that produced
the Baruch 3 and Letter of Jeremiah faults. The last two are split, and split is the
signature of a genuine textual variant rather than a fault: 3 John really is printed with
both 14 and 15 verses, and Revelation 12:18 is set as its own verse in some editions and
joined to 13:1 in others. A declaration cannot be right for both.

## Corpora that agree exactly

Trustworthy as witnesses, having been checked rather than assumed:
`wlc` (929), `novavulgata` (1300), `lsv` (1189), `jps` (929), `lee` (928), `ulb` (1170),
`oebcw`/`oebus` (548), `ourb` (540).

## Scripture portions, removed

Four eBible editions printed selected passages rather than continuous text, and are no
longer fetched or indexed:

| corpus | edition | chapters held complete | verses held |
|---|---|---|---|
| `nna` | Nyangumarta English Bible | 12% | 46% |
| `barkly` | Barkly Bible Portions | 19% | 87% |
| `pev` | Plain English Version | 29% | 80% |
| `aoi` | Anindilyakwa English Bible | 39% | 95% |

Every other English edition holds 86% or more of its chapters complete. The gap is wide
enough that the boundary is not a judgement call.

The catalogue cannot find them: eBible's declared counts put "Barkly Bible Portions" at
26.8 verses per chapter, squarely among the complete Bibles, because its chapters *are*
whole and merely few. Only the measured completeness separates a portion from a short
complete text, which is why `PORTIONS` is a fixed measured list rather than a rule applied
to the catalogue.

Dropping them removed 13,842 verses and 13,799 indexed texts — the 43-text difference
being verses rendered identically by a surviving translation, which the deduplicated index
correctly kept.

## Corpora that cannot be judged

`e2t` (Jonah alone), `glw` (four books), `niv` (an on-demand cache) and `swete-daniel` hold
too few chapters to place, though each is complete in what it carries. `n1904` is New
Testament only, so it matches `org`, `lxx` and `nvl` equally well and its declared family is
unfalsifiable by this method.
