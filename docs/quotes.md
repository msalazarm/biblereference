# Finding every quotation that can be found

*A design for the next generation of quotation, allusion and reference detection.
2026-08-15. Grounded in the measurements of `churchfathers/review/` and three research
passes over the text-reuse literature; every number below names its source.*

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
| **Zero-content-word allusions.** Boyce read the sense; there are no words to match. | **9 of 35** indirect misses share zero content words with the verse (`indirect-misses.json`); 22 share 1–3. | Stratum 3, honestly bounded — and §11 |

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
  false positives 22–30%. *Transfers:* formula-scoped gating (§9) — the only published use
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

## 4. Stratum 0 — make the text match the text

The cheapest recall in the ledger is not in the matcher at all.

**4.1 Fetch the Byzantine Greek New Testament.** Eight documented Boyce cases agree with
Byzantine wording against every Greek NT we hold, and they are unrecoverable by any
threshold because the text is simply absent. The Robinson–Pierpont Byzantine Textform is
stated public domain (verify at fetch; eBible carries it) — register it as a source, build,
index, done. This also serves the consumer's attribution goal: "the father reads the
Byzantine text here" is itself a finding of scholarly value, exactly as `anachronistic`
already is for translations.

**4.2 Wire the itacised tier.** `fold(orthographic=True)` collapses ει/ι, η/ι, ω/ο — "the
single largest class of orthographic variant in Greek manuscripts" by its own docstring —
and nothing reaches it. Add it as an opt-in *second* matching tier under `inflected`: exact
fold first, itacised fold only where the first declines, matches flagged `itacised` so the
looseness is visible. Priced on the control corpus like every other loosening. (It makes
ὑμεῖς/ἡμεῖς one string; the flag is what makes that survivable.)

**4.3 Enumerate all local alignments per span.** The matcher keeps one best match per
cluster, so a sentence weaving five sayings yields at most one finding and four structural
misses — per-clause, as `indirect-misses.json` shows for 1 Clem 13:2's Matt 5:7 and 6:14
clauses. Adopt the BLAST-HSP / ACT-Compound discipline: after the winner is taken, re-run
the alignment on the *uncovered remainder* of the span until nothing above the gate remains.
Each finding carries its own axes; `_without_overlaps` already knows how to arbitrate
overlapping claims. Expected recovery: the conflation rows, which include some of the 34
missed directs.

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

## 6. Stratum 2 — quotation families

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

## 7. Stratum 3 — the allusion pass

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

## 8. Stratum 4 — convention immunity

Two classes are systematic and deserve structural answers rather than thresholds:

- **Stock phrases.** The biblical half — "this span's lemma sequence stands in N places" —
  falls out of the Stratum 2 family index free. The patristic half — "and it is ubiquitous
  in Christian prose" — needs patristic frequencies, which is the consumer's corpus and, by
  agreement, their build; we carry whatever signal they compute on the response. A small
  hand-curated stoplist of doxologies and graces (the research pass found no published
  one — ours would be the first) guards the gap until then.
- **Salutations.** Positional: the span is a letter's address or farewell and the target is
  an epistle's first or last verse. Position in the *document* is the consumer's knowledge;
  the library's half is an epistle first/last-verse table, one afternoon's data, exposed on
  the match as `positional_candidate` for them to combine.

## 9. Instrumentation — measuring what we miss

- **The formula-anchored false-negative detector.** `formulae.py` already recognises
  γέγραπται and its kin, measured at 6× enrichment in the fathers. An announced quotation
  with **no match within reach** is a *measured miss* — the one kind of false negative
  visible without gold data. No published system uses formulae this way (the literature
  pass found only the DHQ precision filter). Report unmatched formulae per scan; the list
  *is* the recall-debt ledger, self-updating.
- **Recall stratified by announcement.** Formula-adjacent vs unmarked, per Manjavacas'
  segmentation finding — if the ceiling is mostly unmarked citations, that is a fact about
  the corpus worth knowing before more tuning.
- **Gold**: `boyce-golden.jsonl` (159+14), the 5,044 PTA editor marks, the control corpus.
  **BiblIndex** (270k verified patristic references, Sources Chrétiennes) has no open
  licence and an auth-gated API — worth one email to Laurence Mellerin's team; as gold it
  would dwarf everything above. Until then it prices nothing and validates methodology only.

## 10. Roadmap

Ordered by misses-bought per false-positive risk; every stratum is priced on the control
corpus and the golden set before its default changes anything.

| order | work | buys (from §2) | FP price | effort |
|---|---|---|---|---|
| 1 | **0.1** Byzantine NT fetched + indexed | 8 named variant cases, likely more unmeasured | none — more text, same gates | S |
| 2 | **0.3** all alignments per span | conflation clauses (≥7 named loci) | control re-run; per-clause gates unchanged | M |
| 3 | **0.2** itacised tier, flagged | unmeasured; the largest MS variant class | control re-run before default | S |
| 4 | **9** formula FN detector + stratified recall | measurement, not recall — steers everything after | none | S |
| 5 | **2** quotation families | 34 misfire verdicts; doxology addresses; family-precision | none — reporting change | M |
| 6 | **1** E-values + containment | defensible thresholds; conflation scoring | is itself the pricing tool | M |
| 7 | **3** allusion pass | the 26 one-to-three-word indirects, bounded honestly | full control pricing gate before any default | L |
| 8 | **4** convention immunity | 29 doxology/salutation verdicts | none — flags and stoplists | S |

Division of labour, standing: patristic-side frequencies, document position, and
threshold choice are the consumer's; corpora, indexes, axes, families, and pricing tools
are the library's.

## 11. What this design refuses to do

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
