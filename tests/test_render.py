from __future__ import annotations

from pathlib import Path

import pytest

from biblereference import Config, Renderer


@pytest.fixture(scope="module")
def renderer() -> Renderer:
    """These tests are about the body of a document.

    Appendix Z is appended by default, since copyright notices are an obligation, but it
    would be trailing noise in every assertion here. It has its own tests in
    test_appendix.py.
    """
    return Renderer(Config(notices=False))


def render(renderer: Renderer, text: str) -> str:
    out, report = renderer.render_text(text)
    assert report.ok, report.errors
    return out


# --------------------------------------------------------------------------------------
# The two default shapes
# --------------------------------------------------------------------------------------


def test_short_form_renders_inline(renderer: Renderer) -> None:
    out = render(renderer, "As it says in {{Luke 2:42}}, the child...")
    assert out.startswith("As it says in *And when he was twelve years old")
    assert "(Luke 2:42, ASV)" in out
    assert out.endswith(", the child...")
    assert "\n" not in out  # a sentence stays a sentence


def test_attribute_form_renders_as_a_blockquote(renderer: Renderer) -> None:
    out = render(renderer, '[passage="Ps 23:1"]')
    assert out.splitlines() == [
        "> **Psalms 23:1 (American Standard Version)**",
        "> Jehovah is my shepherd; I shall not want.",
    ]


def test_a_range_is_joined_into_one_passage(renderer: Renderer) -> None:
    out = render(renderer, '[passage="Ps 23:1-3"]')
    assert "Psalms 23:1-3" in out
    assert "green pastures" in out and "shepherd" in out
    assert len(out.splitlines()) == 2


# --------------------------------------------------------------------------------------
# Versification actually being applied
# --------------------------------------------------------------------------------------


def test_a_reference_in_hebrew_numbering_finds_the_right_english_verse(
    renderer: Renderer,
) -> None:
    """Hebrew Psalm 51:3 is English 51:1 -- the heading takes the first two verses."""
    out = render(renderer, '[passage="Ps 51:3" vrs="org"]')
    assert "Have mercy upon me, O God" in out


def test_the_rendition_reports_the_numbering_it_actually_used(renderer: Renderer) -> None:
    resolved = renderer.resolve(next(iter(_tags('[passage="Dan 4:1" vrs="org"]'))))
    english = resolved.renditions[0]
    assert english.renumbered
    assert english.reference == "Daniel 4:4"
    assert resolved.reference == "Daniel 4:1"


def test_vulgate_daniel_14_is_bel_which_no_english_protocanon_carries(
    renderer: Renderer,
) -> None:
    """Douay-Rheims Daniel 14 is Bel and the Dragon. The reference is perfectly valid;
    the ASV simply has no such book, and that must be said rather than guessed around."""
    _, report = renderer.render_text('[passage="Dan 14:1" vrs="vul" en="ASV"]')
    assert not report.ok
    assert "no English text" in report.errors[0]


def test_asking_for_an_unbuilt_text_says_how_to_build_it(renderer: Renderer) -> None:
    """ "WEBC" is not an unknown version -- it is a downloaded one that isn't there yet,
    and the difference is the difference between a typo and a missing step."""
    _, report = renderer.render_text('[passage="Sir 24:1" en="WEBC"]')
    assert "biblereference fetch" in report.errors[0]
    assert "not built" in report.errors[0]


def test_substituting_for_an_unreachable_version_is_reported(tmp_path: Path) -> None:
    """Falling back because a version has no Sirach is the system working, and silent.
    Falling back because the version asked for could not be reached is a substitution
    nobody requested, and printing another translation's words under the citation without
    saying so is exactly the failure this library exists to prevent."""
    renderer = Renderer(
        Config(
            notices=False,
            offline=True,
            data_home=tmp_path / "empty",
            # Somewhere for the fallback to land, so this tests the substitution rather
            # than a total failure to find any English at all.
            deuterocanon_english="ASV",
        )
    )

    out, report = renderer.render_text('[passage="John 3:16" en="NIV"]')

    assert "American Standard Version" in out, "the fallback should have supplied the text"
    assert report.warnings, "a version was silently swapped for another"
    assert "NIV was asked for" in report.warnings[0]


# --------------------------------------------------------------------------------------
# Failure is visible
# --------------------------------------------------------------------------------------


def test_an_unresolvable_citation_is_left_in_place_and_reported(renderer: Renderer) -> None:
    text = "Before {{Sir 24:1}} after."
    out, report = renderer.render_text(text)
    assert "{{Sir 24:1}}" in out, "the tag must survive so the gap is visible"
    assert not report.ok
    assert report.total == 1 and report.resolved == 0
    assert "Sirach 24:1" in report.errors[0]


def test_a_bad_verse_number_is_reported_not_rendered(renderer: Renderer) -> None:
    out, report = renderer.render_text("{{Ps 23:99}}")
    assert "{{Ps 23:99}}" in out
    assert "does not exist" in report.errors[0]


def test_an_unknown_book_is_reported(renderer: Renderer) -> None:
    out, report = renderer.render_text("{{Hezekiah 1:1}}")
    assert not report.ok
    assert "{{Hezekiah 1:1}}" in out


def test_one_bad_citation_does_not_stop_the_others(renderer: Renderer) -> None:
    out, report = renderer.render_text("{{Luke 2:42}} then {{Sir 24:1}} then {{John 3:16}}")
    assert report.total == 3 and report.resolved == 2
    assert "{{Sir 24:1}}" in out
    assert "twelve years old" in out and "God so loved the world" in out


def test_strict_mode_turns_warnings_into_errors() -> None:
    """A citation that resolved but lost something -- a missing original -- is an error
    when the author has asked for certainty."""
    lenient = Renderer(Config(strict=False, notices=False))
    strict = Renderer(Config(strict=True, notices=False))
    text = '[passage="Sir 24:1" en="ASV"]'
    assert not lenient.render_text(text)[1].ok  # no deuterocanon in the ASV either way
    assert not strict.render_text(text)[1].ok


# --------------------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------------------


def test_template_can_be_chosen_per_tag(renderer: Renderer) -> None:
    out = render(renderer, '[passage="Ps 23:1" template="inline"]')
    assert out.startswith("*Jehovah is my shepherd")


def test_footnote_template_moves_the_text_to_the_end(renderer: Renderer) -> None:
    out = render(renderer, 'It says in [passage="Ps 23:1" template="footnote"] plainly.')
    body, _, notes = out.partition("\n\n")
    assert body == "It says in Psalms 23:1[^bref1] plainly."
    assert notes.startswith("[^bref1]: **Psalms 23:1**")
    assert "my shepherd" in notes


def test_footnotes_are_numbered_across_a_document(renderer: Renderer) -> None:
    out = render(
        renderer,
        '[passage="Ps 23:1" template="footnote"] and [passage="Ps 23:2" template="footnote"]',
    )
    assert "[^bref1]" in out and "[^bref2]" in out


def test_a_missing_template_is_reported(renderer: Renderer) -> None:
    _, report = renderer.render_text('[passage="Ps 23:1" template="nonesuch"]')
    assert "no template named 'nonesuch'" in report.errors[0]


def test_custom_template_directory_wins(tmp_path: Path) -> None:
    (tmp_path / "blockquote.md.j2").write_text("<<{{ reference }}>>", encoding="utf-8")
    out, report = Renderer(Config(template_dir=tmp_path, notices=False)).render_text(
        '[passage="Ps 23:1"]'
    )
    assert report.ok
    assert out == "<<Psalms 23:1>>"


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


def test_text_around_tags_is_preserved_exactly(renderer: Renderer) -> None:
    text = "# Heading\n\nSome prose.\n\n{{Luke 2:42}}\n\nMore prose.\n"
    out = render(renderer, text)
    assert out.startswith("# Heading\n\nSome prose.\n\n")
    assert out.endswith("\n\nMore prose.\n")


def test_a_document_with_no_tags_is_unchanged(renderer: Renderer) -> None:
    text = "Just prose, no citations at all.\n"
    out, report = renderer.render_text(text)
    assert out == text
    assert report.total == 0 and report.ok


def test_render_file_round_trip(tmp_path: Path, renderer: Renderer) -> None:
    source = tmp_path / "treatise.md"
    target = tmp_path / "treatise.out.md"
    source.write_text("As {{Luke 2:42}} says.\n", encoding="utf-8")
    report = renderer.render_file(source, target)
    assert report.ok and report.resolved == 1
    assert "twelve years old" in target.read_text(encoding="utf-8")


def test_report_summary_reads_plainly(renderer: Renderer) -> None:
    _, report = renderer.render_text("{{Luke 2:42}} {{Sir 24:1}}")
    assert report.summary() == "1/2 citations resolved, 1 error(s)"


def _tags(text: str):
    from biblereference.tags import find_citations

    return find_citations(text)
