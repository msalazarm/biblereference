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
