"""Esther's Greek additions.

The additions are the one place where the two ways of citing a passage disagree about
the *shape* of the book, not just its verse numbers: the Vulgate appends them as chapters
11 to 16, while the NRSV and NABRE letter them A to F and print each where the Greek puts
it. Every expectation below was checked against the Douay-Rheims text, and the arithmetic
that makes them line up is recorded in ``esther_additions.json``.
"""

from __future__ import annotations

import pytest

from biblereference.refs import VerseRef, parse_reference
from biblereference.versification import Versification, VersificationGapError
from biblereference.versification.esther import (
    additions,
    letter_to_vulgate,
    vulgate_to_letter,
)


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def vulgate(text: str) -> tuple[int, int]:
    ref = letter_to_vulgate(parse_reference(text).start)
    assert isinstance(ref.chapter, int)
    return ref.chapter, ref.verse


# --------------------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------------------


def test_all_six_additions_are_present() -> None:
    assert sorted(additions()) == ["A", "B", "C", "D", "E", "F"]


@pytest.mark.parametrize(
    ("letter", "length"),
    [("A", 17), ("B", 7), ("C", 30), ("D", 16), ("E", 24), ("F", 11)],
)
def test_addition_lengths(letter: str, length: int) -> None:
    assert additions()[letter].length == length


@pytest.mark.parametrize(
    ("cited", "expected"),
    [
        # A opens at the Vulgate's 11:2, after the colophon that ends F.
        ("Est A:1", (11, 2)),
        ("Est A:17", (12, 6)),
        ("Est B:1", (13, 1)),
        ("Est B:7", (13, 7)),
        ("Est C:1", (13, 8)),
        ("Est C:30", (14, 19)),
        # D begins three verses into chapter 15: 15:1-3 is a Vulgate doublet.
        ("Est D:1", (15, 4)),
        ("Est D:16", (15, 19)),
        ("Est E:1", (16, 1)),
        ("Est E:24", (16, 24)),
        ("Est F:1", (10, 4)),
        ("Est F:11", (11, 1)),
    ],
)
def test_letter_citations_resolve_to_vulgate_numbering(
    cited: str, expected: tuple[int, int]
) -> None:
    assert vulgate(cited) == expected


def test_an_addition_that_crosses_a_chapter_boundary() -> None:
    """Addition A runs from 11:2 to the end of chapter 11 and on into chapter 12."""
    assert vulgate("Est A:11") == (11, 12)
    assert vulgate("Est A:12") == (12, 1)


def test_addition_c_crosses_from_chapter_13_into_14() -> None:
    """Mordecai's prayer ends the Vulgate's chapter 13; Esther's opens chapter 14."""
    assert vulgate("Est C:11") == (13, 18)
    assert vulgate("Est C:12") == (14, 1)


# --------------------------------------------------------------------------------------
# The reverse direction
# --------------------------------------------------------------------------------------


def test_vulgate_references_report_their_letter_form() -> None:
    assert vulgate_to_letter(VerseRef("EST", 13, 8, vrs="vul")) == VerseRef(
        "EST", "C", 1, vrs="vul"
    )
    assert vulgate_to_letter(VerseRef("EST", 15, 4, vrs="vul")) == VerseRef(
        "EST", "D", 1, vrs="vul"
    )


def test_the_hebrew_portion_has_no_letter_form() -> None:
    assert vulgate_to_letter(VerseRef("EST", 5, 1, vrs="vul")) is None


def test_the_vulgate_doublet_has_no_letter_form() -> None:
    """15:1-3 recapitulates the instruction of 4:8 and has no Greek counterpart."""
    for verse in (1, 2, 3):
        assert vulgate_to_letter(VerseRef("EST", 15, verse, vrs="vul")) is None
    assert vulgate_to_letter(VerseRef("EST", 15, 4, vrs="vul")) is not None


# --------------------------------------------------------------------------------------
# Through the versification engine
# --------------------------------------------------------------------------------------


def test_the_vulgates_esther_has_sixteen_chapters(vrs: Versification) -> None:
    """Upstream gives the Vulgate only the Septuagint's ten; the Clementine has sixteen."""
    assert vrs.chapter_count("vul", "EST") == 16
    assert vrs.max_verse("vul", "EST", 13) == 18
    assert vrs.max_verse("vul", "EST", 16) == 24


def test_a_letter_citation_validates(vrs: Versification) -> None:
    vrs.validate(parse_reference("Est C:12-30"))


def test_a_verse_beyond_an_addition_is_caught(vrs: Versification) -> None:
    with pytest.raises(VersificationGapError, match="has verses 1-16"):
        vrs.validate(parse_reference("Est D:17"))


def test_letter_chapters_belong_to_esther_alone(vrs: Versification) -> None:
    with pytest.raises(VersificationGapError, match="only Esther has"):
        vrs.validate(parse_reference("Gen A:1"))


def test_a_letter_range_expands_across_the_chapter_boundary(vrs: Versification) -> None:
    verses = vrs.expand(parse_reference("Est C:10-13"))
    assert [(v.chapter, v.verse) for v in verses] == [(13, 17), (13, 18), (14, 1), (14, 2)]
    assert {v.vrs for v in verses} == {"vul"}


def test_a_letter_range_converts_to_vulgate_numbering(vrs: Versification) -> None:
    (segment,) = vrs.convert_range(parse_reference("Est E:1-24"), "vul")
    assert str(segment) == "EST 16:1-24"


def test_the_vulgates_esther_refuses_conversion_to_the_greek(vrs: Versification) -> None:
    """The Septuagint interleaves the additions rather than appending them, and the data
    for that interleaving is the material rejected in corrections.json."""
    with pytest.raises(VersificationGapError):
        vrs.convert_range(parse_reference("Est 13:8", vrs="vul"), "org")
