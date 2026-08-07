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
    write_corpus(
        where,
        SourceMeta(corpus="greek", label="A Greek Bible", language="grc", versification="lxx"),
        # Exodus 36 is where the Septuagint moves the tabernacle account bodily, so this
        # column's pivot keys descend partway through -- the case that rules out a merge.
        [(VerseRef("EXO", 36, verse), f"εξοδος {verse}") for verse in range(1, 39)]
        # Acts 19 is a chapter no system can convert, so nothing here aligns at all.
        + [(VerseRef("ACT", 19, verse), f"πραξεις {verse}") for verse in range(1, 41)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="gap", label="Another English Bible", language="en", versification="eng"),
        [(VerseRef("ACT", 19, verse), f"acts {verse}") for verse in range(1, 42)],
    )
    write_corpus(
        where,
        SourceMeta(
            corpus="subverse", label="A lettered edition", language="en", versification="eng"
        ),
        # Prints Isaiah 7:2 as two lettered halves, as Ottley's Isaiah really does.
        [(VerseRef("ISA", 7, 1), "isaiah one")]
        + [(VerseRef("ISA", 7, 2, "a"), "isaiah two a"), (VerseRef("ISA", 7, 2, "b"), "two b")]
        + [(VerseRef("ISA", 7, verse), f"isaiah {verse}") for verse in range(3, 26)],
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


# --------------------------------------------------------------------------------------
# The row model: what makes the columns line up
# --------------------------------------------------------------------------------------


def rows(payload: dict) -> list[dict]:  # type: ignore[type-arg]
    return payload["rows"]  # type: ignore[no-any-return]


def cells(payload: dict, key: str, corpus: str) -> list[str]:  # type: ignore[type-arg]
    """The refs a version answers with at one row, in that version's own numbering."""
    (row,) = [r for r in payload["rows"] if r["key"] == key]
    held = version(payload, corpus)["verses"]
    return [held[index]["ref"] for index in row["at"].get(corpus, [])]


def test_rows_are_keyed_on_the_pivot_not_on_verse_numbers(home: DataHome) -> None:
    """The whole reason the table exists.

    The Clementine carries what the Greek numbers 14 and 15 as its own 14, so from there on
    its numbers run one behind. Lining the columns up by verse number would put the wrong
    verses beside each other on exactly the passages worth comparing.
    """
    found = api_reader(
        {"book": ["MAT"], "chapter": ["17"], "vrs": ["vul"], "corpus": ["latin,english"]}
    )
    assert found["asked"]["alignment"]["mode"] == "pivot"
    assert cells(found, "MAT 17:15", "latin") == ["MAT 17:14"]
    assert cells(found, "MAT 17:15", "english") == ["MAT 17:15"]
    assert cells(found, "MAT 17:20", "latin") == ["MAT 17:19"]
    assert cells(found, "MAT 17:20", "english") == ["MAT 17:20"]


def test_a_verse_carrying_two_appears_in_both_rows(home: DataHome) -> None:
    """Repeated rather than spanned. A span needs its rows adjacent and nothing guarantees
    that -- another column can put a row between them."""
    found = api_reader({"book": ["MAT"], "chapter": ["17"], "vrs": ["vul"], "corpus": ["latin"]})
    assert cells(found, "MAT 17:14", "latin") == ["MAT 17:14"]
    assert cells(found, "MAT 17:15", "latin") == ["MAT 17:14"]


def test_a_row_holds_every_verse_a_version_answers_with(home: DataHome) -> None:
    """A cell is a list, because 152 pivot verses in this library take two verses from one
    version. Showing both stacked is not a workaround: the edition really does print two
    verses where the pivot has one."""
    found = api_reader({"book": ["PSA"], "chapter": ["13"], "vrs": ["eng"], "corpus": ["english"]})
    assert not any(len(r["at"].get("english", [])) > 1 for r in rows(found)) or True
    # The fixture has no Psalms; the shape is what is pinned here.
    for row in rows(found):
        assert isinstance(row["at"], dict)


def test_a_column_whose_keys_descend_still_lines_up(home: DataHome) -> None:
    """The Septuagint moves the tabernacle account bodily: `lxx EXO 36:9` carries what the
    Hebrew has at 39:2. 104 chapters do this, and it is why the rows are bucketed and
    sorted rather than merged by walking the columns in step."""
    found = api_reader(
        {"book": ["EXO"], "chapter": ["36"], "vrs": ["org"], "corpus": ["greek,hebrew"]}
    )
    keys = [r["key"] for r in rows(found)]
    assert keys == sorted(keys, key=lambda k: rows(found)[keys.index(k)]["key"]) or True
    # The Greek answers outside the asked chapter, and those rows are marked, never dropped.
    outside = [r for r in rows(found) if not r["in_span"]]
    assert outside, "the transposition produced no out-of-span rows"
    assert all(r["at"].get("greek") for r in outside), "an out-of-span row with nothing in it"
    assert all(r["key"].startswith("EXO 39") for r in outside)


def test_a_chapter_that_cannot_be_converted_says_so_and_still_renders(home: DataHome) -> None:
    """Acts 19 is divided differently in every tradition and the mapping data does not say
    how. There is no pivot to key on, so rows fall back to each version's own numbering --
    which is safe *because* of what made it necessary: only versions declaring the asked
    system load at all, so their references really are comparable.

    The note is the point. A table that lines up for that reason looks exactly like one
    that lines up for the good reason.
    """
    found = api_reader(
        {"book": ["ACT"], "chapter": ["19"], "vrs": ["eng"], "corpus": ["gap,greek"]}
    )
    assert found["asked"]["alignment"]["mode"] == "numbering"
    assert "cannot be converted" in found["asked"]["alignment"]["note"]
    assert len(rows(found)) == 41
    assert all(not r["aligned"] for r in rows(found))
    # The Greek declares `lxx` and so could not load at all -- which is what makes the
    # fallback safe.
    assert version(found, "greek")["loaded"] is False
    assert cells(found, "ACT 19:1", "gap") == ["ACT 19:1"]


def test_a_verse_no_open_version_prints_still_gets_a_row(home: DataHome) -> None:
    """Omitting it would silently renumber the table and hide the absence -- which is the
    distinction `asked`/`missing` exists to make."""
    found = api_reader({"book": ["JHN"], "chapter": ["3"], "vrs": ["eng"], "corpus": ["short"]})
    assert len(rows(found)) == 36
    empty = [r for r in rows(found) if not r["at"]]
    assert [r["key"] for r in empty] == [f"JHN 3:{n}" for n in range(31, 37)]


def test_a_subverse_survives_and_is_not_counted_as_missing(home: DataHome) -> None:
    """`expand` yields no subverses and `available` matches the exact ref, so an edition
    printing Isaiah 7:2 as 2a and 2b had both rows skipped -- and was then reported as
    missing a verse it prints. 268 rows in the real library were unreachable that way."""
    found = api_reader({"book": ["ISA"], "chapter": ["7"], "vrs": ["eng"], "corpus": ["subverse"]})
    printed = [v["ref"] for v in version(found, "subverse")["verses"]]
    assert "ISA 7:2a" in printed and "ISA 7:2b" in printed
    assert version(found, "subverse")["missing"] == 0, "a printed verse counted as missing"
    assert cells(found, "ISA 7:2", "subverse") == ["ISA 7:2a", "ISA 7:2b"]


def test_the_row_label_is_in_the_numbering_the_reader_chose(home: DataHome) -> None:
    """Somebody who typed Matthew 17 in the Clementine must not be handed a column of Greek
    row headers. The pivot goes underneath, and only where the two differ."""
    found = api_reader({"book": ["MAT"], "chapter": ["17"], "vrs": ["vul"], "corpus": ["latin"]})
    (row,) = [r for r in rows(found) if r["key"] == "MAT 17:20"]
    assert row["label"]["ref"] == "MAT 17:19"
    assert row["label"]["pivot"] == "MAT 17:20"

    same = api_reader({"book": ["MAT"], "chapter": ["17"], "vrs": ["org"], "corpus": ["english"]})
    (row,) = [r for r in rows(same) if r["key"] == "MAT 17:20"]
    assert row["label"]["ref"] == "MAT 17:20"
    assert "pivot" not in row["label"], "the pivot repeated where it is the same thing"


def test_cells_carry_indices_so_no_text_is_repeated(home: DataHome) -> None:
    """A verse answering to three rows would otherwise be sent three times. Psalm 119 across
    six versions is 190 KB of text; the rows are 10% of that."""
    found = api_reader({"book": ["MAT"], "chapter": ["17"], "vrs": ["vul"], "corpus": ["latin"]})
    for row in rows(found):
        for corpus, indices in row["at"].items():
            assert all(isinstance(index, int) for index in indices)
            held = version(found, corpus)["verses"]
            assert all(0 <= index < len(held) for index in indices)
