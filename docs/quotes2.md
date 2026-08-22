# The quotations we already found

*A design for the second generation of quotation detection, 2026-08-21/22. Companion to
`quotes.md`, which remains the standing design; this document corrects one of its premises,
retires three of its own proposals, and adds one retrieval channel.*

*Every number below was measured on this machine against the live library at fold 8, and
each names the command or file it came from. Where a measurement in `quotes.md`, in
`churchfathers/boycesofar.md`, or in an earlier pass of my own is contradicted here, the
contradiction is stated rather than quietly fixed. §1, §4 and §10 each correct something I
measured, reported, or proposed and then had to withdraw; the withdrawals are left in place
because the order they came in is the argument.*

> **The finding.** This document was commissioned to design a new way to retrieve 96
> citations that `boycesofar.md` reports as never retrieved. Swept and counted, **the 96 is
> 16 + 17 + 17 + 47**: sixteen are retrieved today and thrown away before anyone can see them
> (fourteen deleted inside our own overlap suppression, two reported in a field churchfathers'
> scorer does not read); seventeen sit at a locus the scan has already spoken for; seventeen
> produce candidates that no gate admits; and **forty-seven produce nothing at all.** Only the
> last group needs a new retrieval idea. **The new channel is still worth building — it is no
> longer the first thing to build, and nothing should be measured until the accounting is
> fixed, or it will take credit for work the library already does.**
>
> **On how to fix the first group I was wrong three times, and §4 records all three.** The
> answer is not a better statistic for picking the winner, nor keeping the loser, nor reading
> the loser downstream. It is that overlap suppression runs *before* the gate and picks its
> winner by something unrelated to it, so **a match that would clear the gate is deleted for
> one that will not**, and the span is then discarded by the gate that would have kept it.

---

## 1. The premise this document was written to test, and how it failed

`churchfathers/boycesofar.md` scores this library against Stephen Boyce's hand-marked set:
**209 citations, 75 found, 38 gated, 96 unseen**, and frames the split as two problems —
*gated* is a scoring problem, *unseen* is a retrieval problem. The plan this document was
commissioned under accepted that frame and set out to build a new candidate generator for
the 96, on the reasoning that no threshold can rescue a verse that was never a candidate.

**That reasoning is sound and its premise is partly false.** The 96 are not 96 verses for
which no candidate was generated. The clearest case, verified twice at the sweep's own
settings:

| scored `unseen` | what the scan actually produces |
|---|---|
| Didache 1.4 → MAT 5:39 | **MAT 5:39-42**, run 10, 35.3 bits, coverage 1.000, graded `direct` — generated, then deleted before it could be reported (§2.1) |
| Polycarp 2.3 → MAT 5:10 | **MAT 5:9-10**, carried as an *alternate* on LUK 13:18 — reported, in a field the scorer does not read (§2.2) |

**A caution about how that was measured, because I got it wrong once.** An earlier pass
through this question used `search()` on its own defaults and reported that the library
returns the right book and chapter for 17 of the 96, with 1 Clement 13.1 recovering
JER 9:22-23 at 87.6 bits and 28.3 recovering PSA 138:7-10 at 312.5. **Re-run through
`scan()` at the sweep's settings — coverage 0.50, `min_run` 4-6, `inflected`, the Greek
gate — neither reproduces.** 13.1 returns ODA 3:9-10, 1SA 2:9-10 and 1CO 1:31 and never
names Jeremiah; 28.3 returns only SIR 6:12. `search()` and `scan()` are different entry
points under different settings and they answer different questions, and quoting one while
describing the other is the same error this project has now made in four different
instruments. **The figure for how many of the 96 are already generated is therefore
deliberately absent from this document until `tools/boyce/sweep.py` reports it**, and §10
names that as the measurement it is waiting on.

What survives that correction is not the count but the *mechanism*, and the mechanism is
enough to act on: at least one citation is demonstrably found at run 10 and deleted, and at
least ten more are demonstrably reported and never read (§2.2, measured on churchfathers'
own shipped file). So before designing anything new, §2 asks a different question: **when
the library finds the verse and the ledger says `unseen`, where does the answer go?**

It turns out to go to three different places — one in our matcher, one in their scorer, and
one in an index neither project reads at the moment it would matter — and none of the three
is a failure to retrieve.

---

## 2. P0 — the answer is found, and then three things lose it

### 2.1 Our side: overlap suppression deletes the best answer

`Searcher.scan` ends by sorting candidates on `similarity` and passing them to
`_without_overlaps` (search.py:2877-2879, the function's only call site). Where two matches
claim the same words, the higher-`similarity` one wins; the loser survives as an *alternate*
only if the gap is under `_TIE = 0.06`, and is otherwise deleted without trace.

Didache 1.4 is the clean case. Boyce marks five citations there — 1PE 2:11, MAT 5:39,
MAT 5:41, LUK 6:29, LUK 6:30 — because the passage is a catena of sayings laid end to end.
Instrumenting the suppression on the father's own text gives:

| passage | span | run | bits | similarity | coverage | verdict |
|---|---|---|---|---|---|---|
| MAT 5:40-41 | (141, 189) | 6 | 50.2 | 0.412 | 0.778 | kept |
| LUK 6:29 | (72, 123) | 4 | 15.8 | 0.387 | 0.667 | kept |
| **MAT 5:39-42** | **(68, 123)** | **10** | **35.3** | **0.294** | **1.000** | **DELETED** |
| LUK 6:29-30 | (214, 283) | 3 | 43.2 | 0.286 | 0.467 | kept |

The deleted match has the **longest verbatim run of the four**, the **highest coverage of any
of them**, and is the only one that reaches Boyce's `MAT 5:39`. It loses to a four-word run
worth 15.8 bits because its symmetric similarity is 0.093 lower — and 0.093 exceeds `_TIE`,
so it is not even recorded as an alternate.

**Why similarity is the wrong statistic for this decision, in the codebase's own words.**
`Witness.similarity` is documented as *"How alike this rendering and the query are,
**symmetrically**. This is what **names the translation**"*, and `Witness.coverage` as
*"Share of the query this rendering accounts for. Used to decide **whether the text is a
quotation at all**, where `similarity` decides **which translation it is**"* (search.py:1588-1602).

The library therefore already states the principle: coverage answers *is this a quotation*,
similarity answers *which edition*. `_without_overlaps` is deciding **which passage** — a
third question — and it decides it with the symmetric measure. A symmetric measure is
length-biased by construction: a four-verse target compared against a one-clause quotation
is penalised for the three verses the father did not quote, which is exactly the wrong
penalty when the question is *which passage did he quote from*. In the table above the
length bias is visible directly: the ranking on `similarity` is almost the reverse of the
ranking on `coverage`.

This is the failure family the project keeps meeting, and `SETUP.md` already has the name
for it: **"a measurement that returned a confident answer to a question it was not actually
asking."** Nothing errors here either. A value is produced, it is plausible, and the right
answer is deleted to make room for it.

**Read §4.1 before acting on this section.** The obvious remedy — arbitrate on coverage
instead — was implemented, swept over all nine works, and **lost six citations that are
credited today**. Similarity is the wrong statistic for the question and it is still the
better one to pick a winner with, because *every* choice of winner deletes a loser, and the
deletion is the actual defect. The diagnosis here stands; the remedy it suggests does not.

### 2.2 Their side: `alternates` is emitted and never read

`Match.to_dict` emits `"alternates"` (search.py:1845). churchfathers'
`build_boyce_page.best_for` credits a match when its `target` **or any member of its
`family`** meets one of Boyce's targets — and does not look at `alternates` at all.

In their shipped `review/boyce-now.json`, **71 of 264 matches carry a non-empty alternates
list**. Rescoring their own file, changing nothing but consulting that field:

| scoring rule | found | gated | unseen |
|---|---|---|---|
| as shipped — `target` + `family` | 75 | 38 | 96 |
| + `alternates` consulted | **77** | **46** | **86** |

**Ten citations leave `unseen` for no new computation whatsoever** — the evidence is already
in the file they already hold. Two become found outright; eight become *gated*, which is the
meaningful move, because `gated` is a threshold decision the calibration work can reach and
`unseen` is not.

This is the first item to send back to churchfathers, and it costs them four lines.

### 2.3 The two together, measured on all nine works

The two defects are not independent: because `_without_overlaps` deletes rather than
demotes, the alternates list is *thinner than it should be* — MAT 5:39-42 never reaches it.
So §2.2's figure is a floor, taken with our bug still in place.

`tools/boyce/sweep.py` rescans all 749 passages and records both what the scan returns and
what the suppression deleted. Scoring the same sweep cumulatively:

| what is counted | citations |
|---|---|
| **found** — reported as the match | 75 |
| already an **alternate** on a kept match | +2 |
| **deleted** by overlap suppression | +14 |
| **= class A: found today, credited nowhere** | **16** |
| gated (visible only at the floor) | 37 |
| unseen — nothing generated at all | **81** |
| | *209* |

**`unseen` is 81, not 96.** `found` reproduces at exactly 75, which is how the fork is
checked: it scores the shipped result identically and differs only where it can see
something their sweep cannot.

The 2 here and the 10 in §2.2 reconcile rather than disagree. Two alternates are creditable
at the gate — that is the +2 in both tables — and the other eight sit on floor-pass matches,
so they move citations from `unseen` to `gated` rather than to `found`. Both are worth
having; only the first changes the recall figure.

By Boyce's grade, class A is **4 direct, 6 indirect, 6 partial** — spread across all three,
so it is not an artifact of one kind of citation.

Across the whole corpus the suppression deletes **369 matches and keeps 263**. It discards
more than it returns, and 14 of those discards are citations Boyce marked by hand.

### 2.4 A third leak: the families cannot cover the books the fathers quote most

The emitted `LUK 6:29` carries `family=[]`. `family` is how a match at an address Boyce did
not choose still gets credited, so a gap here is a scoring gap as much as a data one — and
the gap has a precise, structural cause.

**`parallel_family` does not derive families from the text. It verifies a seed list.** The
seeds are OpenBible.info cross-references, of Treasury of Scripture Knowledge lineage
(parallels.py:74-86) — a nineteenth-century Protestant reference work. A pair with no seed
is never proposed, however alike the two verses are, because the builder's only job is to
*confirm* pairs against the Greek.

The consequence is visible in the table's own shape. **29 of the 93 books hold no family row
at all**, and they are exactly the deuterocanonical and LXX-only books:

```
SIR  4,096 Greek verses    1MA  2,765    WIS  1,299    1ES  1,299
4MA  1,441                 JDT  1,020    ODA    796    TOB    492
2MA  1,665                 3MA    682    BAR    423    PSS    934   … and 17 more
```

Roughly 19,000 Greek verses. The builder's own comment shows the provision made and the gap
missed: *"all of the LXX **including the deuterocanon, so no pair fails for want of a
text**"*. The text was put there so that no pair would fail for want of it — and no pair is
ever proposed for those books, so it is never consulted. **A correct provision that nothing
can reach**: the same failure family as §2.1, in a second instrument.

The sharpest instance is not deuterocanonical subtlety but a verbatim duplicate. `ODA 3:10`
is the Song of Hannah, a liturgical extract of `1SA 2:10`, and the two differ in three words
across sixty — φρόνιμος against σοφός, φρονήσει against σοφίᾳ. The pair is **absent**,
because ODA is not in a Protestant cross-reference list. So when 1 Clement 13.1 quotes the
"let him that boasts boast in the Lord" saying, the scan correctly returns ODA 3:9-10,
1SA 2:9-10 and 1CO 1:31 — three witnesses to one saying — and can link none of them to each
other, or to the Jeremiah address Boyce named.

The same cause explains the synoptic gaps, from the other direction. Where a seed *does*
exist, the pair still has to clear `CHAIN_FLOOR = 4` and `BITS_FLOOR = 25.0` on the Greek:

```
MAT 5:3  || LUK 6:20  (the poor)             present
MAT 5:6  || LUK 6:21  (those who hunger)     present
MAT 5:39 || LUK 6:29  (turn the other cheek) ABSENT
MAT 5:44 || LUK 6:27  (love your enemies)    ABSENT
```

The Beatitudes are held and the antitheses are not, because Matthew's ῥαπίζει and Luke's
τύπτοντι share too little surface. So the index that exists to rescue divergent wording is
built by a gate that requires shared wording, and is absent exactly where the wording
diverges.

**Priced honestly: 6 of the 209 golden rows name a target in a book with no family coverage,
and all 6 are currently `unseen`.** That is a small direct lever and a hundred per cent hit
rate on the rows it touches. Its larger cost is elsewhere: Esther and Maccabees — the exact
terrain Marco named as the false-positive risk (§8) — have no family defence at all, so a
match landing there cannot be recognised as the same words at another address.

Fixing this properly means proposing pairs from the text rather than only verifying a seed
list, which is a build-side change of real size. It is scoped in §6.4 rather than in P0.

### 2.5 The denominator, double-checked

Asked to verify the 209, I checked it and it holds up better than expected.

* `data/golden-boyce.json` carries **226 rows: 209 Greek and 17 Latin.** The scorer filters
  to Greek, so 209 is the right denominator for a Greek sweep. (This also explains a
  discrepancy I had flagged: Polycarp shows 50 rows in the file and 33 in the ledger — the
  other 17 are the Latin ones.)
* **Two rows are duplicate questions.** Didache 1.3a and 1.3c both cite MAT 5:44; 2.7a and
  2.7b both cite LEV 19:17. These are genuine separate citations in Boyce's table, but the
  scorer keys on `(work, locus)`, so both rows ask an identical question of identical data
  and always move together. **209 rows, 207 independent questions.** The pair is also graded
  differently (`direct` and `partial`), which distorts the by-grade table slightly.
* **The versification is already handled, and handled well.** 14 of the 256 distinct targets
  name a verse absent from every Greek corpus we hold — eleven Psalms in Hebrew numbering
  (`PSA 51:17`, `PSA 22:7-9`, …), Esther, and two cross-chapter ranges. Every one of the ten
  affected rows *also* names the Greek equivalent alongside it — `PSA 50:19` beside
  `PSA 51:17`, `ESG 4:15-16` beside `EST 4:15-16` — and `best_for` accepts any listed
  target. The golden set was built with the LXX/Hebrew divergence in mind. Nothing is lost.
* **Two targets parse over-broadly.** `parts()` splits on the first `:` and strips
  non-digits, so `EXO 14:26-15:5` becomes `EXO 14:26-155` and `JOB 4:16-5:5` becomes
  `JOB 4:16-55`. Both are bounded to the correct chapter and both rows carry a correctly
  parsed alternative, so the effect today is nil — but it is a latent false-positive and
  belongs in the note to churchfathers.

**Verdict: the denominator is sound.** Report against 209 for continuity with
`boycesofar.md`, and state 207 where independence matters.

---

## 3. What is actually left, measured

The sweep accounts for all 209 without a residue. Reading `boycesofar.md`'s three buckets
against what the scan actually did at each locus:

| | citations | what it means |
|---|---|---|
| **found** | 75 | reported and credited today |
| **A — found, credited nowhere** | **16** | §2. Deleted by suppression (14) or sitting unread in `alternates` (2). |
| **gated** | 37 | a candidate for Boyce's verse exists and the gate refuses it. Threshold work. |
| **B — the locus is already spoken for** | **17** | the scan reports an admitted match *at that locus* and Boyce names a second citation there that it never reaches. §5. |
| **sub-gate at the locus** | **17** | the scan produced candidates at the locus and admitted none of them. A gate story, not a retrieval one. |
| **C — nothing whatever** | **47** | the scan produced no candidate at that locus at all. §6-7. |
| | **209** | |

**So the "96 unseen" decomposes as 16 + 17 + 17 + 47** — and only the last group is the
problem this document was commissioned to solve. **Class C is 47 of 209, not 96.**

Two of those rows deserve emphasis because they change what is worth building:

* **Class B is 17.** These are catenae: 1 Clement 65.2 names both 2CO 13:13 and JUD 1:25 at a
  locus already carrying one claim; Polycarp 2.1 names 1PE 1:21 and 2TI 4:1 the same way.
  The scan is not failing to find them so much as declining to say two things about one
  sentence. That is §5, and it is the same instrument as §2.1 — the difference is only
  whether the rivals overlap or merely adjoin.
* **The 17 sub-gate rows are a scoring problem misfiled as a retrieval one.** The candidate
  exists at the right locus; nothing admits it. Added to the 37 already labelled `gated`,
  **54 of 209 turn on thresholds** — more than twice class A, and reachable by the
  calibration work that already exists rather than by anything new.

Class C is the one `quotes.md` §13 was written about, and its refusals stand. At 47 it is
still the largest single class, and it is now the only one that needs a new idea.

---

## 4. The fix for P0 — and the constraint that decides its shape

There are two ways to stop deleting the right answer, and the choice between them is not
ours alone to make. `tests/test_regression.py` states the standing agreement:

> *"The consumer this exists for holds **513,047 findings** resting on the present
> behaviour, and asked for one thing above every feature: that a change improving recall
> **must not alter a single existing match**, because discovering what moved would mean
> re-adjudicating half a million records."*

That rules on the two options directly.

### 4.1 Change the winner — proposed, measured, and refused

`_without_overlaps` has no comparison step to adjust: it is first-come-wins over whatever
order it is handed, so the winner is decided entirely by the sort one line above it —

```python
matches.sort(key=lambda m: (-m.similarity, m.span or (0, 0)))   # search.py:2877
return self._decorate(_without_overlaps(matches), ...)
```

Rank by coverage first and the match accounting for more of the father's words takes the
span. On Didache 1.4 that is plainly better: `MAT 5:39-42` wins, `LUK 6:29` becomes its
alternate, and the locus goes from crediting three of Boyce's five targets to four.

**Swept over all nine works, it is worse.** Both orderings, same passages, same gate:

| sort key | found | suppressed | found + suppressed | gated | unseen |
|---|---|---|---|---|---|
| `-similarity` — today | **75** | 13 | 88 | 37 | 84 |
| `-coverage` — this proposal | **69** | 19 | 88 | 37 | 84 |

Coverage-first **loses six citations that are credited today**, and they land in the
suppressed column rather than disappearing: the same six are still generated, still deleted,
just deleted the other way round. Didache 1.4 was a real gain and an unrepresentative one.

**The identity in the third column is the finding.** `found + suppressed` is 88 under both
orderings, and `gated` and `unseen` do not move at all. **The sort key does not change what
the matcher can reach. It changes only which of the reachable it destroys** — and the
symmetric similarity it uses today happens to destroy six fewer of Boyce's than coverage
does.

So the instinct behind §2.1 was right about the diagnosis and wrong about the remedy. The
defect is not that the wrong statistic picks the winner. **The defect is that picking a
winner deletes the loser at all**, and no choice of statistic fixes that, because 88 are
reachable and only 75 can be first.

This also settles a question §4.2 would otherwise have had to negotiate. Changing the sort
would have moved reported matches under an agreement that forbids it — and it turns out
there was nothing on the other side of that trade worth asking for.

### 4.2 Keep the loser — implemented, swept, and it buys nothing

If the sort cannot be improved (§4.1), the deletion itself is what to change. A rival at
different coordinates covering at least as much of the span as the winner is kept as an
alternate whatever their similarities look like — `_explains_as_well`, one line:
`match.coverage >= winner.coverage`. The winner does not change, so no reported passage
moves and `tests/data/scan-golden.json` passes untouched.

It ships opt-in — `Searcher(covering_rivals=True)`, and `?covering_rivals=` over HTTP —
because two tests failed on the first attempt and the important one says why:

> `test_alternates_stay_empty_when_the_feature_was_not_asked_for` — *"Filling a field that
> has always been empty changes what every existing scan returns, and half a million
> findings downstream rest on that not happening by surprise."*

Not moving a reported passage is not the same as not changing what a scan returns, and "it
only adds" is an argument this project has already considered and refused.

**Swept over all nine works, it recovers nothing.**

| | found | gated | unseen | alternates emitted |
|---|---|---|---|---|
| today, alternates unread | 75 | 38 | 96 | 90 |
| today, alternates read | 77 | 38 | 94 | 90 |
| **tier on, alternates read** | **77** | **38** | **94** | **284** |

The tier triples the alternates — 90 to 284, on 120 matches instead of 71 — and **not one of
the new ones is a citation Boyce marked.** It does exactly what it was written to do and
that turns out not to be the thing worth doing.

### 4.3 Why — and the defect all three attempts were circling

Didache 1.4 with the tier on, which is the case §2.1 was built from:

```
LUK 6:29      run=4  bits=15.8   admitted=False   alternates=['MAT 5:39-42']
MAT 5:40-41   run=6  bits=50.2   admitted=True    alternates=[]
LUK 6:29-30   run=3  bits=43.2   admitted=True    alternates=[]
```

The tier worked: `MAT 5:39-42` is on the alternate list. **And it is on the alternate list of
a match the gate throws away.** `LUK 6:29` carries four words and 15.8 bits and clears none
of the three gates. `MAT 5:39-42` carries ten words and 35.3 bits and clears the first one
outright.

So the sequence is:

1. suppression picks a winner on **similarity**, a statistic with no relation to the gate;
2. it deletes `MAT 5:39-42` — which would have passed — in favour of `LUK 6:29`, which will
   not;
3. the gate then discards `LUK 6:29`, and everything hanging off it goes too.

**A gate-passing match is deleted for a gate-failing one, and the span ends up empty.** That
is the defect, and it is why none of the three attempts reached it: §4.1 changed the
statistic, §4.2 changed what happens to the loser, §2.2 changed who reads the loser — and
all three left the winner being chosen by something that does not predict survival.

It also explains §4.1's six lost citations. Coverage-first reshuffled winners with no more
regard for the gate than similarity had, so it traded six survivors for none.

**The change this implies** is that a match clearing the gate should win a contested span
over one that does not, before either similarity or coverage is consulted. Suppression runs
before gating and `Gate.admits` needs only the four axes every `Match` already carries, so
the arbitration can be told what the gate will say.

**One wrinkle, and it decides whose change this is.** `LUK 6:29` is an *exact* match, and
the library does not gate exact matches — `self._gates` is consulted inside `_score_cluster`
for graded ones only (search.py:2831), so a graded match failing the gate never reaches
suppression at all, while an exact one always does. The gate that kills `LUK 6:29` is
churchfathers' own `admits`, applied after the fact and deliberately: *"Nineteen of the
twenty errors measured in Boyce's nine works were exact matches"*, including a liturgical
doxology worth 16.8 bits that no run threshold can refuse.

So the library cannot simply prefer "the match that will clear the gate", because on its own
terms `LUK 6:29` clears everything — it is exact. What it can do is prefer, among rivals for
one span, the one that would clear the gates *it was configured with*, applied to exact and
graded alike. That is a real option with a real argument behind it and it is not today's
behaviour, which is why it is measured before it is proposed.

**Nothing in this section should be acted on until that number is in**, including the tier,
which is written, shipped opt-in, and currently earns its place only as the instrument that
found this.

---

## 5. Class B — more than one citation in one span, and it is 17

§4 recovers the case where two *different passages* answer the same words. It does not
recover the case where a father quotes MAT 5:39 **and** MAT 5:41 in one breath, because
those are two spans and the scan returns the better one. Measured, that is **17 of 209**:
loci where the scan reports an admitted match and Boyce names a second citation there that
it never reaches. 1 Clement 65.2 wants both 2CO 13:13 and JUD 1:25; Polycarp 2.1 wants both
1PE 1:21 and 2TI 4:1; 1 Clement 60.3 wants three verses of Psalms at once.

The instrument for this already exists and is half-used. `_claims` distinguishes *the same
passage read as two spans* (one result) from *two quotations written one after another*
(two results) by asking whether a different passage claims **most** of the shorter span —
`shared * 2 > min(length)`, a bare majority. Its own docstring names the case it is
protecting: *"Two quotations written one after another. Neighbours, not rivals. They share
the space between them and sometimes a word, and a bare interval intersection — which this
used to be — deleted the second of them for it."* That fix was made for quotations that
**adjoin**. A catena interleaves them instead, the shared fraction lands just over half, and
the second citation is deleted as a duplicate by the very test written to save it.

**Proposal.** Where two matches are at different coordinates *and each clears the gate on
its own axes*, a bare majority overlap is not sufficient grounds to delete one. Report both,
each with its own span, and let the consumer dispose. This is the two-stage doctrine the
project already follows: the retriever proposes, the gate disposes, and a deletion inside
the retriever is a decision taken in the wrong place.

**But it is not shippable the way §4.2 is.** Reporting two matches where one was reported
adds a finding rather than a field, so it moves what a consumer holds — the same agreement
that governs §4.1 governs this. It must be offered, measured on the control corpus and on
§8's named terrain first, and it is the change most exposed to both: a catena rule that
fires on Esther's rote prayers will fire often.

---

## 6. Class C — the diagnosis, and four prerequisites

For the **47** that produce no candidate at all, `quotes.md`'s analysis stands and this
section only adds measurements. The one-line diagnosis:

**The terms carrying the surprisal in a retelling live in a different index from the terms
the matcher searches, and the index that holds them is one form deep in a language that
declines.**

### 6.1 P1 — the proper nouns are registered in one case only

`entity_form` holds **5,084 forms over 4,068 entities — 1.25 forms each**. Split by
language:

| language | forms | entities | depth |
|---|---|---|---|
| he | 4,376 | 3,679 | 1.19 |
| **grc** | **708** | **576** | **1.23** |

The figure that matters is not 708 but **576 of 4,068**: seven entities in eight have **no
Greek form at all**, and are invisible to a Greek search by construction. For those that do,
the inventory is one case — Sodom's entire Greek registration is `σοδομα`, Lot's is `λωτ`.
Greek declines, so 1 Clement 11.1's `Σοδόμων` matches nothing.

And the lemma channel cannot rescue it, because **proper nouns have no lemma at all**:
`σοδομα`, `σοδομων` and `λωτ` all return NONE from the lexicon. The word is invisible to
both channels at once.

**The fix needs no new data.** `entity_verse` already records which verses attest each
entity. If Sodom is attested at a verse containing `σοδομα` and at another containing
`σοδομων`, both are Sodom's forms. Harvesting the attested surfaces is deterministic.

**Measured, with the rule stated.** Take every verse attesting an entity that already has a
Greek form; admit any folded token in it that shares the known form's stem (the form less
its last two characters) and is at least four characters long. Over `rahlfs` and `n1904`:

```
new forms                     8,132
entities gaining at least one   325 of 576
Greek forms                     708 -> 8,840
```

**The mean is a trap and I read it wrongly first.** 8,840 over 576 entities is 15 forms
each, which looks like runaway over-generation. The distribution says otherwise:

| forms gained | entities |
|---|---|
| 0 | 235 |
| 1 | 184 |
| 2 | 68 |
| 3–9 | 68 |
| 10+ | **5** |

The median entity gains one form. Five entities — LORD, Egypt, Canaan, Judah, Peter — carry
the mean, and they do so because they are attested in hundreds of verses and genuinely
inflect that widely. Spot-checked, the harvest is right: Egypt gains
`αιγυπτε, αιγυπτια, αιγυπτιαν, αιγυπτιασ, αιγυπτιοι, αιγυπτιοισ, …`; Sidon gains
`σιδωνα, σιδωνι, σιδωνιοι, σιδωνιων`; Peter gains `πετρον, πετρου, πετρω, σιμωνα, κηφα`.
These are the paradigms, and they are exactly what a father writing `Σοδόμων` needs.

**The error mode, named.** Two kinds of false form appear. Verb forms sharing a nominal
stem — `κυριευσουσιν` ("they shall rule") admitted under LORD alongside `κυριε, κυριον,
κυριου` — and homographs, `πετρα` ("rock") under Peter. Both are refusable by the same
check: the candidate must not carry a *verb* lemma where the known form carries a nominal
one. The lexicon already answers that question, so P1 should ship with a lemma-class guard
rather than on the stem rule alone, and the guard's cost is one lookup per candidate.

**A discriminative filter was tried and is not worth its complexity**: requiring that at
least half a form's corpus-wide occurrences fall in verses attesting the entity removes
1,476 of the 8,132 and does not remove `κυριευσουσιν`, because that verb also occurs mostly
where the LORD is attested. The lemma-class guard is the right instrument; document
frequency is not.

### 6.2 P2 — the lexicon reads some nouns as verbs, and one of them is κύριος

The case that started this:

```
θεῖον   fold=θειον   ->  ['θεαω', 'θεω']
θείου   fold=θειου   ->  ['θειοσ', 'θειοω']
θεῖος   fold=θειοσ   ->  ['θειοσ']
```

`θεῖον` — the neuter of θεῖος, "brimstone" — is analysed as a form of θεάω *behold* and θέω
*run*, and shares **no lemma** with its own genitive. So in 1 Clement 11.1, where the father
writes `πυρὸς καὶ θείου` against Genesis 19:24's `θεῖον καὶ πῦρ` — the same pair, reversed —
the two occurrences of *brimstone* cannot match each other.

**Audited, because one instance is an anecdote.** Over `rahlfs` and `n1904`, take every
second-declension pair where the nominative `-ος` and the accusative/neuter `-ον` of the
same stem each occur at least twenty times and the lexicon analyses both — 73 pairs. **Three
share no lemma at all**, 4%:

| nominative | acc./neut. | occurrences | lemmas |
|---|---|---|---|
| **κυριοσ** | **κυριον** | **3,388 + 771** | `['κυριοσ']` vs `['κυρεω']` |
| ειδοσ | ειδον | 26 + 275 | `['ειδοσ', 'οιδα']` vs `['ειδον']` |
| ναοσ | ναον | 22 + 50 | `['ναυσ']` vs `['ναοσ']` |

**So the defect is rare in proportion and lands on the most frequent noun in the corpus.**
`κύριον` — *the Lord*, accusative, 771 occurrences — resolves to κυρέω *to happen* and shares
nothing with κύριος. Every quotation naming the Lord as an object loses its lemma link, in a
corpus where that is among the commonest things a quotation does. `ναός` is read as ναῦς,
*ship*.

This changes P2's standing. It was scoped as one bug found by hand; it is a small class,
found by audit, whose largest member is likely worth more on its own than the rest of §6
combined. The audit above is fifteen lines and should be a test, run over whichever lexicon
is installed, asserting that a noun's principal parts share a lemma.

**It also removes an instrument P1 wanted.** §6.1 proposed rejecting harvested forms whose
lemma is a verb where the entity's known form is nominal. That guard would reject `κυριον`
— a correct form — for the same reason it rejects `κυριευσουσιν`. P2 must land before P1's
guard can be trusted, which fixes the ordering between them.

### 6.3 P3 — the profiles are built and unread, and they inherit §2.4's gap

`profiles.sqlite` holds **34,658 profiles, 144,397 members, 833,707 columns and 1,074,060
readings**. The only reference to the module anywhere in `src/` is the *builder* call in
`pipeline.py:129`. `profile_chain` — the matcher-facing function — has **no caller at all**.

A profile aligns one verse across its witnesses and records what each reads at every column.
Its witnesses are of two kinds, and the distinction decides what P3 is worth:

```
MAT 5:3   ->  n1904, grcant, grcbyz, sblgnt, wh, n1904:LUK 6:20      6 witnesses
MAT 5:39  ->  n1904, grcant, grcbyz, sblgnt, wh                      5 witnesses
```

The editions come from the corpus. **The sixth witness on MAT 5:3 is a family member**, and
MAT 5:39 has no sixth witness because §2.4 showed it has no family.

So a profile buys two different things. Across *editions* it carries variant readings, which
is the case of a father following a manuscript the critical text does not print — real,
valuable, and available today for every verse. Across *family members* it carries a synoptic
or doublet parallel's divergent wording in the same column, which is the paraphrase case —
and that half is only ever as complete as `parallel_family` is.

**This corrects a claim I made earlier in drafting**, that wiring the profiles would be the
cheapest route to the Sermon antitheses. It would not: the profile for MAT 5:39 has nothing
to say about LUK 6:29, for exactly the reason the family table has nothing to say about it.
**P3 depends on P4**, and the two must land in that order or P3 is measured on a table
missing 29 books and the antitheses both.

### 6.4 P4 — propose families from the text, not only from a Protestant seed list

§2.4's finding, scoped. `parallel_family` verifies seeds and never proposes them, so 29
books and ~19,000 Greek verses can hold no family however alike their verses are.

**The change.** Add a proposal pass beside the seed pass: for each Greek verse, retrieve
candidate parallels from the lemma index and admit a pair on the *same* `CHAIN_FLOOR = 4`
and `BITS_FLOOR = 25.0` the seed pass already applies. The verification gate does not
change; only the source of candidates does. That keeps the index's meaning identical — a
family member is still a pair verified on the Greek — and removes the canon restriction
that was never intentional.

**Why it is safe to widen here and not elsewhere.** This index is not a match gate. A pair
admitted here makes a finding *creditable at a second address*; it cannot invent a finding.
The floors that keep it honest are already in place and already tuned.

**Cost.** ~31,000 Greek verses retrieved against the lemma index, once, at build time. It
belongs as a `pipeline.py` step beside the existing `parallels` step, and it must carry the
fold stamp like every other artifact — which is exactly the omission that let
`parallel_family` sit six folds stale earlier this month.

**Priced: 6 of 209 golden rows directly (all currently `unseen`), and the FP terrain of §8
gains a family defence it has never had.**

---

## 7. Stratum 5 — conjunctive retrieval over a union index

One new candidate-generation channel, deterministic, built from indexes already held. The
design is unchanged from the approved plan and is restated here in full for the record —
but **its priority has dropped**, and honestly so. It was commissioned as the answer to 96
unreachable citations; §2 shows that a share of those are found already and thrown away, and
§6 shows four cheaper defects standing in front of it. Stratum 5 remains the right answer to
the residue that is genuinely unreachable. It is no longer the first thing to build, and
§10's pending sweep decides how large its share is.

**Query.** The rare terms of a father's span, from both channels unified: entity ids where a
token resolves to one, lemmas otherwise, each carrying its own surprisal.

**Index.** A union posting list, `entity_verse` ∪ `lemma_ref`. Neither alone suffices —
proper nouns exist only in the first, common words only in the second, and a retelling needs
both in one query. For 1 Clement 11.1 the whole available evidence is `{Σόδομα, θεῖον, πῦρ}`
and no single channel can see all three.

**Score.** Summed surprisal of the intersection, **order-free and gap-unbounded**. No run,
no chain, no window. Containment normalised against the shorter unit, reusing `_containment`
(search.py:794). Fragmentation reported as an axis, never as a filter.

**Gate.** Not on term *count* but on the **rarity of the conjunction**: total bits above a
floor *and* at least one term below a df ceiling. The library holds **36,705 Greek verses**
across `rahlfs` and `n1904`, so singling one out costs log₂(36,705) ≈ **15.2 bits**, and that
is the number the floor is calibrated against.

**Disposition.** This channel **proposes only**. The composite scores it, `verify` may check
it, families report rivals, and the existing gate disposes. That two-stage split is the
doctrine the project already follows, and it is what keeps a loose retriever from becoming a
loose result.

**Why the existing instruments cannot be tuned into this instead.** `allusions()` requires
two entities within thirty words (search.py:3005) and churchfathers measured the loci: of 29
register-flagged unseen, **21 name no individual at all**, 7 name one, 1 names two. It also
has no CLI or HTTP caller and is reachable only in-process. PPMI is scoring-only, inside a
two-bit tie window, and both projects have already refused promoting it to a generator.

---

## 8. False-positive control

The standing rule is unchanged: **a change that materially raises the false-positive rate on
pre-Christian Greek is refused whatever it recalls.**

Beyond that, this work's specific exposure is devotional and formulaic repetition, and Marco
named the terrain: **rote prayers in Esther and Maccabees, and the logistics-of-war passages
in the historical books** — muster lists, spoil inventories, siege narrative — which share
rare-ish nouns freely without anyone quoting anyone.

So the measurement is not only the control corpus. It is a **named-terrain suite**: run every
change in this document over Esther, 1-4 Maccabees, and the war material in Joshua, Judges,
Samuel, Kings and Chronicles, and report the proposal rate there *beside* golden-set recall
in the same table. A method that buys Boyce's misses and lights up the muster rolls has not
earned its place.

This applies to §5 as much as to §7. Reporting two claims per span where one was reported
before is a recall change and a precision change at once, and the named terrain is where the
precision cost will show.

Two structural defences, both already in the codebase's idiom: `_may_not_seed`
(search.py:2294) already denies low-complexity spans the right to nominate, and the same
principle extends to conjunctions whose terms are jointly common; and every proposal carries
its own term list as evidence, so a hand check is one line of output rather than a
re-derivation.

---

## 9. What churchfathers needs to change

Sent at the end of this work, not before — but recorded now so it is not lost.

1. **Consult `alternates` in `best_for`.** Measured on their own shipped file: 96 → 86
   unseen, 75 → 77 found, 38 → 46 gated. Four lines. It is the highest-value change in this
   document that costs nobody any new computation, and it is entirely on their side. Paired
   with §4.2 on ours — an opt-in tier they switch on in the sweep — it reaches more of
   class A still, and **neither half moves a reported match**. The 513,047 findings they
   asked us to protect are untouched by both.
2. **Add `"covering_rivals": True` to `GREEK` in `scan.py`** when they want the §4.2 tier.
   It travels: their `_encode` passes an unrecognised boolean straight through as Python's
   `True`, and the server's `_flag` lowercases before comparing, so no special-casing is
   needed the way `inflected` has one. Off by default, so their present sweep is unaffected
   until they ask for it.
3. **`parts()` mis-parses cross-chapter ranges.** `EXO 14:26-15:5` → `EXO 14:26-155`. Inert
   today because every affected row carries a correctly parsed alternative; a latent false
   positive.
4. **Two golden rows are duplicate questions** (Didache 1.3a/1.3c, 2.7a/2.7b). Worth a note
   in the ledger so 209 and 207 are both explicable.
5. **The Latin 17 are excluded silently.** Worth stating in `boycesofar.md`, since the file
   holds 226 rows and the page reports 209.

None of the five is a matcher change, and only item 2 needs anything from us — the tier,
which is written. Item 1 can ship the day they read this; items 3-5 are bookkeeping. Everything else in this document is
ours to do, and §11's last refusal governs the order.

---

## 10. Verification

**The harness is forked, at Marco's direction.** `tools/boyce/sweep.py` and
`tools/boyce/score.py` reproduce churchfathers' settings exactly — `GREEK` tuning, gates
`(3,0,0,35) ∪ (0,6,0,25) ∪ (0,0,8,40)`, the same 749 passages and 21,338 words — so a figure
measured here is comparable with `boycesofar.md` line for line, and anything that differs is
a bug in the fork. Two things are ours and not theirs:

* a **`suppressed`** column — citations the matcher generated and `_without_overlaps`
  deleted, which their sweep cannot see because it observes `scan()`'s return value, and
  deletion happens inside it;
* a **`--coverage-first`** switch, which is §4.1: the suppression is first-come-wins over
  its input, so re-sorting that input *is* the change, and both orderings could be swept
  without touching the library at all. That is what let §4.1 be refuted before it was
  written, rather than after it shipped;
* a **`--covering-rivals`** switch for the tier §4.2 adds.

A note on the fork's own instrument, since this document is about instruments that answer
the wrong question. The first version told kept from deleted with `id()`, and
`_without_overlaps` returns `replace(...)` copies so that it can attach alternates — so
every surviving match is a different object and the spy reported the entire input as
deleted. It ran to completion and produced a confident, wholly wrong number. It now compares
`(passage, span)`.

Then:

1. **Golden-set recall**, gate pass and floor pass in one run so `gated` and `unseen` stay
   distinct, reported before and after **by Boyce's grade**, since direct, indirect and
   partial fail for different reasons.
2. **The named-terrain suite** (§8), reported in the same table as recall, never after it.
3. **The control corpus.** The standing veto, unchanged methodology.
4. **The golden guard.** `tests/data/scan-golden.json` must not move for any existing match.
5. **Per-prerequisite tests.** P2: a noun's principal parts share a lemma, over whichever
   lexicon is installed, with `κύριος/κύριον` named. P1: `Σοδόμων` resolves to Sodom. P4:
   `1SA 2:10` and `ODA 3:10` are one family. P3: `profile_chain` has a caller in `src/`, and
   MAT 5:39's profile carries a sixth witness once P4 has run.
6. **Full gate**: ruff, mypy at the 10-error baseline, pytest.

**What is measured and what is not, as of writing.** Measured: §2.1 (the deletion, twice, on
Didache 1.4), §2.2 (96 → 86 on churchfathers' shipped file), §2.3 (**the full sweep: class A
= 16, unseen 96 → 81, 369 deletions against 263 kept**), §2.4 (29 books, ODA absent, 6 of 209
priced), §2.5 (the denominator), §4.1 (3 of 5 → 4 of 5 on one locus), §6.1 (8,132 forms and
the distribution behind them), §6.2 (73 pairs, 3 broken), §6.3 (no caller).

Also measured, and it changed the plan: **§4.1 swept over all nine works and lost six
credited citations**, which is why §4 recommends the tier and abandons the sort change.

**Pending:** the `covering_rivals` sweep, which prices §4.2 across all nine works rather than
one locus. Nothing else in this document waits on it, and §11's last refusal says nothing
new is built until P0 is settled and re-scored.

---

## 11. What this document refuses

Unchanged from `quotes.md` §13, at Marco's direction:

* **No neural signal in any default path.**
* **No chasing zero-overlap subject matter.** Where no shared term exists, Stratum 5
  proposes nothing, and the honest remainder stays pinned as *not found*.
* **No verdicts.** Evidence, axes and alternates throughout.
* **No promotion of PPMI to a generator** — and Stratum 5 makes it unnecessary, since the
  conjunction supplies the prior PPMI was being asked for.

And four refusals this document adds, three of them learned the hard way:

* **No new retrieval channel is built until P0 ships and the golden set is re-scored.**
  Otherwise a new method takes credit for citations the library already found, and is
  measured against a denominator that is wrong in its favour. The order is not negotiable
  and it is the main finding here.
* **No change that moves a reported match ships without being offered first.**
  `tests/test_regression.py` records why, and 513,047 findings is the number behind it. §4.1
  would have moved them; it was measured before being offered and turned out to be worse, so
  there was nothing to offer. Measuring first is what made that a non-conversation instead of
  a bad trade.
* **No field a default scan leaves empty is filled by default.** Learned the same day, from
  a test that already said so.
* **No fix is described as a fix before it is swept.** Three remedies for one defect were
  proposed here and all three were wrong: a better statistic (§4.1, lost six citations), a
  kept loser (§4.2, gained none), and a downstream reader (§2.2, the only one that helped —
  ten citations out of `unseen`, though only two of them all the way to `found`). Each was
  plausible, each was argued from the code, and the sweep refused two outright and cut the
  third down. §4.3 is the fourth and is being swept before it is written up as anything but
  a hypothesis.

---

## 12. Corpus ledger

Byzantine is closed: `grcbyz` (Robinson–Pierpont 2018) and `grcant` (Antoniades) are both
held. Ten Greek corpora are held in total, and their versifications are worth stating
because §2.5 turns on them:

| corpus | versification | verses |
|---|---|---|
| grcant, grcbyz, n1904, sblgnt, wh | `org` | ~7,950 each |
| rahlfs, rahlfs-cc, swete | `lxx` | 28,443–30,341 |
| rahlfs-alt | `lxx` | 1,323 |
| swete-daniel | `vul` | 422 |

**One entry this ledger does not need.** §2.4 might read as a corpus gap and is not one: the
deuterocanon is fully held — SIR, WIS, 1-4MA, TOB, JDT, BAR, ODA, PSS and the rest, ~19,000
Greek verses in `rahlfs` and `swete`. What is missing is not the text but any *index* over
it, because the cross-reference seed list that builds families stops at the Protestant
canon. Buying more text would not close it; proposing pairs from the text we hold would.

Still to price, each against the misses it would buy or else dropped: **Hexaplaric readings**
(Field, public domain) for OT quotations matching no Rahlfs or Swete wording; **testimonia
collections**, since a father may share wording with a testimony book we do not hold; and
**father-side attested forms** in Justin, Barnabas and Irenaeus as additional surface targets.
