"""The reading screen's three endpoints, against a corpus built here.

The claims worth pinning are about *disagreement*, since agreement is the uninteresting
case: a book one system numbers and another does not, a version that prints fewer verses
than the reference asks for, a verse that carries two, and a name that means two books.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from biblereference.refs import VerseRef
from biblereference.store import DataHome, SourceMeta, write_corpus
from biblereference.web import library as lib
from biblereference.web import server
from biblereference.web.reader import api_books, api_parse, api_reader


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataHome:
    where = DataHome(tmp_path)
    write_corpus(
        where,
        SourceMeta(corpus="english", label="An English Bible", language="en", versification="eng"),
        [(VerseRef("MAT", 17, verse), f"english matthew {verse}") for verse in range(1, 28)]
        + [(VerseRef("JHN", 3, verse), f"english john {verse}") for verse in range(1, 37)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="latin", label="A Latin Bible", language="la", versification="vul"),
        # The Clementine carries the Greek's 14 and 15 as one verse, so its Matthew 17 runs
        # to 26 where the English runs to 27. That offset is the point of the fixture.
        [(VerseRef("MAT", 17, verse), f"latinum matthaeum {verse}") for verse in range(1, 27)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="hebrew", label="A Hebrew Bible", language="hbo", versification="org"),
        [(VerseRef("GEN", 1, verse), f"בראשית {verse}") for verse in range(1, 32)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="syriac", label="A Syriac Bible", language="syc", versification="org"),
        # The apocryphal psalms. `org` and `eng` declare PS2 and `nvl` does not, which makes
        # it the case `api_books` exists to get right.
        [(VerseRef("PS2", 1, verse), f"ܙܥܘܪܐ {verse}") for verse in range(1, 8)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="short", label="A partial edition", language="en", versification="eng"),
        # Prints John 3 as far as verse 30 and no further -- a real editorial difference,
        # not a build fault, and the reader has to be able to tell the two apart.
        [(VerseRef("JHN", 3, verse), f"short john {verse}") for verse in range(1, 31)],
    )
    monkeypatch.setattr(server, "HOME", where)
    monkeypatch.setattr(lib, "_LIBRARY", None)
    monkeypatch.setattr(lib, "_local", threading.local())
    return where


def book(payload: dict, code: str) -> dict:  # type: ignore[type-arg]
    (found,) = [b for b in payload["books"] if b["book"] == code]
    return found  # type: ignore[no-any-return]


def version(payload: dict, corpus: str) -> dict:  # type: ignore[type-arg]
    (found,) = [v for v in payload["versions"] if v["corpus"] == corpus]
    return found  # type: ignore[no-any-return]


# --------------------------------------------------------------------------------------
# The dropdown: the union, not either half
# --------------------------------------------------------------------------------------


def test_the_books_are_grouped_in_reading_order(home: DataHome) -> None:
    payload = api_books({"vrs": ["eng"]})
    labels = [group["label"] for group in payload["groups"]]
    assert labels == ["Hebrew canon", "Deuterocanon", "New Testament", "Appendix"]

    hebrew = next(g for g in payload["groups"] if g["canon"] == "hebrew")
    assert hebrew["books"][:5] == ["GEN", "EXO", "LEV", "NUM", "DEU"]
    assert book(payload, "GEN")["chapters"] == 50
    assert book(payload, "GEN")["verses"][0] == 31


def test_a_book_the_system_lacks_is_still_offered_and_says_so(home: DataHome) -> None:
    """`nvl` declares 73 books and twenty of the ninety-three held are not among them;
    `lxx` has no Daniel, Esther, Nehemiah, Song of the Three or 4 Ezra. A dropdown built
    from the system alone hides a fifth of the library."""
    payload = api_books({"vrs": ["nvl"]})
    codes = {b["book"] for b in payload["books"]}
    assert "PS2" in codes, "nvl has no PS2, but a corpus in this library holds it"
    assert book(payload, "PS2")["from"] == "corpora"
    assert book(payload, "GEN")["from"] == "system"


def test_a_book_neither_the_system_nor_a_corpus_has_is_not_offered(home: DataHome) -> None:
    """The other direction. Offering everything would put chapters in the grid that raise
    the moment they are clicked."""
    payload = api_books({"vrs": ["eng"]})
    assert not any(b["book"] == "ENO" for b in payload["books"])


def test_a_numbered_superscription_is_a_verse_zero(home: DataHome) -> None:
    """A reader starting every chapter at verse 1 drops the psalm titles silently, which is
    the kind of loss nobody reports because nobody sees it.

    Which chapters those are is itself a disagreement between the systems, and not the one
    you would guess: `org` has *none*, because the Hebrew counts the superscription as
    verse 1. It is `eng` (63), `lxx` (139) and `vul` (147) that leave it unnumbered and so
    need a verse 0 to hold it.
    """
    english = api_books({"vrs": ["eng"]})
    assert 3 in book(english, "PSA")["titled"]
    assert 1 not in book(english, "PSA")["titled"]
    assert len(book(english, "PSA")["titled"]) == 63
    assert book(api_books({"vrs": ["org"]}), "PSA")["titled"] == []


def test_the_titles_follow_the_naming_asked_for(home: DataHome) -> None:
    modern = api_books({"vrs": ["eng"]})
    douay = api_books({"vrs": ["vul"], "naming": ["dr"]})
    assert book(modern, "1SA")["title"] == "1 Samuel"
    assert book(douay, "1SA")["title"] == "1 Kings"
    assert book(douay, "1CH")["title"] == "1 Paralipomenon"


def test_an_unknown_naming_or_system_is_refused(home: DataHome) -> None:
    with pytest.raises(ValueError, match="naming"):
        api_books({"naming": ["klingon"]})
    with pytest.raises(ValueError, match="versification"):
        api_books({"vrs": ["nonesuch"]})


# --------------------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------------------


def test_only_the_versions_asked_for_are_read(home: DataHome) -> None:
    """Psalm 119 across every version that carries it is 740 KB. Laziness here is a
    requirement, not an optimisation."""
    payload = api_reader({"book": ["John"], "chapter": ["3"], "corpus": ["english"]})
    assert version(payload, "english")["loaded"] is True
    assert version(payload, "short")["loaded"] is False
    # ...but the stub still says it has it, from the cache and with no query.
    assert version(payload, "short")["carries"] is True
    assert version(payload, "short")["held"] == 30


def test_a_version_that_does_not_have_the_book_is_absent_not_empty(home: DataHome) -> None:
    """A Hebrew Bible asked for John. Loaded-with-nothing-in-it reads as a build fault."""
    payload = api_reader({"book": ["John"], "chapter": ["3"], "corpus": ["hebrew"]})
    row = version(payload, "hebrew")
    assert row["loaded"] is False
    assert row["absent"] is True
    assert row["carries"] is False


def test_a_version_printing_fewer_verses_says_how_many_are_missing(home: DataHome) -> None:
    """ "This edition ends at verse 30" and "the passage is shorter in this numbering" make
    the same short array and are not the same fact, so the count is reported."""
    payload = api_reader({"book": ["John"], "chapter": ["3"], "corpus": ["english,short"]})
    assert (version(payload, "english")["asked"], version(payload, "english")["missing"]) == (36, 0)
    assert (version(payload, "short")["asked"], version(payload, "short")["missing"]) == (36, 6)


def test_each_verse_says_which_pivot_verses_it_carries(home: DataHome) -> None:
    """The hover link, and the reason it needs no per-pair table.

    The Clementine's Matthew 17:14 holds what the Greek numbers 14 and 15, so its `covers`
    names both -- and every verse after it is one behind. Two verses in different versions
    correspond exactly when these sets intersect.
    """
    payload = api_reader(
        {"book": ["Matthew"], "chapter": ["17"], "vrs": ["vul"], "corpus": ["latin,english"]}
    )
    latin = {v["ref"]: v["covers"] for v in version(payload, "latin")["verses"]}
    english = {v["ref"]: v["covers"] for v in version(payload, "english")["verses"]}

    assert latin["MAT 17:14"] == ["MAT 17:14", "MAT 17:15"]
    assert latin["MAT 17:15"] == ["MAT 17:16"]
    assert english["MAT 17:15"] == ["MAT 17:15"]
    # Which is the link: the Latin 14 and the English 15 share a pivot verse.
    assert set(latin["MAT 17:14"]) & set(english["MAT 17:15"])
    assert not set(latin["MAT 17:15"]) & set(english["MAT 17:15"])


def test_the_reading_direction_comes_from_one_list(home: DataHome) -> None:
    """`render.RTL`, promoted from private for exactly this. Greek and Coptic are ancient
    and read left to right, so "old language" is not the criterion."""
    payload = api_reader({"book": ["Genesis"], "chapter": ["1"], "vrs": ["org"]})
    assert version(payload, "hebrew")["dir"] == "rtl"
    assert version(payload, "english")["dir"] == "ltr"


def test_a_chapter_the_system_does_not_have_is_refused_with_its_own_sentence(
    home: DataHome,
) -> None:
    """`parse_reference` validates a chapter-only reference and a `chapter:verse` one only
    for shape, so `Habakkuk 99:1` would otherwise reach every version separately."""
    with pytest.raises(ValueError, match="Habakkuk has 3 chapters"):
        api_reader({"book": ["Habakkuk"], "chapter": ["99"], "verse": ["1"]})


def test_the_reader_takes_a_reference_as_well_as_its_pieces(home: DataHome) -> None:
    """A link carries a reference; the chapter grid carries the pieces it already has."""
    by_ref = api_reader({"ref": ["John 3:16-18"], "corpus": ["english"]})
    assert by_ref["asked"]["usfm"] == "JHN 3:16-18"
    assert [v["n"] for v in version(by_ref, "english")["verses"]] == [16, 17, 18]


# --------------------------------------------------------------------------------------
# Reference, or prose?
# --------------------------------------------------------------------------------------


def test_prose_is_an_answer_rather_than_an_error(home: DataHome) -> None:
    """One box takes either. A 400 here would make every typed character of a quotation an
    error in the console."""
    found = api_parse({"q": ["In the beginning was the Word"]})
    assert found["ok"] is False
    assert found["kind"] == "text"


def test_a_reference_comes_back_ready_to_navigate_to(home: DataHome) -> None:
    found = api_parse({"q": ["John 3:16"]})
    assert (found["ok"], found["kind"], found["usfm"]) == (True, "reference", "JHN 3:16")
    assert (found["book"], found["chapter"], found["verse"], found["single"]) == (
        "JHN",
        3,
        16,
        True,
    )


def test_a_real_book_at_an_impossible_chapter_is_its_own_answer(home: DataHome) -> None:
    """Not prose -- the reader named a real book -- so it carries the library's sentence
    rather than "could not parse"."""
    found = api_parse({"q": ["Habakkuk 99:1"]})
    assert found["kind"] == "unreachable"
    assert found["title"] == "Habakkuk"
    assert "Habakkuk has 3 chapters" in found["error"]


def test_an_ambiguous_name_becomes_a_question(home: DataHome) -> None:
    """ "1 Kings" is 1 Samuel to a Douay reader and 1 Kings to everyone else. This library
    refuses to guess, and the refusal is the most careful distinction it makes -- so it
    becomes something the reader can be asked.

    Titled in modern usage rather than in each scheme, because `book_title("1SA", DR)` is
    "1 Kings" too, and offering both in their own naming shows the same two words twice.
    """
    found = api_parse({"q": ["1 Kings 3:16"], "naming": ["de"]})
    assert found["kind"] == "ambiguous"
    assert {(o["naming"], o["book"], o["title"]) for o in found["options"]} == {
        ("dr", "1SA", "1 Samuel"),
        ("modern", "1KI", "1 Kings"),
        ("lxx", "1KI", "1 Kings"),
    }


def test_the_naming_settles_it_when_it_can(home: DataHome) -> None:
    assert api_parse({"q": ["1 Kings 3:16"], "naming": ["dr"]})["usfm"] == "1SA 3:16"
    assert api_parse({"q": ["1 Kings 3:16"]})["usfm"] == "1KI 3:16"


def test_an_empty_box_is_neither(home: DataHome) -> None:
    assert api_parse({"q": ["   "]})["kind"] == "empty"
    assert api_parse({})["kind"] == "empty"
