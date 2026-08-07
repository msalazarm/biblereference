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
            }
        )

    order = {code: index for index, code in enumerate(CANONICAL_ORDER)}
    return {
        "vrs": system,
        "naming": naming.value,
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


def _covers(ref: VerseRef) -> list[str]:
    """Which pivot verses this verse's text carries.

    Under ``covering``, because the question is what the verse *contains* rather than which
    single verse it most corresponds to -- that is the difference between Douay Matthew
    17:14 answering `MAT 17:14` and answering the two Greek verses it actually holds.
    """
    if ref.vrs == PIVOT:
        return [str(ref)]
    try:
        return [str(one) for one in VRS.convert_all(ref, PIVOT, covering=True)]
    except VersificationError:
        # A verse the pivot has no place for -- a Greek addition, a psalm the Hebrew does
        # not divide there. It links to nothing, which is the honest answer.
        return []


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
    asked = 0
    for segment in segments:
        if not corpus.has_book(segment.book):
            continue
        expected = VRS.expand(segment)
        asked += len(expected)
        for verse in corpus.available(expected):
            verses.append(
                {
                    "n": verse.ref.verse,
                    "sub": verse.ref.subverse,
                    "ref": str(verse.ref),
                    "text": verse.text,
                    "covers": _covers(verse.ref),
                }
            )
    return {
        "loaded": True,
        "ref": ", ".join(segment.pretty() for segment in segments),
        "usfm": ", ".join(str(segment) for segment in segments),
        # Said rather than left to be counted: a reader comparing versions has to be able
        # to tell "this edition does not print that verse" from "the passage is shorter
        # here", and the length of the array cannot distinguish them.
        "asked": asked,
        "missing": asked - len(verses),
        "verses": verses,
    }


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
    chapters = range(int(span.start.chapter), int(span.end.chapter) + 1)
    carried = _carriers().get(span.book, {})

    versions = []
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
        versions.append(row)

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
        },
        "versions": versions,
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
