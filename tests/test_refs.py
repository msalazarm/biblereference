from __future__ import annotations

import pytest

from biblereference.canon import NamingScheme
from biblereference.refs import ReferenceParseError, VerseRange, VerseRef, parse_reference


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
