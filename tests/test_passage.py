"""Reading a verse in the language it was asked for, and in no other.

Every test here is a fault that was actually shipped by a caller composing these same
primitives by hand. The worst of them showed an English verse to a model and asked whether
a Greek passage quoted it; the model said yes, 275 confirmed findings were withdrawn, and
nothing in the loop could have caught it, because the loop was the one place that had no
reason to check. What is tested is therefore not that the right text comes back -- that was
never the difficulty -- but that a wrong one cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.passage import (
    BOOK_NOT_HELD,
    NO_CORPUS,
    OK,
    OUT_OF_RANGE,
    PARTIAL,
    UNCONVERTIBLE,
    VERSE_NOT_HELD,
    PassageReader,
)
from biblereference.refs import VerseRange, VerseRef
from biblereference.store import DataHome, SourceMeta, write_corpus
from biblereference.versification import UnknownVersificationError

#: Psalm 79 is the case that matters. `vul` numbers it 79, `nvl` numbers the same words 80,
#: and the verse each calls 79:5 is a different verse in a different psalm. Roughly 42,000
#: findings in one downstream corpus sat on that difference.
LATIN_VUL = {
    "PSA 79:5": "Domine Deus virtutum, quousque irasceris super orationem servi tui?",
    "PSA 78:5": "Usquequo, Domine, irasceris in finem?",
}
LATIN_NVL = {
    "PSA 80:5": "Domine, Deus virtutum, quousque irasceris super orationem populi tui?",
    "PSA 79:5": "Usquequo, Domine? Irasceris in finem?",
}


def build(
    home: DataHome,
    corpus: str,
    language: str,
    vrs: str,
    verses: dict[str, str],
) -> None:
    """Write a corpus keyed by ``"BOOK chapter:verse"``, in its own numbering."""
    rows = []
    for reference, text in verses.items():
        book, position = reference.split(" ")
        chapter, verse = position.split(":")
        rows.append((VerseRef(book, int(chapter), int(verse), vrs=vrs), text))
    write_corpus(
        home,
        SourceMeta(corpus=corpus, label=corpus.upper(), language=language, versification=vrs),
        rows,
    )


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    return DataHome(tmp_path / "brhome")


@pytest.fixture
def latin(home: DataHome) -> DataHome:
    build(home, "clementine", "la", "vul", LATIN_VUL)
    build(home, "nova", "la", "nvl", LATIN_NVL)
    return home


# --------------------------------------------------------------------------------------
# The language is never crossed
# --------------------------------------------------------------------------------------


def test_a_language_that_does_not_hold_the_book_is_not_answered_in_another(
    home: DataHome,
) -> None:
    """The fault that withdrew 275 confirmed findings.

    A caller's per-language corpus lists all ended `asv, bsb, kjv`, because otherwise a
    verse the Greek corpora lack is simply unavailable -- so Greek Daniel, held by none of
    them, resolved to the American Standard Version and a model was asked whether a *Greek*
    passage quoted an English verse. Not holding the text is the useful answer.
    """
    build(home, "greek-nt", "grc", "org", {"JHN 1:1": "εν αρχη ην ο λογος"})
    build(home, "english", "en", "eng", {"DAN 10:11": "And he said unto me, O Daniel"})

    with PassageReader(home) as reader:
        found = reader.resolve("DAN 10:11", vrs="eng", language="grc")

    assert not found
    assert found.reason == BOOK_NOT_HELD
    assert found.text == ""
    assert found.corpus == ""
    # The English was right there, and is the whole point of the test.
    assert "Daniel" not in found.text


def test_the_same_reference_answers_when_english_is_what_was_asked_for(home: DataHome) -> None:
    """The counterpart. Refusing to cross language is not refusing to answer."""
    build(home, "greek-nt", "grc", "org", {"JHN 1:1": "εν αρχη ην ο λογος"})
    build(home, "english", "en", "eng", {"DAN 10:11": "And he said unto me, O Daniel"})

    with PassageReader(home) as reader:
        found = reader.resolve("DAN 10:11", vrs="eng", language="en")

    assert found
    assert found.language == "en"
    assert found.corpus == "english"


def test_naming_corpora_cannot_smuggle_in_another_language(home: DataHome) -> None:
    """``corpora=`` reorders the candidates; it does not suspend the guarantee."""
    build(home, "greek-nt", "grc", "org", {"JHN 1:1": "εν αρχη ην ο λογος"})
    build(home, "english", "en", "eng", {"JHN 1:1": "In the beginning was the Word"})

    with PassageReader(home) as reader:
        found = reader.resolve("JHN 1:1", vrs="org", language="grc", corpora=["english"])

    assert not found
    assert found.reason == NO_CORPUS
    assert reader.candidates("grc", "org", corpora=["english"]) == []


def test_the_language_asked_for_is_the_language_answered_in(latin: DataHome) -> None:
    with PassageReader(latin) as reader:
        found = reader.resolve("PSA 79:5", vrs="vul", language="la")
    assert found.language == "la"


# --------------------------------------------------------------------------------------
# One reference, two numberings
# --------------------------------------------------------------------------------------


def test_the_numbering_a_reference_is_written_in_decides_which_verse_it_is(
    latin: DataHome,
) -> None:
    """`PSA 79:5` is two different verses depending on which Latin numbering wrote it, and
    nothing but the caller can know which was meant. Hence ``vrs`` with no default."""
    with PassageReader(latin) as reader:
        vulgate = reader.resolve("PSA 79:5", vrs="vul", language="la")
        nova = reader.resolve("PSA 79:5", vrs="nvl", language="la")

    assert vulgate.text.startswith("Domine Deus virtutum")
    assert nova.text.startswith("Usquequo, Domine?")
    assert vulgate.text != nova.text
    # Each answered from the corpus that needed no conversion at all.
    assert (vulgate.corpus, nova.corpus) == ("clementine", "nova")


def test_the_answer_says_what_the_reference_became(latin: DataHome) -> None:
    """The number a reader needs to check the answer by hand. `PSA 79:5` in the Vulgate is
    `PSA 80:5` in the Nova Vulgata, and an answer that did not say so could not be checked."""
    with PassageReader(latin) as reader:
        found = reader.resolve("PSA 79:5", vrs="vul", language="la", corpora=["nova"])

    assert found.corpus == "nova"
    assert [str(span) for span in found.reference] == ["PSA 80:5"]
    assert found.versification == "nvl"
    assert str(found.asked) == "PSA 79:5"
    assert found.asked.vrs == "vul"


def test_the_identity_case_still_returns_a_labelled_reference(latin: DataHome) -> None:
    """Source and target numbering equal used to mean "return the span untouched", and an
    untouched span carries whatever label it arrived with -- which downstream was read as
    `org` and here would default to `eng`. A no-op is not the same as a blank."""
    with PassageReader(latin) as reader:
        found = reader.resolve("PSA 79:5", vrs="vul", language="la")

    assert found.versification == "vul"
    assert found.asked.vrs == "vul"
    assert [span.vrs for span in found.reference] == ["vul"]
    assert all(ref.vrs == "vul" for ref in found.verses)


def test_a_reference_given_as_a_ref_is_relabelled_and_not_converted(latin: DataHome) -> None:
    """A bare `VerseRef` carries `eng` when nobody said otherwise. ``vrs`` is being *told*
    to this call, so the ref is relabelled -- converting it would invent a passage."""
    with PassageReader(latin) as reader:
        by_string = reader.resolve("PSA 79:5", vrs="vul", language="la")
        by_ref = reader.resolve(VerseRef("PSA", 79, 5), vrs="vul", language="la")
        by_range = reader.resolve(
            VerseRange.single(VerseRef("PSA", 79, 5)), vrs="vul", language="la"
        )

    assert by_string.text == by_ref.text == by_range.text
    assert by_ref.asked.vrs == "vul"


# --------------------------------------------------------------------------------------
# Which corpus answers
# --------------------------------------------------------------------------------------


def test_a_corpus_needing_no_conversion_is_tried_first(latin: DataHome) -> None:
    """A text numbered as the reference is numbered cannot be renumbered wrongly, and that
    is worth more than any preference between editions."""
    with PassageReader(latin) as reader:
        assert reader.candidates("la", "vul")[0] == "clementine"
        assert reader.candidates("la", "nvl")[0] == "nova"


def test_a_complete_answer_beats_a_partial_one_from_an_earlier_corpus(home: DataHome) -> None:
    """A half-quoted range is how a citation comes to misrepresent, so the partial is held
    back in case something later can answer in full."""
    build(
        home,
        "gappy",
        "la",
        "vul",
        {f"PSA 79:{n}": str(n) for n in range(1, 6)},  # 79:1-5, and not 79:6
    )
    build(home, "whole", "la", "vul", {"PSA 79:5": "quinque", "PSA 79:6": "sex"})

    with PassageReader(home) as reader:
        # `gappy` is tried first: neither is preferred by name and it is the larger corpus,
        # which is the tie-break. So the preference below is not an accident of ordering.
        assert reader.candidates("la", "vul") == ["gappy", "whole"]
        found = reader.resolve("PSA 79:5-6", vrs="vul", language="la")

    assert found.corpus == "whole"
    assert found.reason == OK
    assert not found.partial


def test_a_partial_answer_is_returned_when_nothing_can_answer_in_full(home: DataHome) -> None:
    build(home, "gappy", "la", "vul", {"PSA 79:5": "quinque"})

    with PassageReader(home) as reader:
        found = reader.resolve("PSA 79:5-6", vrs="vul", language="la")

    assert found
    assert found.partial
    assert found.reason == PARTIAL
    assert found.text == "quinque"
    assert len(found.verses) == 1


def test_naming_corpora_sets_the_order(latin: DataHome) -> None:
    with PassageReader(latin) as reader:
        found = reader.resolve("PSA 79:5", vrs="vul", language="la", corpora=["nova"])
    assert found.corpus == "nova"


# --------------------------------------------------------------------------------------
# Saying which kind of nothing
# --------------------------------------------------------------------------------------


def test_a_range_that_conversion_breaks_apart_reports_every_segment(home: DataHome) -> None:
    """Vulgate `Daniel 3:1-100` is Daniel 3:1-33 and the Song of the Three in the Hebrew
    frame. Calling that one range would be the same tidy lie this module exists to refuse."""
    build(
        home,
        "hebrew-frame",
        "en",
        "org",
        {"DAN 3:1": "In the eighteenth year", "S3Y 1:1": "And they walked"},
    )
    with PassageReader(home) as reader:
        found = reader.resolve("DAN 3:1-100", vrs="vul", language="en")

    assert [str(span) for span in found.reference] == ["DAN 3:1-33", "S3Y 1:1-67"]
    assert found.partial, "only two verses of the span are actually held"


def test_a_reference_past_the_end_of_its_chapter_says_so(latin: DataHome) -> None:
    """Told apart from a verse the library merely does not carry, because it is almost
    always the caller's numbering rather than a gap in the library."""
    with PassageReader(latin) as reader:
        found = reader.resolve("PSA 79:200", vrs="vul", language="la")
    assert found.reason == OUT_OF_RANGE


def test_a_book_held_without_the_verse_is_told_from_a_book_not_held(home: DataHome) -> None:
    build(home, "clementine", "la", "vul", {"PSA 79:5": "quinque"})

    with PassageReader(home) as reader:
        held = reader.resolve("PSA 79:6", vrs="vul", language="la")
        absent = reader.resolve("GEN 1:1", vrs="vul", language="la")

    assert held.reason == VERSE_NOT_HELD
    assert absent.reason == BOOK_NOT_HELD


def test_no_corpus_at_all_in_that_language_says_that(home: DataHome) -> None:
    build(home, "clementine", "la", "vul", {"PSA 79:5": "quinque"})
    with PassageReader(home) as reader:
        assert reader.resolve("PSA 79:5", vrs="vul", language="en").reason == NO_CORPUS


def test_a_reference_the_target_numbering_cannot_express_is_refused_not_guessed(
    home: DataHome,
) -> None:
    """The Hebrew frame has no Sirach. Refusing is the honest answer and a different one
    from "the corpus does not carry it"."""
    build(home, "hebrew", "hbo", "org", {"GEN 1:1": "בראשית"})
    with PassageReader(home) as reader:
        assert reader.resolve("SIR 24:1", vrs="vul", language="hbo").reason == UNCONVERTIBLE


# --------------------------------------------------------------------------------------
# What is the caller's fault, and raises
# --------------------------------------------------------------------------------------


def test_the_callers_own_language_codes_are_accepted(latin: DataHome) -> None:
    """They write `lat`, `eng`, `grc`, `syc`; this library writes `la`, `en`, `grc`, `syc`.
    Translating at the boundary is one more thing to get wrong."""
    with PassageReader(latin) as reader:
        assert reader.resolve("PSA 79:5", vrs="vul", language="lat").corpus == "clementine"
        assert reader.resolve("PSA 79:5", vrs="vul", language="Latin").corpus == "clementine"


def test_an_unknown_language_raises_naming_what_is_held(latin: DataHome) -> None:
    with PassageReader(latin) as reader, pytest.raises(LookupError, match="klingon"):
        reader.resolve("PSA 79:5", vrs="vul", language="klingon")


def test_an_unknown_numbering_raises(latin: DataHome) -> None:
    with PassageReader(latin) as reader, pytest.raises(UnknownVersificationError, match="martian"):
        reader.resolve("PSA 79:5", vrs="martian", language="la")


def test_an_unknown_corpus_raises_rather_than_being_dropped(latin: DataHome) -> None:
    """Silently ignoring it would answer out of whatever was left, which is a different
    corpus than the one asked for and no way to tell."""
    with PassageReader(latin) as reader, pytest.raises(LookupError, match="nope"):
        reader.resolve("PSA 79:5", vrs="vul", language="la", corpora=["nope"])


def test_the_result_is_falsy_when_nothing_was_found(latin: DataHome) -> None:
    """``if found:`` is the intended reading, and it must not be true for an empty answer."""
    with PassageReader(latin) as reader:
        assert not reader.resolve("GEN 1:1", vrs="vul", language="la")
        assert reader.resolve("PSA 79:5", vrs="vul", language="la")
