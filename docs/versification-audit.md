# Auditing the versification mappings

A wrong mapping does not fail. It returns the neighbouring verse, with no error and no
warning, and everything built on it is wrong in a way nothing downstream can detect. This
is what was done to find out whether any were wrong, what it found, and — as much as it
matters — what it cannot tell you.

## The instrument

**The test is differential, never a threshold.** Two translations of one verse can share
almost no words: the Douay-Rheims and the Orthodox Jewish Bible render Psalm 23:1 at 0.15
similarity and are plainly the same verse. Any threshold that accepted that would accept
anything. What survives translation is *relative* position — the right verse still
resembles its counterpart more than the neighbours do — so every check scores the mapped
position against offsets −2…+2 and passes when the mapping's own position wins.

**Both sides of every comparison are in one language.** Asking whether a Hebrew verse and a
Greek one are "the same" conflates the numbering question with the translation question.
Comparing Brenton's Septuagint against the Douay-Rheims — both English, made from the two
traditions being aligned — asks only the one that matters.

| pair | witnesses | language |
|---|---|---|
| `org`–`eng` | `ojb` / `web` | English |
| `org`–`lxx` | `ojb` / `brenton` | English |
| `org`–`vul` | `ojb` / `dra` | English |
| `eng`–`lxx` | `web` / `brenton` | English |
| `eng`–`vul` | `web` / `dra` | English |
| `lxx`–`vul` | `brenton` / `dra` | English |
| `vul`–`nvl` | `latvuc` / `novavulgata` | **Latin** |

Seven of the ten family pairs. The three missing all involve the Nova Vulgata, held here
only in Latin, which no other family has.

**Every verse is checked, not only the mapped ones.** A mapping file records exceptions, so
a verse it does not mention is *asserting* that none is needed — an assertion as capable of
being wrong as an explicit mapping, and only a full sweep catches a mapping that should
exist and does not. About 200,000 comparisons, 173 seconds.

## Reading the output

The first run flagged 4,164 verses. Almost none are faults. They cluster in Numbers,
Exodus, Leviticus, 1 Chronicles, Job and Proverbs — the censuses, the tabernacle
instructions, the genealogies — where adjacent verses are nearly identical and a neighbour
wins by chance.

What a real fault looks like is different: **a run of consecutive verses all preferring the
same offset.** Filtering on runs of three or more reduced 4,164 flagged verses to **60
runs**. That filter is the whole discrimination, and it is available as `--min-run`.

| pair | decisive comparisons | agree |
|---|---|---|
| `org`→`eng` | 30,904 | 99.28% |
| `org`→`lxx` | 22,450 | 96.37% |
| `org`→`vul` | 30,559 | 97.55% |
| `eng`→`lxx` | 27,575 | 97.58% |
| `eng`→`vul` | 32,944 | 98.06% |
| `lxx`→`vul` | 24,591 | 96.43% |
| `vul`→`nvl` | 32,991 | 99.41% |

## The second instrument

A local `gemma-4-E4B-it-qat` on llama.cpp, constrained by the GBNF grammar
`root ::= "YES" | "NO"`, asked whether two verses are the same passage. It reads across
languages, which is what the deterministic test cannot do.

**Every verse is asked twice.** Once about the mapping, once about a verse deliberately
next door. A model inclined to agree says YES to everything and hands back a clean bill of
health for a corpus full of errors — which is worse than not asking, because it looks like
evidence. Only YES to the mapping and NO to the neighbour counts as confirmation.

Over the 60 runs: **39 agreed** the text sits at the offset rather than the mapping, 17
matched neither candidate, 3 could not tell them apart, and **1 was called a false alarm**
(`lxx`→`vul` Leviticus 15:19–22).

### Where the model could not be used, and why

The three `nvl` pairs have no same-language witness, so they were to be the model's own
territory. Run against `nvl`→`org`, it reported contradictions on 6.9% of verses. Reading
six of them showed all six were plainly the same verse:

> `nvl` *Quo mortuo et universis fratribus eius* — `org` "And Yosef died, and all his achim"

The `org` witness is the Orthodox Jewish Bible, which transliterates its Hebrew heavily:
*achim*, *meyalledot*, *nogesim*, *avodah*, *Melech Mitzrayim*. A small quantised model
reads that as a foreign language and rejects the pair. Swapping the witness for a plain
English Bible flipped four of nine test verses from NO to YES — and the model still got two
of nine wrong on verses that are unambiguously correct.

**The control probe did not catch this, and the reason is a fault in this module's own
logic that the episode exposed.** The probe was designed against a model too eager to
agree. A model too eager to *disagree* answers NO to the mapping and NO to the control, and
the original rule scored that as a contradiction — when in truth it is the model saying it
cannot read either text. Corrected so that only a *discriminating* answer counts in either
direction, the same 3,500 judgements yield **11 contradictions instead of 247**, a
twenty-two-fold reduction. The rule is now pinned by `tests/test_judge.py`.

The run was stopped rather than completed. `nvl` does not need it: `nvl`↔`vul` is
Latin against Latin, the strongest comparison available anywhere in this audit, and it
already scores **99.41%**. `nvl` against the other families follows from that through
`vul`, which is itself checked against all three.

## What was found and fixed

Five faults, all of them silent, all now corrected in `corrections.json` with their
reasoning and pinned by `tests/test_alignment.py`.

**1. The Vulgate's Jonah.** `vul.json` carried the *English* Jonah mapping —
`JON 1:17 → JON 2:1` and `JON 2:1-10 → JON 2:2-11`. The proof is in the file's own data:
it gives Vulgate Jonah 1 sixteen verses, so the source verse `JON 1:17` does not exist.
Only the English tradition puts the great fish at 1:17; the Vulgate follows the Hebrew,
where it opens chapter 2. Four witnesses agree — the Clementine and Nova Vulgata both read
*Et praeparavit Dominus piscem grandem* at 2:1, the Douay-Rheims has no 1:17 at all, and
Brenton's Septuagint puts the fish at 2:1. Only the World English Bible has 1:17.

**Every Vulgate citation of Jonah 2 resolved one verse late.** Asking for Jonah 2:1 in
Vulgate numbering returned Jonah's prayer instead of the fish that prompted it. Corrected,
with reasoning, in `corrections.json`; pinned by `tests/test_alignment.py`; Jonah now
scores 100% agreement across all seven pairs.

That fault also yielded a cheap invariant now enforced as a test: **no mapping may name a
verse its own system does not have.** A file that does is describing a different Bible.

**2. Bel and the Dragon, one verse out for its entire length — and an error of mine.**
The data carries both `DAN 13:65 -> BEL 1:1` and `DAN 14:1 -> BEL 1:1`, and an earlier
pass over this file took them for two printings of one verse and *preferred* 14:1. They
are two different verses. The Clementine's 13:65 is *Et rex Astyages appositus est ad
patres suos*, which is Bel 1:1; its 14:1 is *Erat autem Daniel conviva regis*, which is
Bel 1:2. The Clementine closes Susanna with the Astyages sentence instead of opening Bel
with it, so the whole book runs one behind. Measured against the Douay-Rheims, Bel 1:n+1
beats Bel 1:n on **41 of 42 verses**. Corrected to `DAN 14:1-41 -> BEL 1:2-42`.

This is also why the first pass of this audit called Bel "an edition difference, not a
mapping fault" — a conclusion that was wrong, and wrong because it stopped at the first
plausible explanation instead of counting the verses.

**3. Baruch 3:35–37.** The English merges the star passage into a single 3:34 — *"The
stars shone in their watches, and were glad. When he called them, they said, Here we
are"* — where every other system splits it. English Baruch 3 therefore has 37 verses and
the rest have 38, and no mapping recorded it. A citation of Baruch 3:36 returned *"He
found out all the way of knowledge"* instead of *"This is our God, and there shall no
other be accounted of in comparison to him."*

**4. The Letter of Jeremiah.** The English counts the letter's heading as verse 1 and the
Latin does not, so the English runs one ahead for all 72 verses. The old mapping sent its
last verse to `LJE 1:73` — a verse org does not have. That is the Jonah ghost pointing the
other way, and it is now caught by its own invariant: **no mapping may target a verse the
pivot lacks.**

**5. Greek Daniel 5/6 in the Vulgate file.** `DAG 5:1-31 -> DAN 5:1-31` targets an org
verse that does not exist, and `DAG 6:1-28 -> DAN 6:1-28` then leaves org's Daniel 6:29
unreachable. The sentence at issue is *"And Darius the Mede succeeded to the kingdom"*,
which the Greek and Latin print as 5:31 and the Aramaic as 6:1 — and the same file already
states the shift correctly for ordinary Daniel. Found by the second invariant, minutes
after it was written.

**One consequence worth stating on its own.** Every verse of `eng`, `lxx` and `vul` now
round-trips through the pivot and comes back to itself. There used to be exactly one
residual, documented in the test suite as a principled exception — the Bel preference. It
was not principled; it was the symptom of fault 2. The test now asserts an empty list.

## What was found and is *not* a fault

This is the part that matters for reading the other 39, and it is why they are not
presented as 39 bugs.

**Bel and the Dragon (40 and 41 verses, two pairs).** The largest run in the whole audit,
and both instruments agree the text is offset. It is not a mapping error. The Clementine's
Daniel 14:1 reads *Erat autem Daniel conviva regis*, while the Nova Vulgata and the Greek
both begin *Et rex Astyages appositus est ad patres suos*. The Clementine simply **omits
the Astyages verse** and still numbers its chapter 1–42. The 1979 revision restored it. The
editions genuinely differ; the mapping aligns the numbers, which is its job.

**Deuteronomy 29 and the Letter of Jeremiah (Brenton), Jeremiah 31 and Job 3 (Orthodox
Jewish Bible).** Here the confound is the witness rather than the data. Brenton's Letter of
Jeremiah has 73 verses where every system declares 72, and its Deuteronomy 29:1 matches the
Douay's rather than sitting one behind. The Orthodox Jewish Bible begins Jeremiah 31 a
verse later than every other witness and merges Job 3:1 with 3:2. Both corpora are
correctly filed — Brenton fits `lxx` at 97%, the OJB fits `org` at 99% — but each has a
tail, and the tail lands in the audit as a run.

This matters more for `org` than anywhere else, because the OJB is its only full English
witness. Results on the `org` side carry that noise floor and should be read with it.

**The limitation this exposes, stated plainly:** both instruments measure whether the
*text* lines up. Neither can distinguish "the mapping is wrong" from "the two editions
print different content" or "this witness is idiosyncratic here". Separating those needs a
person, and a single family pair is never enough evidence — the Bel case was only settled
by reading four editions in three languages.

**Sirach 6 (15 verses).** All four systems give Sirach 6 thirty-seven verses, and both
witnesses have thirty-seven — they simply put the verse breaks in different places. The
Vulgate's Sirach is a different recension, 1,605 verses to the Greek's 1,401, which is
already why the versification refuses to convert it.

**The Letter of Jeremiah.** The World English Bible and Brenton both give it 73 verses; the
Douay-Rheims gives it 72, and the versification data declares 72. So two corpora carry a
verse the data does not know about — an upstream count that follows the Latin where the
Greek tradition has one more.

**Exodus 39 (three pairs, three different offsets).** The most tempting of the lot, and the
one that looked most like a second Jonah: the Clementine puts the golden plate at 39:29
where the Nova Vulgata and the World English Bible put it at 39:30, all four editions have
exactly 43 verses, and there is no mapping entry at all — the data asserts identity.

Mapping the offset verse by verse is what settles it. It is not a shift. It swings +1, 0,
−1, +2 and back across the chapter, with similarities between 0.10 and 0.73, and Brenton's
Septuagint has 23 verses where the others have 43. This is the tabernacle account of
Exodus 36–40, which the traditions genuinely rearrange rather than renumber. Asserting
identity is a simplification, but no offset mapping would be less wrong, because the
material is not in the same order on both sides.

The lesson generalises: *a run of flagged verses is necessary evidence of a fault, not
sufficient.* What made Jonah provable was a mechanical impossibility — a mapping keyed on a
verse the system does not have. Nothing else so far has one.

## The English family

All 46 corpora filed under `eng`, each checked against the World English Bible verse by
verse with the same offset test. Reference-based rather than pairwise: if every corpus
agrees with the reference, they agree with each other, and the 1,035-edge graph costs
twenty times as much to establish the same thing.

**Forty of forty-five align at 95% or better**, the WEB variants at exactly 100% as they
should. Five came in lower: `wycliffe` 91.8%, `pev` 92.4%, `nna` 93.1%, `aoi` 93.5%,
`barkly` 93.7%.

None of them is misfiled. They are Wycliffe portions and Australian community translations
— Anindilyakwa, Nyangumarta, Barkly, Plain English Version — all partial and all
deliberately paraphrastic, which is exactly the material a similarity test loses power on.
Their drift is scattered rather than systematic (283 of 9,381 verses for `wycliffe`, 3%),
and the independent structural check agrees: every one of the five fits `eng` better than
any other system. The right reading is that the instrument goes quiet on free translations,
not that these belong somewhere else.

## Structural proofs

The textual audit measures. These prove, and they need no corpora at all -- which is why
they are the only thing that reaches `rsc` and `rso`, neither of which has any text.

Four invariants now hold over all seven systems and are enforced by the test suite:

1. **No mapping names a source verse its own system lacks.** A file that does is describing
   a different Bible. This is what identified the Jonah fault.
2. **No mapping targets a verse the pivot lacks.** The mirror. It identified the Letter of
   Jeremiah, and then Greek Daniel 5:31 within minutes of being written.
3. **No conversion can return a verse that does not exist.** The strongest of the four,
   because it is checked over every verse of every system rather than over the mapping
   entries: 253,000 conversions, all of which now land somewhere real.
4. **Every verse of `eng`, `lxx` and `vul` round-trips through the pivot** and comes back
   to itself, with no exceptions.

Invariant 3 was worth 29 defects on first run. Two were fixable by transposing a mapping
the sibling file already stated correctly -- the Nova Vulgata's Daniel 3:91-100, and the
English Letter of Jeremiah in its standalone form. The other eighteen were not fixable at
all, because they are genuine textual pluses with no counterpart on the other side: the six
extra verses of Greek Joshua 24, the pluses in Greek Proverbs 4, the Esdras material, the
sixty-eighth verse of the Song of the Three. For those the fall-through was inventing a
reference that looked like an answer and pointed at nothing, so `convert_all` now refuses
instead. A refusal is the honest result, and it is what this library already does
everywhere else it cannot resolve something.

## Status

- **5 mapping faults found and fixed**, each confirmed against the text of two or more
  editions: Jonah, Bel and the Dragon, Baruch 3, the Letter of Jeremiah, and Greek Daniel
  5/6. All pinned by `tests/test_alignment.py`.
- **Every verse of `eng`, `lxx` and `vul` now round-trips through the pivot**, with no
  documented exceptions left.
- **Runs fell from 91 to 85**, but the count understates it: the runs that went were the
  large ones. Bel alone was 81 verses across two pairs, and Baruch and the Letter of
  Jeremiah another 60.
- **Every run of ten verses or more has now been read.** Beyond the five faults, they fall
  into two kinds and neither is a defect in the data: editions that genuinely differ
  (Exodus 39's tabernacle account, rearranged rather than renumbered; Sirach, a different
  recension at 1,605 verses to the Greek's 1,401) and witnesses with their own verse
  divisions (Brenton in Deuteronomy 29 and the Letter of Jeremiah; the Orthodox Jewish
  Bible in Jeremiah 31 and Job 3).
- **All 45 English corpora verified as belonging to `eng`**, forty by text alignment
  directly and five by the independent structural check where paraphrase defeats the
  text test.
- **7 of 10 family pairs audited deterministically.** The three `nvl` pairs cannot be, and
  the model turned out not to reach them either — but they do not need it. `nvl`↔`vul` is
  Latin against Latin at 99.41%, the strongest comparison in the audit, and `vul` is itself
  checked against the other three families.
- `rsc` and `rso` cannot be audited textually at all — no corpora exist in either
  versification, so only their internal consistency is checkable, which the loader already
  enforces.

The honest summary: one real fault, found and fixed, in mappings that are otherwise sound
to the limit of what two independent instruments can establish — and a clear-eyed account
of what those instruments cannot establish, which is the difference between a wrong mapping
and two editions that genuinely disagree.

## Running it

```bash
biblereference audit                  # every pair, every verse
biblereference audit --book JON       # one book
biblereference audit --min-run 5      # only the clearest runs
```

## The exhaustive walk

`biblereference audit` compares corpora against each other. `biblereference coverage` asks
a different and blunter question: take **every verse of every versification**, convert it,
and account for what came back. Not a sample — 155,578 conversions, about seventy seconds.

Every verse lands in exactly one bucket, and the buckets are chosen so nothing can be
quietly counted as fine:

| bucket | meaning |
|---|---|
| refused | the data says these cannot be lined up. A stated refusal is an answer |
| **ghost** | returned a verse the pivot does not have. **Must be zero** |
| confirmed | a faithful witness on each side, in one language, and the mapped position explains the text better than its neighbours do |
| contradicted | a neighbour explains it better — only meaningful in runs |
| weak | too little shared vocabulary to be evidence either way |
| unwitnessed | structurally sound, textually unchecked, because no faithful witness reaches it |

Current state:

```
eng   40,493 verses   0 ghosts     847 refused   30,903 checked (76.3%)  99.586% confirmed
lxx   40,284 verses   0 ghosts     631 refused   19,639 checked (48.8%)  97.632% confirmed
vul   39,160 verses   0 ghosts   3,111 refused   30,182 checked (77.1%)  98.304% confirmed
nvl   35,641 verses   0 ghosts   2,022 refused        0 checked  (0.0%)        - confirmed
```

**Zero ghosts across all 155,578 conversions.** It was 70 before this pass: the Greek
additions to Daniel are a separate `DAG` in `org` and folded into `DAN` everywhere else,
and the mappings pointed at verses that did not exist. Comparing `MAX(verse)` over the
corpora could never have found it, because the corpora carry those verses even where the
versification does not declare them.

**Half of it cannot be checked against text, and that is the number worth reading.**
"Not contradicted" is not "verified". `nvl` is the extreme case at 0%: its only witness is
the Nova Vulgata itself, in Latin, and `org` has no Latin witness — so there is no
same-language pivot partner anywhere and not one of its 35,641 verses can be checked this
way. It is verified against `vul` instead, Latin against Latin at 99.8%, by the pair
derivation. That is a weaker claim and is recorded as one.

Of the 1,105 contradicted verses, **seven fall in runs of four or more** and every one is a
known textual fact rather than a mapping error: the Septuagint and the Douay reorder and
condense the tabernacle account (`EXO 36`, `EXO 39`), and the censuses and tribal lists
(`NUM 1`, `NUM 26`) are where identically-shaped neighbouring verses
outscore the true match by accident. `NUM 1:6` is "Of Symeon, Salamiel the son of
Surisadai" in Brenton and "Of Shim'on, Shelumiel ben Tzurishaddai" in the Orthodox Jewish
Bible — the same verse, mapped by identity, correctly.

Isolated flags are noise; runs are faults. Only runs are evidence.

```bash
biblereference coverage               # the whole walk; non-zero exit if any ghost
biblereference coverage --min-run 6   # only the longest runs
```

`tests/test_coverage.py` pins all of this, including the runs by name, so a new one
appearing is a test failure. `vul LEV 15` used to be among them and was not repetition at
all -- see the next section.

## The residue, read verse by verse

The exhaustive walk narrows a claim; it does not settle one. Every disagreement outside the
four books already known to be bodily reordered (Exodus, Jeremiah, Numbers, 3 Kingdoms) was
then read against the text, in the source language wherever a witness exists. That is 99
disagreements across about 25 chapters, and the answers divide three ways.

**Twelve were faults in the data.** Each is now written down with its evidence:

| | |
|---|---|
| `eng BAR 6:44-50` | The English Letter of Jeremiah is not one straight offset. It merges two verses at 6:43 and splits one at 6:50, and the two cancel — so 6:44 to 6:50 agree exactly with the Latin, where a single range had made them all one out. "Whatsoever is done among them is false" was resolving to "when any one of them lieth with him". Eight English witnesses and three Latin, unanimous. |
| `nvl SIR 14:17-25` | The Nova Vulgata splits the Greek's Sirach 14:16 exactly as the Clementine does. Recording it for one Latin edition alone made the two disagree across nine verses where they agree word for word. |
| `lxx MAL 3:22-24` | The Greek Malachi puts "Remember the law of Moses" last. Swete has it at 4:6, Brenton at 3:24; the Hebrew has it first at 3:22. A three-verse rotation — which is why a monotonic alignment could only ever report two thirds of it. |
| `vul MAT 5:4-5` | The Clementine puts the meek before those who mourn. A real variant of the Latin tradition, not a numbering habit, and upstream recorded identity — so both beatitudes answered with the wrong verse. |
| `vul LEV 15:20-23` | The Douay splits the Hebrew's 15:19 in two. This one was found by the exhaustive walk as a run of four, and looked exactly like the repetition-noise the other runs are. |
| `vul MIC 5:11` | Merges org 5:10 and 5:11; upstream named the second, which left "I will cut off the cities of thy land" unreachable. Settled three disagreements at once. |
| `vul 1MA 1:36`, `1:52-54` | The Douay divides the chapter twice where org divides once, and the two cancel — so only the verses between them were wrong. |
| `vul REV 20:7-8` | The Clementine merges org 20:7 and 20:8, so "he shall go out to deceive the nations" was resolving to "and they went up on the breadth of the earth". |
| `vul MAT 17:14` | Merges org 17:14 and 17:15; naming the first left "Lord, have mercy on my son" answering with "and I brought him to thy disciples". |
| `eng`/`nvl NEH 7:68` | org has no counterpart to the horses of Nehemiah 7:68 — the Leningrad Codex goes straight from the singers to the camels. The Clementine said so and the other two did not. |

**A rule came out of it.** A system verse carrying two org verses can name only one, because
the forward direction is one-to-one; the reverse fills gaps with the identity. So the target
to name is **the one the identity will not reach** — the second where the system is in step
before the merge and one behind after, the first where it is one ahead before and in step
after. Naming by "whichever the verse opens with" looks principled and is wrong half the
time. Five of the twelve faults above were that mistake. It is written up as
`_merged_verse_note` in `corrections.json`.

**The rest are the instrument, not the data**, and each was confirmed by reading:

- **Brenton is not always the Septuagint.** He merges Proverbs 7:6-7, he prints Joshua 24 in
  the Hebrew order where Swete follows the Greek, and he silently restores the Hebrew order
  of the Decalogue in Deuteronomy 5 where Swete has "Οὐ μοιχεύσεις" before "Οὐ φονεύσεις".
  In all three the vendored data is right and the witness is the outlier. This is why a
  Greek witness was consulted rather than an English one wherever the question was Greek.
- **Monotonic alignment cannot express a transposition or a swap.** Ezekiel 7:3-9 was read
  verse by verse and the data has it exactly (org 3→7, 4→8, 6→3, 7→4, 8→5, 9→6); the
  aligner reports twelve disagreements because it cannot go backwards. The same is true of
  Malachi 3 and Matthew 5 *after* they were fixed — correcting them raised the derivation's
  disagreement count while making the data more correct.
- **A merged verse always reads as a disagreement.** The aligner matches by bulk and lands
  on whichever half is longer, which is not the half the mapping names. Joshua 21,
  1 Chronicles 12, Acts 7, Acts 14, Nehemiah 3, 1 Samuel 20 and Baruch 3 are all this, and
  in every one of them the vendored arrangement is the one that keeps both org verses
  reachable.
- **Two org verses have no counterpart in one system at all** — `LJE 1:43` in `eng` and
  `1MA 1:49` in `vul` — because the merge sits inside a longer re-division and there is
  nowhere honest to put them. The file says so rather than guessing.

### The four reordered books

`EXO`, `JER`, `NUM` and `1KI` were set aside above because the Septuagint rearranges them
bodily and a monotonic alignment cannot follow it. That is true of most of what they
contain, but not all: sorting their 466 disagreements by whether the offset stays inside one
chapter separates the reordering from the rest, and what stayed inside a chapter was read
the same way as everything else. Four more faults came out of it:

| | |
|---|---|
| `lxx NUM 10:34-36` | The Greek moves the cloud verse to the end of the chapter — "Arise, O Lord" at 10:34 and "the cloud overshadowed them by day" at 10:36, where the Hebrew and both Latin editions have the cloud first. A second three-verse rotation, like Malachi's. |
| `vul NUM 27:4-7` | The Clementine, like the Septuagint, has no counterpart to the daughters' plea at org 27:4. The Greek entry had been written and the Latin one had not, so the two Latin editions disagreed across four verses. |
| `lxx NUM 21:19-21` | A merge and a split that cancel: the Greek runs org 21:19 and 21:20 together and then divides org 21:22 in two, so both chapters end at 35 while three verses in between were displaced. |
| `vul NUM 15:15-17` | The same shape in the Douay, which merges org 15:15 and 15:16 and splits org 15:18. Both chapters end at 41. |

Those last two are the case verse counts cannot see at all, and they are the reason counting
was never the instrument here.

`EXO 39` and `EXO 40` were examined again and left alone. In both the Douay condenses rather
than displaces — three Hebrew verses become one Latin one — so there is no offset to write,
and the vendored arrangement already reaches two of every three. `EXO 36`, the Greek
tabernacle account, is reordering across chapter boundaries and stays as it is.

### What the count is worth

Not much on its own. The derivation's disagreements fell from 1,505 to 517 over this work,
but the last hundred moved in both directions: correcting Malachi 3 and Matthew 5 *raised*
the count, because the aligner cannot follow a swap it now has to disagree with. Only
reading settles which way is right.

The measures that did move in one direction are the structural one — 0 ghosts, from 70 — and
the textual confirmation rate, 98.62% to 98.63% on 80,000 checkable conversions, with
`vul LEV 15` dropping out of the runs of four. That last is what a real fault looks like
when it is fixed.

## Two questions, two answers: covering conversion

The mapping model is a function one way and a relation the other. `to_org` gives exactly one
answer; `from_org` gives as many as it needs. That asymmetry is behind most of the hard cases
above. When a verse carries the text of *two* org verses — the Douay's `MAT 17:14` is both
"there came to him a man falling down on his knees" and "Lord, have mercy on my son" — the
forward map can name only one, so the other becomes unreachable. `_merged_verse_note` is the
rule for choosing, and five of the faults listed above were that choice made wrongly before
the rule existed.

So conversion now answers two questions, and you pick which:

```python
vrs.convert_all(ref, "org")  # which verse *is* this one
vrs.convert_all(ref, "org", covering=True)  # every verse needed to carry all of its text
```

```bash
biblereference render --covering  # and verify, compare, audit, coverage
```

The default is unchanged, byte for byte. Covering is a superset: it never loses an answer,
never refuses where the default succeeds, and always comes back in reading order within a
single book. It makes `org LJE 1:43` and `org 1MA 1:49` reachable, which nothing could
before — English carries the first inside Baruch 6:43 and the Douay carries the second
inside 1 Maccabees 1:51.

**Nothing in it is derived, and that was not the original plan.** Deriving looked free: for
921 verses the library already answers an org reference with a system verse whose own forward
answer is a *different* org verse, and treating that as a covering relation would have cost
nothing to implement. It would also have been wrong. Those 921 are the identity fall-through
— what conversion returns when nothing maps to an org verse and it simply keeps its
coordinates — and a fall-through is a guess, not a reading. Greek Exodus 36:9 is "he made the
ephod of gold", part of the tabernacle account the Septuagint moves bodily; org's 36:9 is
"the length of each curtain was twenty-eight cubits". Deriving would have declared that one
contains the other, in 921 places, with no evidence at all.

So `covers` in `corrections.json` holds twenty entries, each read against the text and each
citing the two verses' opening words. Where there is no entry, covering answers exactly what
the default does. A covering claim is worth precisely the reading behind it.

### What it is worth measuring with

Two things move, and one does not.

**The derivation falls from 517 to 502.** Every one of those fifteen was a false flag: a
merged verse always read as a disagreement, because the aligner matches by bulk and lands on
whichever half is longer, which need not be the half the exact map names. `vul`→`nvl` alone
goes from 38 to 25. This is what stops correcting a mapping from *raising* the count, as
Matthew 5 and Malachi 3 did.

**The round trip is now a checkable claim.** Convert every verse into another system and
back, measured through the pivot so that a book with two names does not count as a loss, and
you must land on the text you started from. Over all 753,562 ordered conversions between all
twenty ordered pairs: **2,939 failures under the exact map, 2,851 under covering.**

That remaining 2,851 is the honest work queue, and it is dominated by places where the
question is not really about numbering at all — Greek 2 Esdras (1,702) and Greek Esther (501)
are differently *built* books, not differently numbered ones; then the psalm superscriptions
(~313) and the Greek reorderings of Exodus and Jeremiah (~200). `tests/test_coverage.py`
pins the count so it cannot climb quietly.

The model pass moved it by four, in both directions and for good reasons either way. Four
were *added* by correcting `lxx EXO 36:24`, and they are honest: org's Exodus 36:24 is the
forty silver sockets, the Greek's is the golden wreaths on the rings, and now that the
library knows the second it can no longer pretend the first comes home. Eight were removed by
recording where a Nova Vulgata verse of Sirach carries two of org's. Every reordering
corrected — Numbers 26, Jeremiah 38, Deuteronomy 23 — left the count untouched to the verse,
which is the check a permutation has to pass.

**The exhaustive walk barely moves**, because it scores each conversion at its first target
and covering only ever adds a second. That is worth saying plainly rather than leaving as an
implication: covering improves the *derivation* and the *round trip*, not the textual
confirmation rate.

---

## The model pass, exhaustively

The audit above uses a model on 60 verses. This section is what happened when it was run on
all of them: **126,597 conversions judged**, every one that any witness could reach, over two
nights.

### The witness question, which decided the first run

Run one produced 87 survivors and 82 of them rested on `web` speaking for `org` — an
English-tradition corpus standing in for a system it does not follow. Wherever `eng` and
`org` diverge in numbering, that witness is answering about the wrong verse, and the run was
measuring the gap between two families rather than testing a mapping. It was found from the
inside: `vul MAT 23:13` was flagged, and `vul` and `org` plainly agree there while `web` is
the one out of step.

Reordering the witnesses so that `org` is spoken for by corpora that follow `org` — `wlc`
first, then `n1904`, and only then English — took calibration from 28/28 to **47/47** and
was worth re-running the whole thing for. `witness_for` also had to stop at the first
*faithful* witness rather than the first witness, because `wlc` is a Hebrew text with no New
Testament and no deuterocanon.

### What it agreed with

On verses the deterministic walk had already confirmed, the model agreed on **73,143 of
73,182 informative answers — 99.947%**. That is the number that makes the disagreements worth
reading: two instruments that fail differently, agreeing this closely, mean the residue is
small and readable rather than a wall.

131 contradictions, **107 surviving three fresh seeds**. Split by which instruments spoke:

| | verses | |
|---|---|---|
| both instruments | 43 | four real faults, and the rest repetition |
| model only, nothing else could reach it | 40 | three real faults, all invisible to every other check |
| deterministic said fine | 24 | all artefacts, twenty-two of them one cluster |

### What it found that nothing else could

Seven corrections came out of the 107, and three of them exist only because a model was run.

**`nvl TOB 9:3-4` — Tobias's two reasons, reversed.** He sends Raphael ahead and gives two:
Raguel has made him swear to stay, and his father is counting the days. Swete's Greek puts
the oath first, and so do the World English Bible, the King James, the American Standard,
the Revised Version and Brenton. The Nova Vulgata gives them the other way round, following
the Old Latin order the Clementine also keeps, while numbering with the Greek.

**`nvl JDT 16:1-8` — one verse early throughout**, verified against `web`, `dra` *and*
`brenton`, all three agreeing against the Nova Vulgata.

Neither was reachable by anything else, and the reason is worth stating exactly: `nvl` has
one witness, in Latin, and `org` has none in Latin. **Not one of its 35,641 conversions is
checkable against text**, so the coverage walk does not move by a single verse for either
correction. It scores `nvl` at 0% and that zero is honest.

**`lxx JER 38:35-37` — the Greek swears by the heavens first.** After the new covenant the
Hebrew gives the ordinances of sun and moon, the oath that Israel will not cease while they
last, then the oath about measuring the heavens. The Greek puts the heavens first. Here the
deterministic walk had no witness for a different reason: the Orthodox Jewish Bible has 39
verses in Jeremiah 31 where the Hebrew and the English both have 40, so `faithful_chapters`
refuses it, and the remaining `org` witnesses are Hebrew and Greek — neither of them English,
so no same-language comparison exists.

### What it found that the walk found too

Four more, each flagged by both instruments and settled by reading:

* **`lxx EXO 36:24-38`**, fifteen verses one low, because upstream left 36:24 unmapped as
  though it were a Greek plus. It is not: "they put the golden wreaths on the rings on both
  sides of the oracle" is org 39:17.
* **`vul EXO 38:25-26` and `39:17-38`**, twenty-three verses that nothing upstream said a
  word about. This settled the long-standing refusal to touch Exodus 39 recorded in `TODO.md`.
* **`lxx NUM 26:15-47`**, the Greek second census, which puts Gad sixth and Asher seventh.
* **`lxx DEU 23:25-26`**, the cornfield and the vineyard, reversed.

### Reorderings are expressible, which this audit had wrong

The standing rule was that a transposition cannot be described and should keep identity with
a note. Numbers 26 disproves it. The mapping is a dict, not an offset, and where the moved
blocks have the same number of verses on both sides — which they do, because a reordering
moves material rather than redividing it — the result is an exact bijection. The nine ranges
for Numbers 26 tile 26:15-47 once each; the covering round trip does not move by a verse,
which is the check that a permutation must pass. Jeremiah 38 is a three-cycle and Deuteronomy
23 a two-cycle, both by the same argument.

What genuinely cannot be expressed is a **split and a merge inside one renumbered chapter**.
`latvuc` Psalm 108 looks like one: it breaks org 109:16 at a comma and joins 109:17 and
109:18. Correcting that would leave one org verse with no source, and because the psalm is
renumbered the coordinate fall-through lands in a different psalm — `vul PSA 109` declares
seven verses, so org 109:18 would resolve to a verse that does not exist. It is moot here,
because the Nova Vulgata settles it the other way, but the limit is real and worth knowing.

### The three categories of false alarm

Nearly a hundred flags were read and found correct. They sort into three kinds, and naming
them is what lets the next run's identical flags be dismissed by reference:

**Repetition.** The censuses and the lists. `NUM 1:6-9` in both `lxx` and `vul` is the list of
tribal princes — "Of Simeon, Salamiel the son of Surisaddai" — where Brenton, the Douay and
the World English Bible agree verse for verse and identity is exactly right. Both instruments
flag it, and that is the useful part: **they share this failure mode**, because both ask how
well the text matches and neither can tell twelve near-identical verses apart. The `lxx EXO
25` cluster is the same thing at scale — 22 of the 107 survivors, in a loose translation of
repetitive instructions, all provably correct.

**Free translation.** The Greek abbreviates Jeremiah and Job and gives Proverbs a different
second line; the Douay renders "when the congregation was assembled against Moses and Aaron"
as *cumque oriretur seditio, et tumultus incresceret*. Same verse, different words.

**A corpus, not a system.** Three of these, and they are the most interesting because each
one indicts an instrument rather than the data:

* `latvuc`/`dra` Psalm 108, above — the Nova Vulgata, Latin and independent, agrees with
  `org` and with the mapping.
* `brenton` Joshua 24, which puts "Israel served the Lord" at 29 and Joshua's death at 30,
  reversing the Hebrew. Swete's Greek has them in the Hebrew order. **The faithful-chapter
  restriction cannot see this**, because it compares verse counts and both are 33 — the
  blind spot `faithful_chapters` already documents, now with a second instance.
* `web` Matthew 23:13, which alone among the Greek, the King James and the Douay puts
  "devour widows' houses" first.

### Text-type variants are not versification faults

Three findings were carried into the correction plan as verified and should not have been.
The distinction that kills them is worth stating flatly: **a versification difference is the
same words under different numbers; a text-type variant is the same number over different
words.**

`MAT 21:29-30`, the two sons, differs by manuscript family — but verse 30 begins "he came to
the second" in *both* the Greek and the English, so the verse boundaries are identical and
only the answers inside them are swapped. Mapping across it would be wrong. `PHP 1:16-17`
transposes love and rivalry between the Received Text and the critical text, and English
Bibles themselves disagree — the World English Bible and the King James one way, the ESV and
NIV the other — so `eng` cannot assert either. `MAT 23:13-14` is the `web` quirk above.

None was applied. That they were on the list is the reason this section exists: **a finding
that has not been read is not a finding**, however many instruments agree, and the plan that
carried them said so about a different group without noticing it applied to these.

### Re-judging the corrections

The cheapest possible check on the whole exercise, and it was run last: take every conversion
this audit changed, and put the **old answer against the new one** to the model. A correction
that was right should turn its own contradiction into a confirmation.

85 conversions changed — 33 in `lxx NUM 26`, 21 in `vul EXO 39`, 15 in `lxx EXO 36`, 7 in
`nvl JDT 16`, 3 in `lxx JER 38`, 2 each in `lxx DEU 23`, `vul EXO 38` and `nvl TOB 9`. Judged
against a calibration of 47/47:

```
confirmed      62
uninformative  23
contradicted    0
```

**Zero.** Where the model could tell the two candidates apart it preferred the new answer
every time, and the 23 it could not are the repetitive stretches — consecutive verses of the
tabernacle inventory and the census — where that is the expected answer rather than a
worrying one.

---

## The second model pass — with Syriac, Rahlfs and three Greek New Testaments

The pass above ran against four languages and 55 corpora. This one ran after the TEI import
(see `docs/tei-corpora.md`) added Syriac, Coptic, the Peshitta, Rahlfs, the SBLGNT and
Westcott–Hort, and it is worth recording separately because **the instrument changed, not
just the sample**.

**128,153 verses judged, 113,880 informative, 138 contradicted — 99.879% agreement.**

```
                judged   confirmed  contradicted  uninformative
suspicions       1,432         947            26            459
gap             46,724      39,542            68          7,114
confirmed       79,997      73,253            44          6,700
```

### What the Syriac actually bought

The concrete number is in the witness split for the gap phase — the verses no same-language
witness can reach:

```
who answered for `org` on 46,724 gap tasks
  wlc          24,036   Hebrew
  peshitta-ot  11,622   Syriac    ← new
  n1904         7,451   Greek
  web           3,595   English
```

The Peshitta took over as `org`'s witness for **11,622 verses** — overwhelmingly the
deuterocanon, where `wlc` has nothing and `n1904` no Old Testament, and where the question
had therefore been falling through to an English-tradition text speaking for `org`. That is
the exact fault that invalidated the first overnight run and had to be found from the
inside. It is now answered by a second-century translation made from the Hebrew.

**It confirmed the mappings rather than upsetting them.** 34 of the 138 contradictions rest
on the Peshitta, out of 11,622 tasks: 0.29%.

### One fault, in 128,153 judgements

`vul DEU 6:12-13`. The Vulgate makes a whole verse of what the Hebrew ends 6:11 with — *et
comederis, et saturatus fueris* — and then joins org 6:12 and 6:13 into one. The split and
the merge cancel, both chapters have 25 verses, and identity looked right. It matters more
than two verses usually would: org 6:13 is what Matthew 4:10 quotes, and a citation of the
Vulgate's 6:13 had been resolving to *beware lest thou forget*.

Re-judged against its own old answer with the model: confirmed.

That is the whole of it. Everything else read was a known cluster, a verse already settled
in the first pass, or an artefact — and the artefacts are worth naming because they are the
same three kinds as last time, arriving through new witnesses.

### The three kinds of false alarm, again

**A shorter recension.** `1MA 10:44` was flagged in `eng`, `lxx` *and* `vul` — three systems
independently, which is normally what a real textual fact looks like. Every Latin, Greek and
English witness has the same verse; the **Peshitta's is abbreviated**, lacking the "expense
from the king's revenue" clause, so the model preferred the neighbour that has it. The
Peshitta's Maccabees, Tobit, Wisdom and Baruch are shorter texts throughout, which makes it a
weaker witness *there* than its 82% overall faithfulness suggests. Worth knowing before
trusting a deuterocanon flag that rests on it.

**Model noise on identical text.** `eng GEN 48:12` — "Joseph brought them out from between
his knees, and he bowed himself with his face to the earth" against the org witness's
"Yosef brought them out from between his knees, and he bowed himself with his face to the
ground" — flagged. And `vul MIC 5:11`, which is *one of this module's own calibration
entries*, a mapping known to be correct, marked uninformative during calibration and
contradicted during the run. That is the noise floor, made visible.

**A witness whose counts agree and whose content does not** — and this one is new, and it
is the most useful thing the pass found.

### A third instance of the `faithful_chapters` blind spot, and this time it was caused by it

`ROM 16:27` was flagged in two systems. Tracing why:

1. `n1904` **is** the right witness here and has Romans 16:27, the doxology.
2. But the critical text omits Romans 16:24, so its chapter holds 26 verses numbered 1–27.
3. `faithful_chapters` rejects any chapter where `count != high - low + 1` — "a gap: the
   edition did not print the whole chapter" — so **`n1904` was disqualified**.
4. `peshitta-nt` has 27 verses numbered 1–27 with no gap, so it passed the count test.
5. Its content is shifted: the Peshitta places the grace-benediction *after* the doxology,
   so its 25/26/27 are org's 26/27/benediction.

A real textual omission in the correct witness handed the question to a witness whose counts
agree and whose content does not. `brenton`'s Joshua 24 and `web`'s Matthew 23:13 were the
first two instances of that blind spot; this is the third, and unlike those it was *caused*
by the gap rule rather than merely missed by it.

#### What was done about it

Three instances is the point at which a note stops being enough. `audit._CONTENT_SWAPS` now
names them — keyed `(corpus, book, chapter)`, each with its evidence written out — and
`faithful_chapters` excludes them the way it already excludes a chapter with a gap.

A hand-maintained set is the honest shape here and the cheaper of the two options. The other
was to make the test textual: sample a few verses of every chapter against another witness of
the same system and require agreement. That catches the general case, and it costs a corpus
read per chapter and needs a threshold of its own; the set can be replaced by it later
without anything else moving.

Keyed on the corpus rather than on the pair, because what is recorded is a fact about the
corpus: these verses do not hold what their numbers say, whichever system is asking.

What it changed, both walks run in one process for comparison:

| | before | after |
|---|---:|---:|
| verses converted | 156,146 | 156,146 |
| ghosts | 0 | 0 |
| checked against text | 80,734 (51.704%) | 80,704 (51.685%) |
| confirmed | 98.677% | **98.680%** |
| contradicted | 1,068 | **1,065** |
| runs of 4+ | 2 | 2 |
| `eng` confirmed | 99.586% | **99.592%** |
| `lxx` confirmed | 97.765% | **97.767%** |

Thirty verses fewer are checkable, which is Joshua 24 leaving the `lxx` side, and three
contradictions are gone. Small, and the right size: what these were measuring was the
instrument rather than the data, and the two that moved `eng` were org-side comparisons
answered by the Peshitta's Romans 16.

### Calibration had to be fixed before any of this could be believed

`Calibration.admits` returned `True` for a language pair with no rows, on the reasoning that
an untested pair meant the calibration set had a gap rather than the model having a fault.
That held while every pair a run could produce was in the set. Syriac broke it: a Peshitta
witness produces `en-syc`, `la-syc` and `grc-hbo`, none of which any existing row could
reach, and all three would have been admitted **untested**.

It is now refused, and the report distinguishes "EXCLUDED" from "EXCLUDED — never measured".
Nor was it fixable by adding rows alone: `_calibration_task` picks witnesses through
`witness_for`, which returns the *first* faithful one, so an `org` row is answered by `wlc`
in Hebrew whatever it was written for. A row may now force the pair as `source-target`.

Enumerating the tables rather than waiting to be told: of the twelve pairs a source system
crossed with `org`'s witnesses can produce, eight were measured. The four that were not cost
the first attempt 3,797 skipped verses. Three are now measured. `grc-grc` is not and stays
refused, because it needs Greek on both sides and `org`'s Greek witness reaches only the New
Testament while `lxx` is the Old — no calibration case exists because no real case does.

**75/75 correct across eleven pairs.**

## Can a book be told it got longer? — `extend_books`, and what it turned out to be for

`TODO.md` item 9 asked for a correction kind that could lengthen a book, and gave 1 Enoch as
the case: *"`org` declares 42 chapters of `ENO`. 1 Enoch conventionally has 108."* Building it
meant first checking that diagnosis, and the diagnosis is wrong.

### `org`'s `ENO` is not 1 Enoch as anybody divides it

The four texts First1KGreek holds under `tlg1463.tlg001` were parsed and counted:

| | chapters | verses | note |
|---|---|---:|---|
| Greek, recension 1 | 1–32, 89 | 246 | chapter 4 absent |
| Greek, recension 2 | 1–32 | 235 | chapter 4 absent |
| German | 33–108 | 843 | complete run |
| Latin fragment | 106 | 13 | one chapter |

They agree with each other and with Dillmann's universal division: chapter 1 has 9 verses,
chapter 2 has 2 or 3, chapter 3 has 1. Together they cover 1–108 in about 1,078 verses.

`org` declares `ENO` with **42 chapters and 1,563 verses**, beginning 28, 42, 30, 88, 40. It
is in upstream's own `maxVerses`, not in any correction here. Whatever it describes, it is
not the book these four witnesses transmit, and no chapter of it matches: `ENO 1` is 28
verses where every witness prints 9, `ENO 4` is 88 where the text has one.

So `extend_books` cannot rescue 1 Enoch. Lengthening 42 to 108 would leave chapters 1–42
declaring counts nothing holds, and 1 Enoch would be imported into a book-shaped hole. It
stays unimported, now for a reason that is understood rather than guessed. Correcting `org`'s
`ENO` wholesale — 42 `fix_max_verses` entries and 66 extensions — is the only thing that
would work, and that is a claim about upstream being wrong which nothing here can support.

### Then who wants `extend_books`?

Asked properly, rather than assumed: which `(corpus, book)` pairs hold a chapter their
declared system does not have? **Twenty-one.** Every one was read.

| | verdict |
|---|---|
| `lxx MAL` at 4 chapters (swete, lxx2012, lxx2012uk) | **`lxx` is right.** Rahlfs and Brenton both print 3 chapters ending at 3:24; the three that print 4 are following the English division, where 3:19–24 becomes 4:1–6. `eng` declares exactly their [14, 17, 18, 6]. No correction. |
| `lxx NEH`, `DAN`, `EST`, `S3Y` at 0 chapters | Not lengthening: `lxx` numbers Nehemiah inside 2 Esdras and Daniel's Greek under `DAG`. `add_books` territory, and a modelling question rather than a count. |
| `lxx JOS` 25, `lxx TOB` 15 (rahlfs-cc only) | One witness, and its pair disagrees: `rahlfs` from the Patristic Text Archive has 24 and 14. Two digitisations of one printed edition that differ mean one is wrong — a diff, not a correction. |
| `org EZA` 14 (peshitta-ot) | One witness. 4 Ezra's chapter division varies by more than one chapter across the traditions. |
| `eng ESG` 16 (kjv, rv, wyc2017, wyc2018) | Already `unreliable`. |
| **`org PS2` 155 (peshitta-alt)** | **The one real case.** Below. |

### The one real case: the psalms after 150

`PS2` is the book of psalms following the Hebrew Psalter's 150. `org` declared it with one
chapter of seven verses — Psalm 151, which is where five English corpora put it, at
`PS2 1:1-7`. The Syriac tradition carries four more, psalms 152 to 155, surviving almost only
in Syriac; the Patristic Text Archive's second Peshitta recension has all five.

The import took the files' own chapter numbers, which are *psalm* numbers, so the Syriac
landed at `PS2 151` to `PS2 155` — four chapters past the end of a book with one. Two things
were wrong at once and only one of them was the versification:

* **65 verses were uncitable.** `PS2 152:1` names a chapter no system declares.
* **The Syriac Psalm 151 did not line up with the English one.** It sat at `PS2 151:1` where
  `web`, `webbe`, `webu`, `asvbt` and `ourb` all have `PS2 1:1`, so no comparison could see
  it and no lookup could find it. That was an import fault, not a mapping one.

Both fixed. `corpora/pta.py` renumbers 151–155 to 1–5 on the way in, and `org PS2` is
extended from one chapter to five — `[7, 6, 6, 20, 21]`, read from the manuscript's own
numbering with each psalm's superscription excluded as verse 0. `PS2` also leaves
`SINGLE_CHAPTER_BOOKS`, because `PS2 5` now has to mean Psalm 155 rather than the fifth verse
of Psalm 151, and its title becomes *Additional Psalms* rather than *Psalm 151*.

`biblereference coverage` is unchanged at **0 ghosts**, and Psalm 151:1 now reads
*"I was small among my brothers"* in English and ܙܥܘܪܐ ܗܘܝܬ ܒܐܚܝ̈ in Syriac at the same
coordinate.

### The invariants it carries

`fix_max_verses` raises when a chapter index is out of range, by design: silently growing a
book is how a typo in a chapter number becomes a chapter nobody asked for. `extend_books` is a
separate kind so that it can be strict about the one thing it is allowed to do.

* **Append-only.** The lowest new chapter must be exactly one past the end.
* **Contiguous.** A hole is refused: a book with a missing chapter in the middle cannot be walked.
* **Never alters.** A chapter the system already has is refused, naming `fix_max_verses`.
* **Never introduces.** A book neither upstream nor `add_books` defines is refused, naming `add_books`.
* **No empty chapters.** One nothing can be cited from is not worth declaring.
* **No orphaned mappings.** Extending brings chapters into range that the existing check
  skipped as out-of-range, so the extended books join the set that check covers.

It moves `fingerprint()`, which every dependent is expected to notice.

## An unrelated fault the same discipline caught: `scan` merging two quotations

Not a versification matter, but it was found the same way — by reading the output of a case
that should have been easy — and it is worth recording beside the rest.

`biblereference scan` on *"In the beginning was the Word. And God so loved the world that he
gave his only Son."* returned **one** quotation: John 1:1, quoting the chimera *"In the
beginning was the Word And God so loved the"*, with John 3:16 demoted to an alternate.

`_matched_span` grows a span outward from the longest matching block and stops at the first
real gap, and the gap was measured **only on the searched-text side**:

```
JHN 1:1  blocks [Match(a=0, b=0, size=7), Match(a=7, b=11, size=1), Match(a=10, b=13, size=1)]
JHN 3:16 blocks [Match(a=7, b=1, size=10), Match(a=17, b=12, size=1)]
```

John 1:1's anchor is a genuine seven-word run. The two blocks it then absorbed are the single
words *God* and *the* — which sit at positions 11 and 13 of John 1:1 while the text had not
advanced at all. `blocks[i].b`, where a block sits *in the verse*, was never consulted.

A quotation and the verse it quotes advance together. A speaker interpolating a clause of his
own moves the text on while the verse stands still, which is what the existing gap of eight
words is for; the reverse — the verse leaping several words ahead while the text has not moved
— is a coincidence agreeing, not a quotation continuing. Bounding both sides fixes it, with
the verse side much tighter at two. John 3:16's own closing *Son*, separated from *only* by the
verse's *begotten*, has a verse-side gap of 1 and is still reached.

Two more faults in the same function, both found while fixing it:

* The overlap check was a bare interval intersection, so **one shared character deleted a
  match**. Two quotations written one after another share the space between them. A different
  passage now has to claim most of the shorter span before it counts as reading the same
  words — and the same passage claims any overlap at all, or one verse comes back twice.
* Rebuilding each match to attach its alternates **dropped `composed` and `identified_at`**,
  so after any `scan` every record reported `anachronistic` as False and ignored a configured
  threshold. That is the one field a patristic count is supposed to filter on.

### Measured, both configurations in one process

Twelve pairs of well-known verses written one after another with no filler, and ten patristic
and monastic documents where a lost match would be a regression:

| | before | after |
|---|---:|---:|
| adjacent pairs finding both quotations | 7/12 | **8/12** |
| matches over ten documents | 13 | **17** |

The four the pairs still miss are limits rather than faults: *Jesus wept* is two words, Genesis
1:1 and John 1:1 open with the same four, and the Lord's Prayer in Matthew and Luke is the same
prayer.

The prose gain is the real evidence, because nobody chose those documents to suit the fix.
**Four quotations appear that were not found before** — 2 Corinthians 6:14-15, Acts 13:22-23,
Acts 2:22-24 and Psalm 69:21-25 — each of them previously swallowed by an over-extended
neighbouring span. Nothing was lost: four spans start later than they did, which is the point,
and every passage found before is still found. Revelation 21:4 is also now read correctly where
before it was reported as the parallel at Revelation 7:16-17.
