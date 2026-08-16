"""Gates, the ordered chain, and the thing that was actually broken: `scan`.

The first release of inflected matching had a fault worse than any of its thresholds. The
consumer calls `Searcher.scan`, and `scan` never looked at `inflected` at all -- the whole
feature was reachable only from `search`. So they built a windowing harness around `search`
to use it, every figure they measured came out of that harness, and two of the failures they
reported were the harness rather than the matching: a quotation of fourteen words seen through
a twelve-word window loses the bits of whatever fell outside, and a psalm quotation diluted
with the surrounding prose stops being retrievable.

What is tested here, therefore, is not only that the gates hold but that the thing they gate
runs where it is called from, and that a match weighs the same however the document was cut.
"""

from __future__ import annotations

import pytest

from biblereference.formulae import preceding
from biblereference.lemmata import Lexicon
from biblereference.search import (
    Gate,
    LemmaWeights,
    Searcher,
    _tokens,
    lemma_chain,
    lemma_readings,
    lemma_run,
)
from biblereference.store import DataHome

#: The developer's own library, captured before ``conftest`` isolates the session. Same
#: reasoning as ``test_real_lexicon``: these questions are about the real index or they are
#: about nothing.
REAL = DataHome()

pytestmark = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)

#: Ignatius to Polycarp 2.2, quoting Matthew 10:16. Fourteen words shared with the verse and
#: a longest *identical* run of one. The case the feature was asked for, and the case the
#: consumer's own recommended gates still miss.
POLYCARP_2_2 = "φρόνιμος γίνου ὡς ὁ ὄφις ἐν ἅπασιν καὶ ἀκέραιος εἰς ἀεὶ ὡς ἡ περιστερά"

#: Ignatius to the Philadelphians 11.1a against Acts 6:3. Two words, both paired correctly by
#: any lemmatiser, and the paper's own author did not believe it was a quotation.
PHILADELPHIANS_11_1A = "ἀνδρὸς μεμαρτυρημένου"


def greek(**options: object) -> Searcher:
    settings: dict[str, object] = {
        "coverage": 0.50,
        "min_query": 3,
        "min_run": lambda n: max(4, min(6, n // 2)),
    }
    settings.update(options)
    return Searcher(REAL, languages=["grc"], **settings)  # type: ignore[arg-type]


def axes(text: str, verse: str) -> tuple[int, int, float]:
    """``(lemma_run, chain, bits over the chain's span)`` for a text against a verse."""
    from biblereference.search import shared_bits

    lexicon, weights = Lexicon(REAL), LemmaWeights(REAL)
    weigh = weights.of("grc")
    mine = lemma_readings(_tokens(text, "grc"), "grc", lexicon)
    theirs = lemma_readings(_tokens(verse, "grc"), "grc", lexicon)
    chained = lemma_chain(mine, theirs, weigh)
    first, last = chained.span
    return (
        lemma_run(mine, theirs, weigh).length,
        chained.length,
        shared_bits(mine[first:last], theirs, weigh) if last > first else 0.0,
    )


# --------------------------------------------------------------------------------------
# The fault: `scan` could not do this at all
# --------------------------------------------------------------------------------------


def test_scan_finds_a_re_inflected_quotation(subtests: object = None) -> None:
    """The whole feature, through the call the consumer actually makes.

    Before this it did not matter what the gates were: `scan` read `inflected` nowhere, so a
    re-inflected quotation was unreachable from it however the thresholds were set.
    """
    document = (
        "Πολλὰ περὶ τούτων εἴρηται τοῖς πρὸ ἡμῶν. "
        + POLYCARP_2_2
        + ", φησὶν ὁ κύριος. ταῦτα μὲν οὖν οὕτως ἔχει κατὰ τὴν παράδοσιν."
    )
    with greek() as plain:
        assert "MAT 10:16" not in [str(m.passage) for m in plain.scan(document)]
    with greek(inflected=True) as rich:
        found = [m for m in rich.scan(document) if str(m.passage) == "MAT 10:16"]
    assert found, "scan did not find the quotation the feature exists for"
    assert found[0].grade == "indirect"
    assert found[0].chain >= 8, "nine of Matthew's words, in Matthew's order"


def test_the_weight_is_the_span_not_the_window() -> None:
    """A score that depends on how the document was sliced is not a score of the quotation.

    The consumer measured the same match at 43.1, 47.1, 57.6, 58.6 and 60.8 bits through
    windows of 10, 12, 14, 20 and 24, and reported the spread as the thing to fix. The chain
    decides its own extent, so there is no window left for the answer to depend on.
    """
    lead = "Πολλὰ περὶ τούτων εἴρηται τοῖς πρὸ ἡμῶν καὶ πάλιν λέγομεν ὅτι "
    weights = set()
    for padding in ("", lead, lead + lead):
        with greek(inflected=True) as rich:
            for match in rich.scan(padding + POLYCARP_2_2 + " ταῦτα μὲν οὖν οὕτως ἔχει."):
                if str(match.passage) == "MAT 10:16":
                    weights.add(round(match.bits, 1))
    assert len(weights) == 1, f"the same quotation weighed differently by window: {weights}"


# --------------------------------------------------------------------------------------
# Order, where contiguity cannot decide
# --------------------------------------------------------------------------------------


def test_the_chain_sees_what_the_run_cannot() -> None:
    """Ignatius and Aristotle are both short runs. Only their order tells them apart."""
    import sqlite3

    db = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)

    def verse(book: str, chapter: int, number: int) -> str:
        row = db.execute(
            "SELECT text FROM verse WHERE corpus='n1904' AND book=? AND chapter=? AND verse=?",
            (book, chapter, number),
        ).fetchone()
        return str(row[0])

    quotation = axes(POLYCARP_2_2, verse("MAT", 10, 16))
    coincidence = axes(PHILADELPHIANS_11_1A, verse("ACT", 6, 3))

    assert quotation[0] <= 3, "the identical-lemma run is short -- that is the difficulty"
    assert quotation[1] >= 8, "but nine words agree in order"
    assert coincidence[1] <= 2, "and a coincidence agrees in two"
    # The gap the gate lives in. Stated as a fact rather than a threshold, so that a change
    # narrowing it fails here rather than in somebody's corpus.
    assert quotation[1] - coincidence[1] >= 6


def test_a_chain_cannot_be_stitched_across_a_whole_window() -> None:
    """The gaps are bounded, or a chain would find order in anything long enough.

    A verse's words scattered through a paragraph in the right sequence is not a quotation,
    and without a bound on the verse side that is exactly what would score highest.
    """
    lexicon, weights = Lexicon(REAL), LemmaWeights(REAL)
    weigh = weights.of("grc")
    scattered = _tokens(
        "φρόνιμος μὲν οὖν ἐστιν ὁ τοιοῦτος καθάπερ εἴρηται πολλάκις καὶ γὰρ ὁ ὄφις "
        "λέγεται φρόνιμος εἶναι κατὰ τοὺς παλαιούς ἀλλὰ περιστερά",
        "grc",
    )
    mine = lemma_readings(scattered, "grc", lexicon)
    tight = lemma_readings(_tokens(POLYCARP_2_2, "grc"), "grc", lexicon)
    theirs = lemma_readings(
        _tokens("γίνεσθε οὖν φρόνιμοι ὡς οἱ ὄφεις καὶ ἀκέραιοι ὡς αἱ περιστεραί", "grc"),
        "grc",
        lexicon,
    )
    assert lemma_chain(mine, theirs, weigh).length < lemma_chain(tight, theirs, weigh).length


# --------------------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------------------


def test_a_gate_is_a_conjunction_and_a_searcher_holds_a_union() -> None:
    assert Gate(chain=8, bits=40).admits(run=0, lemma_run=3, chain=9, bits=57.6)
    assert not Gate(chain=8, bits=40).admits(run=0, lemma_run=3, chain=9, bits=20.0)
    assert not Gate(chain=8, bits=40).admits(run=0, lemma_run=3, chain=4, bits=57.6)


def test_the_union_admits_what_any_one_of_its_gates_admits() -> None:
    """Complementary rather than nested, which is why one gate will not do: the consumer
    measured a run gate contributing 20 findings a chain gate missed, and the chain gate 734
    the run gate missed, over the same 150,000 words."""
    document = "καὶ πάλιν· " + POLYCARP_2_2 + " ταῦτα μὲν οὖν οὕτως ἔχει."
    with greek(inflected=True, gates=[Gate(run=6, bits=60.0)]) as narrow:
        assert "MAT 10:16" not in [str(m.passage) for m in narrow.scan(document)]
    with greek(inflected=True, gates=[Gate(run=6, bits=60.0), Gate(chain=8, bits=40.0)]) as union:
        assert "MAT 10:16" in [str(m.passage) for m in union.scan(document)]


def test_the_shorthand_still_means_what_it_meant() -> None:
    """`min_lemma_run=`/`min_bits=` were shipped a day before the gate list and there is code
    against them. Naming either builds that one gate and nothing else."""
    searcher = greek(inflected=True, min_lemma_run=4, min_bits=35.0)
    assert searcher._gates == (Gate(lemma_run=4, bits=35.0),)
    searcher.close()

    with pytest.raises(ValueError, match="not both"):
        greek(inflected=True, gates=[Gate(chain=8)], min_bits=30.0)


def test_a_gate_can_be_written_the_way_the_command_line_writes_it() -> None:
    assert Gate.parse("0:4:0:40") == Gate(lemma_run=4, bits=40.0)
    with pytest.raises(ValueError, match="run:lemma_run:chain:bits"):
        Gate.parse("4:40")


# --------------------------------------------------------------------------------------
# The formula, which is evidence and not a threshold
# --------------------------------------------------------------------------------------


def test_a_citation_formula_is_reported() -> None:
    assert preceding("ταῦτα μὲν οὖν. γέγραπται γάρ· ", 30, "grc") == "γεγραπται"
    assert preceding("λέγει γὰρ ἡ γραφή ", 18, "grc") == "λεγει γαρ"


def test_a_formula_is_not_found_inside_another_word() -> None:
    """`ὡς γέγραπται` lives inside `οὕτως γέγραπται` once the text is folded, and reporting a
    formula the writer did not use would be worse than reporting none."""
    assert preceding("καὶ οὕτως γέγραπται ", 20, "grc") == "γεγραπται"


def test_the_formula_changes_no_threshold() -> None:
    """Measured at 1.52 per thousand words in the fathers against 0.245 in the controls -- a
    sixfold enrichment, and not enough to admit anything the evidence refuses. Aristotle
    writes `φησίν` freely, and Ignatius, whose quotations this feature exists for, uses no
    formula at all."""
    announced = "γέγραπται γάρ· " + PHILADELPHIANS_11_1A
    with greek(inflected=True) as rich:
        assert "ACT 6:3" not in [str(m.passage) for m in rich.scan(announced)]


# --------------------------------------------------------------------------------------
# Formal chaining: gaps paid for, and one finding per source of a conflation
# --------------------------------------------------------------------------------------

#: Polycarp to the Philippians 2.3: one sentence remembering three sayings of the Lord --
#: Matthew 7:1 word for word, then the forgiving/mercy/measure material re-inflected
#: toward Luke 6:37-38, then the beatitude. A single best answer per cluster reported the
#: verbatim clause and made the rest structurally unreachable.
POLYCARP_2_3 = (
    "μνημονεύοντες δὲ ὧν εἶπεν ὁ κύριος διδάσκων· μὴ κρίνετε, ἵνα μὴ κριθῆτε· ἀφίετε, "
    "καὶ ἀφεθήσεται ὑμῖν· ἐλεᾶτε, ἵνα ἐλεηθῆτε· ᾧ μέτρῳ μετρεῖτε, ἀντιμετρηθήσεται ὑμῖν· "
    "καὶ ὅτι μακάριοι οἱ πτωχοὶ καὶ οἱ διωκόμενοι ἕνεκεν δικαιοσύνης, ὅτι αὐτῶν ἐστὶν "
    "ἡ βασιλεία τοῦ θεοῦ."
)


def test_a_long_interpolated_clause_is_paid_for_and_scattered_slack_is_not() -> None:
    """The concave cost is the walls grown up: one long gap costs little per word, so a
    father's own clause in the middle of a quotation no longer severs it, while the same
    slack scattered across the span still buys nothing."""
    from biblereference.search import lemma_chain

    weight = {"α": 8.0, "β": 7.0, "γ": 9.0, "δ": 6.0}
    weigh = weight.__getitem__
    reading = [frozenset(x) for x in "αβ" + "." * 12 + "γδ"]
    verse = [frozenset(x) for x in "αβγδ"]
    assert lemma_chain(reading, verse, weigh).length == 2, "the 8-word wall severs it"
    assert lemma_chain(reading, verse, weigh, concave=True).length == 4, "the cost does not"


def test_every_disjoint_chain_is_reported_not_only_the_winner() -> None:
    from biblereference.search import lemma_chains

    weight = {"α": 8.0, "β": 7.0, "γ": 9.0, "δ": 6.0}
    weigh = lambda lemma: weight.get(lemma, 2.0)  # noqa: E731
    reading = [frozenset(x) for x in "αβ..γδ"]
    assert [c.span for c in lemma_chains(reading, [frozenset(x) for x in "αβ"], weigh)] == [(0, 2)]
    both = lemma_chains(reading, [frozenset(x) for x in "αβγδ"], weigh, concave=True)
    assert both[0].length == 4, "one chain when the verse carries both clauses"


def test_a_conflated_sentence_yields_one_finding_per_source() -> None:
    """Polycarp's verbatim Matthew clause used to be the cluster's whole answer. The
    uncovered remainder is now graded too, so the Lukan material stands beside it as its
    own finding, on its own axes, at a gate that admits its evidence."""
    with greek(inflected=True, gates=(Gate(chain=5, bits=25.0),)) as rich:
        found = {str(m.passage): m.grade for m in rich.scan(POLYCARP_2_3)}
    assert found.get("MAT 7:1-2") == "direct", "the verbatim clause, as before"
    assert "LUK 6:38" in found or "LUK 6:37-38" in found, "and the re-inflected one beside it"


def test_the_defaults_admit_nothing_new_until_the_price_is_known() -> None:
    """The same sentence at the default gates: the Lukan clause's 35 bits do not clear
    them, and multi-chain reporting must widen nothing by itself -- the consumer's
    standing rule is that no default moves before the control corpus prices it."""
    with greek(inflected=True) as rich:
        found = {str(m.passage) for m in rich.scan(POLYCARP_2_3)}
    assert "MAT 7:1-2" in found
    assert not any(p.startswith("LUK 6:") for p in found)


def test_magnesians_9_1_stays_denied_through_every_new_path() -> None:
    """The highest-scoring false positive of the first calibration, and the fixture the
    consumer watches: neither the concave cost, the extra chains, nor the remainder pass
    may bring it back at the defaults."""
    with greek(inflected=True) as rich:
        assert rich.scan(MAGNESIANS_9_1) == []
    with greek(inflected=True, concave=True) as rich:
        assert rich.scan(MAGNESIANS_9_1) == []


def test_concave_costs_change_nothing_the_walls_already_allowed() -> None:
    """Ignatius's interpolations are all shorter than the walls, so paying for gaps and
    walling them agree about him exactly. The loosening is confined to what it exists
    for -- the one long interpolated clause -- and a case the walls handled is reported
    to the bit as it was."""
    axes = {}
    for concave in (False, True):
        with greek(inflected=True, concave=concave) as rich:
            match = next(m for m in rich.scan(POLYCARP_2_2) if str(m.passage) == "MAT 10:16")
            axes[concave] = (match.chain, match.lemma_run, match.bits)
    assert axes[False] == axes[True]


# --------------------------------------------------------------------------------------
# The debt ledger: the formula's other direction
# --------------------------------------------------------------------------------------

#: An announcement kept: γέγραπται, and the words of Job 1:1 follow verbatim.
ANNOUNCED_AND_KEPT = (
    "ἔτι δὲ καὶ περὶ Ἰὼβ οὕτως γέγραπται: Ἰὼβ δὲ ἦν δίκαιος καὶ ἄμεμπτος, ἀληθινός, "
    "θεοσεβής, ἀπεχόμενος ἀπὸ παντὸς κακοῦ."
)

#: An announcement broken: the same γέγραπται, and what follows is nobody's scripture.
ANNOUNCED_AND_BROKEN = (
    "περὶ δὲ τούτων οὕτως γέγραπται: ὁ γὰρ ἀγρὸς τῆς πόλεως μικρὸς ἦν καὶ οἱ ἵπποι "
    "τῶν βαρβάρων ἔφυγον εἰς τὰ ὄρη ταχέως πάνυ."
)


def test_every_formula_in_a_document_is_found_with_its_place() -> None:
    """`announced` is `preceding` walked forward: same folded forms, same longest-first
    rule, but over the whole document, which is what a ledger needs."""
    from biblereference.emphasis import fold
    from biblereference.formulae import announced

    tokens = [fold(w, "grc") for w in "λεγει η γραφη ταδε και παλιν λεγει αλλα".split()]
    assert list(announced(tokens, "grc")) == [
        ("λεγει η γραφη", 0, 3),
        ("και παλιν λεγει", 4, 7),
    ]


def test_an_announced_quotation_with_no_match_is_a_debt() -> None:
    """A formula is a promise that scripture follows. Where nothing is found in reach, the
    document itself has testified to a false negative -- the only kind visible without
    gold data -- and the record says where to go look."""
    with greek(inflected=True) as rich:
        debts = rich.formula_debts(ANNOUNCED_AND_BROKEN)
    assert len(debts) == 1
    assert debts[0].formula == "γεγραπται"
    assert ANNOUNCED_AND_BROKEN[debts[0].at : debts[0].end] == "γέγραπται"
    assert debts[0].announced.startswith("ὁ γὰρ ἀγρὸς")


def test_an_announced_and_matched_quotation_is_no_debt() -> None:
    with greek(inflected=True) as rich:
        assert rich.formula_debts(ANNOUNCED_AND_KEPT) == []


# --------------------------------------------------------------------------------------
# The positional flag: an epistle's frame, reported and never acted on
# --------------------------------------------------------------------------------------


def test_an_epistles_first_and_last_verses_are_flagged() -> None:
    """The consumer knows which paragraph of *their* document is an address and which a
    farewell; this flag is the scripture-side half they combine it with. First verse and
    last verse, from the store's own numbering, no threshold anywhere."""
    with greek() as searcher:
        opening = searcher.search(
            "Ἰάκωβος θεοῦ καὶ κυρίου Ἰησοῦ Χριστοῦ δοῦλος ταῖς δώδεκα φυλαῖς "
            "ταῖς ἐν τῇ διασπορᾷ χαίρειν"
        )
        closing = searcher.search("Ὁ κύριος μετὰ τοῦ πνεύματός σου. ἡ χάρις μεθ' ὑμῶν.")
    assert any(m.passage.book == "JAS" and m.positional_candidate for m in opening), (
        "James opens his letter, and the flag says so"
    )
    assert any(m.passage.book == "2TI" and m.positional_candidate for m in closing), (
        "2 Timothy's farewell blessing is its last verse"
    )


def test_a_gospel_verse_is_never_a_positional_candidate() -> None:
    """Matthew 10:16 is mid-discourse in a narrative book: whatever its wording, it is not
    the frame of a letter, and flagging it would dilute the one thing the flag means."""
    with greek(inflected=True) as rich:
        found = [m for m in rich.scan(POLYCARP_2_2) if m.passage.book == "MAT"]
    assert found and not any(m.positional_candidate for m in found)


# --------------------------------------------------------------------------------------
# What reading eighty-eight findings by hand turned up
#
# The consumer scanned the nine Greek works a scholar had tabulated, read every match at a
# locus he had not annotated, and sorted them. The three cases below are the ones that were
# defects here rather than differences of judgement.
# --------------------------------------------------------------------------------------

#: Ignatius, Magnesians 9.1. Against Romans 5:21 this scored 66 bits -- the highest of the
#: eighty-eight, and a false positive. The two share `ἡ ζωή`, `θάνατος`, `διά`, `Ἰησοῦ
#: Χριστοῦ` and `ἡμῶν`, scattered through forty words of Ignatius and twenty of Paul.
MAGNESIANS_9_1 = (
    "Εἰ οὖν οἱ ἐν παλαιοῖς πράγμασιν ἀναστραφέντες εἰς καινότητα ἐλπίδος ἦλθον, μηκέτι "
    "σαββατίζοντες, ἀλλὰ κατὰ κυριακὴν ζῶντες, ἐν ᾗ καὶ ἡ ζωὴ ἡμῶν ἀνέτειλεν δἰ αὐτοῦ καὶ "
    "τοῦ θανάτου αὐτοῦ, ὅν τινες ἀρνοῦνται, δἰ οὗ μυστηρίου ἐλάβομεν τὸ πιστεύειν, καὶ διὰ "
    "τοῦτο ὑπομένομεν, ἵνα εὑρεθῶμεν μαθηταὶ Ἰησοῦ Χριστοῦ τοῦ μόνου διδασκάλου ἡμῶν:"
)

#: The doxology that closes eleven sections of 1 Clement, and matches whichever epistle
#: happens to end that way -- Galatians, 1 Peter, Jude, Romans, 4 Maccabees.
DOXOLOGY = "ᾧ ἡ δόξα καὶ ἡ μεγαλωσύνη εἰς τοὺς αἰῶνας τῶν αἰώνων. ἀμήν."

#: 1 Clement 17.3, announced with `γέγραπται` and verbatim. Job 1:1 and Job 1:8 carry the
#: same four epithets, so naming either is right and naming both is better.
CLEMENT_17_3 = (
    "ἔτι δὲ καὶ περὶ Ἰὼβ οὕτως γέγραπται: Ἰὼβ δὲ ἦν δίκαιος καὶ ἄμεμπτος, ἀληθινός, "
    "θεοσεβής, ἀπεχόμενος ἀπὸ παντὸς κακοῦ."
)


def weigh(text: str, book: str, chapter: int, number: int, corpus: str = "n1904") -> float:
    """The bits a passage earns against one verse, as the gate computes them."""
    import sqlite3

    db = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)
    row = db.execute(
        "SELECT text FROM verse WHERE corpus=? AND book=? AND chapter=? AND verse=?",
        (corpus, book, chapter, number),
    ).fetchone()
    lexicon, weights = Lexicon(REAL), LemmaWeights(REAL)
    weigher = weights.of("grc")
    mine = lemma_readings(_tokens(text, "grc"), "grc", lexicon)
    theirs = lemma_readings(_tokens(str(row[0]), "grc"), "grc", lexicon)
    chained = lemma_chain(mine, theirs, weigher)
    return sum(weigher(lemma) for lemma in set(chained.lemmas))


def test_a_chain_of_function_words_no_longer_outscores_a_quotation() -> None:
    """The worst finding in the eighty-eight, and the arithmetic behind it.

    Bits were summed over every shared word in the stretch the chain covered, counting three
    occurrences of `καί` as three pieces of evidence; and where a form was ambiguous the
    *rarest* reading was taken, so `διά` -- which this lexicon analyses only as `Ζεύς` and
    `Διός` -- scored 4.6 bits as though Ignatius had written *Zeus*. Distinct links at their
    commonest reading is what puts a real quotation back above a coincidence.
    """
    coincidence = weigh(MAGNESIANS_9_1, "ROM", 5, 21)
    quotation = weigh(POLYCARP_2_2, "MAT", 10, 16)
    assert coincidence < 40, f"the worst false positive still scores {coincidence:.1f}"
    assert quotation > coincidence, "and it no longer outscores Ignatius quoting Matthew"


def test_a_liturgical_formula_scores_like_the_common_words_it_is_made_of() -> None:
    """*To whom be glory for ever and ever, Amen* is not a quotation of Galatians; it is how
    the whole church prayed. Surprisal cannot see that -- the words are rare in the Bible and
    ubiquitous in Christian prose, which is the inverse of what it measures -- but it should
    at least not score them as evidence."""
    assert weigh(DOXOLOGY, "GAL", 1, 5) < 25


def test_an_exact_match_carries_its_axes_when_asked_for_them() -> None:
    """`bits = 0.0` used to mean two different things -- "no information" and "never
    computed" -- and the exact path only ever meant the second, so the doxology came through
    it with no surprisal defence at all."""
    with greek() as plain:
        bare = [m for m in plain.scan(DOXOLOGY) if m.grade == "direct"]
    with greek(inflected=True) as rich:
        weighed = [m for m in rich.scan(DOXOLOGY) if m.grade == "direct"]
    assert bare and weighed, "a nine-word verbatim run is found either way"
    assert bare[0].bits == 0.0 and bare[0].chain == 0, "not asked for, not computed"
    assert weighed[0].bits > 0 and weighed[0].chain > 0, "asked for, and now defensible"


def test_a_rival_inside_the_same_chapter_is_reported() -> None:
    """A scan keeps one span per chapter, so Job 1:8 lost to Job 1:1 before anything could
    call them rivals, and `alternates` came back empty -- which reads as "nothing else fits"
    on a case where something else fits exactly as well."""
    with greek(inflected=True) as rich:
        found = [m for m in rich.scan(CLEMENT_17_3) if m.passage.book == "JOB"]
    assert found, "the quotation is found"
    assert [str(a) for a in found[0].alternates] == ["JOB 1:8"]
    assert found[0].formula == "γεγραπται", "and it is announced, which is also reported"


def test_the_alternates_a_scan_already_found_are_not_overwritten() -> None:
    """`_without_overlaps` rebuilt the field from its own cross-span rivals, discarding what
    the cluster had recorded. Merging is what makes both kinds reachable."""
    from biblereference.search import VerseRange, VerseRef, _merge_passages

    def span(book: str, chapter: int, number: int) -> VerseRange:
        ref = VerseRef(book, chapter, number, vrs="org")
        return VerseRange(ref, ref)

    merged = _merge_passages([span("JOB", 1, 8)], [span("ISA", 53, 6), span("JOB", 1, 8)])
    assert [str(p) for p in merged] == ["JOB 1:8", "ISA 53:6"], "both kinds, no repeat"


#: Clement's Job quotation as a father would carry it in indirect speech -- every content
#: word re-inflected to the accusative, so the exact path has no run to find and only the
#: lemma path can answer. Job 1:1, 1:8 and 2:3 all carry the same epithets, so the rivalry
#: is in the text itself and survives every index rebuild -- unlike a near-tie in bits,
#: which moved the day the Byzantine Textform joined the library and reweighed every lemma.
CLEMENT_17_3_REINFLECTED = (
    "λέγει γὰρ τὸν Ἰὼβ δίκαιον καὶ ἄμεμπτον, ἀληθινόν, θεοσεβῆ, ἀπεχόμενον ἀπὸ παντὸς κακοῦ"
)


def test_the_graded_path_reports_rivals_as_the_exact_path_does() -> None:
    """The first attempt at this wired `alternates` into the exact path only.

    So a match found by dictionary form -- which is most of what this feature exists to find
    -- still came back claiming nothing else fitted. The consumer could not reproduce the fix
    for exactly that reason, and an empty `alternates` reads as evidence when it is silence.
    """
    with greek(inflected=True) as rich:
        graded = [m for m in rich.scan(CLEMENT_17_3_REINFLECTED) if m.grade != "direct"]
    assert graded, "Clement re-inflecting Job is found by the lemma path"
    named = {str(span) for match in graded for span in match.alternates}
    assert named, "and it says what else answered nearly as well"
    assert named & {"JOB 1:1", "JOB 1:8"}, "naming the other verse with the same epithets"


def test_alternates_stay_empty_when_the_feature_was_not_asked_for() -> None:
    """Filling a field that has always been empty changes what every existing scan returns,
    and half a million findings downstream rest on that not happening by surprise."""
    with greek() as plain:
        for match in plain.scan(CLEMENT_17_3):
            assert match.alternates == ()
