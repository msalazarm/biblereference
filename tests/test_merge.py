"""Merging cited ranges into a register.

A treatise quotes the same passage in pieces as the argument needs it. The register at the
back should show each passage once, whole.
"""

from __future__ import annotations

import pytest

from biblereference.refs import parse_reference
from biblereference.versification import Versification


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def merge(vrs: Versification, *texts: str, system: str = "eng") -> str:
    spans = [parse_reference(t, vrs=system) for t in texts]
    return ", ".join(s.pretty() for s in vrs.merge(spans))


def test_the_pieces_of_one_passage_become_one_entry(vrs: Versification) -> None:
    """Cited as 2:7, then 2:4, then 2:1-6, across an argument."""
    assert merge(vrs, "1 Tim 2:7", "1 Tim 2:4", "1 Tim 2:1-6") == "1 Timothy 2:1-7"


def test_overlapping_ranges_join(vrs: Versification) -> None:
    assert merge(vrs, "Rom 8:1-5", "Rom 8:3-9") == "Romans 8:1-9"


def test_a_contained_range_disappears_into_its_container(vrs: Versification) -> None:
    assert merge(vrs, "Rom 8:1-9", "Rom 8:3-4") == "Romans 8:1-9"


def test_the_same_verse_twice_is_one_entry(vrs: Versification) -> None:
    assert merge(vrs, "Rom 8:1", "Rom 8:1") == "Romans 8:1"


def test_adjacent_ranges_join(vrs: Versification) -> None:
    """2:1-6 and 2:7 are one passage with a seam, not two passages."""
    assert merge(vrs, "Rom 8:1-3", "Rom 8:4-6") == "Romans 8:1-6"


def test_a_gap_is_not_bridged(vrs: Versification) -> None:
    assert merge(vrs, "Rom 8:1-3", "Rom 8:6-8") == "Romans 8:1-3, Romans 8:6-8"


def test_ranges_join_across_a_chapter_boundary(vrs: Versification) -> None:
    """1 Timothy 2 ends at verse 15, so 2:15 and 3:1 are consecutive verses."""
    assert vrs.max_verse("eng", "1TI", 2) == 15
    assert merge(vrs, "1 Tim 2:15", "1 Tim 3:1") == "1 Timothy 2:15-3:1"


def test_a_chapter_boundary_is_not_bridged_from_the_wrong_verse(vrs: Versification) -> None:
    assert merge(vrs, "1 Tim 2:14", "1 Tim 3:1") == "1 Timothy 2:14, 1 Timothy 3:1"


def test_different_books_never_join_and_come_back_in_reading_order(
    vrs: Versification,
) -> None:
    out = merge(vrs, "Rev 22:21", "Gen 1:1", "Sir 24:1")
    assert out == "Genesis 1:1, Sirach 24:1, Revelation 22:21"


def test_versifications_are_merged_within_but_never_across(vrs: Versification) -> None:
    """They are different coordinate systems; joining them would mean nothing."""
    spans = [parse_reference("Ps 23:1", vrs="eng"), parse_reference("Ps 23:1", vrs="vul")]
    merged = vrs.merge(spans)
    assert len(merged) == 2
    assert {s.vrs for s in merged} == {"eng", "vul"}


def test_letter_chapters_resolve_before_merging(vrs: Versification) -> None:
    """Esther C:1 and Vulgate Esther 13:8 are the same verse under two citations."""
    spans = [parse_reference("Est C:1"), parse_reference("Est 13:8", vrs="vul")]
    assert len(vrs.merge(spans)) == 1


def test_merging_nothing_gives_nothing(vrs: Versification) -> None:
    assert vrs.merge([]) == []
