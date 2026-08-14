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


def test_the_graded_path_reports_rivals_as_the_exact_path_does() -> None:
    """The first attempt at this wired `alternates` into the exact path only.

    So a match found by dictionary form -- which is most of what this feature exists to find
    -- still came back claiming nothing else fitted. The consumer could not reproduce the fix
    for exactly that reason, and an empty `alternates` reads as evidence when it is silence.
    """
    with greek(inflected=True) as rich:
        graded = [m for m in rich.scan(POLYCARP_2_2) if m.grade != "direct"]
    assert graded, "Ignatius re-inflecting Matthew is found by the lemma path"
    assert graded[0].alternates, "and it says what else answered nearly as well"


def test_alternates_stay_empty_when_the_feature_was_not_asked_for() -> None:
    """Filling a field that has always been empty changes what every existing scan returns,
    and half a million findings downstream rest on that not happening by surprise."""
    with greek() as plain:
        for match in plain.scan(CLEMENT_17_3):
            assert match.alternates == ()
