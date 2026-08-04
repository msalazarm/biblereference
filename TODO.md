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

### 6. `rsc` and `rso` cannot be audited at all

No corpus exists in either. Only the structural invariants in `tests/test_alignment.py`
apply. Nothing to do unless a Russian Synodal corpus is added; noted so it is not mistaken
for verified.

### 7. Exodus 39 — deliberately not fixed

The alignment reports a clean shift and **the text refuses it**. The Douay condenses the
Hebrew's ring-and-chain description, absorbing `org 39:19-20` rather than displacing them,
so the correspondence is many-to-fewer. A mechanical off-by-one would be wrong in a way that
looks right. Revisit only with a verse-by-verse reading, not with an alignment.

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
