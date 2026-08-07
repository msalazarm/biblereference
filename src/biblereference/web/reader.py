"""What the reading screen asks for: the books, a chapter across versions, and a guess.

Three endpoints and one idea holding them together. **A book belongs to the union of what
the systems declare and what the corpora hold, never to either alone.** Measured over this
library: ``nvl`` declares 73 books and 20 of the 93 actually held are not among them;
``lxx`` has no Daniel, Esther, Nehemiah, Song of the Three or 4 Ezra; ``org`` has no Greek
Daniel. A dropdown built from the system alone hides a fifth of the library, and one built
from the corpora alone raises ``VerseOutOfRangeError`` the moment somebody clicks a chapter
the system cannot number. So each book says which of the two it came from and the reader
can act accordingly.

The other idea is how two versions' verses are linked. Every verse, whatever it numbers
itself, is converted to the pivot under ``covering`` -- the set of ``org`` verses whose text
it carries. Two verses correspond exactly when those sets intersect. That is what makes
hovering Douay Matthew 17:14 light up two Greek verses, and it needs no per-pair table:
the pivot the whole library is built around already says it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..canon import (
    CANONICAL_ORDER,
    SINGLE_CHAPTER_BOOKS,
    AmbiguousBookError,
    Canon,
    NamingScheme,
    UnknownBookError,
    book_canon,
    book_title,
    resolve_book,
)
from ..refs import VerseRef, parse_reference
from ..render import RTL
from ..versification import PIVOT, VersificationError
from .library import VRS, corpora, library

__all__ = ["api_books", "api_parse", "api_reader"]

#: What to call each part of the canon in a grouped dropdown.
GROUPS: dict[str, str] = {
    Canon.HEBREW.value: "Hebrew canon",
    Canon.DEUTERO.value: "Deuterocanon",
    Canon.NT.value: "New Testament",
    Canon.APPENDIX.value: "Appendix",
}


def naming_of(params: dict[str, list[str]]) -> NamingScheme:
    """The naming tradition to title books in, refusing one this library does not know."""
    asked = (params.get("naming") or ["modern"])[0]
    try:
        return NamingScheme(asked)
    except ValueError:
        known = ", ".join(scheme.value for scheme in NamingScheme)
        raise ValueError(f"unknown naming scheme {asked!r}; try one of {known}") from None


def system_of(params: dict[str, list[str]], name: str = "vrs") -> str:
    """A versification this server has loaded, or a refusal naming the ones it has."""
    asked = (params.get(name) or ["eng"])[0]
    if asked not in VRS.system_names:
        raise ValueError(
            f"unknown versification {asked!r}; this server has loaded {', '.join(VRS.system_names)}"
        )
    return asked


def _carriers() -> dict[str, dict[str, dict[int, int]]]:
    """``book -> corpus -> chapter -> verses held``, off the process-wide inventory.

    Inverted from the cache's ``corpus -> book`` shape because every question the reader
    asks starts from a book. Cheap either way; this is a few thousand dictionary writes
    over data already in memory, and no query at all.
    """
    out: dict[str, dict[str, dict[int, int]]] = {}
    for corpus, books in library().chapters.items():
        for book, chapters in books.items():
            out.setdefault(book, {})[corpus] = dict(chapters)
    return out


# --------------------------------------------------------------------------------------
# The dropdown
# --------------------------------------------------------------------------------------


def api_books(params: dict[str, list[str]]) -> Any:
    """Every book the reader may navigate to, in reading order and grouped by canon."""
    system = system_of(params)
    naming = naming_of(params)
    carried = _carriers()

    books = []
    for code in CANONICAL_ORDER:
        declared = VRS.has_book(system, code)
        holders = carried.get(code, {})
        if not declared and not holders:
            continue

        if declared:
            count = VRS.chapter_count(system, code)
            verses = [VRS.max_verse(system, code, n) for n in range(1, count + 1)]
            # Chapter zero is a numbered superscription, which the shipped systems model as
            # verse 0. A reader that started every chapter at 1 would silently drop the
            # psalm titles -- 116 of them in the Hebrew.
            titled = [n for n in range(1, count + 1) if VRS.first_verse(system, code, n) == 0]
        else:
            # The system does not have this book, so the editions that hold it are the only
            # authority on its shape. Reported as `from: "corpora"` so the reader can show
            # it without pretending the system agrees.
            highest = max((max(ch) for ch in holders.values() if ch), default=0)
            count = highest
            verses = [
                max((ch.get(n, 0) for ch in holders.values()), default=0)
                for n in range(1, count + 1)
            ]
            titled = []

        books.append(
            {
                "book": code,
                "title": book_title(code, naming),
                "canon": book_canon(code).value,
                "chapters": count,
                "verses": verses,
                "titled": titled,
                "single_chapter": code in SINGLE_CHAPTER_BOOKS,
                "from": "system" if declared else "corpora",
                "carried_by": len(holders),
                # Which loaded systems *do* number it. Where the chosen one does not, this
                # is what lets the reader move to one that does instead of refusing -- and
                # refusing is what it used to do, for a fifth of the library under `nvl`.
                "in": [name for name in VRS.system_names if VRS.has_book(name, code)],
            }
        )

    order = {code: index for index, code in enumerate(CANONICAL_ORDER)}
    return {
        "vrs": system,
        "naming": naming.value,
        # The systems this server actually loaded, so the numbering picker is not a second
        # hard-coded list that can drift from `DEFAULT_SYSTEMS`.
        "systems": list(VRS.system_names),
        "groups": [
            {
                "canon": canon,
                "label": label,
                "books": sorted(
                    (b["book"] for b in books if b["canon"] == canon),
                    key=lambda code: order[str(code)],
                ),
            }
            for canon, label in GROUPS.items()
        ],
        "books": books,
    }


# --------------------------------------------------------------------------------------
# One chapter, across versions
# --------------------------------------------------------------------------------------


def _covers_refs(ref: VerseRef) -> tuple[list[VerseRef], str]:
    """Which pivot verses this verse's text carries, and why not, where it carries none.

    Under ``covering``, because the question is what the verse *contains* rather than which
    single verse it most corresponds to -- that is the difference between Douay Matthew
    17:14 answering `MAT 17:14` and answering the two Greek verses it actually holds. It is
    deliberately not the ``covering`` the caller asked for: that decides which verses are
    *shown*, and if it also decided the alignment key then ticking the box would re-key
    every row. The table stays still under the toggle.

    **The refusal is returned rather than swallowed.** 6,611 verses in this library convert
    to no pivot verse at all, and they cluster by chapter -- every English verse of Acts 19,
    of 2 Corinthians 13, of Numbers 25; 1,508 verses of the Vulgate's Sirach. In every one
    of those cases the versification has a sentence explaining itself, and a screen showing
    an unexplained blank instead is the worse answer.
    """
    if ref.vrs == PIVOT:
        return ([ref], "")
    try:
        return (list(VRS.convert_all(ref, PIVOT, covering=True)), "")
    except VersificationError as exc:
        return ([], str(exc))


def _covers(ref: VerseRef) -> list[str]:
    """The pivot verses as strings, which is what goes on the wire."""
    return [str(one) for one in _covers_refs(ref)[0]]


def _read(corpus: Any, span: Any, covering: bool) -> dict[str, Any]:
    """One version's text for the span, in that version's own numbering."""
    try:
        segments = VRS.convert_range(span, corpus.versification, covering=covering)
    except VersificationError as exc:
        return {"loaded": False, "refused": str(exc)}
    if not segments:
        return {"loaded": False, "refused": "no corresponding passage"}

    if not any(corpus.has_book(segment.book) for segment in segments):
        # A Hebrew Bible asked for John. Not an empty reading -- it is not a version of
        # this passage at all, and showing it as one loaded with nothing in it reads as a
        # build fault.
        return {"loaded": False, "absent": True}

    verses: list[dict[str, Any]] = []
    keys: list[tuple[VerseRef, list[VerseRef]]] = []
    asked = 0
    missing = 0
    unaligned = ""

    def keep(ref: VerseRef, text: str) -> None:
        nonlocal unaligned
        covers, why = _covers_refs(ref)
        if why and not unaligned:
            unaligned = why
        keys.append((ref, covers))
        verses.append(
            {
                "n": ref.verse,
                "sub": ref.subverse,
                "ref": str(ref),
                "text": text,
                "covers": [str(one) for one in covers],
            }
        )

    for segment in segments:
        if not corpus.has_book(segment.book):
            continue
        if not VRS.has_book(corpus.versification, segment.book):
            # The edition holds the book and its declared system does not number it, which
            # `convert_range`'s identity fallback does not check for. Reading it verse by
            # verse would raise; `chapter` needs no list of expected verses, so the
            # edition's own divisions come through instead of being clipped to a system
            # that has none for it.
            for number in _numbered(segment):
                for verse in corpus.chapter(segment.book, number):
                    asked += 1
                    keep(verse.ref, verse.text)
            continue

        expected = VRS.expand(segment)
        asked += len(expected)
        # Read the whole chapter and keep the verses asked for, rather than fetching the
        # expected refs directly. `expand` yields no subverses, and `available` matches on
        # the exact ref *including* the subverse -- so an edition printing Isaiah 7:2 as 2a
        # and 2b had both rows skipped and was then reported as missing a verse it prints.
        # 268 rows in this library were unreachable that way.
        wanted = {(one.book, one.chapter, one.verse) for one in expected}
        found: set[tuple[str, int | str, int]] = set()
        for number in _numbered(segment):
            for verse in corpus.chapter(segment.book, number):
                place = (verse.ref.book, verse.ref.chapter, verse.ref.verse)
                if place not in wanted:
                    continue
                found.add(place)
                keep(verse.ref, verse.text)
        missing += len(wanted - found)

    return {
        "loaded": True,
        "ref": ", ".join(segment.pretty() for segment in segments),
        "usfm": ", ".join(str(segment) for segment in segments),
        # Said rather than left to be counted: a reader comparing versions has to be able
        # to tell "this edition does not print that verse" from "the passage is shorter
        # here", and the length of the array cannot distinguish them. Counted on verse
        # *numbers* rather than rows, so an edition printing one verse as 2a and 2b is not
        # reported as having one too many.
        "asked": asked,
        "missing": missing,
        "verses": verses,
        # Popped by `api_reader` before this goes on the wire.
        "_keys": keys,
        "_unaligned": unaligned,
    }


def _numbered(segment: Any) -> range:
    """The numbered chapters of a segment, skipping Esther's lettered ones.

    ``VerseRef.chapter`` is ``int | str``: Esther's Greek additions are chapters A to F.
    Nothing stores them -- ``SqliteCorpus.fetch`` says so in as many words -- so a range
    over them is empty rather than a ``ValueError`` from ``int('A')``.
    """
    if isinstance(segment.start.chapter, str) or isinstance(segment.end.chapter, str):
        return range(0)
    return range(int(segment.start.chapter), int(segment.end.chapter) + 1)


def _label(key: VerseRef, system: str) -> dict[str, Any]:
    """What to write at the head of a row.

    The reference in the numbering the reader chose, because somebody who typed *Psalm 119*
    must not be handed a column of *Psalm 118* row headers. The pivot reference goes
    underneath and only where the two differ -- reading in ``org`` it disappears entirely,
    which is right, since there it is the same thing said twice.

    Exact rather than covering: this is a label for one row, not a span.
    """
    if key.vrs != PIVOT:
        # A row keyed on a version's own numbering because nothing could be aligned. It has
        # no pivot to name, and the system it belongs to is what identifies it.
        return {"ref": str(key), "vrs": key.vrs}
    if system == PIVOT:
        return {"ref": str(key)}
    try:
        found = VRS.convert_all(key, system)
    except VersificationError as exc:
        return {"ref": str(key), "pivot": str(key), "refused": str(exc)}
    if not found:
        return {"ref": str(key), "pivot": str(key)}
    label: dict[str, Any] = {"ref": str(found[0])}
    if str(found[0]) != str(key):
        label["pivot"] = str(key)
    return label


def _whole(ref: VerseRef) -> VerseRef:
    """The verse a subverse belongs to.

    A subverse is part of a verse, not a verse of its own, so it shares its row. Ottley's
    Isaiah prints 7:2 as 2a and 2b and both belong beside the Hebrew's single 7:2; the
    Greek Esther prints 1:1a to 1:1r where the Hebrew has one verse 1, and putting each on
    its own row would claim eighteen Hebrew verses that do not exist. Stacked in one cell
    is both the true picture and the same shape as every other many-to-one case here.
    """
    return replace(ref, subverse="") if ref.subverse else ref


def _rows(
    system: str,
    loaded: list[tuple[str, list[tuple[VerseRef, list[VerseRef]]]]],
    pivot: set[VerseRef] | None,
) -> list[dict[str, Any]]:
    """One row per verse of the passage, with each version's answer to it.

    **Keyed on the pivot, because verse numbers cannot be the key.** The Douay's Matthew
    17:14 and the Greek's 17:15 are the same words, and any table that lined them up by
    number would be wrong on exactly the passages worth comparing. Every verse says which
    pivot verses it carries, so that is the row.

    Four things make the obvious implementation wrong, all measured:

    *A column's keys do not ascend.* The Septuagint moves the tabernacle account bodily, so
    ``lxx EXO 36`` runs 36:8, 39:2 … 39:10, 36:18. 104 chapters do this. So the verses are
    bucketed and the keys sorted at the end -- a merge walking the columns in parallel would
    produce nonsense.

    *A verse can answer to several rows.* 30 in this library, up to three. It is **repeated**
    in each rather than spanning them: a span needs its rows to be adjacent, and another
    column can put a row between them.

    *Two verses of one version can answer to one row.* 152 cases -- the Douay's Psalm 12:2
    and 12:3 both carry the Hebrew's 13:3. So a cell holds a list, and showing both stacked
    is not a workaround but the truth: the Douay prints two verses where the Hebrew has one.

    *A verse can answer to nothing.* It is keyed on its own reference instead, tagged with
    its versification so two systems' unaligned rows never merge, while two editions of one
    system align exactly.

    Cells carry *indices* into each version's ``verses`` array, so no text is repeated on
    the wire however many rows a verse appears in.
    """
    buckets: dict[VerseRef, dict[str, list[int]]] = {}
    # Seed every verse of the passage, so one no open version prints still gets a row.
    # Dropping it would silently renumber the table and hide the absence.
    for ref in pivot or ():
        buckets.setdefault(_whole(ref), {})
    for corpus, entries in loaded:
        for index, (own, covers) in enumerate(entries):
            for key in covers or [own]:
                buckets.setdefault(_whole(key), {}).setdefault(corpus, []).append(index)

    # A pivot row sorts before an unaligned row at the same coordinate, and the versification
    # breaks the remaining tie -- so the order does not depend on which column arrived first.
    order = sorted(buckets, key=lambda ref: (ref.sort_key(), ref.vrs != PIVOT, ref.vrs))
    return [
        {
            "key": str(key),
            "label": _label(key, system),
            "aligned": key.vrs == PIVOT,
            # False where the passage's own text sits at a pivot verse outside what was
            # asked for -- the transposed Greek Exodus. Marked, never dropped: dropping
            # them would delete 28 of the 38 verses of a loaded column with no explanation.
            "in_span": pivot is None or key in pivot,
            "at": buckets[key],
        }
        for key in order
    ]


def _pivot_span(span: Any) -> tuple[set[VerseRef] | None, dict[str, Any]]:
    """The asked passage in pivot terms, or nothing and the reason why.

    Where a chapter cannot be converted to the pivot at all -- Acts 19 in the English
    numbering, most of the Vulgate's Sirach -- there is no common ground to align on. The
    rows then fall back to each version's own numbering, which is safe *because* of what
    made it necessary: in such a chapter only versions declaring the asked system load at
    all, so their references really are comparable. The note says so, because a table that
    lines up for that reason looks exactly like one that lines up for the good reason.
    """
    try:
        segments = VRS.convert_range(span, PIVOT, covering=True)
        held = {ref for segment in segments for ref in VRS.expand(segment)}
    except VersificationError as exc:
        return (None, {"mode": "numbering", "note": str(exc)})
    return (held, {"mode": "pivot", "note": None})


def api_reader(params: dict[str, list[str]]) -> Any:
    """A chapter, or a range within one, in the versions asked for.

    ``corpus`` is repeatable and names what to *read*. Everything else comes back as a stub
    saying whether it carries the passage at all -- answered from the process-wide chapter
    inventory, so a sixty-six-version index costs no queries. Psalm 119 in every version
    that holds it is 740 KB, which is why nothing is loaded unless it is asked for.
    """
    system = system_of(params)
    naming = naming_of(params)
    covering = bool(params.get("covering"))
    wanted = {name for raw in params.get("corpus", ()) for name in raw.split(",") if name}

    span = _asked_span(params, system, naming)
    chapters = _numbered(span)
    carried = _carriers().get(span.book, {})

    versions = []
    loaded: list[tuple[str, list[tuple[VerseRef, list[VerseRef]]]]] = []
    unaligned = ""
    for corpus in sorted(corpora().values(), key=lambda c: (c.language, c.id)):
        held = carried.get(corpus.id, {})
        row: dict[str, Any] = {
            "corpus": corpus.id,
            "label": corpus.label,
            "language": corpus.language,
            "versification": corpus.versification,
            "dir": "rtl" if corpus.language in RTL else "ltr",
            # Whether it holds the book at all, and how much of what was asked. Both from
            # the cache, so this is free for the versions nobody asked to read.
            "carries": bool(held),
            "held": sum(held.get(n, 0) for n in chapters),
        }
        row.update(_read(corpus, span, covering) if corpus.id in wanted else {"loaded": False})
        # The refs behind the verses, kept for `_rows` and stripped before this goes out.
        keys = row.pop("_keys", None)
        if keys is not None:
            loaded.append((corpus.id, keys))
        unaligned = unaligned or row.pop("_unaligned", "")
        row.pop("_unaligned", None)
        versions.append(row)

    pivot, alignment = _pivot_span(span)
    if alignment["note"] is None and unaligned:
        # The passage converts to the pivot but some verse of some version does not. Rarer
        # than the whole-chapter case and worth the same sentence.
        alignment = {"mode": "pivot", "note": unaligned}

    return {
        "asked": {
            "ref": span.pretty(),
            "usfm": str(span),
            "book": span.book,
            "title": book_title(span.book, naming),
            "chapter": span.start.chapter,
            "vrs": system,
            "naming": naming.value,
            "covering": covering,
            "read": sorted(wanted),
            "alignment": alignment,
        },
        "versions": versions,
        "rows": _rows(system, loaded, pivot),
    }


def _asked_span(params: dict[str, list[str]], system: str, naming: NamingScheme) -> Any:
    """The passage, from either ``ref=`` or ``book=``/``chapter=``/``verse=``.

    Both spellings because the two callers differ: a link carries a reference, and the
    chapter grid carries the pieces it already has and should not have to re-render into a
    string for the server to parse back apart.
    """
    if params.get("ref"):
        return parse_reference(params["ref"][0], vrs=system, naming=naming, allow_chapter=True)
    book = (params.get("book") or [""])[0]
    if not book:
        raise ValueError("give either ref= or book= and chapter=")
    code = resolve_book(book, naming)
    chapter = (params.get("chapter") or ["1"])[0]
    verse = (params.get("verse") or [""])[0]
    asked = f"{code} {chapter}:{verse}" if verse else f"{code} {chapter}"
    span = parse_reference(asked, vrs=system, naming=naming, allow_chapter=True)
    # `parse_reference` validates a chapter-only reference against the system and a
    # `chapter:verse` one only for shape, so `Habakkuk 99:1` parses. Asking here means the
    # reader is refused with "Habakkuk has 3 chapters in 'eng'" rather than being handed a
    # passage that every version will separately decline.
    VRS.validate(span)
    return span


# --------------------------------------------------------------------------------------
# Is this a reference, or is it prose?
# --------------------------------------------------------------------------------------


def api_parse(params: dict[str, list[str]]) -> Any:
    """Decide what the search box holds. **Always 200, even when it does not parse.**

    This is a predicate, not a lookup: one box takes either a reference or a quotation, and
    "that is not a reference" is the *answer* rather than an error. A 400 here would make
    every typed character of a quotation an error in the console.

    The ambiguous case is the interesting one. "1 Kings" means 1 Samuel to a Douay reader
    and 1 Kings to everyone else, and this library refuses to guess -- so the refusal comes
    back as the two readings, which is a question the reader can put to the person typing.
    """
    query = (params.get("q") or [""])[0].strip()
    system = system_of(params)
    naming = naming_of(params)
    if not query:
        return {"ok": False, "kind": "empty", "q": query}

    try:
        span = parse_reference(query, vrs=system, naming=naming, allow_chapter=True)
    except AmbiguousBookError as exc:
        return {
            "ok": False,
            "kind": "ambiguous",
            "q": query,
            "error": str(exc),
            # Titled in *modern* usage, not in the scheme being offered, which is the
            # whole point: `book_title("1SA", DR)` is "1 Kings" and so is
            # `book_title("1KI", MODERN)`, so offering each in its own naming would show
            # the reader the same two words twice. This is the library's own wording in
            # `AmbiguousBookError`, for the same reason.
            "options": [
                {"naming": scheme.value, "book": code, "title": book_title(code)}
                for scheme, code in sorted(exc.options.items())
            ],
        }
    except (UnknownBookError, ValueError) as exc:
        # Everything a person mistypes: an unknown book, a malformed range, a chapter past
        # the end. All ValueErrors, and all meaning "treat this as text".
        return {"ok": False, "kind": "text", "q": query, "error": str(exc)}

    try:
        # `parse_reference` checks a chapter-only reference against the system and a
        # `chapter:verse` one only for shape, so `Habakkuk 99:1` gets this far. It is not
        # prose -- the reader named a real book -- so it is its own answer, carrying the
        # library's own sentence: "Habakkuk has 3 chapters in 'eng'".
        VRS.validate(span)
    except VersificationError as exc:
        return {
            "ok": False,
            "kind": "unreachable",
            "q": query,
            "book": span.book,
            "title": book_title(span.book, naming),
            "error": str(exc),
        }

    return {
        "ok": True,
        "kind": "reference",
        "q": query,
        "ref": span.pretty(),
        "usfm": str(span),
        "book": span.book,
        "title": book_title(span.book, naming),
        "chapter": span.start.chapter,
        "verse": span.start.verse,
        "single": span.is_single_verse,
        "vrs": system,
    }
