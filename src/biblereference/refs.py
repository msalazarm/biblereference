"""Verse references: the value objects, and the parser that produces them.

A reference is always tagged with the versification it was written in. ``Daniel 3:24``
is a different verse depending on whether you meant the Vulgate's numbering or the
Hebrew's, so a bare ``(book, chapter, verse)`` triple is not enough information to look
anything up. :class:`VerseRef` therefore carries a ``vrs`` field, and
:mod:`biblereference.versification` is what moves a ref between systems.

Two shapes of chapter exist. Most are integers. Esther's Greek additions are cited in
some editions by letter -- ``Est C:12`` -- so :class:`VerseRef` also accepts a letter
chapter. Sub-verses (``ESG 1:1a``) are likewise first-class, because the Copenhagen
mappings express Esther's additions that way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import total_ordering
from typing import Final

from .canon import (
    SINGLE_CHAPTER_BOOKS,
    NamingScheme,
    book_title,
    canonical_order,
    resolve_book,
)

__all__ = [
    "ReferenceParseError",
    "VerseRange",
    "VerseRef",
    "parse_reference",
]

#: The letters used for Esther's six Greek additions, in the NRSV/NABRE citation style.
ADDITION_LETTERS: Final = ("A", "B", "C", "D", "E", "F")


class ReferenceParseError(ValueError):
    """A reference string could not be parsed."""


@total_ordering
@dataclass(frozen=True, slots=True)
class VerseRef:
    """A single verse, in a stated versification.

    :param book: USFM book code.
    :param chapter: Chapter number, or one of ``A``-``F`` for an Esther addition.
    :param verse: Verse number.
    :param subverse: Sub-verse letter (``"a"``, ``"b"``…) or ``""``.
    :param vrs: The versification this reference is expressed in.
    """

    book: str
    chapter: int | str
    verse: int
    subverse: str = ""
    vrs: str = "eng"

    def __post_init__(self) -> None:
        if isinstance(self.chapter, str):
            if self.chapter not in ADDITION_LETTERS:
                raise ValueError(f"letter chapter must be one of {ADDITION_LETTERS}")
        elif self.chapter < 1:
            raise ValueError(f"chapter must be positive, got {self.chapter}")
        if self.verse < 0:
            raise ValueError(f"verse must be non-negative, got {self.verse}")

    @property
    def is_letter_chapter(self) -> bool:
        """Whether this is an ``Est C:12`` style reference."""
        return isinstance(self.chapter, str)

    def in_vrs(self, vrs: str) -> VerseRef:
        """This same coordinate, relabelled as belonging to ``vrs``.

        This does **not** convert -- it asserts. Use
        :meth:`~biblereference.versification.Versification.convert` to actually move
        between systems.
        """
        return replace(self, vrs=vrs)

    def _sort_key(self) -> tuple[int, int, int, int, str]:
        # Letter chapters sort after numbered ones within a book, which matches how
        # editions that use them print the additions.
        if isinstance(self.chapter, str):
            chapter_key = (1, ADDITION_LETTERS.index(self.chapter))
        else:
            chapter_key = (0, self.chapter)
        return (canonical_order(self.book), *chapter_key, self.verse, self.subverse)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, VerseRef):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __str__(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}{self.subverse}"

    def pretty(self) -> str:
        """Human-readable form, e.g. ``Sirach 24:1``."""
        return f"{book_title(self.book)} {self.chapter}:{self.verse}{self.subverse}"


@dataclass(frozen=True, slots=True)
class VerseRange:
    """An inclusive span of verses within one book.

    A range may cross chapters (``Est 13:8-14:19``) but never books; a citation
    spanning books is parsed as several ranges.
    """

    start: VerseRef
    end: VerseRef

    def __post_init__(self) -> None:
        if self.start.book != self.end.book:
            raise ValueError(f"range crosses books: {self.start} -> {self.end}")
        if self.start.vrs != self.end.vrs:
            raise ValueError(f"range mixes versifications: {self.start.vrs}/{self.end.vrs}")
        if self.end < self.start:
            raise ValueError(f"range ends before it starts: {self.start} -> {self.end}")

    @classmethod
    def single(cls, ref: VerseRef) -> VerseRange:
        """A range covering exactly one verse."""
        return cls(ref, ref)

    @property
    def book(self) -> str:
        return self.start.book

    @property
    def vrs(self) -> str:
        return self.start.vrs

    @property
    def is_single_verse(self) -> bool:
        return self.start == self.end

    def __str__(self) -> str:
        if self.is_single_verse:
            return str(self.start)
        if self.start.chapter == self.end.chapter:
            return f"{self.start}-{self.end.verse}{self.end.subverse}"
        return f"{self.start}-{self.end.chapter}:{self.end.verse}{self.end.subverse}"

    def pretty(self) -> str:
        """Human-readable form, e.g. ``Sirach 24:1-9``."""
        if self.is_single_verse:
            return self.start.pretty()
        if self.start.chapter == self.end.chapter:
            return f"{self.start.pretty()}-{self.end.verse}{self.end.subverse}"
        return f"{self.start.pretty()}-{self.end.chapter}:{self.end.verse}{self.end.subverse}"


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------

# Anchored at the end of the string rather than scanning forward from the book name.
# Scanning forward mis-splits "Bel and the Dragon 1:5" -- the "and" looks like the start
# of a chapter token -- whereas the tail of a reference is unambiguous.
_TAIL_RE: Final = re.compile(
    r"""
    (?P<rest>
        (?:[A-F]|\d+) \s* : \s* \d+ [a-z]?                 # chapter:verse
        (?: \s* [-–—] \s*
            (?: (?:[A-F]|\d+) \s* : \s* )? \d+ [a-z]?      # ...-verse or -chapter:verse
        )?
    )
    \s*$
    """,
    re.VERBOSE,
)

#: Fallback for single-chapter books, where "Jude 5" means Jude 1:5.
_BARE_VERSE_TAIL_RE: Final = re.compile(
    r"(?P<rest>\d+[a-z]? (?:\s*[-–—]\s* \d+[a-z]?)? ) \s*$", re.VERBOSE
)

_CV_RE: Final = re.compile(r"^(?P<chapter>[A-F]|\d+):(?P<verse>\d+)(?P<sub>[a-z]?)$")
_V_RE: Final = re.compile(r"^(?P<verse>\d+)(?P<sub>[a-z]?)$")
_DASH_RE: Final = re.compile(r"\s*[-–—]\s*")


def _parse_chapter(token: str) -> int | str:
    return token.upper() if token.upper() in ADDITION_LETTERS else int(token)


def parse_reference(
    text: str,
    *,
    vrs: str = "eng",
    naming: NamingScheme = NamingScheme.MODERN,
) -> VerseRange:
    """Parse a reference like ``"Luke 2:42"``, ``"Sir 24:1-9"``, or ``"Est C:12-30"``.

    Single-chapter books may drop the chapter: ``"Jude 5"`` is Jude 1:5, and
    ``"Susanna 44-46"`` is Susanna 1:44-46.

    :param text: The reference as written.
    :param vrs: The versification the reference is expressed in.
    :param naming: Which tradition's book names to expect. See
        :class:`~biblereference.canon.NamingScheme`.
    :raises ReferenceParseError: the string is not a reference this can read.
    :raises ~biblereference.canon.UnknownBookError: the book name is unrecognised.
    :raises ~biblereference.canon.AmbiguousBookError: the book name is tradition-dependent
        and ``naming`` does not settle it.
    """
    stripped = text.strip()
    match = _TAIL_RE.search(stripped)
    implicit_chapter = False

    if match is None:
        # No "chapter:verse" tail. Only single-chapter books may omit the chapter; a
        # whole-book reference is an error rather than a silent expansion to the book.
        match = _BARE_VERSE_TAIL_RE.search(stripped)
        if match is None:
            raise ReferenceParseError(f"could not parse reference: {text!r}")
        implicit_chapter = True

    name = stripped[: match.start("rest")].strip()
    if not name:
        raise ReferenceParseError(f"reference is missing a book name: {text!r}")

    book = resolve_book(name, naming)

    if implicit_chapter and book not in SINGLE_CHAPTER_BOOKS:
        raise ReferenceParseError(
            f"{book_title(book)} has more than one chapter, so {text!r} needs a "
            f"chapter:verse reference"
        )

    parts = _DASH_RE.split(match.group("rest").strip())
    tokens = [p.replace(" ", "") for p in parts]

    start = _parse_endpoint(tokens[0], book, vrs, anchor=None, implicit=implicit_chapter)
    if len(tokens) == 1:
        return VerseRange.single(start)
    if len(tokens) != 2:
        raise ReferenceParseError(f"could not parse reference range: {text!r}")

    end = _parse_endpoint(tokens[1], book, vrs, anchor=start, implicit=implicit_chapter)
    try:
        return VerseRange(start, end)
    except ValueError as exc:
        raise ReferenceParseError(f"{exc} (in {text!r})") from None


def _parse_endpoint(
    token: str, book: str, vrs: str, *, anchor: VerseRef | None, implicit: bool
) -> VerseRef:
    """Parse one side of a range.

    ``anchor`` is the start of the range when parsing its end, which is what lets
    ``"24:1-9"`` read the bare ``9`` as chapter 24 verse 9. ``implicit`` marks a
    single-chapter book cited without a chapter, where a bare number is a verse in
    chapter 1.
    """
    cv = _CV_RE.match(token)
    if cv:
        return VerseRef(
            book=book,
            chapter=_parse_chapter(cv.group("chapter")),
            verse=int(cv.group("verse")),
            subverse=cv.group("sub"),
            vrs=vrs,
        )

    v = _V_RE.match(token)
    if v and (anchor is not None or implicit):
        chapter: int | str = 1 if anchor is None else anchor.chapter
        return VerseRef(
            book=book,
            chapter=chapter,
            verse=int(v.group("verse")),
            subverse=v.group("sub"),
            vrs=vrs,
        )

    raise ReferenceParseError(f"could not parse {token!r} as a chapter:verse reference")
