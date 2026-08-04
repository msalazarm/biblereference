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

from ..canon import book_title
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


@dataclass(frozen=True, slots=True)
class _System:
    """One versification system's data, already validated and expanded."""

    name: str
    max_verses: Mapping[str, tuple[int, ...]]
    to_org: Mapping[_Coord, _Coord]
    from_org: Mapping[_Coord, tuple[_Coord, ...]]
    unreliable_books: frozenset[str]
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
        return self._unmappable[vrs]

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

    def convert(self, ref: VerseRef, target: str) -> VerseRef:
        """Convert a single reference into ``target``'s numbering.

        Where the target splits the verse in two, this returns where its text begins;
        use :meth:`convert_all` to get every part.
        """
        return self.convert_all(ref, target)[0]

    def convert_all(self, ref: VerseRef, target: str) -> list[VerseRef]:
        """Every verse of ``target`` that this reference covers, in text order.

        Usually one. Two when the target system splits the verse -- Hebrew Isaiah 63:19
        is English 63:19 and 64:1, and quoting only the first half would misrepresent it.

        A reference with no explicit mapping keeps its coordinates and is simply
        relabelled: most verses agree across systems, and the mapping files list only the
        ones that don't.
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
        pivot = self._system(ref.vrs).to_org.get(coord, coord)
        finals = self._system(target).from_org.get(pivot, (pivot,))

        out = [
            VerseRef(book=b, chapter=c, verse=v, subverse=s, vrs=target) for b, c, v, s in finals
        ]
        self._must_exist(ref, out, target)
        return out

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

    def convert_range(self, span: VerseRange, target: str) -> list[VerseRange]:
        """Convert a range, returning one segment per contiguous run.

        A range can fall apart under conversion. Vulgate ``Daniel 3:1-100`` becomes three
        pieces in the Hebrew frame -- Daniel 3:1-23, the Song of the Three as its own
        book, then Daniel 3:24-33 -- so this returns a list rather than pretending the
        result is still one span.
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
        converted = [out for ref in self.expand(span) for out in self.convert_all(ref, target)]
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
    return (
        f"{book_title(book)} cannot be resolved in the {vrs!r} versification: the "
        f"upstream mapping data for this book is missing or internally inconsistent. "
        f"See biblereference/versification/data/corrections.json for the details."
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


def _sub(corrections: dict[str, object], key: str) -> dict[str, object]:
    value = corrections.get(key, {})
    assert isinstance(value, dict)
    return value


def _unreliable_books(corrections: dict[str, object], system: str) -> frozenset[str]:
    entries = corrections.get("unreliable", [])
    assert isinstance(entries, list)
    books: set[str] = set()
    for entry in entries:
        if system in entry["systems"]:
            books.update(entry["books"])
    return frozenset(books)


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

    mapped_raw = raw.get("mappedVerses", {})
    assert isinstance(mapped_raw, dict)

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

    return _System(
        name=name,
        max_verses=max_verses,
        to_org=to_org,
        from_org=from_org,
        unreliable_books=_unreliable_books(corrections, name),
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
