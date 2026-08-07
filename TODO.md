# Versification audit — what is left, and what you need to know to resume

Written 2026-08-04, at the end of the family-derivation work. Everything below is open;
everything already done is in `docs/versification-families.md`, `docs/witness-validation.md`
and `docs/versification-audit.md`, and every fix carries its reasoning in
`src/biblereference/versification/data/corrections.json`.

State at the time of writing: 461 tests passing, ruff clean, mypy at its 19 pre-existing
errors (none in files this work touched), working tree clean.

**Updated 2026-08-04, second pass.** Items 1, 2, 3, 4 and 5 are now closed; 6 and 7 stand.
591 tests. `biblereference coverage` walks every one of the 155,578 conversions and reports
**0 ghosts** — no conversion returns a verse the pivot does not have — with 51.9% checkable
against text at 98.62% confirmed and the unreachable half reported rather than assumed. The
derivation's residue was then read verse by verse outside the four bodily-reordered books:
twelve more faults found and fixed, the rest confirmed as limits of the aligner or of the
witnesses. See the last two sections of `docs/versification-audit.md`.

---

## Where things live

| | |
|---|---|
| derived families, as JSON | `~/.local/share/biblereference/audit/families.json` |
| mapping-derivation results | `~/.local/share/biblereference/audit/phasec-after.json` (and `-before-fixes` for comparison) |
| within-family text checks | `~/.local/share/biblereference/audit/phaseb.json` |
| model adjudications | `~/.local/share/biblereference/audit/adjudication.sqlite` |
| the overnight sweep (superseded) | `~/.local/share/biblereference/audit/sweep-COMPLETE-20260804-145138.sqlite` |
| analysis scripts | `~/.local/share/biblereference/audit/scratchpad-rescue/*.py` |

**The scripts are not in the repository.** They live in the data home because they are lab
equipment rather than library code, and they were rescued there from `/tmp` twice already.
The ones that matter:

- `phasec.py` — derives every family pair's mapping from the text and diffs it against the
  vendored data. This is the instrument to re-run after any change to `corrections.json`.
- `boundary.py <BOOK> <src-corpus> <src-system> <tgt-corpus> <tgt-system> [lo-hi]` — prints
  one book's full derived alignment beside what the data claims. This is what you use to
  pin an exact range before writing a correction.
- `triage.py` — for a list of candidate chapters, says which system deviates from org and
  whether the shift is clean enough to express as a range.
- `read_queue.py [filter]` — prints adjudicated passages with source, vendored target and
  derived target side by side, for reading.
- `adjudicate.py` — puts candidates to the local models. Resumable; calibrates first and
  refuses to run if calibration fails.

Re-run the derivation with:

    venv/bin/python ~/.local/share/biblereference/audit/scratchpad-rescue/phasec.py \
        ~/.local/share/biblereference/audit/phasec-after.json

---

## Open work, in the order I would take it

### ~~1. Judith~~ — DONE

Measured rather than assumed: alignment quality 0.289 where an ordinary book runs 0.6–0.8,
72 of ~345 verses with no counterpart, offsets scattering *within* almost every chapter.
A different text, not a differently numbered one. `JDT` and `TOB` are now `unreliable` for
`vul` only — the Nova Vulgata went back to the Greek and its counts match `org`.

It also unlocked what was item 4: `SIR 14` was listed as unjudgeable for want of an org
witness, but `eng ≡ lxx ≡ org` for Sirach was already established, so `eng` stands in.
SIR 14 is mapped; SIR 18 refuses via a new chapter-level `unreliable` entry.

<details><summary>original entry</summary>

### 1. Judith — the largest single block left

`vul`→`nvl` residue is JDT 21, and Judith shows up in `eng`→`vul` and `lxx`→`vul` too. It
is the biggest unexplained block anywhere in the audit.

**Context.** Jerome translated Judith from an Aramaic recension differing from the Greek by
whole clauses. `vul` numbers its chapters [12, 18, 15, 17, 29, …] against `eng`
[16, 28, 10, 15, 24, …]. There is **no Judith mapping in any system**.

**The inconsistency worth resolving first:** the library currently *refuses* `Jdt 8:1` and
*converts* `Jdt 6:13` by identity. That is the per-chapter unmappable guard doing its job —
chapters whose counts differ refuse, chapters whose counts happen to match convert — but the
result is that half the book silently returns plausible wrong answers. Decide one way or the
other: either declare the whole book unmappable for `vul` (there is an `unreliable`
mechanism, book-level, already used for `ESG`), or derive a real mapping.

**Evidence already gathered.** `eng JDT 6:13` "bound Achior, cast him down, left him at the
foot of the hill" is `vul JDT 6:9` "they tied Achior to a tree" — English runs **+4** ahead
in chapter 6. Verified by hand. Whether that offset holds across the book is not known.

**Proposed approach.** Run `boundary.py JDT web eng dra vul` for the whole book and see
whether the correspondence is a small number of clean segments or genuinely unmappable. If
segments, write them; if not, mark the book `unreliable` for `vul` and stop pretending.

</details>

### ~~2. `lxx`→`vul`~~ — TRIAGED, nothing left to fix

Now 160. Every run accounted for, and none of it is a mapping fault:

| cause | runs | disposition |
|---|---|---|
| genuine Greek reordering (`EXO 36`, `JER 25/27/35`) | 7 | chapter-crossing offsets; monotonic alignment cannot describe them and the data is right |
| alignment artifacts in repetitive text (`NUM 26`, `NUM 15`, `LEV 15`) | 4 | all three systems verified identity to `org`; the census and the purity laws are where the aligner slips |
| psalm-superscription convention (`PSA 12`) | 1 | see `_psalm_title_note`; upstream convention, not correctable here |
| `EXO 39` | 1 | declined earlier — the Douay condenses rather than displaces |
| already fixed (`NUM 27`, `EZK 7`) | 2 | verified end to end through `vul` |

<details><summary>original entry</summary>

### 2. `lxx`→`vul` at 185 — the worst remaining pair

Most of it is the Septuagint reordering 3 Kingdoms and the tabernacle account **bodily**,
which monotonic alignment cannot describe and which is a textual fact rather than a mapping
fault. But that has never been separated verse by verse, so the real residue is unknown.

**Proposed approach.** Classify each run: chapter-crossing offsets are reordering (leave
alone, and consider recording them as `unreliable` so the library refuses rather than
guesses); single consistent offsets within a chapter are candidates. `triage.py` already
does exactly this classification — extend its candidate list rather than writing anything
new.

</details>

### ~~3. `lxx` and `vul` have no faithful witness~~ — MITIGATED, and now measured

Still true and still unfixable, but no longer silent. `biblereference coverage` walks all
155,578 conversions and reports per system how many could be checked against text and how
many could not, so nobody can read silence as agreement:

```
eng  30,903 checked (76.3%)   lxx  19,638 (48.7%)   vul  30,181 (77.1%)   nvl  0 (0.0%)
```

`nvl` at 0% is the honest form of what item 6 says about `rsc`/`rso`: its only witness is
Latin, `org` has none, so no same-language comparison exists. It is verified against `vul`
instead — Latin against Latin at 99.88% — which is a weaker claim and is now recorded as
one. The first proposed approach below is what was taken; the other two stand.

<details><summary>original entry</summary>

### 3. `lxx` and `vul` have no faithful witness — the deepest problem

**No corpus follows either system.** Not Brenton (29 chapters off), not Swete (112), not the
Vulgata Clementina (7), not the Douay-Rheims (15). Measured in
`tests/test_witnesses.py::test_no_corpus_is_faithful_to_the_vulgate_system`, which is written
to fail if this is ever fixed.

Every audit of those two systems before this work was measuring the gap between the system
and the nearest edition rather than the mapping. The current workaround — restricting
comparisons to chapters where *both* witnesses are faithful (`audit.faithful_chapters`) —
is sound but covers only 920–1,294 chapters per pair, and it cannot say anything about the
chapters it excludes.

**Proposed approaches, in increasing cost:**
- Accept it, and document per-pair coverage in the audit output so nobody reads silence as
  agreement.
- Correct the shipped `lxx`/`vul` `maxVerses` toward what the editions actually print. This
  needs a mechanism `corrections.json` does not have (see item 5) and would be a large,
  well-evidenced change.
- Find a corpus that genuinely follows the shipped systems. Probably does not exist; these
  are Paratext-derived schemes rather than descriptions of one printed edition.

</details>

### ~~4. One passage that cannot be judged at all~~ — DONE

**`SIR 14` and `JDT 6` are resolved** — see item 1. The claim that they could not be judged
was wrong: `ojb` carries no deuterocanon, but `eng` was triangulated as equal to `org` for
Sirach, so it stands in. Judith needed no witness in the end, being unmappable outright.

**`BAR 6` is resolved too, and the answer was not the one the models gave.** No org witness
was needed in the end: `eng` and `vul` both carry the letter and could be read directly
against each other, and eight English witnesses and three Latin ones are unanimous. The
English is not one straight offset from the Latin — it merges two verses at 6:43 and splits
one at 6:50, and the two cancel, so 6:44 to 6:50 agree exactly. The old single range had all
seven of those wrong. Written up as `_letter_of_jeremiah_note` and pinned by
`test_the_english_letter_of_jeremiah_is_not_one_straight_offset`.

One thing did *not* resolve: org `LJE 1:43` has no English verse of its own, because English
carries it inside 6:43 and the data model maps each source verse to exactly one target. The
file says so rather than guessing.

<details><summary>original entry</summary>

`BAR 6` remains. It has model evidence (6–0) and no org witness, and unlike Sirach there is
no triangulation available: `eng` carries the Letter of Jeremiah as Baruch 6 and `org` as a
standalone `LJE`, so the two are not comparable verse for verse without assuming the very
mapping in question.

**Proposed approach.** Either acquire a deuterocanon-carrying corpus that is exact to `org`
(none of the 55 held here is), or triangulate through `nvl`, which is exact to `nvl` and
close to `org` — but note `nvl` was found to disagree with `org` at the Nehemiah 7 tail, so
it is not a safe proxy without checking each case.

</details>

### ~~5. Two upstream verse counts are wrong and cannot be corrected~~ — DONE

`fix_max_verses` exists, with the two invariants the entry asked for: a correction that
matches upstream is rejected as stale, and no mapping may be left naming a verse outside a
corrected range. Twenty-four chapters corrected, including `eng BAR 1`.

<details><summary>original entry</summary>

### 5. Two upstream verse counts are wrong and cannot be corrected

`corrections.json` can adjust mappings but has **no mechanism for `maxVerses`**. Two known
errors are therefore documented and unfixed:

- **`eng BAR 1` declares 21 verses.** All four witnesses print 22 (web, dra, latvuc,
  novavulgata) and they align verse for verse. Ten of ten English witnesses carrying Baruch
  say 22. Worked around with an identity mapping for 1:1-21 so conversion is not refused;
  the 22nd verse remains unreachable from `eng`.
- **`vul` numbers Psalms 115 and 147 from verses 10 and 12** rather than from 1. Both
  Vulgate witnesses number them from 1. Not worked around.

**Proposed approach.** Add a `fix_max_verses` section to `corrections.json` and apply it in
`_build_system`. Small change, but it alters declared structure rather than mappings, so it
needs its own invariants — at minimum, that no existing mapping is left pointing outside the
corrected range.

</details>

### ~~13. The 691 Rahlfs boundary disagreements~~ — READ, and a quarter of them were not that

Arbitrated all 691 against Swete and Brenton by word overlap rather than a sample of forty
(`tools/rahlfs_boundaries.py`). Two results.

**157 of them — 23% — were two different Greek texts under one coordinate.** Corpus
Corporum's Tobit is the long recension GII, not the short GI it was filed as: 0.9% identical
to `rahlfs` TOB, 75.8% to `rahlfs-alt` TBS. Its heading says ΤΩΒΙΤ and its text says Τωβιθ.
It is `TBS` now, and the same comparison reads 97.8% — which is what two transcriptions of
one book look like. Its chapters were upstream's fault as well: the file numbers them 1-10
then 12-15, so fourteen verses sat at a chapter 15 no system declares. Every book in the
file was checked for this; Tobit was the only one.

**The remaining 534** are draw 270, Corpus Corporum 196, PTA 41, no arbiter 27. Neither
transcription can be preferred wholesale, but the balance is far more lopsided than forty
cases suggested — 20:15 in the sample, nearly 5:1 over the whole set. PTA's wins are
concentrated rather than spread: eleven of the forty-one are Joshua 24 from verse 22, which
is the lettered-plus renumbering already documented, seen from the other end.

**None of the 534 implicates `lxx`.** They are two copies of one printed book disagreeing
about where a clause sits, not two traditions disagreeing about how to number it, so nothing
here becomes a versification correction. The half that are draws would need reading, not
arbitrating; the tool prints them with `--list`. Written up in `docs/tei-corpora.md`.

### 12. A conversion can answer with a book the target system does not have

Found while building the numbering screen, which raised on `Ps 151:1` in `lxx`.

`convert_range` falls back to the identity where neither system maps a book, and **the
fallback does not check that the target declares it**. So `lxx PSA 151:1` converts to
`nvl PS2 1:1`, and the Nova Vulgata has no `PS2`. `expand` and `validate` on that result
raise `VerseOutOfRangeError` — so the library will produce a coordinate it will not accept,
which is an inconsistency rather than a judgement call.

Measured over the shipped tables, converting the first and last verse of every chapter of
every system to every other:

    2,384 conversions across 90 (source, target, book) triples

Every book involved is one system carrying what another does not: `ENO` and `JUB` out of
`org`; `PSS`, `ODA`, `TBS`, `JDB`, `JSA`, `DNT`, `BLT`, `SST` into `vul` and `nvl`; `EZA`
into `eng`; the whole deuterocanonical tail into `nvl`, which declares 73 books. The largest
single triple is `org`→`eng` for `ENO` at 84.

**Why the coverage walk reports 0 ghosts anyway.** A ghost is defined against the *pivot*,
and `org` holds every one of these books. The 156,146 conversions the walk makes are all
to or from `org`, so no ghost check has ever looked at a non-pivot target.

The question is which of two things `convert` should do, and it is a real question rather
than an oversight to sweep up:

- **Refuse**, with a `VersificationGapError` naming the book — consistent with `validate`,
  and consistent with how a missing *verse* is already treated. But it would turn ~2,384
  currently-answered conversions into refusals, and `render`, `audit` and `compare` all
  convert freely; each would need checking for whether it treats a refusal as a gap in the
  data or as an error.
- **Keep answering**, and say in the docstring that the identity fallback means "no mapping
  difference is recorded" rather than "the target has this". Then `validate` is the odd one
  out, and a caller who converts and then expands still gets a raise.

`web/alignment.py` reports it as a refusal on the screen and `web/reader.py` reads such a
book through `SqliteCorpus.chapter`, which needs no declared verse list. Neither is a fix;
both are there so that a screen says "the Nova Vulgata has no Additional Psalms" instead of
returning a 500. `tests/test_web_alignment.py` pins the behaviour.

### 6. `rsc` and `rso` cannot be audited at all

No corpus exists in either. Only the structural invariants in `tests/test_alignment.py`
apply. Nothing to do unless a Russian Synodal corpus is added; noted so it is not mistaken
for verified.

Still true after the TEI import, which added Syriac and Coptic but nothing Slavonic.

### ~~8. `nvl` still has no same-language pivot partner~~ — MEASURED, and the answer is no

Both candidates have now been read, and `nvl` stays at 0% for a reason rather than for want
of trying.

**Castellio** (1551, from the Hebrew and Greek, owing nothing to the Vulgate) measured at
about 90% against every shipped system with `eng` winning narrowly, and its Genesis 31/32 is
55 verses and 32 — the English tradition's division where the Hebrew has 54 and 33.

**Jerome's *Psalterium iuxta Hebraeos*** is Corpus Corporum work 656, text **7213** — the
work idno does not download, which is the two-step this catalogue is easy to get wrong on.
`tools/psalter_segment.py` segments and measures it.

The obstacle turned out not to be the one expected. The entry below says the transcription
has 49 headings for 150 psalms and that segmenting is an alignment job — but **the psalm
numbers are in the text**, set as Roman numerals in brackets, so 149 of the 150 boundaries
are *printed* rather than inferred. (The missing one is Psalm 33, which has no Hebrew
superscription, so Migne set neither a head nor a number and its first verse runs on from
Psalm 32's last.) That is 99.3% by a stronger signal than the 95% gate asked for.

**And it is an `org`-family psalter, decisively.** Every psalm where the Hebrew and the Greek
divide differently comes out Hebrew:

| psalm | this | org | eng | vul | lxx |
|---|---:|---:|---:|---:|---:|
| 9 | 17 | 21 | 21 | 40 | 39 |
| 10 | 19 | 18 | 18 | 9 | 8 |
| 116 | 19 | 19 | 19 | 3 | 3 |
| 117 | 2 | 2 | 2 | 30 | 30 |
| 147 | 20 | 20 | 20 | 20 | 10 |

9 and 10 are separate where the Greek merges them; 116 and 117 are the Hebrew's, not the
Greek's. This is the first Latin text in this library that numbers psalms the Hebrew way.

**It still cannot be a witness, and the reason is verses.** Migne sets the psalter as poetry
with no verse numbers at all — one colon per `<l>` — and the cola are not verses. Deriving
verses from the indentation gets the count right for only 33.6% of psalms and within one for
66.4%; Psalms 111 and 112 come out at 22 apiece, because they are acrostics set one line per
Hebrew letter, where `org` has 10. Psalm 1 comes out at 7 against org's 6, splitting 1:3 at a
line break.

The only way to verse-divide it is to align against the Gallican psalter — Latin against
Latin, and it aligns well (0.57–0.83 wording overlap, and on Psalm 1 it corrects the split
exactly). **But that is circular.** A psalter whose verse boundaries are taken from `vul`
cannot then be evidence about whether `org`'s verse boundaries are right, and verse
boundaries are the only thing the coverage walk checks. It would be a witness that agrees
with whatever it was aligned to.

So: the text is found, identified, and worth having as a *reading* corpus some day. It is not
a witness, and admitting it as one would corrupt the single measurement `nvl` has. Same shape
as the 1 Enoch result in item 9 — the diagnosis was wrong, and knowing why is the result.

The licence is Corpus Corporum's non-commercial; the underlying Migne is out of copyright,
and PL 12 is on the Internet Archive if that matters.

<details><summary>original entry</summary>

### 8. `nvl` still has no same-language pivot partner

`nvl` is checked at 0% by the coverage walk because its only witness is Latin and `org` has
none. The TEI import did not fix this and it is worth recording *why*, since one of the
texts it brought looked like the answer.

Castellio translated the Bible into Latin in 1551 from the Hebrew and Greek, owing nothing
to the Vulgate — so it ought to be an `org` corpus in Latin, which is exactly the missing
piece. Measured, it is not: about 90% against every shipped system with `eng` winning
narrowly, and its Genesis 31/32 is 55 verses and 32, the English tradition's division where
the Hebrew has 54 and 33.

The remaining candidate is Jerome's *Psalterium iuxta Hebraeos*, translated from the Hebrew
and never adopted liturgically, at Corpus Corporum idno 656. It would cover the Psalms only,
which is where `vul` and `nvl` diverge most, so it is worth more than its size suggests. The
obstacle is that the transcription has 49 headings for 150 psalms and the headings are Hebrew
superscriptions rather than numbers: segmenting it is an alignment job against a psalter of
known divisions, not a parse.


</details>

### ~~11. `faithful_chapters` has now been caught out three times~~ — DONE

Option 1 taken: `audit._CONTENT_SWAPS`, keyed `(corpus, book, chapter)`, each entry carrying
the evidence that put it there, consulted by `faithful_chapters` beside the existing gap
test. Three entries, all three verified against the corpus before being written down.

Thirty verses fewer are checkable and three contradictions are gone; `eng` moved 99.586% →
99.592% and the whole walk 98.677% → 98.680%, still at 0 ghosts. Both walks are tabulated in
`docs/versification-audit.md`. Option 2 — a textual sample per chapter — remains available
and would replace the set without anything else moving.

<details><summary>original entry</summary>

### 11. `faithful_chapters` has now been caught out three times

It decides whether a corpus may speak for a system by comparing verse *counts*, and its own
docstring records that this cannot see a content swap. Three instances now:

* `brenton`'s Joshua 24 — puts "Israel served the Lord" at 29 and Joshua's death at 30,
  reversing the Hebrew. Both editions have 33 verses.
* `web`'s Matthew 23:13 — alone among the Greek, the King James and the Douay in putting
  "devour widows' houses" first.
* `peshitta-nt`'s Romans 16 — places the grace-benediction *after* the doxology, so its
  25/26/27 are org's 26/27/benediction.

The third is the one that argues for doing something. It was **caused** by the rule rather
than missed by it: `n1904` is the correct witness and has Romans 16:27, but the critical text
omits 16:24, so its chapter holds 26 verses numbered 1-27 and the gap test disqualified it.
The Peshitta's 27 verses run 1-27 with no gap, so it passed on counts while its content is
shifted. A real textual omission in the right witness handed the question to the wrong one.

Two options, and the first is much cheaper:

1. A hand-maintained exclusion set, `(corpus, book, chapter)`, consulted by
   `faithful_chapters`. Three entries today. Honest, small, and needs a place to record
   *why* each was excluded — which is the part that makes it worth having.
2. Make the test textual rather than structural: sample a few verses of the chapter against
   another witness of the same system and require agreement. Catches the general case, costs
   a corpus read per chapter, and needs its own threshold.

</details>

### 10. ~~`swete` carries editorial sigla in its stored text~~ — DONE

634 markers across 402 verses, stripped in `corpora/swete.py`. Verse counts unchanged, so
nothing was a marker alone. The other differences that diff turned up -- elision apostrophes
and real textual variants between the two digitisations -- are not ours to fix.

<details><summary>original entry</summary>

### 10. `swete` carries editorial sigla in its stored text

389 of its 28,443 verses (1.4%) contain characters like `⸂⸆⸃`, and 13 of `swete-daniel`'s
422 (3.1%). No other Greek corpus here carries any: Rahlfs, Brenton, Nestle 1904, the SBLGNT
and Westcott-Hort are all at zero.

They are in the text that gets searched, folded and quote-checked. Found by diffing our
digitisation of Swete against First1KGreek's, which is what having two copies is for — see
`docs/tei-corpora.md`. The other differences that diff turned up are elision apostrophes
(U+1FBD against U+2019) and real textual variants; the first two are ours to fix and the
third is not.

Not done yet only because changing an `lxx` witness while an audit is running would move the
instrument under the measurement.

</details>

### ~~9. A book cannot be told it got longer~~ — DONE, and the case it was written for was wrong

`extend_books` exists, append-only, with five invariants and no orphaned mappings, applied in
`_build_system` beside `fix_max_verses`.

**But 1 Enoch is not what it is for.** `org`'s `ENO` is 42 chapters and 1,563 verses,
beginning 28, 42, 30, 88 — and all four First1KGreek witnesses divide 1 Enoch as everyone
does, 108 chapters and ~1,078 verses, chapter 1 with nine. Extending 42 to 108 would leave the
first 42 declaring counts nothing holds. 1 Enoch stays unimported, now for a reason that was
measured.

Asking which books *do* outrun their system turned up 21 pairs and exactly one real case: the
Syriac apocryphal psalms. `org PS2` was one chapter — Psalm 151 — and the Peshitta's second
recension carries 152 to 155 as well, which the import had put at `PS2 151-155` where nothing
could cite them and where the Syriac Psalm 151 did not line up with the five English witnesses
holding it at `PS2 1`. `PS2` is five chapters now, the import renumbers, and `PS2` has left
`SINGLE_CHAPTER_BOOKS`. Still 0 ghosts. All 21 pairs are tabulated in
`docs/versification-audit.md`.

<details><summary>original entry</summary>

### 9. A book cannot be told it got longer

`org` declares 42 chapters of `ENO`. 1 Enoch conventionally has 108, and the texts on hand
run to 89 (Greek), 108 (German) and a Latin fragment that is chapter 106 alone.
`fix_max_verses` raises when the chapter index is out of range, by design, so there is no way
to extend a book — only to correct a verse count inside one.

What is needed is an `extend_books` correction kind: append-only, able to lengthen and never
to alter an existing count, with a recorded reason. It changes declared structure rather than
mappings, so it wants its own invariant — at minimum that no existing mapping is left
pointing outside the corrected range — and it moves `fingerprint()`, which every dependent is
expected to notice.

Until it exists, `ENO` stays modelled with no text, and 1 Enoch stays on disk unimported.

</details>

### 7. Exodus 39 — ~~deliberately not fixed~~ settled by reading

**Done.** The diagnosis here was right in every particular and so was the refusal to act on
it: the Douay does condense the ring-and-chain description, absorbing `org 39:19-20` rather
than displacing them, and a mechanical off-by-one would have been wrong in a way that looks
right. What it needed was the verse-by-verse reading this entry asked for, which the model
pass finally made worth doing — the chapter runs two behind from 39:20, one behind from
39:28, and level again from 39:39, with `org 39:28` divided across two Douay verses. Twenty
verses of chapter 39 and three of chapter 38 are now written down, both `vul EXO 39` runs
are gone from the coverage walk, and the covering round trip did not move.

The lesson is worth keeping even though the item is closed: **an alignment that reports a
clean shift over a condensed passage is reporting the average of several different offsets**,
and the only way to tell that from a real displacement is to read the verses.

---

## Things that will bite you if you forget them

These each cost real time or produced a wrong answer that looked right.

- **Equal verse counts prove nothing.** Sirach 6 is 37 verses on both sides with a split at
  6:19 and an omission at 6:35 cancelling out; Leviticus 8 is 36 both sides for the same
  reason. Every fault found in this pass was invisible to count comparison.
- **The instrument's witness must be faithful on the chapter being judged.** `ojb` is off
  from `org` on ten chapters and using it blind killed 13 findings of the overnight sweep.
  `faithful_chapters` exists for this; `boundary.py` does **not** apply it, so check
  membership by hand when using that script.
- **`ojb` carries no deuterocanon.** Any org-side comparison in SIR/BAR/JDT/TOB/WIS/MAC is
  vacuous.
- **Witnesses are chosen per pair, not per system.** Choosing for faithfulness alone put
  English against Latin and every book was rejected at similarity 0.02. Same language first,
  faithful-chapter restriction on top.
- **The alignment band must exceed the cumulative drift.** At 60 it ran out of room around
  Psalm 89 — the Septuagint numbers psalm titles as verse 1 and the English tradition does
  not store them at all — and shifted every remaining psalm by one, for 1,030 false
  disagreements. It is 200 now. Psalms is the worst case.
- **Monotonic alignment cannot express a transposition.** Where the Greek swaps blocks
  (Ezekiel 7, 3 Kingdoms 20/21, Greek Exodus) the alignment reports a plausible partial
  shift. Ezekiel 7 was only resolved by reading both texts; the alignment's version of it
  was wrong.
- **Per-book alignment cannot express a cross-book mapping.** The Vulgate's Daniel absorbs
  Susanna, Bel and the Song of the Three, which `org` holds separately: 250 apparent
  disagreements, every one of them the data being right.
- **Adding a mapping to a book changes the refusal guard.** It is per chapter now, but a new
  mapping still vouches for the chapter it names. Adding one verified Sirach 6 mapping used
  to switch off refusal for all 51 chapters.
- **A deprioritised book must not absorb the book it aliases.** This was worth 250
  disagreements on `org`→`vul` and predated all of this work. Fixed, tested, but the shape
  of the bug is worth remembering: `deprioritize_books` ranks candidates, and by the time it
  runs the identity may already have been dropped from the pool.
- **The models need the chat endpoint and a non-zero temperature.** `/completion` at
  temperature 0 made an instruction-tuned model reject nearly everything, which looks
  exactly like a corpus full of faults. Calibration figures are in `judge.py`'s docstring;
  `adjudicate.py` calibrates on hand-verified pairs and exits if it fails.
- **Only a discriminating pair of answers is evidence.** Scoring NO/NO as a contradiction
  once inflated the count from 11 to 247 on identical data.
