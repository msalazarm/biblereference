from __future__ import annotations

import pytest

from biblereference import Config, Renderer
from biblereference.quotecheck import check_quotation

ASV = "And when he was twelve years old, they went up after the custom of the feast;"
NRSV_ISH = "And when he was twelve years old, they went up as usual for the festival."
DIFFERENT = "The Lord is my shepherd; I shall not want."


def test_a_different_translation_of_the_same_verse_passes() -> None:
    """The whole point of supplying a quotation is to print your own translation, so the
    check must not object to one."""
    assert check_quotation(NRSV_ISH, ASV).plausible


def test_an_exact_match_scores_one() -> None:
    assert check_quotation(ASV, ASV).ratio == 1.0


def test_a_different_verse_is_caught() -> None:
    result = check_quotation(DIFFERENT, ASV)
    assert not result.plausible
    assert result.ratio < 0.2


def test_punctuation_and_case_do_not_count() -> None:
    assert check_quotation(ASV.upper().replace(",", " --"), ASV).ratio == 1.0


def test_accents_do_not_count() -> None:
    """So a Greek quotation typed without diacritics still checks out."""
    greek = "Καὶ ὅτε ἐγένετο ἐτῶν δώδεκα"
    assert check_quotation("Και οτε εγενετο ετων δωδεκα", greek).ratio == 1.0


def test_an_empty_quotation_scores_zero() -> None:
    assert check_quotation("   ", ASV).ratio == 0.0


def test_the_message_shows_both_texts() -> None:
    message = check_quotation(DIFFERENT, ASV).message("Luke 2:42")
    assert "supplied:" in message
    assert "Luke 2:42:" in message
    assert "shepherd" in message and "twelve years" in message


def test_the_threshold_is_configurable() -> None:
    assert check_quotation(DIFFERENT, ASV, threshold=0.0).plausible


# --------------------------------------------------------------------------------------
# Through the renderer
# --------------------------------------------------------------------------------------
#
# original="none" throughout: these test the quotation check, and pulling in Greek would
# add a warning about a corpus that has not been built in the test environment.


def test_a_supplied_quotation_is_what_gets_printed() -> None:
    renderer = Renderer(Config(notices=False))
    out, report = renderer.render_text(
        f'[passage="Luke 2:42" original="none" context="{NRSV_ISH}"]'
    )
    assert report.ok and not report.warnings
    assert "as usual for the festival" in out
    assert "after the custom of the feast" not in out
    assert "(as quoted)" in out


def test_a_mismatched_quotation_is_warned_about_but_still_rendered() -> None:
    renderer = Renderer(Config(notices=False))
    out, report = renderer.render_text(
        f'[passage="Luke 2:42" original="none" context="{DIFFERENT}"]'
    )
    assert report.ok  # a warning, not a failure
    assert len(report.warnings) == 1
    assert "does not look like that passage" in report.warnings[0]
    assert "shepherd" in out


def test_strict_mode_makes_a_mismatched_quotation_an_error() -> None:
    renderer = Renderer(Config(strict=True, notices=False))
    out, report = renderer.render_text(
        f'[passage="Luke 2:42" original="none" context="{DIFFERENT}"]'
    )
    assert not report.ok
    assert "does not look like that passage" in report.errors[0]
    assert "{{" not in out  # the tag is left as written


def test_emphasis_applies_to_the_supplied_text() -> None:
    renderer = Renderer(Config(notices=False))
    out, report = renderer.render_text(
        f'[passage="Luke 2:42" original="none" context="{NRSV_ISH}" '
        f'bold.en="twelve years .. festival"]'
    )
    assert report.ok, report.errors
    assert "**twelve years old, they went up as usual for the festival**" in out


def test_an_emphasis_anchor_missing_from_the_supplied_text_is_an_error() -> None:
    """Silently skipping it would claim an emphasis the output does not carry."""
    renderer = Renderer(Config(notices=False))
    _, report = renderer.render_text(
        f'[passage="Luke 2:42" original="none" context="{NRSV_ISH}" bold.en="custom .. feast"]'
    )
    assert not report.ok
    assert "could not find 'custom'" in report.errors[0]


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_the_renderer_honours_the_configured_threshold(threshold: float) -> None:
    renderer = Renderer(Config(quote_threshold=threshold, notices=False))
    _, report = renderer.render_text(f'[passage="Luke 2:42" original="none" context="{NRSV_ISH}"]')
    assert bool(report.warnings) is (threshold == 1.0)
