# What changed, why, and what it bought

*biblereference → churchfathers, 2026-08-22. Branches: `quotes2` here,
`quotes2-gate-first` in churchfathers. Written after the work rather than before it, so
every number below is measured and several of them refute what I told you earlier.*

---

## The short version

You reported 209 citations as 75 found / 38 gated / 96 unseen, and asked for a new retrieval
channel to reach the 96. **The 96 is 16 + 17 + 17 + 47.** Only the last group needs a new
idea; the first sixteen were being found and thrown away, in two places, one on each side.

Both leaks are now closed. Measured on your nine works with a forked copy of your harness:

| | found | gated | unseen | Boyce's 19 Greek negatives |
|---|---|---|---|---|
| where we started | 75 | 38 | 96 | 2 |
| you: `alternates` read | 77 | 46 | 86 | 2 |
| us: `gate_first` | 81 | 38 | 90 | 2 |
| **both together** | **83** | 45 | **81** | **2** |

**+8 citations, and the negatives column does not move.** None of that recall is bought from
precision: the twenty loci Boyce marked as *not* quotations are matched exactly as often as
before, and they are the same two.

---

## What we changed and why

### `gate_first` — the one that matters

`_without_overlaps` deletes overlapping candidates before anything is gated, and picks the
survivor on `similarity`. Our own docstring says `similarity` names the *translation* while
`coverage` decides whether the text is a quotation at all — and being symmetric it is
length-biased, marking a four-verse passage down for the three verses the father did not
quote.

Didache 1.4 is the case. The scan generates `MAT 5:39-42` — ten words, 35.3 bits, over your
first gate — and deletes it in favour of `LUK 6:29`, four words and 15.8 bits, under every
gate you set. Your `admits` then refuses the survivor. **The span reports nothing while
having held the answer the whole time**, and Boyce's MAT 5:39 scores `unseen`. It is one of
the seven register leads in `boycesofar.md`: the register scan could see scripture there and
could not name it, and this is why.

With `gate_first`, a match clearing the gates *the caller sent* wins the span:

```
MAT 5:39-42   run=10  bits=35.3  admitted=True   alternates=['LUK 6:29']
MAT 5:40-41   run=6   bits=50.2  admitted=True
LUK 6:29-30   run=3   bits=43.2  admitted=True
```

Four of Boyce's five at a locus that scored one, and `LUK 6:29` is not lost — it becomes the
alternate, which you now read.

**It arbitrates on your gates, not ours.** The library does not gate exact matches at all;
you do, deliberately, because nineteen of the twenty errors you measured were exact. So
"prefer the match that will pass" is not a question this library can answer by itself — it
answers it with the gates that arrived on the request. A caller sending none gets the old
behaviour byte for byte.

Opt-in, for the reason `tests/test_regression.py` gives: you hold 513,047 findings on the
present behaviour and asked that recall changes never move an existing match. This one moves
them, so it is offered rather than shipped. `Searcher(gate_first=True)`, `?gate_first=1`, and
`"gate_first": True` in your `GREEK` mapping — which is the one-line change on your side, and
it is already committed on `quotes2-gate-first`.

### `covering_rivals` — kept, and honest about earning nothing

Keeps a rival covering at least as much of the span as the winner, whatever the similarity
gap. It triples the alternates (90 → 284) and **credits none of Boyce's citations.** It is in
because it is what found the real defect: it put `MAT 5:39-42` on the alternate list of a
match your gate discards, which is how the gating order became visible. Off by default.

---

## Three things I proposed and then had to withdraw

Recorded because you would otherwise be reading my earlier messages as advice.

1. **Arbitrate on coverage instead of similarity.** Right on Didache 1.4 — 3 of Boyce's 5
   became 4 — and **it loses six citations across the nine works**, 75 → 69. The useful
   residue: `found + suppressed` is 88 under both orderings, so the sort key never changed
   what was reachable, only which reachable match got destroyed.
2. **Keep the covering loser as an alternate.** Implemented, and it gains nothing (above).
3. **"It only adds, so it is safe to default."** Wrong, and your own suite said so before I
   did — `test_alternates_stay_empty_when_the_feature_was_not_asked_for` is explicit that
   filling a field which has always been empty changes what every scan returns.

---

## What is left, and it is smaller than 96

| class | size | whose |
|---|---|---|
| found today, credited nowhere | **16** | closed, both sides |
| the locus is already spoken for | **17** | ours — a catena rule, under investigation |
| candidates exist, no gate admits them | **17** | **yours** — threshold work, and with the 37 already `gated` that is 54 of 209 turning on numbers |
| nothing generated at all | **47** | ours — the new channel, and it is 47 rather than 96 |

---

## Other findings, none of them urgent

**`parallel_family` cannot cover the books you quote most.** It verifies an OpenBible.info
seed list of Treasury of Scripture Knowledge lineage, and never proposes a pair from the
text. So **29 of 93 books hold no family row at all** — SIR, WIS, 1–4MA, TOB, JDT, BAR, ODA,
PSS, 1ES, ~19,000 Greek verses. `1SA 2:10` and `ODA 3:10` are the same sixty words differing
in three and are not a family, because the Odes are not in a Protestant cross-reference list.
Since `family` decides recall on your side, this is a recall gap as much as a data one:
6 of the 209 name a target in one of those books and all 6 are unseen.

**The lexicon reads some nouns as verbs.** `κύριον` → κυρέω, sharing no lemma with `κύριος`
— 771 and 3,388 occurrences. `θεῖον` → θεάω/θέω. `ναός` → ναῦς. An audit of 73
second-declension pairs found 3 broken, so it is rare in proportion and lands on the most
frequent noun in the corpus.

**Profiles are built and unread.** 34,658 profiles, 1,074,060 readings, and `profile_chain`
has no caller in `src/`. They carry family members as witnesses, so they inherit the gap
above.

**Your denominator is sound** — details in `review/filing-and-parts-2026-08-19.md`. 226 rows,
209 Greek, 17 Latin; two pairs are duplicate questions, so 209 rows and 207 independent ones.
The Hebrew/LXX Psalm numbering was already handled properly. One fix: `parts()` read
`EXO 14:26-15:5` as `EXO 14:26-155` and matched anything from Exodus 14:26 to the end of the
chapter — inert, since both affected rows name a within-chapter equivalent, but it now
raises. The same function is copied into nine other tools and they still widen.

---

## How to re-run any of this

The harness is forked into `tools/boyce/` here — `sweep.py` and `score.py` reproduce your
settings exactly (`GREEK`, gates `(3,0,0,35) ∪ (0,6,0,25) ∪ (0,0,8,40)`, the same 749
passages and 21,338 words). `found` comes out at 75 against your 75, which is how the fork
is checked. It adds what your sweep cannot see — a `suppressed` column for matches the
library generated and deleted — and switches for each arbitration tried:

```bash
venv/bin/python tools/boyce/sweep.py --library-gate-first --out review/gate-first.json
venv/bin/python tools/boyce/score.py --sweep review/gate-first.json \
    --floor ~/churchfathers/review/boyce-floor.json
venv/bin/python tools/boyce/control.py --words 200000     # the pre-Christian FP price
```

The full design, with everything measured and everything refused, is `docs/quotes2.md`.
