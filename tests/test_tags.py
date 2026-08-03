from __future__ import annotations

import pytest

from biblereference.canon import NamingScheme
from biblereference.tags import Emphasis, TagSyntaxError, find_citations


def one(text: str):
    found = list(find_citations(text))
    assert len(found) == 1, f"expected exactly one tag, got {len(found)}"
    return found[0]


# --------------------------------------------------------------------------------------
# Short form
# --------------------------------------------------------------------------------------


def test_short_form_is_just_a_reference() -> None:
    tag = one("As it says in {{Luke 2:42}}, the child...")
    assert tag.reference == "Luke 2:42"
    assert tag.inline
    assert tag.english is None and tag.original is None


def test_short_form_takes_options_after_a_pipe() -> None:
    tag = one("{{Sir 24:1-9 | en=DRA | original=lxx}}")
    assert tag.reference == "Sir 24:1-9"
    assert tag.english == "DRA"
    assert tag.original == ("lxx",)


def test_short_form_reports_a_bad_option() -> None:
    with pytest.raises(TagSyntaxError, match="could not read option"):
        list(find_citations("{{Luke 2:42 | this is not an option}}"))


def test_short_form_needs_a_reference() -> None:
    with pytest.raises(TagSyntaxError, match="no reference"):
        list(find_citations("{{ | en=ASV}}"))


# --------------------------------------------------------------------------------------
# Attribute form
# --------------------------------------------------------------------------------------


def test_attribute_form() -> None:
    tag = one(
        '[passage="Luke 2:42" en="ASV" original="auto" '
        'context="And when he was twelve years old." '
        'bold.en="twelve years .. feast"]'
    )
    assert tag.reference == "Luke 2:42"
    assert tag.english == "ASV"
    assert tag.original == ("auto",)
    assert tag.context == "And when he was twelve years old."
    assert tag.emphasis["en"] == (Emphasis("twelve years", "feast", "bold"),)
    assert not tag.inline


def test_attribute_form_tolerates_a_bracket_inside_a_quoted_value() -> None:
    tag = one('[passage="Luke 2:42" context="he said [sic] this"]')
    assert tag.context == "he said [sic] this"


def test_attribute_form_rejects_unknown_options() -> None:
    with pytest.raises(TagSyntaxError, match="unknown option"):
        list(find_citations('[passage="Luke 2:42" colour="blue"]'))


# --------------------------------------------------------------------------------------
# Block form
# --------------------------------------------------------------------------------------

BLOCK = """```passage
ref: Dan 3:24-90
vrs: vul
english: DRA
original: [lxx, theodotion]
naming: dr
emphasis:
  en:  {span: "Blessed art thou .. for ever", style: bold}
  grc: {span: "ευλογητος .. αιωνας", style: italic}
```
"""


def test_block_form() -> None:
    tag = one(BLOCK)
    assert tag.reference == "Dan 3:24-90"
    assert tag.vrs == "vul"
    assert tag.english == "DRA"
    assert tag.original == ("lxx", "theodotion")
    assert tag.naming is NamingScheme.DR
    assert tag.emphasis["en"][0].style == "bold"
    assert tag.emphasis["grc"][0] == Emphasis("ευλογητος", "αιωνας", "italic")
    assert not tag.inline


def test_block_form_accepts_several_spans_per_language() -> None:
    tag = one(
        "```passage\n"
        "ref: Luke 2:42\n"
        "emphasis:\n"
        "  en:\n"
        '    - {span: "twelve .. old", style: bold}\n'
        '    - {span: "custom .. feast", style: italic}\n'
        "```\n"
    )
    assert len(tag.emphasis["en"]) == 2


def test_block_form_needs_a_ref() -> None:
    with pytest.raises(TagSyntaxError, match="no 'ref'"):
        list(find_citations("```passage\nenglish: ASV\n```\n"))


def test_block_form_reports_bad_yaml() -> None:
    with pytest.raises(TagSyntaxError, match="could not read YAML"):
        list(find_citations("```passage\nref: [unclosed\n```\n"))


# --------------------------------------------------------------------------------------
# Options common to every form
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("auto", ("auto",)),
        ("lxx", ("lxx",)),
        ("hebrew,lxx", ("hebrew", "lxx")),
        ("hebrew lxx", ("hebrew", "lxx")),
        ("none", ("none",)),
    ],
)
def test_original_accepts_a_word_or_a_list(written: str, expected: tuple[str, ...]) -> None:
    assert one(f"{{{{Gen 1:1 | original={written}}}}}").original == expected


def test_original_rejects_contradictions() -> None:
    """The three booleans this replaced could contradict each other; this cannot."""
    with pytest.raises(TagSyntaxError, match="cannot be combined"):
        list(find_citations("{{Gen 1:1 | original=none,lxx}}"))
    with pytest.raises(TagSyntaxError, match="cannot be combined"):
        list(find_citations("{{Gen 1:1 | original=auto,hebrew}}"))


def test_latin_is_available_but_never_automatic() -> None:
    """The Vulgate is a translation; printing it beside the originals is a choice."""
    assert one("{{John 1:1 | original=latin}}").original == ("latin",)
    assert one("{{Ps 23:1 | original=hebrew,lxx,latin}}").original == ("hebrew", "lxx", "latin")


def test_original_rejects_unknown_values() -> None:
    with pytest.raises(TagSyntaxError, match="unknown original"):
        list(find_citations("{{Gen 1:1 | original=aramaic}}"))


def test_emphasis_span_without_a_separator_is_a_single_anchor() -> None:
    tag = one('[passage="Luke 2:42" bold.en="twelve years"]')
    assert tag.emphasis["en"][0] == Emphasis("twelve years", "twelve years", "bold")


def test_emphasis_rejects_an_unknown_style_or_language() -> None:
    with pytest.raises(TagSyntaxError, match="unknown emphasis style"):
        list(find_citations('[passage="Luke 2:42" bold.en="a .. b" underline.en="c .. d"]'))
    with pytest.raises(TagSyntaxError, match="unknown language"):
        list(find_citations('[passage="Luke 2:42" bold.klingon="a .. b"]'))


def test_naming_scheme_is_read() -> None:
    assert one('[passage="1 Kings 2:3" naming="dr"]').naming is NamingScheme.DR
    with pytest.raises(TagSyntaxError, match="unknown naming scheme"):
        list(find_citations('[passage="1 Kings 2:3" naming="clementine"]'))


# --------------------------------------------------------------------------------------
# Scanning a document
# --------------------------------------------------------------------------------------


def test_tags_are_found_in_document_order_with_positions() -> None:
    text = 'One {{Luke 2:42}} two [passage="Gen 1:1"] three.'
    tags = list(find_citations(text))
    assert [t.reference for t in tags] == ["Luke 2:42", "Gen 1:1"]
    assert [t.start for t in tags] == sorted(t.start for t in tags)
    for tag in tags:
        assert text[tag.start : tag.end] == tag.raw


def test_single_braces_are_not_tags() -> None:
    assert list(find_citations("A set {a, b} in prose")) == []


def test_an_empty_tag_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(TagSyntaxError, match="no reference"):
        list(find_citations("{{}}"))


def test_short_form_does_not_span_lines() -> None:
    assert list(find_citations("{{Luke\n2:42}}")) == []
