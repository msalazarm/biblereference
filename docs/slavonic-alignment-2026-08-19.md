# Overnight watch — Slavonic judge run

Started 2026-08-19 03:35. pid 649968, log `overnight-slavonic2.log`,
database `~/.local/share/biblereference/audit/judgement-slavonic.sqlite`.
Hourly check at :23 past. Notes appended below, newest last.

## 03:35 launch
Resumed at 19,058 judged of 80,227; 27,699 to go at ~2.6/s, ETA ~06:30.
Calibration 77/77 both runs. rso now present in both witness maps (was the bug).

## 03:45 relaunch (pid 651127, log overnight-slavonic3.log)
Slavonic finally judging. Two earlier starts did zero rso: first because WITNESSES lacked
rso, second because admits() refuses uncalibrated language pairs. Five chu calibration rows
added (verified against text first). chu-grc 1/1, chu-hbo 2/2, calibration 80/80.
56,651 to judge, ~6h at 2.6/s. First rso rows: 428 confirmed, 31 uninformative, 0 contradicted.

## 04:35 hourly check — healthy, with one finding that needs the morning

Run alive (pid 651127, 52 min), 6,000/56,651 (11%), 2.6/s, ETA ~09:45. No errors.

Slavonic is flowing and the model reads it: rso 459 -> **4,687** judged,
4,305 confirmed / 369 uninformative / **13 contradicted**. Uninformative **7.9%**, far
below the 25% that would have meant Gemma cannot read Church Slavonic. That question is
answered: it can.

### The 13 contradictions, none in Daniel

```
  EXO 36:10 -> 36:10   NUM 10:35 -> 10:35   SNG 6:1  -> 6:1    PSA 114:8 -> 116:8
  EXO 36:28 -> 36:28   JOS 12:19 -> 12:19   SNG 6:3  -> 6:3    PSA 139:3 -> 140:3
  ISA 3:19  -> 3:20    PRO 18:16 -> 18:15   SNG 6:5  -> 6:5    PSA 139:4 -> 140:4
                                            SNG 6:10 -> 6:10
```

Nine of thirteen are *identity* mappings — same address both sides — so the model is
saying the two texts differ, not that the number is wrong. Most likely the org witness is
Hebrew (wlc) where the Slavonic follows the Greek, and LXX and MT genuinely diverge there.
**Song of Songs 6 has four of the thirteen**, which is a cluster rather than noise and is a
known LXX/MT versification seam. Worth a hand-read, not an alarm.

### ⚠ The correction I most wanted tested cannot be tested by this run

`DAN 3:24-90 -> S3Y 1:1-67` — last night's correction, endpoints verified by hand, 65
interior verses unverified — has **0 of 67 judged, and will stay 0.** Not the shuffle:

```
  org witnesses the judge may use : wlc, n1904, peshitta-ot, peshitta-nt, ojb, web
  of those, holding S3Y           : NONE
  corpora that do hold S3Y        : kjv, kjvcpb, wyc2017/18, lxx2012(uk), asvbt, rv  (all English)
```

`_task` cannot build a pair whose org side nobody may quote, so every verse of the block
falls out as unreachable. **Deliberately not fixed at 04:30 unsupervised**: the only
candidate witnesses are English, and WITNESSES' own comment records that an
English-tradition text speaking for org "is the exact fault that invalidated the first
overnight run". Changing witness policy on that axis while nobody is watching is not a
call to make alone.

For the morning: either accept the block stays unverified, or add an English org witness
for S3Y *knowingly* and re-run just that block.
## 05:35 hourly check — healthy, and the run has found its first real mapping error

Alive (pid 651127, 1h52m), 16,000/56,651 (28%), 2.6/s, ETA ~09:45.
rso 4,687 -> **9,492** judged, uninformative steady **7.7%**, contradicted 13 -> 26.
The contradiction *rate* is flat at ~0.27%, so this is not degradation with volume.

### ⚠ CONFIRMED FAULT: rso's Proverbs mappings are wrong

Five of the 26 are Proverbs, and four are a consecutive run — the signature of a
misalignment rather than noise:

```
  rso PRO 13:18 -> org 13:17      rso PRO 18:15 -> org 18:14
  rso PRO 18:9  -> org 18:8       rso PRO 18:16 -> org 18:15
  rso PRO 18:10 -> org 18:9
```

Read the text and the model is right. rso.json declares only two Proverbs mappings —
`PRO 13:15-26 -> 13:14-25` and `PRO 18:9-25 -> 18:8-24`, a one-verse shift because the
Slavonic chapters run 26 and 25 against org's 25 and 24. But at the verse the shift is
declared to *start*:

```
  GK rahlfs 18:9  ὁ μὴ ἰώμενος ἑαυτὸν ἐν τοῖς ἔργοις αὐτοῦ ἀδελφός…
  SL chuelz 18:9  Не изцеляяй себе во своих делех брат есть погубляющему…   <- identical
  MT wlc    18:9  גַּם מִתְרַפֶּה בִמְלַאכְתּוֹ אָח הוּא לְבַעַל מַשְׁחִית   <- same proverb
  MT wlc    18:8  דִּבְרֵי נִרְגָּן…  "the words of a talebearer"            <- what rso claims
```

Slavonic 18:8, 18:9 and 18:10 each match Greek 18:8, 18:9, 18:10 exactly. At verse 9 all
three traditions agree on the number, so the shift begins later than declared — or does not
exist where declared. Note `lxx` gives Proverbs 18 **22** verses against org's 24 and rso's
25 and declares *no* mapping at all, so the three systems genuinely disagree about this
chapter and only rso states a shift.

**Not fixed unsupervised**, for the same reason as the Daniel block: the fix needs the true
divergence point found by reading Proverbs 13 and 18 verse by verse, and a guessed range
would put a wrong verse behind a right-looking reference. Diagnosed, not patched.

This is the first confirmed versification error the model has produced, and it is a
pre-existing fault in the vendored rso data rather than anything introduced last night —
exercised for the first time because rso only joined DEFAULT_SYSTEMS yesterday.

DAN 3:24-90 remains 0 of 67, unreachable as established at 04:35 (task #166).
## 06:35 hourly check — healthy, and the Proverbs fault is now pinned exactly

Alive (2h52m), 24,000/56,651 (42%), 2.6/s, ETA ~09:45. rso 9,492 -> **13,960**,
uninformative easing to **7.4%**, contradicted 26 -> 33 (rate flat at 0.24%).
DAN 3:24-90 still 0, unreachable as established (task #166).

### PRO 18 — the exact correction is now known, not just the fault

The declared range `PRO 18:9-25 -> 18:8-24` has 12 of 17 verses judged:

```
   9 cont  10 cont  11 cont  12 cont  15 cont  16 cont  18 unin
  20 cont  21 unin  22 cont  24 CONF  25 CONF
```

Eight contradicted, and **the two confirmed are at the end**. That is not noise — it says
the shift is real but begins much later than declared. Reading the boundary settles it:

```
  SL 18:22  Иже обрете жену добру…      = org 18:22  "Whoso findeth a wife"     identity
  SL 18:23  Иже изгоняет жену добрую…   = nothing    an LXX plus, no Hebrew counterpart
  SL 18:24  С молении глаголет убогий…  = org 18:23  "The poor useth intreaties"
  SL 18:25  Муж любовен к дружбе…       = org 18:24  "A man that hath friends"
```

So the truth is: **18:1-22 identity, 18:23 an LXX plus with no org counterpart, 18:24-25 ->
org 18:23-24.** The current entry shifts everything from verse 9 and gives the plus no
home. It happens to get 24 and 25 right, which is exactly why those two confirmed.

Correction to write (APPEND to rso's five existing entries, do not replace — an earlier
Daniel attempt overwrote them and only the diff caught it):
```
  drop_mapped rso : "PRO 18:9-25"
  add_mapped  rso : "PRO 18:24-25" -> "PRO 18:23-24"
```
PRO 13:15-26 needs the same treatment and does not yet have the data — 4 judged, 1
contradicted, inconclusive. Leave both until the run finishes and do them together.

**Still not applied.** The evidence is complete but writing versification data unsupervised
is not what an hourly *check* is for, and half a fix — 18 without 13 — is worse than none.
Two minutes' work when someone is awake. Task #167 updated with the exact entries.

## 07:45 hourly check — healthy; two NEW structural faults found, and PRO 13 cleared

Alive (3h52m), 34,000/56,651 (60%), 2.5/s, ETA ~10:00. rso 17,363 confirmed / 44
contradicted / 1,426 uninformative. Uninformative rate **7.6%**, far under the 25% line —
the model reads Church Slavonic perfectly well.

### The discriminator: contiguity

44 contradictions across 20 chapters. Sorting them by whether they form a *contiguous run*
separates real faults from model noise cleanly, and every case checked bears it out:

```
  contiguous  SNG  6   9 of 10   <- NEW, structural
  contiguous  PRO 18   8 in a run   <- pinned at 06:35
  contiguous  PSA 139  v1-v4     <- NEW, structural
  scattered   EXO 36   v10,v28,v36   identity mapping, reads correct -> noise
  scattered   ECC  7   v4,v6         identity mapping, reads correct -> noise
  scattered   ~20 chapters with exactly 1 each          -> noise
```

### NEW — SNG 6: a mapping that was never written

rso's own file gives SNG 6 twelve verses; org gives thirteen. Chapters 1 and 6 are the
only two in the book that differ, both by one — and **chapter 1 has a mapping while
chapter 6 has none**, so every Slavonic verse falls through to identity one verse early.

The cause is visible in the text: SL 5:16 carries org 5:16 AND org 6:1 in a single verse.
"...сей брат мой и сей ближний мой, дщери Иерусалимли. **Камо отиде брат твой, добрая в
женах?**" — the second sentence is org 6:1, "Whither is thy beloved gone, O fairest among
women?". Everything after it is shifted. Verified at both ends: SL 6:1 = org 6:2, SL 6:12
= org 6:13; chapter 7 has 13 = 13 and resumes clean.

  add_mapped rso : "SNG 6:1-12" -> "SNG 6:2-13"     (org 6:1 an honest gap, per PSA 114:8)

### NEW — PSA 139: off by one through v6, correct from v7, with a split in the middle

Declared `PSA 139:0-14 -> PSA 140:0-14`, straight through. But org Psalm 140 numbers the
superscription as verse 1 ("For the one directing. Mizmor of Dovid" — ojb, wlc), while
Slavonic 139:1 is already "Изми мя" / "Deliver me". So the head is off by one:

```
  SL 139:1-4   = org 140:2-5     "Deliver me" .. "keep me from the hands of the wicked"
  SL 139:5-6   = org 140:6       TWO onto ONE -- a split no range can state
  SL 139:7-14  = org 140:7-14    identity, confirmed at v7, v8, v13, v14
```

**I nearly filed this as an instrument fault.** My first read compared against KJV, which
numbers Psalms in `eng` with titles unnumbered; against that, verses 1-4 look perfectly
aligned and the judge looks wrong. Re-read against an org-numbered witness and the judge is
right. The witness's numbering is part of the measurement — checking a versification claim
against a corpus that does not follow the system under test measures the edition, not the
mapping. Same trap as the ojb/org chapter mismatch that killed thirteen findings.

The 5-6 -> 6 split is the same species as the documented PSA 114:8 case and equally
unstatable as a range; the head (verse 0 vs the superscription at org 140:1) needs
deriving rather than guessing.

### CLEARED — PRO 13 needs no fix

The declared shift confirms: v17->13:16, v21->13:20, v22->13:21 all confirmed, v15->13:14
uninformative, v1-13 identity confirmed. **One** contradiction (v18) out of 12 — a
singleton against a mapping the surrounding verses vindicate. Dropped from the fix list.

### DAN 3 — last night's correction verified at the seam

DAN 3:91,92,96,99 -> org 3:24,25,29,32 all **confirmed**, 13 confirmed / 0 contradicted in
the chapter. That is the post-hymn resumption, the endpoint that was hand-checked. The 65
interior verses of DAN 3:24-90 -> S3Y 1:1-67 remain unjudged and unreachable exactly as
established — no org witness holds S3Y. Task #166 unchanged.

**Nothing applied.** Three fixes, one book-read still owed (the PSA 139 head), and the run
still has 2h to go — it may yet turn up more. All three land together when someone is awake.

## 08:45 hourly check — healthy; a FOURTH fault, and it overturns a hand-made correction

Alive (4h52m), 44,000/56,651 (78%), 2.5/s, ETA ~10:00. rso 21,794 confirmed / 52
contradicted / 1,839 uninformative; rate steady at **7.8%**. DAN 3:24-90 still 0 judged.

### The taxonomy sharpened: read the contradictions against per-chapter blindness

Sorting by contiguity was right but incomplete. Cross-tabulating each cluster against its
chapter's *uninformative* rate separates the three populations completely:

```
                n   confirmed  contradicted  uninformative
  PSA 139      12       7           5            0   ( 0%)   <- fault, instrument fully sighted
  PSA 114       8       2           5            1   (12%)   <- fault, NEW
  SNG   6      12       0          10            2   (17%)   <- fault
  PRO  18      22       6          10            6   (27%)   <- fault
  ---
  EXO  36      31       7           4           20   (65%)   <- BLIND chapter, verdicts uninterpretable
  ECC   7      26       1           2           23   (88%)   <- BLIND chapter
```

The faults live where the instrument can see; the leftovers live where it cannot. I had
EXO 36 and ECC 7 filed as "scattered = model noise" at 07:45. That was the right call for
the wrong reason: their contradictions are not random slips, they are verdicts from a probe
that has gone blind, and they carry ~no information either way.

**Why it goes blind, and what it cannot see.** The control probe demands NO to the
neighbouring verse. Where consecutive verses are near-duplicates the model correctly says
YES to both, and the verdict is `uninformative` — the probe refusing to certify what it
cannot discriminate. The list of blind chapters names the phenomenon by itself:

```
  HAG  2  95%   PSA 135  67%   1CH 25  61%   NEH  7  47%
  ECC  7  88%   EXO  36  65%   NUM 26  50%   LEV 13  42%   PRO 9/22/26  43-62%
```

Psalm 135 ("for his mercy endureth for ever" in every verse), the Numbers census, the
Nehemiah returnee list, the courses of musicians, Leviticus' leprosy diagnostics, the
tabernacle inventory, proverb couplets. **This run cannot verify mappings in repetitive
material at all** — roughly 8% of Slavonic verses globally, but concentrated so that some
chapters are entirely unexamined. A clean rso result must be reported with that exclusion
stated, not as blanket coverage.

### NEW — PSA 114, and the correction it overturns

v2, v3 confirmed; **v4, v5, v6, v7, v8 all contradicted.** Contiguous, in a sighted
chapter. Reading it against ojb (org numbering, per this morning's lesson):

```
  SL 114:1-3  = org 116:1-3    identity
  SL 114:4    = org 116:4 AND 116:5    ONE onto TWO -- the Slavonic merges them:
               "о, Господи, избави душу мою: милостив Господь и праведен и Бог наш милует"
               = "O LORD, deliver my soul" (org 4) + "gracious is the LORD, and righteous,
                 yea our God is merciful" (org 5)
  SL 114:5    = org 116:6      "Храняй младенцы" / "the LORD preserveth the simple"
  SL 114:6    = org 116:7      "Обратися, душе моя, в покой твой" / "Return unto thy rest"
  SL 114:7    = org 116:8      "изят душу мою от смерти" / "delivered my soul from death"
  SL 114:8    = org 116:9      "во стране живых" / "in the land of the living"
```

The declared `PSA 114:0-8 -> PSA 116:0-8` is straight-through and wrong from v4 on.

**And this reverses one of our own corrections.** corrections.json drops the stray
`PSA 114:8 -> PSA 116:9`, reasoning that `PSA 114:0-8 -> 116:0-8` is "exact and complete"
and that the stray was "apparently to express that one Orthodox verse covers two Hebrew
ones". The measurement says the opposite: the straight-through range is NOT exact, the
verse covering two is **114:4 not 114:8**, and the stray `114:8 -> 116:9` was *correct*.
We dropped the right entry and kept the wrong one. The note's closing line — "leaves org
116:9 with no rso source, which is an honest gap" — describes a gap we created.

That correction was made by inspection last night. Four judged verses overturned it. It is
the strongest argument yet for running the judge over every correction we write by hand,
and the reason the other three fixes below must be re-judged rather than assumed.

  drop_mapped rso : "PSA 114:0-8"
  add_mapped  rso : "PSA 114:1-3" -> "PSA 116:1-3"
  add_mapped  rso : "PSA 114:5-8" -> "PSA 116:6-9"
  SL 114:4 -> org 116:4-5 is a 1-onto-2 merge no range can state; and the verse-0 head
  needs the same care as PSA 139's. Amend the old drop's *reason* text too -- it is wrong.

**Nothing applied.** Four faults now, two of them touching heads (verse 0 / superscription)
that still need deriving rather than guessing. Run finishes ~10:00; fix them together after.

## 09:45 hourly check — healthy, 92%, nothing new

Alive (5h52m), 52,000/56,651 (92%), 2.5/s, ~31 min left, finishing ~10:15. rso 26,245
confirmed / 58 contradicted / 2,213 uninformative; rate flat at **7.8%** for the third
hour running. DAN 3:24-90 still 0 judged, unreachable as established.

The last 8,500 verses produced **no new cluster**. The contradiction table is unchanged in
shape — PRO 18 (11), SNG 6 (10), PSA 114 (5), PSA 139 (5) are the four faults; EXO 36 (4)
and ECC 7 (3) remain the two blind chapters; the rest are singletons. The fault set looks
closed, though the tail of the run is still to come.

Nothing to do. Next check catches the finish and the report.

## 10:15 — FINISHED CLEAN at 09:56. Final result, and a fifth fault.

56,651 judged in 371 min (2.5/s). Coverage exit 0, tests exit 0. Report at
`~/.local/share/biblereference/audit/overnight.md`.

```
  family   judged   confirmed  contradicted        uninformative
  rso      30,184     27,770     64  (0.21%)       2,350  (7.8%)
  nvl      32,815     31,252     12  (0.04%)       1,551  (4.7%)
  lxx       5,390      4,629     49  (0.91%)         712 (13.2%)
  eng       5,769      5,171      7  (0.12%)         591 (10.2%)
  vul       2,783      2,397      7  (0.25%)         379 (13.6%)
```

**The Slavonic came out better than the Greek and the Latin on both axes.** Its
contradiction rate (0.21%) is under vul's and a quarter of lxx's, and its uninformative
rate (7.8%) is the second lowest in the run — the model reads Church Slavonic more reliably
than it reads Brenton's Greek or the Vulgate. The worry that prompted this run, that a new
language would prove unreadable, is answered in the opposite direction.

The 64 contradictions decompose completely, with nothing left over:

```
  33  five structural faults    PRO 18 (11), SNG 6 (10), PSA 114 (5), PSA 139 (5), NUM 10 (2)
   8  two blind chapters        EXO 36 (5), ECC 7 (3)   -- 65% and 88% uninformative
  23  singletons               one chapter each, all against identity, model slips
  --
  64
```

### NEW, and the last one — NUM 10:34-36 is transposed, not shifted

31 of 36 confirmed, only 3 uninformative: a fully sighted chapter, so the two
contradictions are signal. They land on the passage the Masoretes marked with **inverted
nuns** — the scribal flag for exactly this displacement:

```
  SL 10:34  "И бысть егда воздвизаху кивот, и рече Моисей: востани, Господи"
            when the ark set out, Moses said: Rise up, O LORD          = org 10:35
  SL 10:35  "И в поставлении (кивота) рече: возвращай, Господи"
            and when it rested he said: Return, O LORD                 = org 10:36
  SL 10:36  "И облак Господнь бысть осеняющь над ними в день"
            and the cloud of the LORD was upon them by day             = org 10:34
```

The Slavonic follows the LXX in putting the cloud verse *after* the two ark formulas; the
Hebrew puts it before. This is a **rotation of three verses, not a shift** — and unlike the
splits in PSA 114 and PSA 139 it is perfectly statable, as two equal-length ranges:

  add_mapped rso : "NUM 10:34-35" -> "NUM 10:35-36"
  add_mapped rso : "NUM 10:36"    -> "NUM 10:34"

### Where this leaves things

Five faults to write (task #167), all pinned by reading the text against an org-numbered
witness. Two of them touch superscription heads that still need deriving. One of them,
PSA 114, overturns a correction we made by hand last night — which is why every one of
these must be re-judged after writing rather than assumed.

DAN 3:24-90 finished at 0 judged, exactly as predicted: no permitted org witness holds S3Y,
so the run could never reach it. Task #166 stands untouched by six hours of compute, which
is itself the answer — that block needs a different instrument, not more of this one.

Hourly watch cron deleted; its job is done.
