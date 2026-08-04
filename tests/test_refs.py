from __future__ import annotations

import pytest

from biblereference.canon import NamingScheme, UnknownBookError
from biblereference.refs import (
    ReferenceParseError,
    VerseRange,
    VerseRef,
    parse_reference,
    parse_references,
    roman_to_arabic,
)
from biblereference.versification import VerseOutOfRangeError


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Luke 2:42", "LUK 2:42"),
        ("Sir 24:1-9", "SIR 24:1-9"),
        ("Ecclesiasticus 51:1-30", "SIR 51:1-30"),
        ("1 Cor 13:4-7", "1CO 13:4-7"),
        ("Dan 3:24-90", "DAN 3:24-90"),
        ("Est 13:8-14:19", "EST 13:8-14:19"),
        ("2 Macc 7:28", "2MA 7:28"),
        ("Rev 22:21", "REV 22:21"),
        ("Wisdom 2:12–20", "WIS 2:12-20"),  # en dash
        ("  Ps 119:105-112  ", "PSA 119:105-112"),
    ],
)
def test_parses_ordinary_references(text: str, expected: str) -> None:
    assert str(parse_reference(text)) == expected


def test_book_names_containing_digits_or_conjunctions() -> None:
    """ "Bel and the Dragon 1:5" must not split at "and"."""
    assert str(parse_reference("Bel and the Dragon 1:5")) == "BEL 1:5"
    assert str(parse_reference("Song of Songs 2:1")) == "SNG 2:1"
    assert str(parse_reference("Prayer of Azariah 1:35")) == "S3Y 1:35"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Jude 5", "JUD 1:5"),
        ("Philemon 6", "PHM 1:6"),
        ("Obadiah 1-4", "OBA 1:1-4"),
        ("Susanna 44-46", "SUS 1:44-46"),
        ("Prayer of Azariah 35", "S3Y 1:35"),
    ],
)
def test_single_chapter_books_may_omit_the_chapter(text: str, expected: str) -> None:
    assert str(parse_reference(text)) == expected


def test_multi_chapter_books_may_not_omit_the_chapter() -> None:
    with pytest.raises(ReferenceParseError, match="more than one chapter"):
        parse_reference("Genesis 5")


def test_whole_book_reference_is_an_error_not_a_silent_expansion() -> None:
    with pytest.raises(ReferenceParseError):
        parse_reference("Genesis")


def test_letter_chapters_for_esther_additions() -> None:
    span = parse_reference("Est C:12-30")
    assert span.start.chapter == "C"
    assert span.start.is_letter_chapter
    assert str(span) == "EST C:12-30"


def test_subverse_references() -> None:
    span = parse_reference("ESG 1:1a")
    assert span.start.subverse == "a"
    assert str(span) == "ESG 1:1a"


def test_range_end_inherits_the_start_chapter() -> None:
    span = parse_reference("Sir 24:1-9")
    assert span.start == VerseRef("SIR", 24, 1, vrs="eng")
    assert span.end == VerseRef("SIR", 24, 9, vrs="eng")


def test_versification_is_carried_on_the_reference() -> None:
    span = parse_reference("Dan 3:24", vrs="vul")
    assert span.vrs == "vul"
    assert span.start.in_vrs("org").vrs == "org"


def test_naming_scheme_is_honoured() -> None:
    assert parse_reference("1 Kings 2:3", naming=NamingScheme.DR).book == "1SA"
    assert parse_reference("1 Kings 2:3", naming=NamingScheme.MODERN).book == "1KI"


def test_backwards_range_is_rejected() -> None:
    with pytest.raises(ReferenceParseError, match="ends before it starts"):
        parse_reference("Luke 2:42-10")


def test_range_across_books_is_rejected() -> None:
    with pytest.raises(ValueError, match="crosses books"):
        VerseRange(VerseRef("LUK", 2, 42), VerseRef("JHN", 1, 1))


def test_range_mixing_versifications_is_rejected() -> None:
    with pytest.raises(ValueError, match="mixes versifications"):
        VerseRange(VerseRef("LUK", 2, 42, vrs="eng"), VerseRef("LUK", 2, 43, vrs="org"))


def test_pretty_uses_readable_titles() -> None:
    assert parse_reference("Sir 24:1-9").pretty() == "Sirach 24:1-9"
    assert parse_reference("Est 13:8-14:19").pretty() == "Esther 13:8-14:19"
    assert parse_reference("Luke 2:42").pretty() == "Luke 2:42"


def test_references_sort_in_reading_order() -> None:
    refs = [
        VerseRef("MAT", 1, 1),
        VerseRef("GEN", 1, 1),
        VerseRef("SIR", 1, 1),
        VerseRef("GEN", 1, 2),
    ]
    assert [r.book for r in sorted(refs)] == ["GEN", "GEN", "SIR", "MAT"]


def test_letter_chapters_sort_after_numbered_ones() -> None:
    assert VerseRef("EST", 10, 3) < VerseRef("EST", "A", 1)
    assert VerseRef("EST", "A", 1) < VerseRef("EST", "B", 1)


def test_verse_zero_is_allowed_for_psalm_titles() -> None:
    assert VerseRef("PSA", 3, 0).verse == 0


def test_invalid_letter_chapter_is_rejected() -> None:
    with pytest.raises(ValueError, match="letter chapter"):
        VerseRef("EST", "G", 1)


# --------------------------------------------------------------------------------------
# The forms printed editions actually use
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 Tim. iii. 16", ["1TI 3:16"]),
        ("Matt. v. 13", ["MAT 5:13"]),
        ("Eccles. vii. 29", ["ECC 7:29"]),
        ("Isa. liii. 5", ["ISA 53:5"]),
        ("Rom. i. 21, 22", ["ROM 1:21", "ROM 1:22"]),
        ("1 Cor. xv. 3, 4", ["1CO 15:3", "1CO 15:4"]),
        ("Luke xiv. 34, 35; Matt. v. 13", ["LUK 14:34", "LUK 14:35", "MAT 5:13"]),
        ("Psa. 3.1", ["PSA 3:1"]),
        ("2 Chron. 6.42", ["2CH 6:42"]),
        ("Jn. 1:14", ["JHN 1:14"]),
        ("Rom 1:21, 22", ["ROM 1:21", "ROM 1:22"]),
        ("Luke 14:34, 35; Matt 5:13", ["LUK 14:34", "LUK 14:35", "MAT 5:13"]),
        # A range is one passage where a list is two citations, and editors mean the
        # difference.
        ("Rom 1:21-22", ["ROM 1:21-22"]),
    ],
)
def test_the_forms_printed_editions_use_all_read(text: str, expected: list[str]) -> None:
    """Of 43,963 editor-tagged references in a patristic corpus, 15,706 are one of these
    four forms. None is patristics-specific -- anyone reading Spurgeon, Wesley, Newman or
    the Puritans meets the same set."""
    assert [str(r) for r in parse_references(text)] == expected


def test_a_plain_reference_gives_exactly_one_range() -> None:
    assert len(parse_references("John 3:16")) == 1


def test_parse_reference_is_unchanged() -> None:
    """The singular entry point keeps its contract: one range, and it raises. Callers route
    between dialects on which error it raises, so widening it would break them."""
    with pytest.raises(UnknownBookError):
        parse_reference("Rom. i. 21, 22")


def test_an_unreadable_string_raises_rather_than_returning_empty() -> None:
    """Otherwise a caller cannot tell "could not read this" from "names no passages"."""
    with pytest.raises(ReferenceParseError):
        parse_references("not a reference at all")


def test_a_trailing_period_is_not_read_as_a_division() -> None:
    assert [str(r) for r in parse_references("Matt. v. 13.")] == ["MAT 5:13"]


@pytest.mark.parametrize(
    ("numeral", "value"), [("i", 1), ("iii", 3), ("iv", 4), ("xiv", 14), ("liii", 53)]
)
def test_roman_numerals_read(numeral: str, value: int) -> None:
    assert roman_to_arabic(numeral) == value


def test_something_that_is_not_a_numeral_is_not_read_as_one() -> None:
    assert roman_to_arabic("john") is None
    assert roman_to_arabic("") is None


# --------------------------------------------------------------------------------------
# Whole-chapter references
# --------------------------------------------------------------------------------------


def test_a_whole_chapter_becomes_its_verses() -> None:
    """Expanded rather than left open-ended, so every consumer of a VerseRange keeps
    working and the range is exact."""
    assert str(parse_reference("1 Cor 15", allow_chapter=True)) == "1CO 15:1-58"


def test_a_whole_chapter_is_still_an_error_by_default() -> None:
    """The library's own tag syntax must keep refusing it: there, a chapter with no verse
    is a mistake rather than a citation."""
    with pytest.raises(ReferenceParseError):
        parse_reference("1 Cor 15")


def test_a_whole_book_is_an_error_even_when_chapters_are_allowed() -> None:
    with pytest.raises(ReferenceParseError):
        parse_reference("1 Corinthians", allow_chapter=True)


def test_the_chapter_length_comes_from_the_versification() -> None:
    """Psalm 119 is 176 verses in every system; Psalm 117 is 2."""
    assert str(parse_reference("Ps 117", allow_chapter=True)) == "PSA 117:1-2"
    assert str(parse_reference("Ps 119", allow_chapter=True)) == "PSA 119:1-176"


def test_a_chapter_the_versification_lacks_is_refused() -> None:
    with pytest.raises(VerseOutOfRangeError):
        parse_reference("Ps 200", allow_chapter=True)
