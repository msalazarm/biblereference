"""Moving verse references between versification systems.

Hebrew, Greek, Latin and English Bibles do not agree on where verses begin and end.
Psalm 23 in an English Bible is Psalm 22 in the Septuagint and the Vulgate. The Song of
the Three sits inside Daniel 3 in a Catholic Bible and is a separate book in the Hebrew
frame. Citing a verse therefore means nothing until you say which system you are
counting in.

Everything here pivots on ``org``, the Copenhagen Alliance's "original" versification:
the Masoretic frame for the Hebrew canon, the Greek New Testament frame for the NT, and
Catholic numbering for the deuterocanon. A conversion is always two steps --
``source -> org -> target`` -- so adding a system means writing one mapping, not one per
pair.

The vendored upstream data contains a handful of errors that would produce silently wrong
citations. They are corrected at load time from ``data/corrections.json``, which records
what was wrong and how each fix was verified; see also ``data/NOTICE.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

from ..canon import book_title, canonical_order
from ..refs import VerseRange, VerseRef

__all__ = [
    "DEFAULT_SYSTEMS",
    "PIVOT",
    "UnknownVersificationError",
    "VerseOutOfRangeError",
    "Versification",
    "VersificationDataError",
    "VersificationError",
    "VersificationGapError",
    "fingerprint",
]

#: The versification everything converts through.
PIVOT: Final = "org"

#: Systems loaded by default: the pivot, plus the ones this library's corpora use.
#: ``rsc`` and ``rso`` (Russian Synodal, Catholic and Orthodox) are vendored and can be
#: passed to :meth:`Versification.load`, but they carry unresolved conflicts of their own
#: in the Psalms and are not needed for a Hebrew/Greek/Latin/English workflow.
DEFAULT_SYSTEMS: Final = ("org", "eng", "lxx", "vul", "nvl")

#: Everything available, including the systems not loaded by default.
AVAILABLE_SYSTEMS: Final = ("org", "eng", "lxx", "vul", "nvl", "rsc", "rso")

#: A bare verse coordinate, versification-free. Used as a mapping key so that lookups
#: don't depend on which system a :class:`VerseRef` claims to belong to.
_Coord = tuple[str, int, int, str]


class VersificationError(ValueError):
    """Base class for versification problems."""


class UnknownVersificationError(VersificationError):
    """A versification system was named that isn't loaded."""


class VerseOutOfRangeError(VersificationError):
    """A reference points past the end of its chapter or book."""


class VersificationGapError(VersificationError):
    """The data needed to resolve this reference is missing or known to be unreliable.

    Raised rather than guessed. See ``data/corrections.json`` for what is flagged and
    why.
    """


class VersificationDataError(VersificationError):
    """The vendored mapping data is malformed, or a correction no longer applies.

    A correction that stops applying usually means upstream fixed the bug, and the
    correction should be dropped -- not that anything is on fire.
    """


_REF_RE: Final = re.compile(
    r"^(?P<book>\w+) (?P<chapter>\d+):(?P<verse>\d+)(?P<sub>[a-z]?)"
    r"(?:-(?P<verse2>\d+)(?P<sub2>[a-z]?))?$"
)


def _parse_entry(text: str) -> list[_Coord]:
    """Expand one side of a mapping entry into its verse coordinates.

    Entries look like ``"GEN 32:1"``, ``"GEN 32:1-32"``, or ``"ESG 1:1a"``. Ranges never
    cross chapters in the upstream data, and only single (non-range) entries carry a
    sub-verse letter -- both facts are asserted here rather than assumed.
    """
    match = _REF_RE.match(text)
    if not match:
        raise VersificationDataError(f"malformed mapping entry: {text!r}")

    book = match["book"]
    chapter = int(match["chapter"])
    start = int(match["verse"])

    if match["verse2"] is None:
        return [(book, chapter, start, match["sub"])]

    if match["sub"] or match["sub2"]:
        raise VersificationDataError(f"sub-verse letters in a range are unsupported: {text!r}")

    end = int(match["verse2"])
    if end < start:
        raise VersificationDataError(f"range runs backwards: {text!r}")
    return [(book, chapter, v, "") for v in range(start, end + 1)]


def _reading_order(coord: _Coord) -> tuple[int, int, int, str]:
    """Sort key putting verse coordinates in the order a reader meets them."""
    book, chapter, verse, sub = coord
    return (canonical_order(book), chapter, verse, sub)


@dataclass(frozen=True, slots=True)
class _System:
    """One versification system's data, already validated and expanded."""

    name: str
    max_verses: Mapping[str, tuple[int, ...]]
    to_org: Mapping[_Coord, _Coord]
    from_org: Mapping[_Coord, tuple[_Coord, ...]]
    covers: Mapping[_Coord, tuple[_Coord, ...]]
    """Every pivot verse this verse holds any part of, in reading order.

    ``to_org`` answers "which verse *is* this one" and can name only one, because a
    mapping file is a function in that direction. But a verse can carry the text of two:
    the Douay's Matthew 17:14 is both "there came to him a man falling down on his knees"
    and "Lord, have mercy on my son". Naming one of those leaves the other unreachable,
    and choosing which to name is the whole subject of ``_merged_verse_note``.

    This is the relation instead of the function, so the question does not arise. It holds
    only the verses where the two differ and someone has read the text to establish it --
    see :func:`_resolve_covers` for why it is not derived -- so a verse absent from it is
    one whose exact answer is already complete.
    """
    covered_by: Mapping[_Coord, tuple[_Coord, ...]]
    """The transpose of :attr:`covers`, in reading order and within a single book.

    ``from_org`` picks the book where it has an opinion, so covering never contradicts the
    exact answer about which of two names a verse goes by -- English carries the Letter of
    Jeremiah under both LJE and BAR 6, and answering with both would quote it twice.
    """
    unreliable_books: frozenset[str]
    unreliable_chapters: frozenset[tuple[str, int]]
    """Chapters declared unmappable by hand, because counting cannot find them."""
    titled: frozenset[tuple[str, int]]
    """Chapters carrying a verse 0. In systems that number psalm superscriptions
    separately, the title is verse 0 and is not counted by ``maxVerses``."""


def _load_json(name: str) -> dict[str, object]:
    path = resources.files(__package__).joinpath("data", name)
    with path.open(encoding="utf-8") as handle:
        data: dict[str, object] = json.load(handle)
    return data


class Versification:
    """Converts references between versification systems.

    Construct via :meth:`load`, which caches -- the mapping data is a few hundred
    kilobytes and immutable, so there is no reason to parse it twice.
    """

    def __init__(self, systems: Mapping[str, _System]) -> None:
        self._systems = dict(systems)
        self._unmappable = {
            name: _unmappable_chapters(system, self._systems[PIVOT])
            for name, system in self._systems.items()
            if name != PIVOT
        }

    def unmappable_chapters(self, vrs: str) -> frozenset[tuple[str, int]]:
        """Chapters of ``vrs`` that cannot be converted to or from the pivot.

        A chapter lands here when its verses do not line up with the pivot's and no
        mapping says how they correspond -- the Vulgate's Sirach, Tobit and Judith, above
        all, which Jerome translated from source texts that differ from the Greek by whole
        clauses. Converting them would produce a plausible-looking verse number pointing
        at different words, so conversion refuses instead.
        """
        if vrs == PIVOT:
            return frozenset()
        return self._unmappable[vrs] | self._system(vrs).unreliable_chapters

    # -- construction ------------------------------------------------------------------

    @classmethod
    def load(cls, systems: Iterable[str] = DEFAULT_SYSTEMS) -> Versification:
        """Load the vendored mapping data, applying corrections."""
        return _load_cached(tuple(systems))

    # -- introspection -----------------------------------------------------------------

    @property
    def system_names(self) -> tuple[str, ...]:
        return tuple(self._systems)

    def _system(self, vrs: str) -> _System:
        try:
            return self._systems[vrs]
        except KeyError:
            raise UnknownVersificationError(
                f"unknown versification {vrs!r}; loaded: {', '.join(self._systems)}"
            ) from None

    def has_book(self, vrs: str, book: str) -> bool:
        """Whether ``book`` exists at all in ``vrs``."""
        return book in self._system(vrs).max_verses

    def chapter_count(self, vrs: str, book: str) -> int:
        """Number of chapters ``book`` has in ``vrs``. Zero if the book is absent."""
        return len(self._system(vrs).max_verses.get(book, ()))

    def resolve_letter_chapter(self, ref: VerseRef) -> VerseRef:
        """Turn ``Est C:12`` into the Vulgate numbering the additions are held in.

        Letter chapters are Esther's alone. See :mod:`biblereference.versification.esther`.

        :raises VersificationGapError: the reference is not an Esther addition.
        """
        from .esther import SUMMARY, letter_to_vulgate

        if ref.book != "EST":
            raise VersificationGapError(
                f"{ref.pretty()} uses a letter chapter, which only Esther has. {SUMMARY}"
            )
        try:
            return letter_to_vulgate(ref)
        except (KeyError, ValueError) as exc:
            raise VersificationGapError(str(exc)) from exc

    def first_verse(self, vrs: str, book: str, chapter: int) -> int:
        """Lowest verse number in a chapter -- 0 where a psalm superscription is numbered.

        Systems that follow the Greek and Latin psalm numbering give the superscription
        its own verse 0, which ``maxVerses`` does not count. Chapters without one start
        at 1.
        """
        return 0 if (book, chapter) in self._system(vrs).titled else 1

    def max_verse(self, vrs: str, book: str, chapter: int) -> int:
        """Highest verse number in a chapter.

        Note this is the highest verse *number*, not the number of verses: a chapter with
        a numbered superscription has one more verse than this, namely verse 0.

        :raises VerseOutOfRangeError: the book has no such chapter in this system.
        """
        chapters = self._system(vrs).max_verses.get(book)
        if not chapters:
            raise VerseOutOfRangeError(
                f"{book_title(book)} does not exist in the {vrs!r} versification"
            )
        if not 1 <= chapter <= len(chapters):
            raise VerseOutOfRangeError(
                f"{book_title(book)} has {len(chapters)} chapters in {vrs!r}, "
                f"so chapter {chapter} does not exist"
            )
        return chapters[chapter - 1]

    # -- validation --------------------------------------------------------------------

    def validate(self, ref: VerseRef | VerseRange) -> None:
        """Check that a reference exists in its own versification.

        This is what catches ``Sirach 51:31`` when Sirach 51 ends at verse 30 -- the
        error a citation tool exists to prevent.

        Only existence is checked. Whether the reference can be *converted* to another
        numbering is a separate question, and a separate refusal: the Vulgate's Esther
        11:2 is a perfectly real verse that no data can line up against the Greek.

        :raises VerseOutOfRangeError: the reference points past the end of its chapter.
        :raises VersificationGapError: a letter chapter that names no addition.
        """
        if isinstance(ref, VerseRange):
            self.validate(ref.start)
            if ref.end != ref.start:
                self.validate(ref.end)
            return

        if ref.is_letter_chapter:
            # Esther's additions, cited A-F. Resolving them into Vulgate numbering is
            # what checks them: the letter and the verse have to name a verse that exists.
            self.validate(self.resolve_letter_chapter(ref))
            return

        assert isinstance(ref.chapter, int)
        limit = self.max_verse(ref.vrs, ref.book, ref.chapter)
        if ref.verse > limit:
            raise VerseOutOfRangeError(
                f"{ref.pretty()} does not exist: {book_title(ref.book)} chapter "
                f"{ref.chapter} has {limit} verses in the {ref.vrs!r} versification"
            )

    # -- conversion --------------------------------------------------------------------

    def convert(self, ref: VerseRef, target: str, *, covering: bool = False) -> VerseRef:
        """Convert a single reference into ``target``'s numbering.

        Where the target splits the verse in two, this returns where its text begins;
        use :meth:`convert_all` to get every part.
        """
        return self.convert_all(ref, target, covering=covering)[0]

    def convert_all(self, ref: VerseRef, target: str, *, covering: bool = False) -> list[VerseRef]:
        """Every verse of ``target`` that this reference covers, in text order.

        Usually one. Two when the target system splits the verse -- Hebrew Isaiah 63:19
        is English 63:19 and 64:1, and quoting only the first half would misrepresent it.

        A reference with no explicit mapping keeps its coordinates and is simply
        relabelled: most verses agree across systems, and the mapping files list only the
        ones that don't.

        :param covering: Answer with every verse needed to carry *all* of this one's text,
            rather than with the single verse it most corresponds to. The two differ only
            where an edition merges what another divides -- the Douay's Matthew 17:14 is
            org's 17:14 and 17:15 together -- and there the default names one of them and
            this names both. Use it when you are quoting or comparing text and must not
            lose a clause; leave it off when you want the one verse that answers to this
            one, which is what citation, indexing and rendering normally mean. The result
            is always a superset of the default's, and never refuses where it would not.
        """
        if ref.is_letter_chapter:
            ref = self.resolve_letter_chapter(ref)

        if ref.vrs == target:
            return [ref]

        for name in (ref.vrs, target):
            if ref.book in self._system(name).unreliable_books:
                raise VersificationGapError(_gap_message(ref.book, name))

        assert isinstance(ref.chapter, int)
        for name in (ref.vrs, target):
            if (ref.book, ref.chapter) in self.unmappable_chapters(name):
                raise VersificationGapError(
                    f"{ref.pretty()} cannot be converted between the {ref.vrs!r} and "
                    f"{target!r} versifications: {book_title(ref.book)} chapter "
                    f"{ref.chapter} is divided differently in {name!r} than in the "
                    f"original-language numbering, and the mapping data does not say how "
                    f"the verses correspond. Quote it from a {name!r} text directly, or "
                    f"cite the passage in {name!r} numbering."
                )

        coord: _Coord = (ref.book, ref.chapter, ref.verse, ref.subverse)
        source, into = self._system(ref.vrs), self._system(target)
        exact = source.to_org.get(coord, coord)
        pivots = source.covers.get(coord, (exact,)) if covering else (exact,)

        finals: list[_Coord] = []
        for pivot in pivots:
            reached = into.from_org.get(pivot, (pivot,))
            if covering:
                reached = into.covered_by.get(pivot, reached)
            finals.extend(f for f in reached if f not in finals)

        out = [
            VerseRef(book=b, chapter=c, verse=v, subverse=s, vrs=target) for b, c, v, s in finals
        ]
        if covering:
            # A covered pivot the target simply does not have is dropped rather than
            # allowed to turn a good answer into a refusal: covering must never refuse
            # where the default succeeds, or the guarantee it offers would cost more than
            # it is worth. Only an empty result is a real gap, and _must_exist says so.
            kept = [v for v in out if self._exists(v)]
            if kept:
                return kept
        self._must_exist(ref, out, target)
        return out

    def _exists(self, ref: VerseRef) -> bool:
        """Whether the reference names a verse its own system actually declares."""
        system = self._systems.get(ref.vrs)
        if system is None or ref.is_letter_chapter or ref.book not in system.max_verses:
            return True
        chapters = system.max_verses[ref.book]
        chapter = int(ref.chapter)
        return 1 <= chapter <= len(chapters) and ref.verse <= chapters[chapter - 1]

    def _must_exist(self, ref: VerseRef, out: list[VerseRef], target: str) -> None:
        """Refuse rather than return a reference the target system does not have.

        A verse with no mapping keeps its coordinates and is relabelled, which is right
        for the overwhelming majority: the files list only the verses that move. But where
        a system has a verse the pivot does not -- the six extra verses Greek Joshua 24
        carries, the pluses in Greek Proverbs, the Esdras material -- that fall-through
        invents a reference. It looked like an answer and pointed at nothing.

        Eighteen such conversions existed when this was written. Each one is a genuine
        textual plus with no counterpart on the other side, so there is no mapping that
        would be correct; the honest result is the refusal this library already gives for
        everything else it cannot resolve.
        """
        for verse in out:
            if verse.vrs == ref.vrs or verse.is_letter_chapter:
                continue
            system = self._systems.get(verse.vrs)
            if system is None or verse.book not in system.max_verses:
                continue
            chapters = system.max_verses[verse.book]
            if not 1 <= int(verse.chapter) <= len(chapters):
                break
            if verse.verse > chapters[int(verse.chapter) - 1]:
                break
        else:
            return
        raise VersificationGapError(
            f"{ref.pretty()} has no counterpart in the {target!r} versification: it would "
            f"land on {out[0].pretty()}, which {target!r} does not have. This happens where "
            f"one tradition carries text the other does not, and no mapping can bridge it -- "
            f"quote the passage from a {ref.vrs!r} text directly."
        )

    def convert_range(
        self, span: VerseRange, target: str, *, covering: bool = False
    ) -> list[VerseRange]:
        """Convert a range, returning one segment per contiguous run.

        A range can fall apart under conversion. Vulgate ``Daniel 3:1-100`` becomes three
        pieces in the Hebrew frame -- Daniel 3:1-23, the Song of the Three as its own
        book, then Daniel 3:24-33 -- so this returns a list rather than pretending the
        result is still one span.

        :param covering: See :meth:`convert_all`. A covering range can only grow, and
            often grows into its neighbour and coalesces, so the segment count may fall.
        """
        if span.start.is_letter_chapter:
            # A letter chapter names a Vulgate verse whatever numbering the rest of the
            # document is written in, so resolve it before anything looks at ``vrs``.
            span = VerseRange(
                self.resolve_letter_chapter(span.start),
                self.resolve_letter_chapter(span.end),
            )
        if span.vrs == target:
            return [span]
        converted = [
            out
            for ref in self.expand(span)
            for out in self.convert_all(ref, target, covering=covering)
        ]
        return _coalesce(converted)

    def merge(self, spans: Iterable[VerseRange]) -> list[VerseRange]:
        """Join ranges that overlap or touch, in reading order.

        Built for a register of everything a work cites, where the same passage gets
        quoted in pieces across an argument. Citing 1 Timothy 2:7, then 2:4, then 2:1-6
        should produce one entry -- 1 Timothy 2:1-7 -- not three.

        Touching counts, not only overlapping: 2:1-6 and 2:7 are one passage with a
        seam, and printing them separately would be pedantry. Ranges join across a
        chapter boundary too, where the earlier one ends its chapter.

        Ranges in different versifications are merged within each, not across: they are
        different coordinate systems, and joining them would be meaningless.
        """
        by_system: dict[str, list[VerseRange]] = {}
        for span in spans:
            resolved = span
            if span.start.is_letter_chapter:
                resolved = VerseRange(
                    self.resolve_letter_chapter(span.start),
                    self.resolve_letter_chapter(span.end),
                )
            by_system.setdefault(resolved.vrs, []).append(resolved)

        out: list[VerseRange] = []
        for group in by_system.values():
            out.extend(self._merge_one_system(group))
        return sorted(out, key=lambda s: s.start)

    def _merge_one_system(self, spans: list[VerseRange]) -> list[VerseRange]:
        merged: list[VerseRange] = []
        for span in sorted(spans, key=lambda s: (s.start, s.end)):
            if merged and self._joins(merged[-1], span):
                previous = merged[-1]
                merged[-1] = VerseRange(previous.start, max(previous.end, span.end))
                continue
            merged.append(span)
        return merged

    def _joins(self, first: VerseRange, second: VerseRange) -> bool:
        """Whether ``second`` overlaps ``first`` or takes up immediately after it."""
        if first.book != second.book:
            return False
        if second.start <= first.end:
            return True
        return second.start == self._next_verse(first.end)

    def _next_verse(self, ref: VerseRef) -> VerseRef | None:
        """The verse after this one, or ``None`` at the end of the book."""
        if ref.is_letter_chapter or ref.subverse:
            return None
        assert isinstance(ref.chapter, int)
        try:
            if ref.verse < self.max_verse(ref.vrs, ref.book, ref.chapter):
                return VerseRef(ref.book, ref.chapter, ref.verse + 1, vrs=ref.vrs)
            if ref.chapter < self.chapter_count(ref.vrs, ref.book):
                first = self.first_verse(ref.vrs, ref.book, ref.chapter + 1)
                return VerseRef(ref.book, ref.chapter + 1, first, vrs=ref.vrs)
        except VerseOutOfRangeError:
            return None
        return None

    def expand(self, span: VerseRange) -> list[VerseRef]:
        """List every verse in a range, walking across chapter boundaries if needed."""
        self.validate(span)
        if span.start.is_letter_chapter:
            # An addition is contiguous in Vulgate numbering, so resolving the two ends
            # and walking between them covers it -- including where it crosses a chapter,
            # as Addition A does at 11:12 to 12:1.
            span = VerseRange(
                self.resolve_letter_chapter(span.start),
                self.resolve_letter_chapter(span.end),
            )
        start, end = span.start, span.end
        assert isinstance(start.chapter, int) and isinstance(end.chapter, int)

        out: list[VerseRef] = []
        for chapter in range(start.chapter, end.chapter + 1):
            first = (
                start.verse
                if chapter == start.chapter
                else self.first_verse(span.vrs, span.book, chapter)
            )
            last = (
                end.verse
                if chapter == end.chapter
                else self.max_verse(span.vrs, span.book, chapter)
            )
            out.extend(
                VerseRef(book=span.book, chapter=chapter, verse=v, vrs=span.vrs)
                for v in range(first, last + 1)
            )
        return out


def _unmappable_chapters(system: _System, pivot: _System) -> frozenset[tuple[str, int]]:
    """Find chapters whose verses cannot honestly be lined up with the pivot's.

    The test is deliberately narrow: a chapter is flagged when its verse count differs
    from the pivot's *and* upstream has written no mapping anywhere in that book. A
    differing count means the two traditions divide the text differently; no mapping in
    the whole book means nobody has said how. Together they mean an unmapped verse would
    fall through to the identity and land on a real verse containing different words --
    a citation that looks right and is not.

    Vouching is per *chapter*, not per book, and the distinction is not academic. The rule
    used to be that any mapping anywhere in a book vouched for the whole of it, on the
    reasoning that a shift is usually recorded on the chapter that gains the verses rather
    than the one that loses them, so silence nearby is meaningful. That holds for upstream's
    complete files and fails badly for a partially corrected book: adding a verified mapping
    for the Vulgate's Sirach 6 switched off the refusal for all fifty-one chapters, so
    Sirach 24 began converting by identity into a chapter Jerome translated from a different
    text. One fixed chapter should not vouch for fifty unexamined ones.

    A chapter therefore counts as vouched for when a mapping mentions it -- as source or as
    target, since a shift may be recorded from either side -- and neighbouring chapters are
    still trusted through the range that carries them.

    In practice this catches the Vulgate's Sirach, Tobit and Judith, which Jerome
    translated from source texts differing from the Greek by whole clauses, and the
    handful of chapters where Greek Sirach manuscripts transpose material.

    Note what it cannot catch: a chapter whose verse *count* matches the pivot but whose
    text is divided differently inside it. The Vulgate's Sirach 6 is exactly that -- 37
    verses both sides, with a split at 6:19 and an omission at 6:35 cancelling out -- so it
    converted silently and wrongly until the alignment audit found it. Equal counts are not
    evidence of equal division.
    """
    # A chapter counts as mapped whether it appears as a source or as a target: English
    # carries the Letter of Jeremiah as Baruch 6, so every entry about it is keyed on BAR
    # while the book that needs vouching for is LJE.
    mapped: set[tuple[str, int]] = set()
    for source, target in system.to_org.items():
        mapped.add((source[0], source[1]))
        mapped.add((target[0], target[1]))

    bad: set[tuple[str, int]] = set()
    for book, chapters in system.max_verses.items():
        pivot_chapters = pivot.max_verses.get(book)
        if pivot_chapters is None:
            # The pivot does not carry the book at all -- nothing to line up against.
            continue
        for chapter, count in enumerate(chapters, start=1):
            if (book, chapter) in mapped:
                continue
            if chapter > len(pivot_chapters) or count != pivot_chapters[chapter - 1]:
                bad.add((book, chapter))

    return frozenset(bad)


def _gap_message(book: str, vrs: str) -> str:
    """Why a whole book refuses, and what to do about it.

    Two different things end up here and the message has to be true of both: upstream data
    that contradicts itself (the Septuagint's interleaved Esther), and a book the two
    traditions do not share a text for at all (Jerome translated Judith and Tobit from
    Aramaic recensions differing from the Greek by whole clauses). Blaming the data was
    wrong for the second and unhelpful for both, since it told a reader nothing they could
    act on.
    """
    return (
        f"{book_title(book)} cannot be converted to or from the {vrs!r} versification: the "
        f"two traditions do not divide this book the same way, and the mapping data does "
        f"not say how the verses correspond -- either because it is missing or because the "
        f"editions translate different source texts. Quote it from a {vrs!r} text directly, "
        f"or cite the passage in {vrs!r} numbering. See "
        f"biblereference/versification/data/corrections.json for which applies here."
    )


def _coalesce(refs: list[VerseRef]) -> list[VerseRange]:
    """Group consecutive references back into ranges.

    Two references join only if they are genuinely adjacent -- same book, same chapter,
    consecutive verse numbers, no sub-verse letters. Sub-verses and chapter jumps end a
    run, which keeps a rendered citation honest about where the text actually breaks.
    """
    if not refs:
        return []

    # Converting a range can land two source verses on one target verse, and can emit
    # them out of order across a book boundary. Normalise before grouping.
    ordered = sorted(set(refs))

    out: list[VerseRange] = []
    run_start = run_end = ordered[0]
    for ref in ordered[1:]:
        adjacent = (
            ref.book == run_end.book
            and ref.chapter == run_end.chapter
            and not ref.subverse
            and not run_end.subverse
            and ref.verse == run_end.verse + 1
        )
        if adjacent:
            run_end = ref
        elif ref == run_end:
            continue  # many-to-one mapping collapsed onto the verse we're already on
        else:
            out.append(VerseRange(run_start, run_end))
            run_start = run_end = ref
    out.append(VerseRange(run_start, run_end))
    return out


# --------------------------------------------------------------------------------------
# Loading and correcting the vendored data
# --------------------------------------------------------------------------------------


def _apply_corrections(
    name: str, mapped: dict[str, str], corrections: dict[str, object]
) -> dict[str, str]:
    """Apply the documented fixes for one system, verifying each still applies."""
    result = dict(mapped)

    drops = _sub(corrections, "drop_mapped").get(name, [])
    assert isinstance(drops, list)
    for group in drops:
        for key in group["keys"]:
            if result.pop(key, None) is None:
                raise VersificationDataError(
                    f"correction for {name!r} drops mapping {key!r}, which is no longer "
                    f"present upstream -- the correction can probably be removed"
                )

    fixes = _sub(corrections, "fix_mapped").get(name, {})
    assert isinstance(fixes, dict)
    for key, spec in fixes.items():
        current = result.get(key)
        if current != spec["from"]:
            raise VersificationDataError(
                f"correction for {name!r} expected {key!r} to map to {spec['from']!r} "
                f"but found {current!r} -- upstream data has changed, re-check the fix"
            )
        result[key] = spec["to"]

    additions = _sub(corrections, "add_mapped").get(name, {})
    assert isinstance(additions, dict)
    for key, spec in additions.items():
        if key in result:
            raise VersificationDataError(
                f"correction for {name!r} adds mapping {key!r}, but upstream now "
                f"defines it as {result[key]!r} -- the correction can probably be removed"
            )
        result[key] = spec["to"]

    return result


def _resolve_reverse(
    name: str,
    candidates: dict[_Coord, list[_Coord]],
    to_org: dict[_Coord, _Coord],
    max_verses: Mapping[str, tuple[int, ...]],
    corrections: dict[str, object],
) -> dict[_Coord, tuple[_Coord, ...]]:
    """Work out which verses of this system correspond to each org verse.

    The answer is a tuple, not a single verse, because systems split verses: Hebrew
    Isaiah 63:19 is English 63:19 *and* 64:1, and rendering only the first half would
    misquote it. Sources are returned in text order, best first.

    Candidates come from two places. Explicit mappings are one. The other is the identity
    -- most verses agree across systems and are listed nowhere, so a verse that isn't
    explicitly mapped elsewhere is its own counterpart. Identity is skipped for
    *absorbed* books: where every explicit source for an org book comes from some other
    book, the system prints that material inside its host rather than standing alone.
    Susanna is Daniel 13 in the Vulgate; the Letter of Jeremiah is Baruch 6 in English.

    Ties break in this order: an explicit ``prefer_source`` correction, then the identity,
    then books not marked ``deprioritize_books``, then the lowest verse.
    """
    overrides_raw = _sub(corrections, "prefer_source").get(name, {})
    assert isinstance(overrides_raw, dict)
    overrides = {
        _parse_entry(target)[0]: _parse_entry(spec["source"])[0]
        for target, spec in overrides_raw.items()
    }

    spec = _sub(corrections, "deprioritize_books").get(name)
    demoted: frozenset[str] = frozenset()
    if spec is not None:
        assert isinstance(spec, dict)
        demoted = frozenset(spec["books"])

    # A book is absorbed when the other system carries it inside a differently-named book
    # and not under its own name at all -- English has the Letter of Jeremiah only as
    # Baruch 6, so org's LJE must resolve there rather than to an identity that would point
    # at nothing.
    #
    # A *deprioritised* book does not absorb anything, and the difference is not academic.
    # Mapping English Greek Daniel onto org's DAN made every verse of Daniel look absorbed
    # into DAG, which suppressed the identity and sent an ordinary citation of Daniel 1:1
    # into Greek Daniel -- a numbering no English protocanon corpus can render. The whole
    # point of deprioritising a book is that it is an alias to fall back on, never the
    # reason to abandon the book's own name.
    absorbed = {
        target[0]
        for target, sources in candidates.items()
        if all(source[0] != target[0] for source in sources)
        and any(source[0] not in demoted for source in sources)
    }

    def in_grid(coord: _Coord) -> bool:
        book, chapter, verse, _ = coord
        chapters = max_verses.get(book)
        return bool(chapters) and 1 <= chapter <= len(chapters) and verse <= chapters[chapter - 1]

    resolved: dict[_Coord, tuple[_Coord, ...]] = {}
    for target, sources in candidates.items():
        override = overrides.get(target)
        if override is not None and override not in sources:
            raise VersificationDataError(
                f"{name}: prefer_source names {override} for {target}, but that mapping "
                f"is not present upstream -- re-check the correction"
            )

        if override is not None:
            # An editorial choice between two real placements, not a split verse.
            resolved[target] = (override,)
            continue

        pool = list(sources)
        identity_ok = (
            target[0] not in absorbed and in_grid(target) and to_org.get(target, target) == target
        )
        if identity_ok and target not in pool:
            pool.append(target)

        # Pick the book first -- identity, then anything not deprioritised -- then take
        # every candidate in that book, in text order. Same-book candidates are the parts
        # of one split verse; a different book is an alias, and emitting both duplicates.
        def rank(
            coord: _Coord, *, want: _Coord = target, prefer_identity: bool = identity_ok
        ) -> tuple[int, int, str]:
            return (
                0 if coord[0] == want[0] and prefer_identity else 1,
                1 if coord[0] in demoted else 0,
                coord[0],
            )

        best_book = min(pool, key=rank)[0]
        resolved[target] = tuple(sorted(c for c in pool if c[0] == best_book))

    unused = set(overrides) - set(candidates)
    if unused:
        raise VersificationDataError(
            f"{name}: prefer_source targets {sorted(unused)} which nothing maps to -- "
            f"the correction can probably be removed"
        )
    return resolved


def _resolve_covers(
    name: str,
    to_org: dict[_Coord, _Coord],
    from_org: dict[_Coord, tuple[_Coord, ...]],
    corrections: dict[str, object],
) -> tuple[dict[_Coord, tuple[_Coord, ...]], dict[_Coord, tuple[_Coord, ...]]]:
    """Which pivot verses each verse's text covers, and the transpose.

    Every entry here is read against the text, and that is not a stylistic preference. It
    would be easy to derive this instead: for 921 verses the library already answers an org
    reference with a system verse whose own forward answer is a *different* org verse, and
    treating that as a covering relation would have cost nothing. It would also have been
    wrong. Those 921 are the identity fall-through -- what conversion returns when nothing
    maps to an org verse and it keeps its coordinates -- and the fall-through is a guess.
    Greek Exodus 36:9 is "he made the ephod of gold", part of the tabernacle account the
    Septuagint moves bodily, and org's 36:9 is "the length of each curtain was twenty-eight
    cubits". Deriving would have declared that one contains the other.

    So a covering claim is only ever as good as the reading behind it, and this file records
    the readings. Where there is no entry, covering answers exactly what the default does.
    """
    explicit: dict[_Coord, list[_Coord]] = {}
    entries = _sub(corrections, "covers").get(name, {})
    assert isinstance(entries, dict)
    for key, spec in entries.items():
        raw = spec["to"]
        targets: list[_Coord] = []
        # A list, because one case crosses a chapter boundary and a range cannot: the
        # English 1 Samuel 20:42 carries both org 20:42 and org 21:1.
        for piece in raw if isinstance(raw, list) else [raw]:
            targets.extend(_parse_entry(piece))
        for source in _parse_entry(key):
            explicit.setdefault(source, []).extend(targets)

    covers: dict[_Coord, tuple[_Coord, ...]] = {}
    for source, targets in explicit.items():
        exact = to_org.get(source, source)
        whole = set(targets) | {exact}
        if whole == {exact}:
            raise VersificationDataError(
                f"correction for {name!r} says {source} covers {sorted(whole)}, which is "
                f"only what it already maps to -- the correction can be removed"
            )
        covers[source] = tuple(sorted(whole, key=_reading_order))

    transposed: dict[_Coord, set[_Coord]] = {}
    for source, covered in covers.items():
        for target in covered:
            transposed.setdefault(target, set()).add(source)

    covered_by: dict[_Coord, tuple[_Coord, ...]] = {}
    for target, extra in transposed.items():
        lead = from_org.get(target, ())
        # The verse of the same number, where nothing sends it elsewhere. Conversion falls
        # through to it anyway when from_org is silent, and it is often a genuine part of
        # the answer rather than a stand-in: the Clementine's Revelation 20:10 really does
        # hold the tail of org 20:10, while its 20:9 holds the head, and dropping either
        # would lose half the verse. Where to_org *does* send it elsewhere the fall-through
        # is simply wrong, and covering is right to replace it.
        identity = {target} if to_org.get(target, target) == target else set()
        pool = sorted({*lead, *extra, *identity}, key=_reading_order)
        # One book only, exactly as _resolve_reverse insists: same-book answers are the
        # parts of one divided verse, but a different book is an alias for the same words,
        # and English holds the Letter of Jeremiah under both LJE and BAR 6. Emitting both
        # would quote the passage twice. The book ``from_org`` chose wins where it has
        # one, so covering never contradicts the exact answer about where a verse lives.
        book = lead[0][0] if lead else pool[0][0]
        covered_by[target] = tuple(c for c in pool if c[0] == book)

    return covers, covered_by


def _sub(corrections: dict[str, object], key: str) -> dict[str, object]:
    value = corrections.get(key, {})
    assert isinstance(value, dict)
    return value


def _unreliable_books(corrections: dict[str, object], system: str) -> frozenset[str]:
    """Books this system cannot be converted to or from at all.

    An entry naming ``chapters`` is *not* one of these -- it refuses those chapters only,
    through :func:`_unreliable_chapters`.
    """
    entries = corrections.get("unreliable", [])
    assert isinstance(entries, list)
    books: set[str] = set()
    for entry in entries:
        if system in entry["systems"] and not entry.get("chapters"):
            books.update(entry["books"])
    return frozenset(books)


def _unreliable_chapters(corrections: dict[str, object], system: str) -> frozenset[tuple[str, int]]:
    """Individual chapters declared unmappable, on top of the ones counting finds.

    The automatic guard refuses a chapter whose verse count differs from the pivot's, which
    catches most of them and is silent on the rest. A chapter can be unmappable and still
    have the same number of verses -- the Vulgate's Sirach 18 merges two verses, expands one
    into two, omits another and splits two more, all inside thirty-three verses that the
    Greek also numbers thirty-three -- and counting cannot see any of it.

    Naming such a chapter is the only way to refuse it. This is deliberately a list rather
    than a rule: each entry is a chapter somebody read.
    """
    entries = corrections.get("unreliable", [])
    assert isinstance(entries, list)
    out: set[tuple[str, int]] = set()
    for entry in entries:
        chapters = entry.get("chapters")
        if chapters and system in entry["systems"]:
            for book in entry["books"]:
                out.update((book, int(chapter)) for chapter in chapters)
    return frozenset(out)


def _build_system(name: str, corrections: dict[str, object]) -> _System:
    raw = _load_json(f"{name}.json")

    max_raw = raw["maxVerses"]
    assert isinstance(max_raw, dict)
    max_verses = {book: tuple(int(v) for v in counts) for book, counts in max_raw.items()}

    for book, spec in _sub(corrections, "add_books").get(name, {}).items():  # type: ignore[union-attr]
        if book in max_verses:
            raise VersificationDataError(
                f"correction for {name!r} adds book {book!r}, which upstream now defines "
                f"-- the correction can probably be removed"
            )
        max_verses[book] = tuple(int(v) for v in spec["maxVerses"])

    _fixed_books: set[str] = set()
    fixes = _sub(corrections, "fix_max_verses").get(name, {})
    assert isinstance(fixes, dict)
    for book, spec in fixes.items():
        if book not in max_verses:
            raise VersificationDataError(
                f"correction for {name!r} fixes verse counts in {book!r}, which upstream "
                f"does not define -- the correction is stale or the book code is wrong"
            )
        counts = list(max_verses[book])
        for chapter, count in spec["chapters"].items():
            index = int(chapter) - 1
            if not 0 <= index < len(counts):
                raise VersificationDataError(
                    f"correction for {name!r} fixes {book} {chapter}, which upstream does "
                    f"not have ({book} has {len(counts)} chapters)"
                )
            if counts[index] == int(count):
                raise VersificationDataError(
                    f"correction for {name!r} sets {book} {chapter} to {count}, which is "
                    f"already what upstream says -- the correction can be removed"
                )
            counts[index] = int(count)
        max_verses[book] = tuple(counts)
        _fixed_books.add(book)

    # Lengthening a book, which `fix_max_verses` refuses to do by design: it raises when the
    # chapter index is out of range, because silently growing a book is how a typo in a
    # chapter number becomes a new chapter nobody asked for. So this is a separate kind with
    # its own invariants, and the strictest of them is that it can only append.
    extensions = _sub(corrections, "extend_books").get(name, {})
    assert isinstance(extensions, dict)
    for book, spec in extensions.items():
        if book not in max_verses:
            raise VersificationDataError(
                f"correction for {name!r} extends {book!r}, which neither upstream nor "
                f"add_books defines -- use add_books to introduce a book, not extend_books"
            )
        counts = list(max_verses[book])
        added = sorted((int(chapter), int(count)) for chapter, count in spec["chapters"].items())
        for offset, (chapter, count) in enumerate(added):
            if chapter <= len(counts):
                raise VersificationDataError(
                    f"correction for {name!r} extends {book} to chapter {chapter}, which it "
                    f"already has ({book} has {len(counts)} chapters) -- extend_books only "
                    f"appends; use fix_max_verses to change a chapter that exists"
                )
            if chapter != len(counts) + 1 + offset:
                raise VersificationDataError(
                    f"correction for {name!r} extends {book} to chapter {chapter}, leaving a "
                    f"hole after {len(counts) + offset} -- an extension must be contiguous, "
                    f"because a book with a missing chapter in the middle cannot be walked"
                )
            if count < 1:
                raise VersificationDataError(
                    f"correction for {name!r} gives {book} {chapter} {count} verses -- a "
                    f"chapter nothing can be cited from is not worth declaring"
                )
        max_verses[book] = tuple(counts) + tuple(count for _, count in added)
        # Extending brings chapters into range that the orphan check below skipped as
        # out-of-range, so the same check has to cover them.
        _fixed_books.add(book)

    mapped_raw = raw.get("mappedVerses", {})
    assert isinstance(mapped_raw, dict)

    # A corrected verse count must not orphan a mapping that was written against the old
    # one. Checked only for books fix_max_verses touched, because the vendored data has
    # pre-existing inconsistencies elsewhere that are not this correction's business.
    if _fixed_books:
        for key in mapped_raw:
            match = _REF_RE.match(key)
            if match is None or match["book"] not in _fixed_books:
                continue
            declared = max_verses.get(match["book"])
            chapter = int(match["chapter"])
            if not declared or chapter > len(declared):
                continue
            highest = int(match["verse2"] or match["verse"])
            if highest > declared[chapter - 1]:
                raise VersificationDataError(
                    f"{name}: fix_max_verses set {match['book']} {chapter} to "
                    f"{declared[chapter - 1]} verses, but the mapping {key!r} names verse "
                    f"{highest} -- correct or drop the mapping too"
                )

    if name in _sub(corrections, "ignore_self_mapped"):
        # The pivot's own "mappings" are an aside about book layout, not conversions.
        mapped_raw = {}

    mapped = _apply_corrections(name, dict(mapped_raw), corrections)

    to_org: dict[_Coord, _Coord] = {}
    candidates: dict[_Coord, list[_Coord]] = {}
    for key, value in mapped.items():
        sources = _parse_entry(key)
        targets = _parse_entry(value)
        if len(sources) != len(targets):
            raise VersificationDataError(
                f"{name}: {key!r} covers {len(sources)} verses but {value!r} covers "
                f"{len(targets)} -- the mapping cannot be aligned"
            )
        for source, target in zip(sources, targets, strict=True):
            if source in to_org and to_org[source] != target:
                raise VersificationDataError(
                    f"{name}: {source} is mapped to both {to_org[source]} and {target}"
                )
            to_org[source] = target
            candidates.setdefault(target, []).append(source)

    from_org = _resolve_reverse(name, candidates, to_org, max_verses, corrections)
    covers, covered_by = _resolve_covers(name, to_org, from_org, corrections)

    return _System(
        name=name,
        max_verses=max_verses,
        to_org=to_org,
        from_org=from_org,
        covers=covers,
        covered_by=covered_by,
        unreliable_books=_unreliable_books(corrections, name),
        unreliable_chapters=_unreliable_chapters(corrections, name),
        titled=frozenset((book, chapter) for book, chapter, verse, _ in to_org if verse == 0),
    )


@cache
def _load_cached(systems: tuple[str, ...]) -> Versification:
    corrections = _load_json("corrections.json")
    return Versification({name: _build_system(name, corrections) for name in systems})


def _iter_books(system: _System) -> Iterator[str]:
    yield from system.max_verses


@cache
def fingerprint(systems: Iterable[str] = DEFAULT_SYSTEMS) -> str:
    """A stable digest of the versification data and the corrections applied to it.

    A version string cannot stand in for this. A mapping fix is a change to a JSON file
    rather than a release -- seven of them landed in one afternoon while auditing Greek
    Daniel, Sirach 6 and Leviticus 8 -- so anything that resolved references before them and
    stored the results is now silently disagreeing with the library that produced it, and
    nothing about it looks wrong.

    Anything deriving stored data from this library should record what this returned and
    warn when it moves. It exists so a dependent does not have to reach into this package's
    data files to compute one itself.

    The loaded system names are included, so asking for a different set of systems is
    visible too: ``rsc`` and ``rso`` carry mappings the default five do not.
    """
    digest = hashlib.sha256()
    data = resources.files("biblereference.versification").joinpath("data")
    for name in sorted(entry.name for entry in data.iterdir() if entry.name.endswith(".json")):
        digest.update(name.encode())
        digest.update(data.joinpath(name).read_bytes())
    # After the files, so that a system list which happens to spell a filename cannot
    # collide with one.
    digest.update(b"\x00systems\x00")
    digest.update(",".join(sorted(systems)).encode())
    return digest.hexdigest()
