"""The parallel-family index: verified verbally, spoken in the Greek's own coordinates.

The 34-of-102 verdict class this exists for is the scanner naming Acts 8:32 where the
scholar names Isaiah 53 -- both right, because Acts is quoting Isaiah. What is tested
here is the two halves of the promise: the seed's English numbering is converted to the
coordinates the Greek is held in, and only *verbal* parallels survive the build.
"""

from __future__ import annotations

import pytest

from biblereference.lemmata import Lexicon
from biblereference.parallels import BITS_FLOOR, CHAIN_FLOOR, SOURCE
from biblereference.store import DataHome
from biblereference.versification import Versification

REAL = DataHome()


def test_the_seed_licence_is_the_files_own_header() -> None:
    assert SOURCE.terms is not None and SOURCE.terms.id == "cc-by-4.0"


def test_seed_references_arrive_in_the_greeks_own_numbering() -> None:
    """OpenBible counts as the King James counts, and the Greek does not: English
    Psalm 121:2 is the Septuagint's 120:2, and storing the English number would build an
    index that misses every Greek psalm quotation off by one."""
    from biblereference.parallels import _greek_ref

    verses = Versification.load()
    assert str(_greek_ref(verses, "Ps.121.2")) == "PSA 120:2"
    assert str(_greek_ref(verses, "Acts.8.32")) == "ACT 8:32"
    assert str(_greek_ref(verses, "Gen.1.1")) == "GEN 1:1"
    # The vrs label itself, asserted -- str() hides it, and hiding it is how every New
    # Testament verse shipped labelled `lxx`: both versification systems claim the whole
    # canon, so the book decides, not has_book().
    assert _greek_ref(verses, "Acts.8.32").vrs == "org"
    assert _greek_ref(verses, "Ps.121.2").vrs == "lxx"
    assert _greek_ref(verses, "Matt.10.16").vrs == "org"
    assert _greek_ref(verses, "NotABook.1.1") is None
    assert _greek_ref(verses, "Gen.1") is None


def test_a_seed_range_becomes_its_member_verses_or_nothing() -> None:
    """The `To Verse` column carries ranges. Each member verse is verified on its own
    words -- the table is verse-granular -- and a whole-chapters link is refused before
    the chain ever runs, because "see also five chapters" is the topical kind of
    reference the verbal gate exists to drop."""
    from biblereference.parallels import _greek_refs

    verses = Versification.load()
    assert [str(r) for r in _greek_refs(verses, "Lev.8.16-Lev.8.17")] == ["LEV 8:16", "LEV 8:17"]
    assert [str(r) for r in _greek_refs(verses, "Ps.119.1-Ps.119.2")] == ["PSA 118:1", "PSA 118:2"]
    assert _greek_refs(verses, "Isa.1.1-Isa.5.30") == []
    assert [str(r) for r in _greek_refs(verses, "Acts.8.32")] == ["ACT 8:32"]


@pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)
def test_the_floors_pass_verbal_parallels_and_refuse_topical_links() -> None:
    """The whole build stands on this separation. Acts quotes Isaiah and chains 20 deep;
    Genesis 1:1 and Job 38:4 are about the same subject and share nothing but common
    words, whose bits the floor refuses. Chain length alone would not do it -- the
    topical pair chains 4 -- and that is why both floors must hold."""
    import sqlite3

    from biblereference.search import LemmaWeights, _tokens, lemma_chain, lemma_readings

    lexicon = Lexicon(REAL)
    lexicon.require("grc")
    weigh = LemmaWeights(REAL).of("grc")
    db = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)

    def axes(corpus_a: str, a: tuple, corpus_b: str, b: tuple) -> tuple[int, float]:
        row = lambda corpus, key: db.execute(  # noqa: E731
            "SELECT text FROM verse WHERE corpus=? AND book=? AND chapter=? AND verse=?",
            (corpus, *key),
        ).fetchone()[0]
        chained = lemma_chain(
            lemma_readings(_tokens(row(corpus_a, a), "grc"), "grc", lexicon),
            lemma_readings(_tokens(row(corpus_b, b), "grc"), "grc", lexicon),
            weigh,
        )
        return chained.length, chained.bits

    def clears(pair: tuple[int, float]) -> bool:
        return pair[0] >= CHAIN_FLOOR and pair[1] >= BITS_FLOOR

    assert clears(axes("rahlfs", ("ISA", 53, 7), "n1904", ("ACT", 8, 32)))
    assert clears(axes("rahlfs", ("PSA", 13, 1), "rahlfs", ("PSA", 52, 2)))
    assert not clears(axes("rahlfs", ("GEN", 1, 1), "rahlfs", ("JOB", 38, 4)))
    assert not clears(axes("rahlfs", ("GEN", 1, 1), "rahlfs", ("PSA", 120, 2)))


@pytest.mark.skipif(
    not REAL.database.exists(),
    reason="needs a built library",
)
def test_a_family_is_read_in_both_directions_or_not_at_all() -> None:
    """Before the index is built the reader answers with silence, not an error; after,
    the Ethiopian's Isaiah is in Acts' family and Acts in Isaiah's, because a quotation
    is not a directed edge when what is asked is 'what else carries these words'."""
    import sqlite3

    connection = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)
    from biblereference.parallels import Parallels

    index = Parallels(connection)
    if not index._held:
        assert index.of("ACT", 8, 32, 33) == ()
        pytest.skip("parallel_family not built; run `biblereference parallels`")
    forward = index.of("ACT", 8, 32, 33)
    backward = index.of("ISA", 53, 7, 8)
    assert any(name.startswith("ISA 53:") for name in forward)
    assert any(name.startswith("ACT 8:") for name in backward)


@pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)
def test_a_match_carries_its_family() -> None:
    """The 34-verdict class, closed: the Ethiopian's verse scans to Acts 8:32, and the
    match itself now says Isaiah 53:7 carries the same words -- so a consumer scoring it
    against a scholar who wrote 'Isaiah 53' can see they agreed, with no threshold
    involved anywhere."""
    import sqlite3

    from biblereference.parallels import Parallels
    from biblereference.search import Searcher

    connection = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)
    if not Parallels(connection)._held:
        pytest.skip("parallel_family not built; run `biblereference parallels`")
    with Searcher(
        REAL,
        languages=["grc"],
        coverage=0.50,
        min_query=3,
        min_run=lambda n: max(4, min(6, n // 2)),
    ) as searcher:
        found = searcher.scan(
            "ὡς πρόβατον ἐπὶ σφαγὴν ἤχθη καὶ ὡς ἀμνὸς ἐναντίον τοῦ κείραντος αὐτὸν ἄφωνος"
        )
    ethiopian = next(m for m in found if m.passage.book in ("ACT", "ISA"))
    other = "ISA 53:7" if ethiopian.passage.book == "ACT" else "ACT 8:32"
    assert other in ethiopian.family
