"""Seed masking and the stoplist: furniture may not nominate, and may still be covered.

The §9 guarantee is the load-bearing test here: a real quotation that happens to contain
a doxology is unharmed, because masking withholds only the right to *seed* -- the cluster
around a neighbouring window's nomination still scores the masked stretch.
"""

from __future__ import annotations

import pytest

from biblereference.emphasis import fold
from biblereference.lemmata import Lexicon
from biblereference.search import Searcher
from biblereference.stoplist import COVER_SHARE, covered, phrases
from biblereference.store import DataHome

REAL = DataHome()

real = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)

#: The doxology as a father writes it, standing alone: liturgical furniture that
#: matches five epistle endings and quotes none of them.
DOXOLOGY = "ᾧ ἡ δόξα εἰς τοὺς αἰῶνας τῶν αἰώνων ἀμήν"


def toks(text: str) -> list[str]:
    return [fold(word) for word in text.split()]


def test_the_stoplist_loads_and_covers_whole_phrases() -> None:
    assert phrases(), "the first published doxology stoplist is not empty"
    stream = toks("καὶ πάλιν λέγει " + DOXOLOGY + " ταῦτα μὲν οὖν")
    hit = covered(tuple(stream))
    assert len(hit) == len(DOXOLOGY.split()), "the doxology's positions, nothing else"
    assert 0 not in hit and len(stream) - 1 not in hit


def test_the_tail_inside_the_full_doxology_is_the_doxologys() -> None:
    """Longest-first: `εἰς τοὺς αἰῶνας...` inside the full phrase does not double-cover
    or truncate -- the same rule `formulae.announced` walks by."""
    stream = toks(DOXOLOGY)
    assert covered(tuple(stream)) == frozenset(range(len(stream)))


def test_cover_share_is_a_fraction_worth_the_name() -> None:
    assert 0.5 < COVER_SHARE <= 1.0


@real
def test_a_bare_doxology_seeds_nothing_under_the_mask() -> None:
    """Their 19 liturgical-formula verdicts, structurally: standing alone, the doxology
    may not nominate, so it stops matching five epistle endings it quotes none of."""
    opts = {"coverage": 0.50, "min_query": 3, "min_run": lambda n: max(4, min(6, n // 2))}
    with Searcher(REAL, languages=["grc"], **opts) as plain:  # type: ignore[arg-type]
        assert plain.scan(DOXOLOGY), "unmasked, the furniture matches something"
    with Searcher(REAL, languages=["grc"], seed_mask=True, **opts) as masked:  # type: ignore[arg-type]
        assert masked.scan(DOXOLOGY) == []


@real
def test_a_real_quotation_containing_the_doxology_is_still_covered() -> None:
    """The §9 guarantee. Galatians 1:4-5 ends in the doxology; quoted together, the
    non-doxology words nominate the chapter and the cluster scores the whole stretch --
    so the match survives the mask, doxology included."""
    import sqlite3

    db = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)
    gal = " ".join(
        str(row[0])
        for row in db.execute(
            "SELECT text FROM verse WHERE corpus='n1904' AND book='GAL' AND chapter=1 "
            "AND verse IN (4, 5) ORDER BY verse"
        )
    )
    assert "δοξα" in fold(gal, "grc"), "the doxology is in the quoted stretch"
    opts = {"coverage": 0.50, "min_query": 3, "min_run": lambda n: max(4, min(6, n // 2))}
    with Searcher(REAL, languages=["grc"], seed_mask=True, **opts) as masked:  # type: ignore[arg-type]
        found = masked.scan("καθὼς γέγραπται· " + gal)
    assert any(
        m.passage.book == "GAL" and m.passage.start.chapter == 1 for m in found
    ), "the quotation is found with the mask on"
    spans = [m for m in found if m.passage.book == "GAL"]
    assert any(
        m.span and "αιωνασ" in fold(("καθὼς γέγραπται· " + gal)[m.span[0] : m.span[1]], "grc")
        for m in spans
    ), "and its span covers the doxology it contains"


@real
def test_the_mask_changes_nothing_it_was_not_asked_for() -> None:
    """Off by default: the same scan without the flag answers exactly as before, which
    is the golden guard's promise restated at the feature's own door."""
    from tests.test_gates import CLEMENT_17_3

    opts = {"coverage": 0.50, "min_query": 3, "min_run": lambda n: max(4, min(6, n // 2))}
    with Searcher(REAL, languages=["grc"], **opts) as plain:  # type: ignore[arg-type]
        before = [(str(m.passage), m.grade) for m in plain.scan(CLEMENT_17_3)]
    assert before, "the control case still answers"
