"""Reading back the reasons the mapping corrections were made for.

Two hundred of them sit in ``corrections.json``, every one written by somebody who had just
read the verses, and until now the loader consumed the keys and discarded the prose. These
tests exist for one thing above all: that nothing is lost between the file and the index.
A reason that cannot be reached is a reason nobody will ever see again.

No corpus and no server needed -- this runs anywhere.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from biblereference.versification import (
    AVAILABLE_SYSTEMS,
    Correction,
    Versification,
    corrections,
    fingerprint,
)


def raw() -> dict:
    path = resources.files("biblereference.versification").joinpath("data/corrections.json")
    return json.loads(path.read_text("utf-8"))


def every_reason(node: object) -> list[str]:
    """Walk the file and collect every ``"reason"`` string, however deeply it sits."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "reason" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(every_reason(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(every_reason(item))
    return found


# --------------------------------------------------------------------------------------
# Nothing lost between the file and the index
# --------------------------------------------------------------------------------------


def test_every_reason_written_in_the_file_is_reachable() -> None:
    """The test this module exists for.

    Not a count of corrections -- one reason produces several, because a `drop_mapped`
    entry lists many keys and an `unreliable` entry names several systems and books. The
    invariant is about the prose: every reason in the file must come back out.
    """
    occurrences = every_reason(raw())
    written = set(occurrences)
    indexed = {correction.reason for correction in corrections().all()}

    assert written == indexed, f"unreachable: {sorted(written - indexed)}"
    # 216 written, 211 distinct: five entries share their prose with a sibling, which is
    # what a fix explained once and applied twice looks like.
    #
    # 202 -> 216 on 2026-08-20, and the fourteen are one piece of work: the five rso faults
    # the Slavonic judge run found. Three drops (PRO 18:9-25, PSA 139:0-14, PSA 114:0-8) and
    # eleven mappings to replace them, across Proverbs 18, Psalms 139 and 114, Song 6-7 and
    # the transposed ark formulas at Numbers 10:34-36.
    assert len(occurrences) == 216, "the count moved; add or remove the reason deliberately"
    assert len(written) == 211


def test_every_correction_names_a_system_the_library_knows() -> None:
    known = set(AVAILABLE_SYSTEMS)
    for correction in corrections().all():
        assert correction.system in known, f"{correction.kind} {correction.key}"
        assert correction.reason.strip(), f"{correction.system} {correction.key} has no reason"
        assert correction.scope in {"verse", "chapter", "book", "system"}


def test_the_kinds_are_the_ones_the_loader_applies() -> None:
    """An entry filed under a kind `_build_system` ignores is a correction that does
    nothing, and this is the only place that would notice."""
    assert {c.kind for c in corrections().all()} == {
        "add_books",
        "add_mapped",
        "covers",
        "deprioritize_books",
        "drop_mapped",
        "extend_books",
        "fix_mapped",
        "fix_max_verses",
        "ignore_self_mapped",
        "unreliable",
    }


# --------------------------------------------------------------------------------------
# The one key upstream cannot parse
# --------------------------------------------------------------------------------------


def test_exactly_one_key_is_malformed_and_it_is_the_known_one() -> None:
    """`vul`'s `DAG 3:52-23` is a transposed `3:52-53`, and it is in the file verbatim
    because that is how upstream writes it -- `_apply_corrections` pops it by string
    identity and never parses it, which is why nothing had ever noticed.

    Pinned so that a *new* malformed key fails here rather than quietly losing its reason.
    """
    assert corrections().malformed == (("vul", "drop_mapped", "DAG 3:52-23"),)


def test_the_malformed_key_still_answers_at_its_chapter() -> None:
    """Filed at chapter scope from a lenient match, so the reason is reachable even though
    the range cannot be expanded."""
    found = corrections().at("vul", "DAG", 3, 52)
    assert any(c.key == "DAG 3:52-23" for c in found)
    assert any("transposed" in c.reason for c in found)


# --------------------------------------------------------------------------------------
# Looking one up
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        (("vul", "MAT", 17, 14), {("add_mapped", "MAT 17:14"), ("covers", "MAT 17:14")}),
        (("vul", "DAG", 13, 40), {("fix_mapped", "DAG 13:1-63"), ("deprioritize_books", "DAG")}),
        (("vul", "DAG", 13, 64), {("add_mapped", "DAG 13:64"), ("deprioritize_books", "DAG")}),
        (("vul", "SIR", 18, 1), {("unreliable", "SIR")}),
        (("vul", "SIR", 6, 1), set()),
        (
            ("eng", "BAR", 6, 43),
            {("drop_mapped", "BAR 6:1-73"), ("add_mapped", "BAR 6:2-43"), ("covers", "BAR 6:43")},
        ),
        (("org", "4MA", 12, 20), {("fix_max_verses", "4MA")}),
        (("org", "PS2", 2, 1), {("extend_books", "PS2")}),
    ],
)
def test_a_lookup_finds_what_touches_the_verse(
    where: tuple[str, str, int, int], expected: set[tuple[str, str]]
) -> None:
    found = corrections().at(*where)
    assert {(c.kind, c.key) for c in found} == expected


def test_a_ranged_key_answers_at_every_verse_it_names() -> None:
    """`"DAG 13:1-63"` is one entry covering sixty-three coordinates. A UI asking about
    13:40 has to find it, and asking about 13:64 has to not."""
    inside = corrections().at("vul", "DAG", 13, 40)
    outside = corrections().at("vul", "DAG", 13, 64)
    assert any(c.key == "DAG 13:1-63" for c in inside)
    assert not any(c.key == "DAG 13:1-63" for c in outside)


def test_the_general_refusal_comes_before_the_particular_entry() -> None:
    """Least specific first, so a reader meets "the whole book is deprioritised" above
    "and this verse was remapped"."""
    found = corrections().at("vul", "DAG", 13, 64)
    assert [c.scope for c in found] == ["book", "verse"]


def test_asking_about_a_chapter_leaves_out_the_verse_entries() -> None:
    with_verse = corrections().at("vul", "DAG", 13, 64)
    without = corrections().at("vul", "DAG", 13)
    assert {c.kind for c in without} == {"deprioritize_books"}
    assert len(without) < len(with_verse)


def test_for_book_gathers_every_scope() -> None:
    found = corrections().for_book("vul", "DAG")
    assert {c.scope for c in found} >= {"book", "verse"}
    assert all(c.system == "vul" for c in found)


def test_a_lookup_is_stable_across_calls() -> None:
    """It is `@cache`d, so a caller holding the result must not be able to disturb it."""
    first = corrections().at("vul", "MAT", 17, 14)
    assert first == corrections().at("vul", "MAT", 17, 14)
    assert isinstance(first[0], Correction)


# --------------------------------------------------------------------------------------
# The index and what the loader actually did
# --------------------------------------------------------------------------------------


def test_the_index_and_the_loaded_systems_do_not_drift() -> None:
    """The index is built by reading the file a second time, so it could in principle
    describe corrections `_build_system` never applied. Every book an entry names must be
    one its system actually has -- which is the cheapest check that the two agree.

    Two kinds are exempt, both deliberately. `drop_mapped` names what upstream had, which
    is the point of dropping it. `unreliable` casts wide on purpose: its Esther entry names
    all six systems and `rsc` has no `ESG` at all, and declaring a book unmappable for a
    system that does not have it costs nothing while saving the entry from going stale
    unnoticed if one ever gains it.
    """
    vrs = Versification.load(AVAILABLE_SYSTEMS)
    for correction in corrections().all():
        if correction.scope == "system" or correction.kind in {"drop_mapped", "unreliable"}:
            continue
        book = correction.key.split(" ", 1)[0]
        assert vrs.has_book(correction.system, book), (
            f"{correction.system} {correction.kind} {correction.key}: "
            f"{book} is not a book of {correction.system}"
        )


def test_reading_the_reasons_does_not_move_the_fingerprint() -> None:
    """Nothing about the data files changes; a dependent must not be told to re-derive."""
    before = fingerprint()
    corrections().all()
    assert fingerprint() == before
