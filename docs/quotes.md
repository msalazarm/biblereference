# Finding every quotation that can be found

*A design for the next generation of quotation, allusion and reference detection.
2026-08-15, augmented same day with three further research passes — sequence
bioinformatics, security/forensics, and a survey of open ancient scripture corpora.
Grounded in the measurements of `churchfathers/review/`; every number below names its
source, and every licence stated was verified on the licence page itself or is marked
unverified.*

---

## 1. Where we stand

Against the 159 citations Stephen Boyce tabulated by hand across nine Greek works (80
direct, 43 partial, 36 indirect — `review/boyce-golden.jsonl`), the recalibrated frontier
(`review/gate-calibration-greek.md`):

| errors | recall | precision | gate |
|---|---|---|---|
| 0 | 43/159 · **27%** | 100.0% | `lemma_run>=3, 35 bits` |
| 2 | 55/159 · **35%** | 96.9–98.4% | `run>=3/35 ∪ lemma_run>=4/25 ∪ chain>=4/40` |
| 3 | 57/159 · 36% | 97.1–97.8% | `run>=3/25 ∪ lemma_run>=2/40` |

At the wide-open gate — every threshold at its floor — the ceiling decomposes by Boyce's own
grades: **direct 46/80 (57%), partial 2/43 (5%), indirect 1/36 (3%)**. No threshold reaches
past roughly 40%, because the rest is not written in the verse's words.

**That is the frontier of the field, not a shortfall against it.** The one published study
of our exact problem — Manjavacas, Long & Kestemont, *On the Feasibility of Automated
Detection of Allusive Text Reuse* (LaTeCH-CLfL 2019, [aclanthology.org/W19-2514](https://aclanthology.org/W19-2514/)),
biblical allusion in Bernard of Clairvaux against all 34,835 Vulgate verses — found the best
method retrieves the right verse in the top twenty **less than half the time** (P@20 47.6%),
and that the hand-crafted Tesserae intertextuality score *loses to plain TF-IDF*. The best
number on any adjacent task is F1 = 0.91 on Midrashic Hebrew quotation
([ACT, arXiv:2512.23504](https://arxiv.org/pdf/2512.23504)), against Dicta's 0.78 and
passim's 0.62 on the same gold set.

So the frame of this document is not "catch up." It is: **the remaining misses have names
and counts, and each class is bought separately, priced on the control corpus before it
ships.** The consumer's rule stands throughout: a change that materially raises the
false-positive rate on pre-Christian Greek is refused whatever it recalls.

## 2. The miss ledger

Everything proposed below buys rows in this table and nothing else. Sources:
`review/extras-verdicts.json` (102 verdicts, every open-gate proposal in the nine works read
by hand), `review/indirect-misses.json` (35 records), `review/gate-calibration-greek.md`,
and Boyce's own prose (extraction: 231 pp., all six papers).

**Misses** — citations Boyce grades that no gate reaches:

| class | evidence | bought by |
|---|---|---|
| **Byzantine-variant quotations.** The father's Greek matches Byzantine/Majority wording; the library's Greek NTs (`n1904`, `sblgnt`, `wh`) are all critical editions. | 8 documented cases in Boyce (Did. 1:3b, 9:1, 10:5, 16; 1 Clem 23:5b; Pol. 1:3, 4:1, 12:3c). **No Greek Byzantine NT is held at all.** | Stratum 0: fetch Robinson–Pierpont |
| **Itacism drift.** Scribal ει/ι, η/ι, ω/ο interchange between transmission and edition. | `emphasis.fold(orthographic=True)` exists (`emphasis.py:251`) and **no search path ever passes it** — verified by grep, the parameter is used only in its own tests. | Stratum 0: itacised tier |
| **Conflations.** Several verses fused into one sentence; the matcher returns one best match per span, so the other sources are structurally invisible. | 1 Clem 13:2 fuses **five** sayings (Boyce's own table lists three); Polycarp 2:3 fuses three; ~10 more named in his prose (34:6a, 35:7, 36:5, 46:8, 51:4a…). | Stratum 0: all local alignments per span |
| **Paraphrase substitution.** Synonym, title, or case swaps inside otherwise-close quotation (1 Clem 4:4 → Gen 4:6-7: "the Lord God"→"God", added πρὸς, dropped article — the one miss inside a six-verse run otherwise found exactly). | Moritz et al. (EMNLP 2016, [D16-1190](https://aclanthology.org/D16-1190/)) taxonomize exactly these operations on BiblIndex-annotated Bible reuse and find most real reuse shares under 50% of tokens. | Stratum 1 scoring + Stratum 3 annex |
| **Zero-content-word allusions.** Boyce read the sense; there are no words to match. | **9 of 35** indirect misses share zero content words with the verse (`indirect-misses.json`); 22 share 1–3. | Stratum 3, honestly bounded — and §13 |

**Misfires** — the 102 verdicts on what the open gate proposes:

| class | n | bought by |
|---|---|---|
| named the *other end* of an inner-biblical quotation (ACT 8:32 for ISA 53; both right) | **34** | Stratum 2: quotation families |
| liturgical formula (one doxology, five biblical addresses) | **19** | Stratum 2 + Stratum 4 |
| plain false positive | 15 | Stratum 1 significance |
| genuine citation Boyce did not list | 14 | — the return on the exercise |
| epistolary salutation (positional, up to 58 bits, no lexical defence) | 10 | Stratum 4 |
| unclear / filed one section over / other held edition | 6+3+1 | family reporting absorbs most |

## 3. Prior art, and what transfers

Each entry: mechanism, then the one thing this design takes from it.

- **Tesserae** (Coffee, Forstall et al.; [github.com/tesserae](https://github.com/tesserae)) — ≥2 shared
  lemmata per phrase pair, scored `ln[(1/f₁ + 1/f₂)/(d_source + d_target)]` where distance
  is measured between the two *rarest* shared words. Recall on the Lucan–Vergil commentary
  benchmark rose from ~25% to 62–72% when frequency+distance scoring replaced raw overlap.
  *Transfers:* anchoring distance to the rarest shared pair; and their graded 1–5
  significance benchmark as a template for enriching gold data.
- **TRACER** (Büchler, eTRAP; [manual](https://tracer.gitbook.io/manual/)) — a
  preprocessing → featuring → selection → linking → scoring pipeline with ~60 selection
  strategies. *Transfers:* the **Moving Window** linking mode (short verse inside a long
  non-quoting sentence) and the **containment vs resemblance** distinction — score overlap
  against the *shorter* unit when lengths are asymmetric, which is exactly the
  verse-in-patristic-sentence shape. BiblIndex itself has run TRACER experimentally.
- **passim** (D. Smith; [Programming Historian lesson](https://programminghistorian.org/en/lessons/detecting-text-reuse-with-passim)) —
  n-gram shingle index for candidates, then Smith–Waterman **anchored to the shingle seeds**
  rather than run in full. *Transfers:* the seed-and-extend cost bound, which our
  FTS-seeded pipeline already approximates and should keep.
- **Shmidman, Koppel & Porat** ([JDMDH 2018](https://jdmdh.episciences.org/4175); now
  Dicta) — each word hashed to its **two least-frequent letters**; matching 4-of-5-word
  skip-grams with ≤8-word gaps found 4,602 parallel-passage pairs in the 1.8M-word Talmud in
  seconds, with effectively complete recall on the audited tractate pair. *Transfers:* a
  dictionary-free candidate generator to backstop lemmatizer coverage gaps — our lexicon
  analyses `διά` only as *Zeus*, and there will be more like it.
- **ACT** ([arXiv:2512.23504](https://arxiv.org/pdf/2512.23504)) — four quotation styles:
  Simple, **Wave** (quotation interleaved with commentary), Echo, Compound. F1 0.91.
  *Transfers:* the Wave/Compound framing for conflation handling in Stratum 0.
- **Manjavacas et al. 2019** — see §1. Two further findings transfer: **query
  span-bounding matters more than scoring refinement** (hand-bounded queries beat sliding
  windows regardless of method; trained annotators only reach κ=0.22 on the bounds), which
  independently validates the chain-defines-the-span design already shipped; and **bounded
  semantics beat both pure lexical and pure embeddings** (soft-cosine + fastText 47.6 P@20
  vs TF-IDF 43.4 vs WMD 27.9) — semantics as a *backoff where lemma match fails*, never a
  re-ranking of everything.
- **Bamman & Crane 2008** ([Perseus PDF](https://www.perseus.tufts.edu/~ababeu/latech2008.pdf)) —
  lexical, word-order and syntactic features folded into **one** TF-IDF space rather than
  bolted-on gates. *Transfers:* the architecture, if dependency parses ever arrive.
- **DHQ Jerome tool** ([DHQ 18.3](https://dhq.digitalhumanities.org/vol/18/3/000716/000716.html)) —
  an *Auctoritas* filter keeping only matches co-occurring with an explicit attribution cut
  false positives 22–30%. *Transfers:* formula-scoped gating (§10) — the only published use
  of citation formulae in detection, and it worked.
- **Oxford Society of Historical Theology 1905** (*The NT in the Apostolic Fathers*,
  [archive.org](https://archive.org/details/thenewtestamenti00unknuoft), public domain) —
  the A/B/C/D certainty classes, with a/b/c/d sub-ranks: an eight-level ordinal certainty
  scale with 120 years of standing. *Transfers:* citable precedent that graded certainty —
  not binary verdicts — is how the discipline itself records this.
- **Gregory & Tuckett 2005** — reference / quotation ("significant degree of verbal
  identity") / allusion ("less verbal identity"), with the warning against maximalist
  criteria. **BiblIndex's own methodology page** goes further: the quotation/allusion
  distinction "cannot be objective, it remains an insufficient sorting criterion."
  *Transfers:* the whole evidence-over-verdict doctrine this system already follows is the
  field's own conclusion, and can now cite it.

### 3b. Sequence bioinformatics

Genomics has spent thirty years on our exact shape of problem — find a short, mutated
subsequence of a known reference inside a large noisy text, at controlled false-positive
rates — and it wrote the theory down.

- **Spaced seeds** (PatternHunter, [Ma–Tromp–Li 2002](https://academic.oup.com/bioinformatics/article/18/3/440/236636);
  [PatternHunter II](https://pubmed.ncbi.nlm.nih.gov/15359419/)) — a seed like
  `111*1**1*1**11*111` requires matches only at its `1` positions. At *equal weight* —
  hence equal expected random-hit rate — an optimally spaced seed is markedly more
  sensitive than a contiguous one, because scattered substitutions rarely hit every
  required position, while one substitution kills a contiguous run. ~20% more true
  alignments than BLAST at equal speed; multiple-seed sets get near Smith–Waterman
  sensitivity. *Transfers:* our `run`/`lemma_run` gates are the degenerate contiguous case.
  A spaced *lemma* seed (say weight 6 of 8) is a candidate gate axis for re-inflected
  quotations that break contiguity — with an actual sensitivity/FP theory behind it instead
  of hand-tuning, and priced per-seed on the control corpus like any gate.
- **Formal co-linear chaining** ([minimap2, Li 2018](https://arxiv.org/pdf/1708.01492);
  [Jain–Gibney–Thankachan 2022](https://par.nsf.gov/servlets/purl/10342340)) — chaining
  anchors under a **concave gap cost** (`0.01·w̄·|l| + 0.5·log₂|l|`): one long interpolated
  clause is penalised far less per word than the same slack scattered, which matches how
  fathers actually interrupt a quotation. Optimal chaining is O(n log n), not a greedy
  walk; and **multiple near-optimal chains are reported**, not just the winner. *Transfers:*
  our hard 8/2 gap bounds become a cost function; the chain DP becomes optimal; and
  multi-chain reporting is the *principled* mechanism for conflations (§4.3) — one sentence
  weaving five sayings yields five chains, each gated on its own evidence.
- **Profiles** (PSI-BLAST PSSMs, [Altschul et al. 1997](https://academic.oup.com/nar/article/25/17/3389/1061651);
  profile HMMs, [HMMER](https://github.com/EddyRivasLab/hmmer)) — match a query against a
  *family* of related sequences at once, with per-position weights learned from a multiple
  alignment: conserved positions demand a match, variable positions carry the attested
  alternatives natively, insert states absorb interpolation. *Transfers:* see §6 — this is
  the proper shape for the edition-variant problem, and the research pass ranked it the
  single highest-value transfer.
- **Variation graphs** ([vg, Garrison et al. 2018](https://www.nature.com/articles/nbt.4227)) —
  the reference as a graph whose alternative paths are the attested variants; align once
  against the graph instead of against N editions. *Transfers:* the documented scale-up of
  profiles, named in §6 as the version to build only after profiles prove the cost is real.
- **Low-complexity masking** (SEG, [Wootton & Federhen — described in Bioinformatics 2005](https://academic.oup.com/bioinformatics/article/21/2/160/187330);
  DUST, [docs](https://meme-suite.org/meme/doc/dust.html)) — repeats and low-entropy runs
  are masked *before* search, so they can neither seed a hit nor pad a score. *Transfers:*
  the structural answer to the doxology, adopted in §9: a window whose aggregate surprisal
  is too low **may not seed**, which is exclusion, not down-weighting — a different and
  stronger mechanism than the weights we already apply.
- **FracMinHash containment** ([sourmash line; estimator paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12082993/)) —
  unbiased "what fraction of small set A is inside large set B" from sketches, built for
  exactly our set-size asymmetry (a verse's k-grams inside a paragraph's). *Transfers:* a
  cheap order-agnostic pre-filter/secondary score before the chain DP runs.
- **Two-hit seeding and X-drop extension** ([gapped BLAST 1997](https://academic.oup.com/nar/article/25/17/3389/1061651)) —
  require two nearby seeds on one diagonal before paying for extension (~3.2× more raw
  hits, ~0.14× the extensions); abandon an extension whose score falls X below its best.
  *Transfers:* pure compute controls for the 45M-word sweep, same acceptance semantics.
- **Kraken-style LCA attribution** ([Wood & Salzberg 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC4053813/)) —
  when k-mers are ambiguous among taxa, classify to the lowest common ancestor the evidence
  supports. *Transfers:* report the most specific level the words support —
  verse → parallel-family → book — instead of forcing a single verse; §6's families give
  the hierarchy.

### 3c. Forensics, plagiarism and intelligence

The security world's problem is ours inverted: find the foreign material an author tried
*not* to mark. Three of its traditions converge on one capability we lack — see §7.

- **Winnowing / MOSS** ([Schleimer, Wilkerson & Aiken, SIGMOD 2003](https://theory.stanford.edu/~aiken/publications/papers/sigmod03.pdf)) —
  local fingerprinting with a *proof*: any match of length ≥ t is detected, at ~1/w storage
  density, within a constant factor of the optimum. *Transfers:* run over the lemma stream,
  it gives the one thing no gate can — a guarantee that nothing verbatim-ish above a stated
  length is silently missed by candidate generation.
- **Fuzzy hashing from malware forensics** — ssdeep's context-triggered chunking misbehaves
  on short inputs; [sdhash](http://roussev.net/sdhash/sdhash.html) selects 64-byte
  **statistically improbable features** (our surprisal weighting, independently reinvented
  in digital forensics) and scores by Bloom-filter overlap; TLSH publishes operating points
  (distance ≤ 30 → FP 0.00181%, secondary source); [LZJD](https://arxiv.org/abs/1708.03346)
  is the short-fragment-sensitive design. Two field lessons transfer directly: **thresholds
  must be set per content type** (Roussev drops text's threshold 4× vs binaries), and
  **[FP rates measured on curated corpora understate scale](https://documents.trendmicro.com/assets/wp/wp-using-randomization-to-attack-similarity-digests.pdf)** —
  which is why the control corpus, not the golden set, prices every gate here.
- **SimHash + Hamming-ball indexing** (Charikar; Manku et al., WWW 2007) — 64-bit weighted
  fingerprints searched within Hamming distance k via C(6,3)=20 permuted tables, no
  distance computations. *Transfers:* sub-linear candidate generation if FTS seeding ever
  binds; blind to zero-overlap allusion, like everything lexical.
- **Intrinsic plagiarism / style-change detection** (PAN@CLEF; founding method
  [Meyer zu Eissen & Stein 2006](https://link.springer.com/chapter/10.1007/11735106_66)) —
  find inserted foreign text with **no reference corpus at all**, from internal style shift:
  windowed function-word rates, word-frequency-class profiles, character n-grams, outlier
  merging. Sobering numbers, honestly reported: the best span-level plagdet at
  [PAN 2011](https://pan.webis.de/clef11/pan11-web/intrinsic-plagiarism-detection.html) was
  **0.33** (Oberreuter), and Stamatatos' n-gram method a decade later reached ~0.33 F on
  PAN-PC-09 — while *document-level* style-change classification hit ~0.90 at PAN 2018.
  Granularity, not scoring, is what collapses performance. *Transfers:* §7 — with one
  crucial difference in our favour: PAN discriminates same-register prose from same-register
  prose; we discriminate **translationese scripture from literary patristic prose**, a
  genuine register gap.
- **Rolling stylometry** ([Eder, DSH 2016](https://computationalstylistics.github.io/projects/rolling-stylometry/)) —
  Burrows' Delta (deterministic function-word frequency distance, no training) in sliding
  windows, locating authorial takeover points; demonstrated on a Bible translation (Queen
  Sophia's Bible) and on Conrad/Ford, where the signal survived heavy editing. *Transfers:*
  §7's second detector — Delta to *two* profiles, the father's own corpus and scripture's;
  a window that swings toward scripture's profile is a boundary signal.
- **Payload anomaly detection** (PAYL/Anagram, Wang & Stolfo,
  [RAID 2004](http://www.cs.columbia.edu/ids/sites/default/files/RAID4.PDF)) — model
  "normal" n-gram distributions, flag deviation; Anagram's move to higher-order n-grams
  defeats mimicry, Bloom filters hold the model. *Transfers:* §7's primary detector — a
  **dual n-gram LM log-likelihood-ratio scan**, `log P(window|scripture) − log
  P(window|father)`, deterministic, built from counting, thresholded on the control corpus.
  The n>1 lesson answers ambient idiom: a father's own biblical flavour matches his own
  model at the n-gram level; only borrowed runs are jointly improbable under his model and
  probable under scripture's.
- **Forensic idiolect** ([Wright & Johnson, n-gram textbites](https://eprints.whiterose.ac.uk/90461)) —
  recurrent 2–6-word n-grams are strongly idiolectal. *Transfers:* the **recurrence test**:
  a scripture-matching chunk that recurs ≥2× elsewhere in the father's *own* prose is his
  idiom, not a quotation — a deterministic filter for the ambient-idiom class, applied as
  evidence on the match rather than as a silent veto.
- **Detection-theory reporting** (watermarking/steganalysis convention) — publish
  probability-of-detection against probability-of-false-alarm at stated operating points,
  the way TLSH does. *Transfers:* §10 adopts it; it is the honest form for a near-zero-FP
  instrument.

## 4. Stratum 0 — make the text match the text

The cheapest recall in the ledger is not in the matcher at all.

**4.1 Fetch the Byzantine Greek New Testament — now verified.** Eight documented Boyce
cases agree with Byzantine wording against every Greek NT we hold, and they are
unrecoverable by any threshold because the text is simply absent. The Robinson–Pierpont
Byzantine Textform is **confirmed public domain** ("The text and its analysis are in the
Public Domain"), official source
[github.com/byztxt/byzantine-majority-text](https://github.com/byztxt/byzantine-majority-text)
— TEI-XML, Unicode CSV, *and morphologically parsed*, which can also enrich the Greek
lemma lexicon. Beside it, two companions from the same verified survey: the **Antoniades
1904 Patriarchal text** (PD, [github.com/byztxt/greektext-antoniades](https://github.com/byztxt/greektext-antoniades)),
the received Orthodox liturgical text — what a Byzantine-era father's tradition actually
read aloud; and **Codex Bezae's Latin column** (**CC BY**, TEI-XML at Birmingham eprints
[1664](https://epapers.bham.ac.uk/1664)), a fifth Old Latin witness covering Gospels *and
Acts*, which our two Old Latin codices do not. All three serve the attribution goal too:
"the father reads the Byzantine text here" is itself a finding of scholarly value, exactly
as `anachronistic` already is for translations.

**4.2 Wire the itacised tier.** `fold(orthographic=True)` collapses ει/ι, η/ι, ω/ο — "the
single largest class of orthographic variant in Greek manuscripts" by its own docstring —
and nothing reaches it. Add it as an opt-in *second* matching tier under `inflected`: exact
fold first, itacised fold only where the first declines, matches flagged `itacised` so the
looseness is visible. Priced on the control corpus like every other loosening. (It makes
ὑμεῖς/ἡμεῖς one string; the flag is what makes that survivable.)

**4.3 Enumerate all local alignments per span.** The matcher keeps one best match per
cluster, so a sentence weaving five sayings yields at most one finding and four structural
misses — per-clause, as `indirect-misses.json` shows for 1 Clem 13:2's Matt 5:7 and 6:14
clauses. The principled mechanism is **multi-chain reporting from formal co-linear
chaining** (§3b): run the optimal chaining DP and report every near-optimal chain over the
span, not the winner alone — one sentence weaving five sayings yields five chains, each
gated on its own evidence. (The BLAST-HSP fallback — re-run on the uncovered remainder —
gives the same behaviour with today's ad hoc chain if the formal DP waits.) Each finding
carries its own axes; `_without_overlaps` already knows how to arbitrate overlapping
claims. Expected recovery: the conflation rows, which include some of the 34 missed
directs.

## 5. Stratum 1 — principled significance

Thresholds today are hand-tuned bit floors chosen from measured tables. Two refinements,
one of them (to our knowledge, per the literature pass) novel in this field:

**5.1 E-values.** Bioinformatics scores an alignment by the *expected number of
equally-good chance hits given the database size* (Karlin–Altschul). No text-reuse system
found in the literature applies this formally — passim thresholds raw alignment length,
Tesserae hand-tunes. We hold what the fit needs: a 2.79M-word control corpus in which every
match is false by construction, giving the null score distribution directly. Fit the tail
(Gumbel if it obliges; empirical percentiles if not — the fallback is what we already do),
and report `E` on every match: *"0.03 expected chance hits this good in 44.9M words"* is a
defensible sentence in a way *"41 bits"* is not. Gates keep working unchanged; `E` rides
alongside until it earns trust.

**5.2 Containment scoring.** `_coverage` is already asymmetric (matched share *of the
query*). TRACER's lesson is to be deliberate about the other direction too: when a
candidate verse is much shorter than the span (one clause of a conflation), score
containment of the *verse*, so a whole short verse embedded in a long sentence is not
diluted by the sentence. Feeds 4.3.

**5.3 The chain grows up.** Replace the hard 8/2 gap bounds with minimap2's concave gap
cost, run the optimal O(n log n) chaining DP instead of the current heuristic walk, and
report near-optimal secondary chains (§3b). Same objective, actually maximised — a pure
recall gain at unchanged FP semantics — and the multi-chain output is what 4.3 consumes.

**5.4 Priced experiments and compute controls.** A **spaced lemma-seed** gate axis
(PatternHunter theory, §3b): candidate patterns priced individually on the control corpus,
shipped only if a pattern beats the contiguous gates at equal measured FP. **FracMinHash
containment** as a cheap pre-filter before the chain DP. **Two-hit seeding** and **X-drop**
as compute controls on the 45M-word sweep — same acceptance semantics, fewer wasted
extensions.

## 6. Stratum 2 — quotation families, and the profile that makes them matchable

The single largest verdict class (34 of 102) is the scanner being right in a way the
scoring calls wrong: it names Acts 8:32 where Boyce names Isaiah 53, and *both are the same
words* because Acts is quoting Isaiah. The doxology is the same shape harder: one prayer,
five biblical addresses, no principled winner.

Precompute the Bible's internal parallel structure, once, at index time:

- **Seed** from OpenBible cross-references (~340k verse pairs, CC BY,
  [a.openbible.info/data/cross-references.zip](https://a.openbible.info/data/cross-references.zip) —
  built on the public-domain Treasury of Scripture Knowledge).
- **Verify** each seeded pair with our own lemma-chain — a cross-reference is a topical
  link, not necessarily a verbal one, and only verbal parallels belong in the index. The
  verification is the same `lemma_chain` the matcher runs; a pair that cannot clear a
  conservative gate against itself is dropped.
- **Extend** with pairs our own index finds that the seed list lacks (the all-pairs sweep is
  bounded by FTS seeding, same as any scan).

Store as `parallel_family(verse ↔ verse, chain, bits)`. Then:

- A match reports its **family**, not an arbitrary member: `ISA 53:7-8 ≡ ACT 8:32-33` in
  one finding, with the evidence for which end the father's wording actually favours (1 Clem
  43:1's wording is Numbers 12:7, not Hebrews 3:5 — the system already sees this; now it can
  say it).
- The doxology returns **all five addresses**, which is what the consumer concluded it
  should ("`alternates` listing all five is the right shape of answer after all").
- **Family-precision** becomes the reported metric: a finding is correct if the family
  contains the scholar's address. The 34-verdict class stops being scored as error, which
  it never was.

**6b. The per-verse profile — the family made matchable.** The research pass's top-ranked
transfer (§3b) gives the family index its matching form. For each verse-family, align every
held edition of the verse (critical, Byzantine, Antoniades) and every family member (LXX
doublet, synoptic parallel, NT quotation of it) — a small MSA, MAFFT-style, a handful of
sequences. The alignment's columns become a **position-specific profile**: where every
witness agrees, a match is demanded; where witnesses vary, the attested alternatives are
carried natively (an itacistic spelling, a Byzantine plus-word, a doublet's divergent
clause); insertions get insert-columns, so a parallel with extra material does not corrupt
the shared core. The matcher then scores a father's sentence against **one profile per
family**, not against N editions separately — which removes the recall dilution of N
independent attempts, represents the §4.1/§4.2 variants structurally rather than as special
cases, and makes "which reading does the father follow" a *free output* of the alignment
rather than a separate study. **Variation graphs** (§3b) are the documented scale-up if
profiles prove the cost is real; profiles are the MVP, and the §4 fetches are their
feedstock — the cheap per-edition matching ships first and is never gated behind the
profile build.

## 7. Stratum R — register scanning

The three forensics traditions of §3c converge on a capability no quotation stratum has:
detecting scripture **as foreign material in the father's prose, with no source match at
all**. This attacks the two hardest open problems at once — span bounding, which Manjavacas
showed matters more than scoring, and the zero-overlap allusions no lexical method can see.

- **The primary detector: a dual n-gram log-likelihood-ratio scan.** Two count-based
  language models — scripture's (ours, from the held corpora) and the father's own (built
  from his securely-attested prose, which is the consumer's corpus and their side of the
  build). Slide a window; score `log P(window | scripture) − log P(window | father)`;
  peaks are boundary signals. Deterministic, closed-form, thresholded on the control corpus
  like everything else. Higher-order n-grams (Anagram's lesson) are what separate borrowing
  from a father's own biblical flavour: his idiom matches *his* model; only inherited runs
  are jointly improbable under his and probable under scripture's.
- **The second opinion: rolling Delta to two profiles.** Burrows' Delta — function-word
  frequency distance, no training — in sliding windows against the same two profiles. The
  father's particles (μέν/δέ/γάρ; enim/autem/igitur) against translationese's; a window
  swinging toward scripture's profile marks a candidate span. Known to survive heavy
  editorial revision (the Conrad/Ford result), which is what a manuscript tradition does to
  a quotation.
- **The ambient-idiom filter: the recurrence test.** A scripture-matching chunk that recurs
  ≥2× elsewhere in the father's own corpus is his idiom, not a quotation. Deterministic;
  reported as evidence on the match, never a silent veto.

Three disciplines on this stratum. It is **instrumentation first**: a flagged
scripture-register span with no resolved source joins the unmatched-formula ledger (§10) as
a measured miss — that alone justifies the build. It is **default never** until priced:
PAN's span-level numbers (~0.33 F) are humbling even granting that our cross-register case
is materially easier than their same-register one, and the coarse-vs-fine gap in PAN's own
results (~0.90 document-level vs ~0.33 span-level) says boundaries will need conservative
merging. And it is **shared work**: the scripture-side model is the library's; the
father-side profile needs the consumer's corpus, and the interface is a model file, not a
coupling.

## 8. Stratum 3 — the allusion pass

The layer for what word-matching cannot reach, built from the user's three design ideas —
each of which the research pass independently validated — plus the field's one hard
finding about method.

**7.1 The entity index** *(user's idea; the data already exists, licensed)*. Fetch
**TIPNR** (Tyndale House STEPBible-Data, CC BY 4.0): every biblical proper noun with every
verse reference, Hebrew and Greek surface forms cross-linked per individual — 4,263
entities. Project onto every held corpus via versification, exactly as `PassageReader`
already projects references. Fetch **Theographic** (CC BY-SA 4.0) for the per-verse
people/places table (31,101 rows) and its 449 narrative **events** — the episode index. The
ShareAlike obligation is tracked in `licences.py` like every other licence; it binds any
*published derivative dataset*, not internal use.

**7.2 Activation only where no quotation covers the span** *(user's idea)*. The allusion
pass never competes with the quotation strata: it runs on the residue. This is both the
precision discipline (a span already explained needs no looser explanation) and the
consumer's standing doctrine ("keeping both accounts… and never merging them").

**7.3 Retrieval, lexical-first.** Manjavacas is unambiguous: on this task, TF-IDF-class
lexical retrieval beats embeddings, and *bounded* semantic backoff beats both. So: score a
candidate episode/verse-set by (a) entity co-mention (the gazetteer), (b) rare-lemma
overlap weighted by the surprisal machinery that already exists, (c) a **PPMI soft-cosine
backoff** for content words the lemma match misses — count-based vectors derived by us from
a pinned snapshot of the Diorisis corpus (10.2M words, CC BY 4.0, figshare DOI
10.6084/m9.figshare.6187256), bit-reproducible from corpus + script (Levy, Goldberg &
Dagan's standard argument). No neural signal in this path, per the consumer's constraint —
the deterministic line is held.

**7.4 The author prior, for ties only** *(user's idea)*. The evidence for it is already in
the consumer's own tables: Augustine quotes Matthew over Mark **16.4 : 1**, Aquinas
6.8 : 1. Where two candidate sources score within the tie margin, prefer the book the
*document itself* has already quoted — computed from the deterministic strata's findings for
that document, so the pass stays order-independent (quotes first, allusions second — the
user's two-pass framing). Two guards: the prior **never** promotes a candidate past the
gate, only orders near-ties; and `alternates` always carries what lost, so the
rich-get-richer bias this could introduce is visible rather than silent.

**7.5 Output.** New grades `allusion` and `reference` (the Gregory & Tuckett names),
never merged with quotation grades, each carrying its axes: entities shared, lemmas shared,
episode matched, prior applied or not, and `E` once Stratum 1 lands. The Oxford A–D scheme
is the citable precedent for shipping graded certainty rather than verdicts.

## 9. Stratum 4 — convention immunity

Two classes are systematic and deserve structural answers rather than thresholds:

- **Stock phrases.** The structural mechanism is genomics' (§3b): **a low-complexity span
  may not seed.** DUST/SEG mask repeats *before* alignment so they neither trigger a search
  nor pad a score — exclusion, which is stronger than the down-weighting we already do. A
  window whose aggregate surprisal falls below a floor is masked from seeding (it can still
  be *covered* by a match seeded elsewhere, so a real quotation that happens to contain a
  doxology is unharmed). The biblical half of "is this a stock phrase" — "this span's lemma
  sequence stands in N places" — falls out of the Stratum 2 family index free. The
  patristic half — "and it is ubiquitous in Christian prose" — needs patristic
  frequencies, which is the consumer's corpus and, by agreement, their build; we carry
  whatever signal they compute on the response. A small hand-curated stoplist of doxologies
  and graces (the research pass found no published one — ours would be the first) guards
  the gap until then.
- **Salutations.** Positional: the span is a letter's address or farewell and the target is
  an epistle's first or last verse. Position in the *document* is the consumer's knowledge;
  the library's half is an epistle first/last-verse table, one afternoon's data, exposed on
  the match as `positional_candidate` for them to combine.

## 10. Instrumentation — measuring what we miss

- **The formula-anchored false-negative detector.** `formulae.py` already recognises
  γέγραπται and its kin, measured at 6× enrichment in the fathers. An announced quotation
  with **no match within reach** is a *measured miss* — the one kind of false negative
  visible without gold data. No published system uses formulae this way (the literature
  pass found only the DHQ precision filter). Report unmatched formulae per scan; the list
  *is* the recall-debt ledger, self-updating.
- **The unresolved-register-span detector** (once Stratum R exists): a span the register
  scan flags as scripture-shaped with no resolved source is the second self-updating miss
  ledger, and the only one that can see zero-overlap allusions at all.
- **Recall stratified by announcement.** Formula-adjacent vs unmarked, per Manjavacas'
  segmentation finding — if the ceiling is mostly unmarked citations, that is a fact about
  the corpus worth knowing before more tuning.
- **Detection-theory reporting.** Operating points published as probability-of-detection
  against probability-of-false-alarm (the fuzzy-hashing and watermarking convention, §3c),
  with the control corpus as the false-alarm denominator — the honest form for an
  instrument that promises near-zero false positives.
- **Gold**: `boyce-golden.jsonl` (159+14), the 5,044 PTA editor marks, the control corpus.
  **BiblIndex** (270k verified patristic references, Sources Chrétiennes) has no open
  licence and an auth-gated API — worth one email to Laurence Mellerin's team; as gold it
  would dwarf everything above. Until then it prices nothing and validates methodology only.

## 11. The corpus ledger — texts we do not hold

Every entry verified on its own licence page during the survey (2026-08-15); "unstated"
means exactly that. Fetched-never-vendored, terms recorded in `licences.py`, as always.

**Acquire** — clean licences, machine-readable, ordered by quotation-matching value:

| text | source | licence (verified) | extent | why |
|---|---|---|---|---|
| Robinson–Pierpont Byzantine Textform | [github.com/byztxt/byzantine-majority-text](https://github.com/byztxt/byzantine-majority-text) | **Public domain** (stated in repo) | whole NT, TEI/CSV, morphologically parsed | the 8 named variant cases; what most post-4th-c. Greek fathers quote toward |
| Antoniades 1904 Patriarchal NT | [github.com/byztxt/greektext-antoniades](https://github.com/byztxt/greektext-antoniades) | **Public domain** (stated in repo) | whole NT, parsed | the received Orthodox liturgical text |
| Codex Bezae, Latin column | [epapers.bham.ac.uk/1664](https://epapers.bham.ac.uk/1664) | **CC BY** | Gospels + Acts, TEI | a fifth Old Latin witness; Acts is new coverage |
| Coptic Scriptorium Sahidic OT | [copticscriptorium.org](https://copticscriptorium.org/download/corpora/sahidic_bible_ot.html) | **CC BY-SA 4.0** (ShareAlike tracked) | Pentateuch–Jeremiah incl. full Psalter | our whole Coptic holding today is 45 verses of Mark |
| Van Dyck Arabic | [ebible.org arb-vd](https://ebible.org/find/details.php?id=arb-vd) | **Public domain** (stated on eBible) | whole Bible | positions the Arabic extension, zero licence friction |
| Elizabeth Bible (Church Slavonic, 1757) | CrossWire/SWORD `CSlElizabeth` | **Public domain** (module .conf) | whole Bible | the only fully open Slavonic scripture found |
| Samaritan Pentateuch | Text-Fabric dataset (Chester Beatty 751 + Garizim 1) | **CC BY 4.0** | Torah | occasional Origen/Eusebius/Jerome "Samaritan" discussions |

**Recorded dead ends** — so the searching is never repeated:

- **Geʽez/Ethiopic**: no open machine-readable NT exists at all; the one OT module
  (HaCohen, from Dillmann/Ludolf) is non-commercial-only and partial.
- **Theodotion/Hexapla beyond Daniel**: nothing digitized openly; Field 1875 is PD *page
  scans* only; the Hexapla Institute's edition is unpublished; Göttingen's apparatus is
  print-only and commercial.
- **Old Syriac gospels** (Sinaiticus, Curetonianus): no machine-readable text anywhere;
  Lewis's PD editions are scans; Kiraz's comparative edition is commercial.
- **Armenian** (Zohrab/1895): TITUS is view-only restrictive; Arak29 grants NC-only; Calfa
  is proprietary; PROIEL's Künzle NT is CC BY-NC-SA.
- **Georgian, OCS Codex Marianus**: TITUS restrictive; PROIEL/UD are NC-SA. No open text.
- **Dead Sea Scrolls**: IAA all-rights-reserved; most transcriptions not even published.
- **CAL** (Comprehensive Aramaic Lexicon): no stated terms at all — browse-only in practice.
- **Vetus Latina Iohannes** (ITSEE, 29 witnesses to John): licence **unstated** — one email
  to ITSEE before any use. **Sefaria Targums**: licence varies per text — check each badge.
- **Sahidica NT** (Wells; also behind Coptic Scriptorium's NT): *gratis, not open* — free
  electronic use with attribution, no modification/print/commercial rights. Recordable, but
  as its own licence class, never as CC.

## 12. Roadmap

Ordered by misses-bought per false-positive risk; every stratum is priced on the control
corpus and the golden set before its default changes anything.

| order | work | buys (from §2) | FP price | effort |
|---|---|---|---|---|
| 1 | **0.1** RP Byzantine + Antoniades + Bezae-Latin fetched, indexed | 8 named variant cases, likely more unmeasured; Old Latin Acts | none — more text, same gates | S |
| 2 | **0.3 + 5.3** formal chaining: concave gaps, optimal DP, multi-chain | conflation clauses (≥7 named loci); interpolated-clause misses | control re-run; per-chain gates unchanged | M |
| 3 | **0.2** itacised tier, flagged | unmeasured; the largest MS variant class | control re-run before default | S |
| 4 | **10** formula FN detector + stratified recall + POD/PFA reporting | measurement, not recall — steers everything after | none | S |
| 5 | **2** quotation families | 34 misfire verdicts; doxology addresses; family-precision | none — reporting change | M |
| 6 | **1** E-values + containment; spaced-seed experiment priced | defensible thresholds; conflation scoring; maybe a new axis | is itself the pricing tool | M |
| 7 | **6b** per-verse profiles (MSA over editions + family) | edition-variant dilution, structurally; free "which reading" output | none — attested readings only | L |
| 8 | **R** register scanning, instrumentation-first | span bounds; the only visibility into zero-overlap spans | strict: control-priced, default never until then | L |
| 9 | **3** allusion pass | the 26 one-to-three-word indirects, bounded honestly | full control pricing gate before any default | L |
| 10 | **4** convention immunity: seed masking, stoplist, positional flag | 29 doxology/salutation verdicts | none — flags and masks | S |
| — | breadth fetches: Sahidic OT, Van Dyck, Elizabeth, Samaritan Pent. | future languages, not today's recall | none | S each |

Division of labour, standing: patristic-side frequencies, the father's own language model,
document position, and threshold choice are the consumer's; corpora, indexes, axes,
families, profiles, the scripture-side model, and pricing tools are the library's.

## 13. What this design refuses to do

- **Neural signals in any default path.** A pinned-artifact annex (Diogenet fastText,
  Zenodo DOI 10.5281/zenodo.5594787, CC BY 4.0; Latin BERT, MIT) may be *compared against*
  the deterministic core in experiments — the AGREE benchmark's finding that neural-only
  suggestions score 54.5/100 against expert judgement is reason enough to keep it there.
- **Chasing the nine zero-overlap allusions.** Clement retelling the furnace with the
  Hebrew names, the Judith summary, the Rahab story: a method that found these would be
  finding subject matter, and both sides have already agreed not to trust one. They are the
  permanent, honest remainder — pinned in tests as *not found*, so nobody tunes toward them.
- **Bulk BiblIndex use without terms.** No open licence exists; browsing and one email are
  the whole of what is proper.
- **Verdicts.** The field's own leading data project declined to encode quotation-vs-allusion
  intentionality as data. Everything here ships evidence — axes, families, flags, E — and
  the grade names stay descriptions of evidence, not judgements of intent.
