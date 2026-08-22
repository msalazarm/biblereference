# Scripture quoting scripture

*A plan for building verse families from the text instead of importing them, 2026-08-22.
Companion to `quotes2.md` §6.4, which diagnoses the problem; this is the build.*

---

## The idea, in one line

**A verse family is a quotation found inside the corpus, and we own a quotation finder.**

Nehemiah quotes Deuteronomy. Chronicles quotes Kings. The Odes *are* Samuel and Habakkuk and
Jonah, lifted for liturgy. Sirach quotes Exodus. The gospels quote each other and all three
quote Isaiah. Every one of those is the same problem this library already solves for Clement
and the Didache — find the verse these words came from — turned to face the corpus itself.

## Why the families we have are the shape they are

`parallel_family` holds **12,641 pairs**, and it does not *find* them. It **verifies** a seed
list: OpenBible.info cross-references, of Treasury of Scripture Knowledge lineage, checked
against the Greek and admitted at `CHAIN_FLOOR = 4` and `BITS_FLOOR = 25.0`. A pair with no
seed is never proposed, however alike the two verses are.

Three consequences, all measured:

* **29 of 93 books hold no family row at all** — the whole deuterocanon, ~19,000 Greek
  verses. SIR, WIS, 1–4MA, TOB, JDT, BAR, ODA, PSS, 1ES. TSK is a nineteenth-century
  Protestant reference work and it never listed them.
* **`1SA 2:10 ‖ ODA 3:10` is absent.** They are the same sixty words differing in three —
  φρόνιμος against σοφός, φρονήσει against σοφίᾳ. Asked directly they chain at **73 links
  and 265.72 bits** against floors of 4 and 25. Nothing about the text was ever the problem.
* **The table was thinner than its own floors imply, for an editorial reason** — fixed
  2026-08-22, and it was worth **+2,433 pairs, +19.2%**. `lemma_chain`
  is asymmetric — `span_gap=8` one way, `verse_gap=2` the other — and *which verse lands on
  the left is decided by the seed's From/To column*. Five stored pairs were tested in both
  directions and **all five would have been refused had the seed listed them the other way
  round** (`JON 3:10 ‖ JER 25:5`: 10 links / 14.5 bits one way, 14 / 29.0 the other).

## What it is worth

Families are not a decoration. `family` **decides recall** in churchfathers' scorer: a
citation counts as found when the gate returns Boyce's verse *or a match whose family holds
it*. A server once misconfigured to return no families scored 75 → 64 found and 96 → 111
unseen — roughly forty citations riding on this table. And `profiles.sqlite` takes its
witnesses from families, so **34,658 profiles inherit whatever gaps this has** (`quotes2.md`
§6.3).

Measured on a prototype, proposing from the text takes families **12,641 → ~43,000 pairs**
and verses carrying a family **27% → 52%**.

---

## The method

Per verse, in its own language:

1. **Retrieve.** The 14 rarest lemmas of the verse against `lemma_fts`,
   `ORDER BY bm25 LIMIT 400`. Measured: ~62–90 ms, flat in the limit — the MATCH scan is the
   cost, not the number returned. **258 candidate pairs per verse.**
2. **Prefilter**, with provable upper bounds on both axes: chain length cannot exceed the
   count of positions whose reading meets the other verse's lemma union; chain bits cannot
   exceed the sum over those positions of the best shared reading. Cuts **10.7×**, to 24
   survivors. Verified lossless on Jonah — identical keys, identical `(chain, bits)`, with
   and without.
3. **Chain and admit, in both directions.** ~2.24 admitted per verse.

**Cost: ~160 ms/verse, ≈1.6 h single-threaded over 36,705 Greek verses.** It shards by book
and the box has 32 threads — with a process pool, minutes. (Threads will not do it: scanning
is CPU-bound Python and the GIL caps a thread pool at ~500% of 3,200%, which is how the
control-corpus harness wasted forty-five minutes before it was converted.)

**Recall against what we already have** — the honest check, since anything that loses
existing pairs is a regression whatever else it finds: **27/27 on Jonah, 198/200 on a random
sample** once both retrieval ends are counted. The two misses sit at ranks 759 and 1180 and
would need `LIMIT 1500` at ~4× the cost; they are not worth it.

---

## The problem, and it is the same problem as Esther

**At today's floors, proposal is 35–40% wrong.** A blind read of 16 random proposal-only
pairs: 6 clear false positives, 4 borderline, 6 right.

```
2CH 13:2 ‖ 2KI 23:36   regnal formula, different kings
EZK 13:2 ‖ EZK 21:33   "son of man, prophesy and say"
2SA 3:18 ‖ EZK 38:17   "by the hand of my servant"
DEU 19:5 ‖ JDG 9:48    two men swing an axe at a tree
ACT 7:16 ‖ GEN 34:2    Shechem and Hamor, the names alone
```

And the litany blow-up: of the Odes' 1,896 proposed pairs, **1,001 are Ode 8 matching
itself** — the Benedicite's antiphon, 32 verses against 31. `NUM 29:25` draws 37 members
from the festival refrain.

**This is the same phenomenon the control corpus just measured from the other side.** Of 25
false positives on 122,699 words of pre-Christian Greek, **19 are Esther and Maccabees**,
Greek Esther alone 15. Formulaic Greek generates matches against anything — against the
fathers, against the classical corpus, and against itself. One defence serves all three, and
building it once is the point of doing this properly.

### Why the floors do not catch it

`CHAIN_FLOOR = 4` and `BITS_FLOOR = 25.0` were calibrated for **verifying** a pair a human
editor had already proposed. The seed list was doing the work of excluding regnal formulae
silently and for free, so the floors never had to learn to. Discovery inherits no such
filter. This is the shape `quotes2.md` keeps finding: an instrument asked a question it was
not calibrated against, returning a confident value rather than failing.

### The defence: score the phrase, not the terms

Bits today are **the sum of independent term surprisals**. A stock phrase defeats that
directly: ten individually rare-ish words in *"…reigned N years in Jerusalem, and his
mother's name was…"* sum to 34 bits while the phrase itself is common. The terms are rare;
the *conjunction* is not.

So gate on the conjunction's own frequency: for a candidate pair's shared lemma set, how many
verses in the corpus contain **all** of it? Singling one verse out of ~36,700 is worth
log₂(36,700) ≈ 15.2 bits; a chain shared by twenty verses is worth ~10.8, not 34. That is one
`lemma_ref` intersection per pair, it reuses `LemmaWeights` and the existing surprisal
vocabulary, and it is the same idea `_may_not_seed` (search.py:2294) already applies to spans
— low-complexity evidence may not nominate.

Two cheap companions:

* **Require both ends.** 91% of admitted pairs are retrieved from both verses independently;
  requiring it costs 9% of true pairs and kills one-directional accidents.
* **Report degree, and let it be evidence.** A verse with 37 family members on one chain is
  telling you it is a refrain. Do not cap it — `ODA 8:63` legitimately has 64 — but carry it
  as an axis so a consumer can weigh it, which is this project's standing doctrine.

**What must not be used as a filter:** same-book and same-chapter. Proposals are 51%
same-book and 25% same-chapter; the existing seed table is **53% and 18%**. The distributions
are too close to separate a refrain from a genuine doublet, and Leviticus 18:9 ‖ 18:13 is
real.

---

## The build, in order

| phase | what | done when |
|---|---|---|
| **1** ✅ | Bidirectional admission in the *existing* verification pass | **done: 12,641 → 15,074 pairs, +2,433, +19.2%**, at unchanged floors and from no new data. Golden recall unmoved — see below |
| **2** | Proposal pass behind a flag, same floors, Greek only, sharded by book over a process pool | reproduces ≥99% of today's pairs; `1SA 2:10 ‖ ODA 3:10` present |
| **3** | The conjunction gate, calibrated on a hand-read sample | the 16-pair blind read goes from 6 clear FPs to ≤2 without losing the 6 right ones |
| **4** | The named-terrain suite: Esther, 1–4 Maccabees, and the war material in Joshua/Judges/Samuel/Kings/Chronicles | proposal rate there reported beside recall, in one table |
| **5** | Default on for Greek; then Latin, Syriac, Hebrew, each on its own corpora | fold-stamped, `pipeline.py` step, `doctor` reports staleness |

**Same language throughout, and it is not incidental.** A family is evidence that two verses
say the same thing *in the words their own tradition used*. An English Sirach beside an
English Exodus tells you about the translators, not the texts. This is the rule the
versification work already established for witnesses. The library holds 10 Greek corpora,
8 Latin, 3 Syriac, 2 Hebrew — every one of those is a separate pass over its own texts.

**Stamped like everything else.** `parallel_family_state` carries a fold version because this
table sat six folds stale while reporting current; a proposal pass must record its own
inputs the same way, and `quotes2.md` §6.2 adds the lesson that a *source list* needs
recording too, since a fold number cannot see a missing input.

---

## What this does not buy

**Phase 1 moved the golden set by nothing, and that is now measured rather than predicted.**
Families 12,641 → 15,074, swept: found 87, gated 44, unseen 78 — identical. Three more
matches carry a family (107 → 110) and no citation changes status. The pairs the bidirectional
rule adds are not the pairs Boyce's citations needed, which is what this section already said
would happen and is worth having confirmed rather than assumed.

**It does not move Boyce recall.** Six of the 209 golden citations name a target in a
no-family book; three of those are unreachable anyway (Daniel is held as `DNT`, not
`DAN`/`DAG`), and the prototype gives the remaining three — `SIR 4:31`, `TOB 12:9`,
`JDT 8:1` — no family under any floor. `JDT 8:1` draws six members and all six are genealogy
name-collisions.

Do this for the corpus, for the profiles that inherit it, and because a Protestant
cross-reference list is the wrong authority for a library holding ten Greek editions
including the deuterocanon. Do not do it expecting the golden set to move, and do not let a
recall number decide whether it was worth doing.
