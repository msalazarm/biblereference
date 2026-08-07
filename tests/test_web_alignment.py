"""Why a mapping is where it is, as the numbering screen asks it.

These run against the shipped versification data and need no corpus, which is the point:
the alignment is a property of the tables, not of what happens to be built. The five
passages here are the ones the browsing page has recommended since it was written, and each
one now has to explain itself as well as answer.
"""

from __future__ import annotations

import pytest

from biblereference.versification import corrections
from biblereference.web.alignment import api_alignment, api_corrections


def row(payload: dict, system: str) -> dict:  # type: ignore[type-arg]
    (found,) = [r for r in payload["systems"] if r["system"] == system]
    return found  # type: ignore[no-any-return]


def reasons(payload: dict, system: str) -> str:  # type: ignore[type-arg]
    return "\n".join(why["reason"] for why in row(payload, system)["why"])


# --------------------------------------------------------------------------------------
# Exact beside covering
# --------------------------------------------------------------------------------------


def test_a_verse_carrying_two_says_so_under_covering() -> None:
    """The Douay's Matthew 17:14 holds what the Greek numbers 14 and 15. Exact names the
    one it most *is*; covering names every verse it needs."""
    found = api_alignment({"ref": ["Matt 17:14"], "vrs": ["vul"]})
    assert row(found, "org")["exact"]["ref"] == "Matthew 17:15"
    assert row(found, "org")["covering"]["ref"] == "Matthew 17:14-15"
    assert row(found, "org")["differs"] is True
    # And its own system does not differ from itself.
    assert row(found, "vul")["differs"] is False


def test_a_cover_that_crosses_a_chapter_boundary() -> None:
    """The only one in the file, and the reason covers are a list rather than a range."""
    found = api_alignment({"ref": ["1Sam 20:42"], "vrs": ["eng"]})
    assert row(found, "org")["exact"]["ref"] == "1 Samuel 21:1"
    assert row(found, "org")["covering"]["ref"] == "1 Samuel 20:42, 1 Samuel 21:1"
    assert "chapter boundary" in reasons(found, "org")


def test_a_verse_that_moves_to_another_book() -> None:
    found = api_alignment({"ref": ["Bar 6:43"], "vrs": ["eng"]})
    assert row(found, "org")["exact"]["ref"] == "Letter of Jeremiah 1:42"
    assert row(found, "org")["covering"]["ref"] == "Letter of Jeremiah 1:42-43"
    assert "the whole covering mode exists for" in reasons(found, "org")


def test_a_verse_the_greek_moved_to_the_end() -> None:
    """Malachi 3:22 is 4:4 in English and 3:24 in the Septuagint, and the correction that
    put it there records that a monotonic alignment could not have found it."""
    found = api_alignment({"ref": ["Mal 3:22"], "vrs": ["org"]})
    assert row(found, "eng")["exact"]["ref"] == "Malachi 4:4"
    assert row(found, "lxx")["exact"]["ref"] == "Malachi 3:24"
    assert "jump forward" in reasons(found, "lxx")


def test_a_text_type_variant_is_a_mapping_not_a_gap() -> None:
    """The Clementine puts the meek before those who mourn. Different words under the same
    number, which is a fact about the Latin tradition rather than about its numbering --
    and the recorded reason is where that distinction is kept."""
    found = api_alignment({"ref": ["Matt 5:4"], "vrs": ["vul"]})
    assert row(found, "org")["exact"]["ref"] == "Matthew 5:5"
    assert "Beati mites" in reasons(found, "vul")


# --------------------------------------------------------------------------------------
# Why
# --------------------------------------------------------------------------------------


def test_a_refusal_is_carried_through_as_its_own_sentence() -> None:
    """Every VersificationError here is written for a person to read. Flattening one to a
    null would replace the most informative thing on the screen with a dash."""
    found = api_alignment({"ref": ["Ps 151:1"], "vrs": ["lxx"]})
    refusals = [r["exact"]["refused"] for r in found["systems"] if "refused" in r["exact"]]
    assert refusals, "no system refuses Psalm 151, so this test is testing nothing"
    assert all(len(text.split()) > 3 for text in refusals)


def test_the_reasons_come_from_both_ends_of_the_mapping() -> None:
    """A verse can be moved by a correction to the system it came from or by one to the
    system it is going to, and a screen showing only one half explains half the cases."""
    found = api_alignment({"ref": ["Matt 17:14"], "vrs": ["vul"]})
    assert {why["system"] for why in row(found, "org")["why"]} == {"vul"}

    onwards = api_alignment({"ref": ["Mal 3:22"], "vrs": ["org"]})
    assert "lxx" in {why["system"] for why in row(onwards, "lxx")["why"]}


def test_a_reason_is_not_repeated_within_a_row() -> None:
    """A ranged correction covers many verses and would otherwise come back once per verse
    of the range -- sixty-three times, for the Greek Daniel."""
    found = api_alignment({"ref": ["Dan 13:1-63"], "vrs": ["vul"]})
    for system in found["systems"]:
        keys = [(why["system"], why["kind"], why["key"]) for why in system["why"]]
        assert len(keys) == len(set(keys)), system["system"]


def test_an_unknown_target_is_refused_rather_than_skipped() -> None:
    with pytest.raises(ValueError, match="nonesuch"):
        api_alignment({"ref": ["John 3:16"], "to": ["nonesuch"]})


def test_a_book_the_target_system_has_no_place_for_says_so() -> None:
    """`convert_range` falls back to the identity where neither system maps a book, and the
    fallback does not check that the target *has* it: `org` 1 Enoch 1:1 converts to `nvl`
    1 Enoch 1:1, and the Nova Vulgata declares no 1 Enoch.

    2,384 conversions do this, across 90 (source, target, book) triples. The pivot holds
    every one of the books involved, which is why the coverage walk -- whose ghost check is
    against the pivot -- reports none of them. Recorded in TODO.md as its own question;
    what is pinned here is only that the screen says it rather than raising, because
    `expand` on the result does raise and a 500 is the wrong way to learn this.
    """
    found = api_alignment({"ref": ["Ps 151:1"], "vrs": ["lxx"]})
    assert "Additional Psalms is not a book of 'nvl'" in row(found, "nvl")["exact"]["refused"]
    assert row(found, "org")["exact"]["ref"] == "Additional Psalms 1:1"


# --------------------------------------------------------------------------------------
# Browsing them
# --------------------------------------------------------------------------------------


def test_everything_recorded_is_reachable_through_the_endpoint() -> None:
    everything = api_corrections({})
    assert everything["total"] == len(corrections().all())
    assert sum(everything["kinds"].values()) == everything["total"]


def test_the_one_key_upstream_cannot_parse_is_reported_not_hidden() -> None:
    """It is in the file on purpose -- `_apply_corrections` pops it by string identity and
    never parses it -- so the honest thing is to say so on the screen."""
    assert api_corrections({})["malformed"] == [
        {"system": "vul", "kind": "drop_mapped", "key": "DAG 3:52-23"}
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"kind": ["covers"]}, {"covers"}),
        ({"kind": ["covers,add_mapped"]}, {"covers", "add_mapped"}),
    ],
)
def test_filtering_by_kind(query: dict[str, list[str]], expected: set[str]) -> None:
    found = api_corrections(query)
    assert set(found["kinds"]) == expected
    assert all(c["kind"] in expected for c in found["corrections"])


def test_narrowing_by_system_then_book_then_verse() -> None:
    system = api_corrections({"system": ["vul"]})
    book = api_corrections({"system": ["vul"], "book": ["Daniel (Greek)"]})
    verse = api_corrections(
        {"system": ["vul"], "book": ["Matthew"], "chapter": ["17"], "verse": ["14"]}
    )

    assert all(c["system"] == "vul" for c in system["corrections"])
    assert 0 < book["total"] < system["total"]
    assert {(c["kind"], c["key"]) for c in verse["corrections"]} == {
        ("add_mapped", "MAT 17:14"),
        ("covers", "MAT 17:14"),
    }


def test_every_correction_carries_its_prose() -> None:
    """The point of the whole endpoint. A row with no reason is a row that cannot be
    checked by anybody who was not there when it was written."""
    for correction in api_corrections({})["corrections"]:
        assert correction["reason"].strip(), correction["key"]
