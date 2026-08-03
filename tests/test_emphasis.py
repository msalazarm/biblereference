"""Emphasis spans.

The Greek and Hebrew here are the real texts from the built corpora, because the whole
point of the folding is that an anchor typed without accents or points finds them.
"""

from __future__ import annotations

import pytest

from biblereference.emphasis import SpanNotFoundError, apply_spans, fold
from biblereference.tags import Emphasis

ASV_LUKE = "And when he was twelve years old, they went up after the custom of the feast;"
GREEK_LUKE = "Καὶ ὅτε ἐγένετο ἐτῶν δώδεκα, ἀναβαινόντων αὐτῶν κατὰ τὸ ἔθος τῆς ἑορτῆς,"
HEBREW_ISAIAH = "הִנֵּ֣ה הָעַלְמָ֗ה הָרָה֙ וְיֹלֶ֣דֶת בֵּ֔ן"


def bold(start: str, end: str) -> Emphasis:
    return Emphasis(start, end, "bold")


# --------------------------------------------------------------------------------------
# Folding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "folded"),
    [
        ("δώδεκα", "δωδεκα"),
        ("Ἰησοῦς", "ιησουσ"),  # breathings, circumflex, and final sigma
        ("ᾧ", "ω"),  # iota subscript
        ("הָעַלְמָ֗ה", "העלמה"),  # niqqud and cantillation
        ("אַל־תִּפְגְּעִי", "אל תפגעי"),  # maqqef reads as a space
        ("  spaced   out  ", "spaced out"),
    ],
)
def test_folding_removes_what_an_anchor_will_not_be_typed_with(written: str, folded: str) -> None:
    assert fold(written) == folded


def test_final_sigma_folds_to_medial() -> None:
    """So an anchor can end a word without knowing where the quotation will cut it."""
    assert fold("λόγος") == fold("λόγοσ")


# --------------------------------------------------------------------------------------
# Applying spans
# --------------------------------------------------------------------------------------


def test_english_span() -> None:
    assert apply_spans(ASV_LUKE, [bold("twelve years", "feast")]) == (
        "And when he was **twelve years old, they went up after the custom of the feast**;"
    )


def test_a_single_anchor_marks_just_that_phrase() -> None:
    assert apply_spans(ASV_LUKE, [bold("twelve years", "twelve years")]) == (
        "And when he was **twelve years** old, they went up after the custom of the feast;"
    )


def test_italic_uses_one_marker() -> None:
    out = apply_spans(ASV_LUKE, [Emphasis("twelve", "years", "italic")])
    assert "*twelve years*" in out and "**" not in out


def test_unaccented_greek_anchor_finds_accented_text() -> None:
    out = apply_spans(GREEK_LUKE, [Emphasis("ετων δωδεκα", "εορτης", "italic")])
    assert out.startswith("Καὶ ὅτε ἐγένετο *ἐτῶν δώδεκα")
    assert out.endswith("τῆς ἑορτῆς*,")


def test_unpointed_hebrew_anchor_finds_pointed_text() -> None:
    out = apply_spans(HEBREW_ISAIAH, [bold("העלמה", "הרה")])
    assert "**הָעַלְמָ֗ה" in out


def test_a_hebrew_span_keeps_its_pointing_inside_the_markers() -> None:
    """A closing marker between a letter and its cantillation would split the word."""
    out = apply_spans(HEBREW_ISAIAH, [bold("העלמה", "הרה")])
    assert "הָרָה֙**" in out
    assert "הָרָה**֙" not in out


def test_text_outside_the_span_is_untouched() -> None:
    out = apply_spans(GREEK_LUKE, [bold("δωδεκα", "δωδεκα")])
    assert out.replace("**", "") == GREEK_LUKE


def test_several_spans_in_one_verse() -> None:
    out = apply_spans(
        ASV_LUKE,
        [bold("twelve", "years"), Emphasis("custom", "feast", "italic")],
    )
    assert "**twelve years**" in out and "*custom of the feast*" in out


def test_spans_apply_left_to_right_regardless_of_the_order_given() -> None:
    out = apply_spans(
        ASV_LUKE,
        [Emphasis("custom", "feast", "italic"), bold("twelve", "years")],
    )
    assert out.index("**twelve years**") < out.index("*custom of the feast*")


# --------------------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------------------


def test_a_missing_anchor_raises_and_shows_the_text() -> None:
    with pytest.raises(SpanNotFoundError) as excinfo:
        apply_spans(ASV_LUKE, [bold("unicorn", "feast")])
    assert "could not find 'unicorn'" in str(excinfo.value)
    assert ASV_LUKE in str(excinfo.value)


def test_an_end_anchor_before_the_start_raises() -> None:
    with pytest.raises(SpanNotFoundError, match="but not 'twelve' after it"):
        apply_spans(ASV_LUKE, [bold("feast", "twelve")])


def test_overlapping_spans_raise() -> None:
    with pytest.raises(SpanNotFoundError, match="overlap"):
        apply_spans(ASV_LUKE, [bold("twelve", "went"), bold("old", "custom")])


def test_no_spans_leaves_the_text_alone() -> None:
    assert apply_spans(ASV_LUKE, []) == ASV_LUKE
