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
    AmbiguousBookError,
    NamingScheme,
    UnknownBookError,
    book_title,
    canonical_order,
    resolve_book,
)

__all__ = [
    "ReferenceParseError",
    "VerseRange",
    "VerseRef",
    "parse_reference",
    "parse_references",
    "roman_to_arabic",
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

    def sort_key(self) -> tuple[int, int, int, int, str]:
        """Where a reader meets this verse: canon order, then chapter, verse, subverse.

        Public because sorting references is not only this class's own business. The
        comparison reader keys its rows on pivot references drawn from several versions at
        once and has to put them in reading order, and those references cross books --
        ``BAR 6:43`` answers to ``LJE 1:42`` -- so comparing the USFM strings would put
        ``1SA`` before ``GEN``. One ordering, here, rather than a second one that drifts.
        """
        # Letter chapters sort after numbered ones within a book, which matches how
        # editions that use them print the additions.
        if isinstance(self.chapter, str):
            chapter_key = (1, ADDITION_LETTERS.index(self.chapter))
        else:
            chapter_key = (0, self.chapter)
        return (canonical_order(self.book), *chapter_key, self.verse, self.subverse)

    #: The old private spelling, kept so nothing in the tree has to change at once.
    _sort_key = sort_key

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, VerseRef):
            return NotImplemented
        return self.sort_key() < other.sort_key()

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

#: A tail that is nothing but a chapter number, for ``allow_chapter``.
_CHAPTER_ONLY_RE: Final = re.compile(r"\d{1,3}")

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
    allow_chapter: bool = False,
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
    :param allow_chapter: Read a bare chapter -- ``"1 Cor 15"`` -- as the whole of it,
        expanded to the verses the versification says it holds. Off by default, because a
        chapter with no verse is a mistake in this library's own tag syntax; on for reading
        somebody else's footnotes, where ``1 Cor. xv`` is how an editor cites a chapter.
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
        if allow_chapter:
            return _whole_chapter(book, match.group("rest").strip(), vrs, text)
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


def _whole_chapter(book: str, rest: str, vrs: str, text: str) -> VerseRange:
    """``1 Cor 15`` as the range of verses that chapter actually holds.

    Expanded to its verses rather than left open-ended, so that every existing consumer of
    a :class:`VerseRange` keeps working and the range is exact rather than a promise. The
    count comes from the versification, which is also what makes ``Ps 200`` an error rather
    than an empty range.
    """
    if not _CHAPTER_ONLY_RE.fullmatch(rest):
        raise ReferenceParseError(f"could not parse reference: {text!r}")

    # Deferred: versification imports this module, so importing it at the top would be a
    # cycle. Only a whole-chapter reference needs to know how long a chapter is.
    from .versification import Versification

    chapter = int(rest)
    vrs_data = Versification.load()
    last = vrs_data.max_verse(vrs, book, chapter)
    # max(..., 1) because the Psalms model a superscription as verse 0, and a citation of
    # the whole psalm means its text rather than its title.
    first = max(vrs_data.first_verse(vrs, book, chapter), 1)
    return VerseRange(
        VerseRef(book, chapter, first, vrs=vrs), VerseRef(book, chapter, last, vrs=vrs)
    )


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


# --------------------------------------------------------------------------------------
# The forms printed editions actually use
# --------------------------------------------------------------------------------------

_ROMAN: Final[dict[str, int]] = {
    "i": 1,
    "v": 5,
    "x": 10,
    "l": 50,
    "c": 100,
    "d": 500,
    "m": 1000,
}

#: A chapter as a lower-case roman numeral between periods: ``1 Tim. iii. 16``. The book
#: may itself begin with a numeral, which is why the book group allows a leading digit.
#: Lower case matters -- it is the convention in this position, and it usefully separates a
#: numeral from a book name that happens to be spelled with the same letters.
_ROMAN_REF_RE: Final = re.compile(
    r"""^\s*
    (?P<book>(?:[1-4]\s*)?[A-Za-z][A-Za-z.\s]*?)
    \s*\.?\s+
    (?P<chapter>[ivxlcdm]+)
    (?:\s*\.\s*(?P<verses>[\d,\s–-]+))?
    \s*\.?\s*$
    """,
    re.VERBOSE,
)

#: Chapter and verse in arabic with a period between them: ``Psa. 3.1``, ``2 Chron. 6.42``.
#: Tried last, because a period is also a sentence stop and ``Psa. 3.`` alone must not
#: become ``PSA 3:1``.
_DOTTED_REF_RE: Final = re.compile(
    r"^\s*(?P<book>(?:[1-4]\s*)?[A-Za-z][A-Za-z.\s]*?)\s*\.?\s+(?P<chapter>\d+)"
    r"\s*\.\s*(?P<verses>[\d,\s–-]+)\s*$"
)

#: ``Rom 1:21, 22`` -- one reference naming several verses of one chapter.
_VERSE_LIST_RE: Final = re.compile(
    r"^\s*(?P<head>.*?[:.]\s*\d+[a-z]?)\s*,\s*(?P<tail>[\d,\s–-]+?)\s*$"
)


def roman_to_arabic(text: str) -> int | None:
    """Read a roman numeral, or ``None`` where the text is not one."""
    lowered = text.strip().lower()
    if not lowered or any(character not in _ROMAN for character in lowered):
        return None
    total = 0
    highest = 0
    for character in reversed(lowered):
        value = _ROMAN[character]
        total += -value if value < highest else value
        highest = max(highest, value)
    return total or None


def parse_references(
    text: str,
    *,
    vrs: str = "eng",
    naming: NamingScheme = NamingScheme.MODERN,
    allow_chapter: bool = False,
) -> list[VerseRange]:
    """Every passage a reference string names, in the forms printed editions use.

    :func:`parse_reference` reads the form a modern writer types. It does not read the forms
    nineteenth-century editions print, which is most of what any historical corpus contains:
    verse lists, semicolon-separated references, roman-numeral chapters, and chapters
    separated from their verse by a period. Of 43,963 editor-tagged references in a patristic
    corpus, 15,706 -- 36% -- are one of those four, and none of them is patristics-specific.
    Anyone reading Spurgeon, Wesley, Newman or the Puritans meets the same set.

    A cascade, unambiguous forms first:

    1. split on ``;`` and recurse, since one tag routinely holds several citations
    2. :func:`parse_reference` unchanged -- most input is ordinary and this is the fast path
    3. a verse list, ``Rom. i. 21, 22``, which is two verses where ``21-22`` is one range
    4. a roman-numeral chapter, ``1 Tim. iii. 16``
    5. a dotted chapter, ``Psa. 3.1``, last because a period is also a sentence stop

    :raises ReferenceParseError: nothing in the string could be read as a reference. An
        unreadable string raises rather than returning empty, so a caller cannot mistake
        "could not read this" for "names no passages".
    """
    found = _references(text, vrs=vrs, naming=naming, allow_chapter=allow_chapter)
    if not found:
        raise ReferenceParseError(f"could not parse reference: {text!r}")
    return found


def _references(
    text: str, *, vrs: str, naming: NamingScheme, allow_chapter: bool
) -> list[VerseRange]:
    """The cascade itself, returning ``[]`` rather than raising so it can recurse."""
    stripped = text.strip()
    if not stripped:
        return []

    if ";" in stripped:
        out: list[VerseRange] = []
        for part in stripped.split(";"):
            out.extend(_references(part, vrs=vrs, naming=naming, allow_chapter=allow_chapter))
        return out

    # Trailing sentence stop, which an editor's footnote carries and a reference does not.
    trimmed = stripped.rstrip(".").strip()

    for reader in (_plain, _verse_list, _roman_chapter, _dotted_chapter):
        got = reader(trimmed, vrs, naming, allow_chapter)
        if got:
            return got
    return []


def _try(text: str, vrs: str, naming: NamingScheme, allow_chapter: bool) -> list[VerseRange]:
    try:
        return [parse_reference(text, vrs=vrs, naming=naming, allow_chapter=allow_chapter)]
    except (ReferenceParseError, UnknownBookError, AmbiguousBookError, ValueError):
        return []


def _plain(text: str, vrs: str, naming: NamingScheme, allow_chapter: bool) -> list[VerseRange]:
    """An ordinary modern citation, which :func:`parse_reference` reads unaided."""
    return _try(text, vrs, naming, allow_chapter)


def _verse_list(text: str, vrs: str, naming: NamingScheme, allow_chapter: bool) -> list[VerseRange]:
    """``Rom 1:21, 22`` -- several verses of one chapter, one range each.

    Note that ``21, 22`` is two verses and ``21-22`` is one range. Both occur, and an editor
    means something slightly different by each: the list is two citations and the range is
    one passage.
    """
    match = _VERSE_LIST_RE.match(text)
    if match is None or ":" not in match.group("head"):
        # Only the modern form is handled here. A roman or dotted reference also lists its
        # verses with commas -- "Rom. i. 21, 22" -- but its own reader captures the whole
        # list and _spread splits it, so intercepting here would take the head and drop the
        # tail.
        return []

    head = _references(match.group("head"), vrs=vrs, naming=naming, allow_chapter=allow_chapter)
    if not head:
        return []

    prefix = match.group("head").rsplit(":", 1)[0]
    out = list(head)
    for piece in match.group("tail").split(","):
        piece = piece.strip()
        if piece:
            out.extend(
                _references(f"{prefix}:{piece}", vrs=vrs, naming=naming, allow_chapter=False)
            )
    return out


def _roman_chapter(
    text: str, vrs: str, naming: NamingScheme, allow_chapter: bool
) -> list[VerseRange]:
    """``1 Tim. iii. 16`` -- the form Schaff and his contemporaries print."""
    match = _ROMAN_REF_RE.match(text)
    if match is None:
        return []
    chapter = roman_to_arabic(match.group("chapter"))
    if chapter is None:
        return []
    return _spread(match.group("book"), chapter, match.group("verses"), vrs, naming, allow_chapter)


def _dotted_chapter(
    text: str, vrs: str, naming: NamingScheme, allow_chapter: bool
) -> list[VerseRange]:
    """``Psa. 3.1`` -- arabic chapter, period before the verse."""
    match = _DOTTED_REF_RE.match(text)
    if match is None:
        return []
    return _spread(
        match.group("book"),
        int(match.group("chapter")),
        match.group("verses"),
        vrs,
        naming,
        allow_chapter,
    )


def _spread(
    book: str,
    chapter: int,
    verses: str | None,
    vrs: str,
    naming: NamingScheme,
    allow_chapter: bool,
) -> list[VerseRange]:
    """One book and chapter over however many verses the reference lists."""
    name = book.strip().rstrip(".").strip()
    if not verses or not verses.strip():
        if allow_chapter:
            return _try(f"{name} {chapter}", vrs, naming, True)
        return []
    out: list[VerseRange] = []
    for piece in verses.split(","):
        piece = piece.strip()
        if piece:
            out.extend(_try(f"{name} {chapter}:{piece}", vrs, naming, False))
    return out
