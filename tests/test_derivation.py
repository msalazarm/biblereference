"""Deriving a mapping from the text, rather than checking one against it.

Everything in :mod:`biblereference.audit` above these functions *verifies*: it takes the
mapping's answer and asks whether the text prefers it to its neighbours. A two-verse window
is the right instrument for that and cannot possibly find a mapping nobody wrote down --
which is the failure that let the Letter of Jeremiah run one verse out for seventy-two
verses with nothing to flag it.

So these test the opposite direction: given only the words, recover the correspondence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.audit import align_book, faithful_chapters
from biblereference.refs import VerseRef
from biblereference.store import DataHome
from biblereference.versification import Versification


def verses(system: str, texts: list[str], book: str = "JON", chapter: int = 1):
    return [(VerseRef(book, chapter, i, vrs=system), t) for i, t in enumerate(texts, 1)]


WORDS = [
    "the word of the lord came to jonah",
    "arise go to nineveh that great city",
    "but jonah rose up to flee to tarshish",
    "but the lord sent out a great wind",
    "then the mariners were afraid and cried",
]


def test_an_identical_sequence_aligns_one_to_one() -> None:
    pairs = align_book(verses("vul", WORDS), verses("org", WORDS), language="en")
    assert [(str(a), str(b)) for a, b in pairs] == [
        (f"JON 1:{i}", f"JON 1:{i}") for i in range(1, 6)
    ]


def test_an_inserted_verse_shifts_everything_after_it() -> None:
    """The shape of every versification fault this project has found: one side carries a
    verse the other does not, and everything downstream runs one out."""
    pairs = align_book(
        verses("vul", WORDS), verses("org", ["a heading nobody translates", *WORDS]), language="en"
    )
    assert pairs[0] == (None, VerseRef("JON", 1, 1, vrs="org"))
    assert [(str(a), str(b)) for a, b in pairs[1:]] == [
        (f"JON 1:{i}", f"JON 1:{i + 1}") for i in range(1, 6)
    ]


def test_alignment_is_monotonic_even_when_a_later_verse_matches_better() -> None:
    """The reason this uses an alignment rather than a per-verse argmax.

    Psalm 14 and Psalm 53 are near-duplicates, so picking each verse's best match
    independently will happily cross the two over. Order is the constraint that forbids it:
    editions renumber scripture, they do not reorder it.
    """
    left = verses("vul", ["alpha unique words here", "shared middle text exactly"])
    right = verses("org", ["shared middle text exactly", "alpha unique words here"])
    pairs = align_book(left, right, language="en")

    matched = [(a, b) for a, b in pairs if a is not None and b is not None]
    assert all(
        int(matched[i][1].verse) < int(matched[i + 1][1].verse) for i in range(len(matched) - 1)
    ), "alignment crossed over and is not monotonic"


def test_an_empty_side_yields_gaps_rather_than_an_error() -> None:
    pairs = align_book(verses("vul", WORDS), [], language="en")
    assert all(b is None for _, b in pairs)
    assert len(pairs) == len(WORDS)


# --------------------------------------------------------------------------------------
# Which chapters a witness may be trusted on
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def home() -> DataHome:
    data = DataHome(Path.home() / ".local/share/biblereference")
    if not Path(data.database).exists():
        pytest.skip("corpus not built; run `biblereference fetch`")
    return data


def test_a_witness_is_trusted_only_where_it_numbers_as_its_system_does(home: DataHome) -> None:
    """No corpus is faithful to `lxx` or `vul` anywhere near throughout, so an audit that
    demanded a wholly faithful witness could not run on them at all. Restricting to the
    chapters where a witness *is* faithful is what keeps the comparison sound.

    The Orthodox Jewish Bible is the case that matters: off from `org` on ten chapters, and
    right on the other 1,179.
    """
    vrs = Versification.load()
    ojb = faithful_chapters(home, "ojb", "org", vrs)
    if not ojb:
        pytest.skip("ojb not present")

    assert 1100 < len(ojb) < 1189, "expected the OJB to be faithful on most chapters, not all"
    # The chapters it is wrong on must be excluded, not quietly included.
    assert ("JER", 30) not in ojb
    assert ("GEN", 1) in ojb


def test_the_leningrad_codex_is_faithful_to_org_throughout(home: DataHome) -> None:
    vrs = Versification.load()
    wlc = faithful_chapters(home, "wlc", "org", vrs)
    if not wlc:
        pytest.skip("wlc not present")
    assert len(wlc) == 929


def test_no_corpus_is_faithful_to_the_vulgate_system(home: DataHome) -> None:
    """Recorded because it is the finding, not because it is desirable. Neither the
    Clementine nor the Douay-Rheims numbers its verses the way the shipped `vul` says --
    seven chapters and fifteen respectively -- so every audit of `vul` before this was
    measuring the gap between the system and the nearest edition rather than the mapping.

    If this ever fails, `vul` has been corrected and the audit of it can be believed.
    """
    vrs = Versification.load()
    latvuc = faithful_chapters(home, "latvuc", "vul", vrs)
    if not latvuc:
        pytest.skip("latvuc not present")
    assert len(latvuc) < 1334
