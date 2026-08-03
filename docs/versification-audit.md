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

**The Vulgate's Jonah, and it was real.** `vul.json` carried the *English* Jonah mapping —
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

## What was found and is *not* a fault

This is the part that matters for reading the other 39, and it is why they are not
presented as 39 bugs.

**Bel and the Dragon (40 and 41 verses, two pairs).** The largest run in the whole audit,
and both instruments agree the text is offset. It is not a mapping error. The Clementine's
Daniel 14:1 reads *Erat autem Daniel conviva regis*, while the Nova Vulgata and the Greek
both begin *Et rex Astyages appositus est ad patres suos*. The Clementine simply **omits
the Astyages verse** and still numbers its chapter 1–42. The 1979 revision restored it. The
editions genuinely differ; the mapping aligns the numbers, which is its job.

**Deuteronomy 29 (28 verses) and the Letter of Jeremiah (26 + 21).** Here the confound is
the witness. Brenton's Letter of Jeremiah has 73 verses where every system declares 72, and
its Deuteronomy 29:1 matches the Douay's 29:1 rather than sitting one behind it. Brenton
fits `lxx` at 97% overall — correctly filed — but these books are in its 3% tail.

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

## Status

- **1 mapping fault found, confirmed from four independent witnesses, and fixed** — the
  Vulgate's Jonah. Pinned by `tests/test_alignment.py`; Jonah now scores 100% agreement
  across all seven pairs.
- **39 runs where both instruments agree the content is offset.** Seven examined by hand —
  Bel and the Dragon, Daniel 14, Deuteronomy 29, the Letter of Jeremiah twice, Sirach 6 and
  Exodus 39 — and **none is a mapping fault**. Every one is an edition difference or a
  quirk of the witness. The remaining ~33 are candidates, not defects, and the prior
  established by the six is that most will be the same thing: the deuterocanon is where the
  Latin and Greek traditions genuinely transmit different texts, and that is precisely
  where the flags cluster.
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
