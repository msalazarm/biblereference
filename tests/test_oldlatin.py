"""Reading a mutilated manuscript without inventing what is missing.

Every test here is about a way this parser could quietly produce a reading nobody printed.
That is the whole risk of this source: the text is Latin prose with bare `N.` verse numbers
in the middle of it and runs of spaced dots where the page is gone, and every one of those
dots is also a full stop.
"""

from __future__ import annotations

import hashlib

import pytest

from biblereference.corpora.oldlatin import (
    CORPORA,
    DERIVED,
    SKIPPED,
    _Bound,
    _derived_verses,
    _readable,
    _roman,
    _verses,
)
from biblereference.corpora.tei import GAP
from biblereference.refs import VerseRef

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
    """Corbeiensis and Brixianus are printed exactly like this. This parser answers nothing
    for them rather than guessing; their divisions come from the alignment below instead,
    which at least records that the guess is a guess."""
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


def test_the_four_manuscripts_are_imported_three_ways() -> None:
    """Two carry Bianchini's numbers, two are cut by alignment, and three gospels of
    Corbeiensis are not a manuscript text at all. An absence with no reason beside it is
    indistinguishable from a bug."""
    assert set(CORPORA) == {"Vercellensis", "Veronensis"}
    assert set(DERIVED) == {"Brixianus", "Corbeiensis"}
    assert set(SKIPPED) == {"Corbeiensis Mark, Luke and John"}
    for name, why in SKIPPED.items():
        assert len(why.split()) > 8, f"{name} is dismissed without a reason"


def test_a_derived_corpus_says_so_in_its_own_label() -> None:
    """The notes are read by whoever goes looking; the label is read by everyone. A verse
    division nobody printed must not be able to reach a reader looking like one that was."""
    for _, label, _ in DERIVED.values():
        assert "derived, not printed" in label


def test_corbeiensis_takes_matthew_only() -> None:
    """Its Mark, Luke and John are Bianchini's apparatus -- twelve-word fragments, some of
    them notes about the manuscript rather than readings from it."""
    assert DERIVED["Corbeiensis"][2] == ("MAT",)
    assert DERIVED["Brixianus"][2] == ("MAT", "MRK", "LUK", "JHN")


# --------------------------------------------------------------------------------------
# The derived divisions, which are this library's and not the edition's
# --------------------------------------------------------------------------------------


def _record(stream: list[str], cuts: dict[str, int]) -> _Bound:
    digest = hashlib.sha256(" ".join(stream).encode()).hexdigest()[:16]
    return _Bound(digest, cuts)


def test_offsets_are_refused_when_the_stream_is_not_the_one_they_were_measured_on() -> None:
    """The offsets are word positions. A parser change that shifts the stream by one word
    would move every verse in the manuscript, and would do it without any symptom -- so the
    reading is checked against a digest rather than assumed to be the same one."""
    stream = ["Liber", "generationis", "Jesu", "Christi", "Abraham", "genuit", "Isaac"]
    record = _record(stream, {"1:1": 0, "1:2": 4})
    verses, _ = _derived_verses(stream, "MAT", record)
    assert len(verses) == 2

    with pytest.raises(ValueError, match="different reading"):
        _derived_verses([*stream, "extra"], "MAT", record)


def test_text_before_the_first_verse_is_returned_rather_than_dropped() -> None:
    """Corbeiensis opens Matthew with sixty-one words of genealogy from Adam that the
    Vulgate has no verse for. Slicing from the first cut discards it, and a reading that
    divergent going missing in silence is exactly what this module exists to prevent."""
    stream = ["Deus", "fecit", "Adam.", "Liber", "generationis", "Jesu"]
    verses, prologue = _derived_verses(stream, "MAT", _record(stream, {"1:1": 3}))
    assert prologue == "Deus fecit Adam."
    assert verses == [(VerseRef("MAT", 1, 1), "Liber generationis Jesu")]


def test_the_cuts_partition_the_stream_without_overlap_or_loss() -> None:
    """Every word after the first cut lands in exactly one verse. A projection that ran
    backwards would duplicate text across two verses and read as a manuscript repeating
    itself."""
    stream = "a b c d e f g h".split()
    verses, prologue = _derived_verses(
        stream, "MAT", _record(stream, {"1:1": 0, "1:2": 3, "1:3": 5})
    )
    assert not prologue
    assert [text for _, text in verses] == ["a b c", "d e", "f g h"]


def test_an_empty_verse_is_left_out_rather_than_stored_blank() -> None:
    """Two cuts at the same offset mean the alignment found nothing between them. Storing
    the empty string would read as a verse the manuscript omits."""
    stream = "a b c".split()
    verses, _ = _derived_verses(stream, "MAT", _record(stream, {"1:1": 0, "1:2": 3, "1:3": 3}))
    assert [str(ref) for ref, _ in verses] == ["MAT 1:1"]
