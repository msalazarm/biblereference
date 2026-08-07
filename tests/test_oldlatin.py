"""Reading a mutilated manuscript without inventing what is missing.

Every test here is about a way this parser could quietly produce a reading nobody printed.
That is the whole risk of this source: the text is Latin prose with bare `N.` verse numbers
in the middle of it and runs of spaced dots where the page is gone, and every one of those
dots is also a full stop.
"""

from __future__ import annotations

import pytest

from biblereference.corpora.oldlatin import CORPORA, SKIPPED, _readable, _roman, _verses
from biblereference.corpora.tei import GAP

# --------------------------------------------------------------------------------------
# The hole, which is the whole difficulty
# --------------------------------------------------------------------------------------


def test_a_verse_number_followed_by_a_hole_survives() -> None:
    """The one that was got wrong first, and the reason the order in `_verses` is what it is.

    `2. . . . . . Abraham` is a verse number and then a hole. Marking holes first begins the
    run at the number's own full stop and eats it, leaving a bare `2` that no longer looks
    like a verse number -- so Vercellensis Matthew 1:2 and 1:3 were absorbed into 1:1, in a
    verse already so damaged that the loss did not show. 119 verses came back when the order
    was reversed.
    """
    found = _verses("1. Liber generatio. . . . . Christi. 2. . . . . . . Abraham.. . . it Isaac.")
    assert [n for n, _ in found] == [1, 2]
    assert found[0][1].startswith("Liber generatio")
    assert GAP in found[0][1]
    assert "Abraham" in found[1][1]


def test_a_hole_is_marked_rather_than_closed_over() -> None:
    """A gap silently healed is a manufactured reading, and this text would be full of
    them: 5,615 dot runs across the file."""
    ((_, text),) = _verses("1. Liber generatio. . . . . Christi filii Da. . . . . . lii Abr.")
    assert GAP in text
    assert ". . . ." not in text
    assert "Liber generatio" in text and "Christi" in text


def test_an_ordinary_full_stop_is_not_a_hole() -> None:
    """Two dots or more. One `. ` ends a sentence, and turning those into holes would put a
    mark of damage through every undamaged verse in the book."""
    ((_, text),) = _verses("2. dicentes: Ubi est qui natus est Rex Judaeorum? Vidimus enim.")
    assert GAP not in text
    assert text.endswith("Vidimus enim.")


def test_a_verse_that_is_only_a_hole_is_not_a_verse() -> None:
    """The editor saying the page is gone, not the manuscript omitting anything. Stored, a
    reader would take the blank for a reading."""
    assert _readable("Liber generatio") is True
    assert _readable(f"Liber {GAP} generatio") is True
    assert _readable(f"{GAP}") is False
    assert _readable(f" {GAP} . {GAP} ") is False


def test_a_number_inside_a_word_is_not_a_verse_number() -> None:
    """`N.` only where a verse can begin. Migne's Latin is full of abbreviations."""
    assert _verses("1. Cum ergo natus esset Jesus in Bethlem. Herodis 4.Regis venerunt.") == [
        (1, "Cum ergo natus esset Jesus in Bethlem. Herodis 4.Regis venerunt.")
    ]


def test_text_with_no_verse_numbers_yields_nothing() -> None:
    """Corbeiensis and Brixianus are printed exactly like this, and the honest answer for
    them is nothing rather than a guess."""
    assert _verses("Liber generationis Jesu Christi, filii David, filii Abraham.") == []


# --------------------------------------------------------------------------------------
# The chapters
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "expected"),
    [("PRIMUM", 1), ("II", 2), ("IV", 4), ("IX", 9), ("XVII", 17), ("XXVIII", 28)],
)
def test_the_chapter_numerals(printed: str, expected: int) -> None:
    """`CAPUT PRIMUM.` for the first and Roman numerals after it."""
    assert _roman(printed) == expected


# --------------------------------------------------------------------------------------
# What is deliberately absent
# --------------------------------------------------------------------------------------


def test_two_manuscripts_are_imported_and_two_are_recorded_as_not() -> None:
    """An absence with no reason beside it is indistinguishable from a bug. Corbeiensis and
    Brixianus have no verse numbers and no chapter heads at all; numbering them would mean
    aligning against the Vulgate and calling the result the manuscript's own."""
    assert set(CORPORA) == {"Vercellensis", "Veronensis"}
    assert set(SKIPPED) == {"Corbeiensis", "Brixianus"}
    for name, why in SKIPPED.items():
        assert len(why.split()) > 8, f"{name} is dismissed without a reason"
