"""Esther's Greek additions, cited by letter.

The NRSV and the NABRE letter the six additions A to F and print each where the Greek
puts it; editions following the Vulgate append them all to the end of the book as
chapters 10:4 to 16:24. Both name the same text. This module resolves a letter citation
into Vulgate numbering, which is what the Douay-Rheims -- the corpus that carries the
additions -- is numbered in.

The table lives in ``data/esther_additions.json``, where each row records how it was
checked against the text. The Septuagint's own numbering, which interleaves the additions
as sub-verses, is deliberately not reconciled: see that file for why.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

from ..refs import ADDITION_LETTERS, VerseRef

__all__ = ["Addition", "additions", "letter_to_vulgate", "vulgate_to_letter"]


@dataclass(frozen=True, slots=True)
class Addition:
    """One of Esther's six Greek additions."""

    letter: str
    title: str
    first_letter_verse: int
    last_letter_verse: int
    start: tuple[int, int]
    """Its first verse in Vulgate numbering, as ``(chapter, verse)``."""
    end: tuple[int, int]
    """Its last verse in Vulgate numbering."""

    @property
    def length(self) -> int:
        return self.last_letter_verse - self.first_letter_verse + 1


@cache
def additions() -> dict[str, Addition]:
    """The six additions, keyed by letter."""
    path = resources.files(__package__).joinpath("data", "esther_additions.json")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    out: dict[str, Addition] = {}
    for letter, entry in data["additions"].items():
        first, last = entry["letters"]
        out[letter] = Addition(
            letter=letter,
            title=entry["title"],
            first_letter_verse=first,
            last_letter_verse=last,
            start=tuple(entry["vulgate"]["from"]),  # type: ignore[arg-type]
            end=tuple(entry["vulgate"]["to"]),  # type: ignore[arg-type]
        )

    missing = set(ADDITION_LETTERS) - set(out)
    if missing:
        raise ValueError(f"esther_additions.json is missing addition(s) {sorted(missing)}")
    return out


def _vulgate_verses(addition: Addition) -> list[tuple[int, int]]:
    """Every Vulgate verse of an addition, in order.

    An addition may span a chapter boundary -- A runs from 11:2 to 12:6 -- so this walks
    the chapters between its ends. The chapter lengths come from the versification data
    rather than being written down twice.
    """
    from . import Versification

    versification = Versification.load()
    (first_chapter, first_verse), (last_chapter, last_verse) = addition.start, addition.end

    out: list[tuple[int, int]] = []
    for chapter in range(first_chapter, last_chapter + 1):
        low = first_verse if chapter == first_chapter else 1
        high = (
            last_verse
            if chapter == last_chapter
            else versification.max_verse("vul", "EST", chapter)
        )
        out.extend((chapter, verse) for verse in range(low, high + 1))

    if len(out) != addition.length:
        raise ValueError(
            f"Esther addition {addition.letter} covers {addition.length} lettered verses "
            f"but {len(out)} Vulgate verses; esther_additions.json disagrees with the "
            f"Vulgate chapter lengths in corrections.json"
        )
    return out


def letter_to_vulgate(ref: VerseRef) -> VerseRef:
    """Convert ``Est C:12`` into the Vulgate's numbering.

    :raises ValueError: the letter is not one of A-F, or the verse is outside it.
    """
    if not ref.is_letter_chapter:
        raise ValueError(f"{ref} is not a letter-chapter reference")

    addition = additions()[str(ref.chapter)]
    if not addition.first_letter_verse <= ref.verse <= addition.last_letter_verse:
        raise ValueError(
            f"Esther {addition.letter}:{ref.verse} does not exist: addition "
            f"{addition.letter} ({addition.title}) has verses "
            f"{addition.first_letter_verse}-{addition.last_letter_verse}"
        )

    chapter, verse = _vulgate_verses(addition)[ref.verse - addition.first_letter_verse]
    return VerseRef(book="EST", chapter=chapter, verse=verse, vrs="vul")


def vulgate_to_letter(ref: VerseRef) -> VerseRef | None:
    """Convert a Vulgate Esther reference into its letter form, if it has one.

    Returns ``None`` for the Hebrew portion of the book, which is cited by chapter and
    verse in every tradition, and for the three-verse Vulgate doublet at 15:1-3.
    """
    if ref.book != "EST" or ref.is_letter_chapter:
        return None
    for addition in additions().values():
        for index, (chapter, verse) in enumerate(_vulgate_verses(addition)):
            if (chapter, verse) == (ref.chapter, ref.verse):
                return VerseRef(
                    book="EST",
                    chapter=addition.letter,
                    verse=addition.first_letter_verse + index,
                    vrs="vul",
                )
    return None


#: Where the additions begin, for error messages that need to say what exists.
SUMMARY: Final = (
    "Esther's Greek additions are cited either by letter (A:1-17, B:1-7, C:1-30, "
    "D:1-16, E:1-24, F:1-11) or in Vulgate numbering (10:4-16:24)."
)
