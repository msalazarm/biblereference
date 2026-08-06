"""The two appendices.

Appendix Y is what a reader checks the work against. Appendix Z is what makes the work
publishable, or says why it is not yet.
"""

from __future__ import annotations

import pytest

from biblereference import Config, Renderer
from biblereference.appendix import (
    Usage,
    check_quota,
    cross_scheme_references,
    public_domain_note,
    quota_for,
    recommended_alternative,
)
from biblereference.refs import parse_reference
from biblereference.versification import Versification


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def usage(corpus: str, label: str, verses: int, words: int) -> Usage:
    out = Usage(corpus, label)
    out.verses = {("SIR", 1, i, "") for i in range(1, verses + 1)}
    out.words = words
    return out


# --------------------------------------------------------------------------------------
# Quotas
# --------------------------------------------------------------------------------------


def test_the_nrsv_family_shares_one_quota() -> None:
    """The National Council of Churches sets the same terms across the RSV and NRSV."""
    for version in ("nrsvce", "nrsvace", "nrsvue", "rsvce", "rsv", "nrsv"):
        quota = quota_for(version)
        assert quota is not None
        assert quota.verses == 500


def test_the_nrsv_counts_verses_and_the_nabre_counts_words() -> None:
    """A single limit would be wrong for one of them."""
    nrsv, nabre = quota_for("nrsvce"), quota_for("nabre")
    assert nrsv is not None and nabre is not None
    assert (nrsv.verses, nrsv.words) == (500, None)
    assert (nabre.verses, nabre.words) == (None, 5000)


@pytest.mark.parametrize(("verses", "exceeded"), [(499, False), (500, False), (501, True)])
def test_the_verse_limit_is_measured_exactly(verses: int, exceeded: bool) -> None:
    finding = check_quota(usage("nrsvce", "NRSVCE", verses, verses * 10), 500_000)
    assert finding is not None
    assert finding.exceeded is exceeded


def test_the_nabre_trips_on_words_while_its_verse_count_is_irrelevant() -> None:
    finding = check_quota(usage("nabre", "NABRE", 100, 6_000), 500_000)
    assert finding is not None
    assert finding.exceeded
    assert "6,000 words" in finding.reasons[0]


def test_the_share_of_the_work_is_its_own_limit() -> None:
    """Under the verse cap, but more than half this work's words."""
    finding = check_quota(usage("nrsvce", "NRSVCE", 200, 12_000), 20_000)
    assert finding is not None
    assert finding.exceeded
    assert any("of this work's words" in reason for reason in finding.reasons)


def test_a_publisher_with_no_published_quota_says_to_ask() -> None:
    finding = check_quota(usage("rsv2ce", "RSV-2CE", 10, 200), 10_000)
    assert finding is not None
    assert not finding.exceeded
    assert "Ignatius" in finding.message(recommended_alternative())


def test_public_domain_texts_have_no_quota_at_all() -> None:
    for version in ("asv", "kjv", "webc", "dra", "latvuc", "bsb"):
        assert quota_for(version) is None
        assert public_domain_note(version) is not None


def test_the_over_quota_message_names_a_way_out() -> None:
    finding = check_quota(usage("nrsvce", "NRSVCE", 612, 14_000), 20_000)
    assert finding is not None
    message = finding.message(recommended_alternative())
    assert "612 distinct verses" in message
    assert "NRSV Permissions Office" in message
    assert "Berean Standard Bible" in message
    assert "30 April 2023" in message


# --------------------------------------------------------------------------------------
# Cross-scheme references
# --------------------------------------------------------------------------------------


def test_a_psalm_reports_the_greek_and_latin_numbering(vrs: Versification) -> None:
    out = cross_scheme_references(vrs, parse_reference("Ps 23:1"))
    assert any("Septuagint Psalms 22:1" in line for line in out)
    assert any("Vulgate Psalms 22:1" in line for line in out)


def test_a_book_named_differently_says_so(vrs: Versification) -> None:
    out = cross_scheme_references(vrs, parse_reference("Sir 24:1"))
    assert any("Ecclesiasticus" in line and "Douay-Rheims" in line for line in out)


def test_a_passage_that_agrees_everywhere_produces_no_noise(vrs: Versification) -> None:
    """A line of identical references would tell a reader nothing."""
    assert cross_scheme_references(vrs, parse_reference("Luke 2:42")) == ()


# --------------------------------------------------------------------------------------
# Through the renderer
# --------------------------------------------------------------------------------------


def test_the_register_merges_the_pieces_of_a_passage() -> None:
    """Cited as 2:7, then 2:4, then 2:1-6 across an argument."""
    renderer = Renderer(Config(appendix=True, original="none"))
    out, report = renderer.render_text(
        "{{1 Tim 2:7}} then {{1 Tim 2:4}} then [passage='1 Tim 2:1-6']"
    )
    assert report.ok, report.errors
    assert "Appendix Y" in out
    register = out.split("Appendix Y")[1]
    assert "### 1 Timothy 2:1-7" in register
    assert "### 1 Timothy 2:4" not in register


def test_the_register_is_off_unless_asked_for() -> None:
    out, _ = Renderer(Config(original="none")).render_text("{{Luke 2:42}}")
    assert "Appendix Y" not in out


def test_the_notices_are_on_by_default() -> None:
    out, _ = Renderer(Config(original="none")).render_text("{{Luke 2:42}}")
    assert "Appendix Z" in out
    assert "American Standard Version (1901). Public domain." in out


def test_the_notices_can_be_turned_off() -> None:
    out, _ = Renderer(Config(original="none", notices=False)).render_text("{{Luke 2:42}}")
    assert "Appendix Z" not in out


def test_the_notices_credit_the_versification_data() -> None:
    """Appendix Y reproduces reference correspondences derived from it."""
    out, _ = Renderer(Config(original="none", appendix=True)).render_text("{{Luke 2:42}}")
    assert "Copenhagen Alliance" in out
    assert "CC BY-SA 4.0" in out


def test_a_public_domain_only_work_gets_no_permissions_section() -> None:
    out, _ = Renderer(Config(original="none")).render_text("{{Luke 2:42}} {{John 3:16}}")
    assert "### Permissions" not in out
    assert "### Public domain" in out


def test_a_document_with_no_citations_gets_no_appendices() -> None:
    out, report = Renderer(Config(appendix=True)).render_text("Just prose.\n")
    assert out == "Just prose.\n"
    assert report.total == 0


# --------------------------------------------------------------------------------------
# What the licence obliges, which is not what the publisher permits
# --------------------------------------------------------------------------------------


def test_a_credit_line_is_not_a_permission_note() -> None:
    """Most texts here are public domain or ask only for attribution, and the credit line
    already prints. Repeating that as a permission would bury the two that matter.
    """
    from biblereference.appendix import check_terms
    from biblereference.licences import get

    quoted = usage("demo", "Demo", 3, 40)
    assert check_terms(quoted, None) is None
    assert check_terms(quoted, get("public-domain")) is None
    assert check_terms(quoted, get("cc-by-4.0")) is None


def test_a_non_commercial_text_says_so_in_full() -> None:
    """A CC BY-NC text has no publisher quota at all, so nothing in the old machinery
    would have mentioned it. The obligation is real and belongs on the page.
    """
    from biblereference.appendix import check_terms
    from biblereference.licences import get

    finding = check_terms(
        usage("peshitta-ot", "Peshitta Old Testament", 12, 300), get("cc-by-nc-4.0")
    )
    assert finding is not None
    message = finding.message()
    assert "12 distinct verses" in message
    assert "may not be used commercially" in message.lower()


def test_share_alike_says_to_keep_the_work_separable() -> None:
    from biblereference.appendix import check_terms
    from biblereference.licences import get

    finding = check_terms(usage("rahlfs", "Rahlfs Septuagint", 5, 90), get("cc-by-sa-4.0"))
    assert finding is not None and "separable" in finding.message()


def test_a_text_whose_file_misstates_its_own_licence_prints_both() -> None:
    """The Patristic Text Archive publishes the SBL Greek New Testament under a CC BY
    header. Printing only the header's claim would state something untrue.
    """
    from dataclasses import replace

    from biblereference.appendix import check_terms
    from biblereference.licences import get

    declared = replace(get("cc-by-4.0"), underlying=get("sblgnt"))
    finding = check_terms(usage("sblgnt", "SBL Greek New Testament", 4, 60), declared)
    assert finding is not None
    message = finding.message()
    assert "CC BY 4.0" in message
    assert "SBL Greek New Testament licence" in message
    assert "Society of Biblical Literature" in message
