"""The Nova Vulgata, the Church's current official Latin text.

Two things about it matter more than they might seem to.

**It is numbered by the Hebrew, not by the Vulgate.** Its Psalm 23 is headed
``PSALMUS 23 (22)``, giving the old Greek number in parentheses. So this corpus declares
``org``, and a comparison against the Clementine has to go through the pivot -- a
verse-by-verse diff without it would line Psalm 22 up against Psalm 22 and report the
whole Psalter as divergent.

**It is a revision away from Jerome, not toward him.** Where the Clementine has *Dominus
regit me*, the Nova Vulgata has *Dominus pascit me*. For the question "what did a
fourth-century reader see", the Clementine is the better witness; the Nova Vulgata is the
interesting contrast.

It is under copyright, Libreria Editrice Vaticana, so it is fetched for personal study,
archived, never redistributed, and its notice is emitted -- the same footing as the
NRSVCE.

The pages are hand-built HTML rather than a data file, so nothing here is trusted on
faith: every book is checked against the pivot's own verse counts as it is parsed, and a
book that does not reconcile is left out with a note rather than indexed wrongly. The
edition also brackets the verse numbers it omits -- ``(21) 22 Conversantibus...`` at
Matthew 17 -- which is recorded, because a missing verse that the edition deliberately
lacks is a different fact from one the parser dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from ..versification import (
    VerseOutOfRangeError,
    Versification,
    VersificationError,
)

__all__ = ["SOURCE", "build", "parse_book"]

_BASE: Final = "https://www.vatican.va/archive/bible/nova_vulgata/documents"

#: The Vatican's Latin slugs, and the USFM codes they answer to.
_OLD_TESTAMENT: Final[dict[str, str]] = {
    "genesis": "GEN",
    "exodus": "EXO",
    "leviticus": "LEV",
    "numeri": "NUM",
    "deuteronomii": "DEU",
    "iosue": "JOS",
    "iudicum": "JDG",
    "ruth": "RUT",
    "i-samuelis": "1SA",
    "ii-samuelis": "2SA",
    "i-regum": "1KI",
    "ii-regum": "2KI",
    "i-paralipomenon": "1CH",
    "ii-paralipomenon": "2CH",
    "esdrae": "EZR",
    "nehemiae": "NEH",
    "thobis": "TOB",
    "iudith": "JDT",
    "esther": "EST",
    "i-maccabaeorum": "1MA",
    "ii-maccabaeorum": "2MA",
    "iob": "JOB",
    "psalmorum": "PSA",
    "proverbiorum": "PRO",
    "ecclesiastes": "ECC",
    "canticum-canticorum": "SNG",
    "sapientiae": "WIS",
    "ecclesiasticus": "SIR",
    "isaiae": "ISA",
    "ieremiae": "JER",
    "lamentationes": "LAM",
    "baruch": "BAR",
    "ezechielis": "EZK",
    "danielis": "DAN",
    "osee": "HOS",
    "ioel": "JOL",
    "amos": "AMO",
    "abdiae": "OBA",
    "ionae": "JON",
    "michaeae": "MIC",
    "nahum": "NAM",
    "habacuc": "HAB",
    "sophoniae": "ZEP",
    "aggaei": "HAG",
    "zachariae": "ZEC",
    "malachiae": "MAL",
}

_NEW_TESTAMENT: Final[dict[str, str]] = {
    "evang-matthaeum": "MAT",
    "evang-marcum": "MRK",
    "evang-lucam": "LUK",
    "evang-ioannem": "JHN",
    "actus-apostolorum": "ACT",
    "epist-romanos": "ROM",
    "epist-i-corinthios": "1CO",
    "epist-ii-corinthios": "2CO",
    "epist-galatas": "GAL",
    "epist-ephesios": "EPH",
    "epist-philippenses": "PHP",
    "epist-colossenses": "COL",
    "epist-i-thessalonicenses": "1TH",
    "epist-ii-thessalonicenses": "2TH",
    "epist-i-timotheum": "1TI",
    "epist-ii-timotheum": "2TI",
    "epist-titum": "TIT",
    "epist-philemonem": "PHM",
    "epist-hebraeos": "HEB",
    "epist-iacobi": "JAS",
    "epist-i-petri": "1PE",
    "epist-ii-petri": "2PE",
    "epist-i-ioannis": "1JN",
    "epist-ii-ioannis": "2JN",
    "epist-iii-ioannis": "3JN",
    "epist-iudae": "JUD",
    "epist-apocalypsis-ioannis": "REV",
    "apocalypsis-ioannis": "REV",
}

_BOOKS: Final[dict[str, tuple[str, str]]] = {
    **{slug: ("vt", code) for slug, code in _OLD_TESTAMENT.items()},
    **{slug: ("nt", code) for slug, code in _NEW_TESTAMENT.items()},
}

#: The Psalter anchors chapters by name rather than by number: ``PSALMUS 23``.
_PSALM_ANCHOR_RE: Final = re.compile(r"^\s*PSALMUS\s+(\d+)")

#: Books the Nova Vulgata numbers by the Hebrew but arranges like the Vulgate, keeping
#: the deuterocanonical additions inside their host: Susanna and Bel as Daniel 13 and 14,
#: the Letter of Jeremiah as Baruch 6. Verified from the pages themselves -- its Daniel
#: has fourteen chapters with chapter 3 running to verse 100, which is the Vulgate's
#: shape, while its Esther has the Hebrew's ten. These are read in Vulgate numbering and
#: converted, rather than being given a mapping of their own.
_VULGATE_ARRANGEMENT: Final = frozenset({"DAN", "BAR"})

SOURCE: Final = Source(
    id="novavulgata",
    label="Nova Vulgata",
    homepage=f"{_BASE}/nova-vulgata_index_lt.html",
    license=(
        "Nova Vulgata, copyright Libreria Editrice Vaticana. Fetched for personal study "
        "and archived; not redistributed."
    ),
    attribution=(
        "Latin: Nova Vulgata, Bibliorum Sacrorum Editio, © Libreria Editrice Vaticana. "
        "Used for private study."
    ),
    files=tuple(
        RemoteFile(
            url=f"{_BASE}/nova-vulgata_{testament}_{slug}_lt.html",
            name=f"{slug}.html",
        )
        for slug, (testament, _) in _BOOKS.items()
        if slug != "epist-apocalypsis-ioannis"
    ),
    build=lambda archive: build(archive),
    note="The Church's current official Latin, numbered by the Hebrew.",
    crawl_delay=2.0,  # vatican.va publishes Crawl-delay: 2
)


def _paragraphs(html: str) -> list[object]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")
    return list(soup.find_all("p"))


def _text_of(paragraph: object) -> str:
    """A paragraph's text with non-breaking spaces flattened.

    The pages separate a verse number from its verse with U+00A0 as often as with a plain
    space, and a pattern that only knows about spaces and tabs silently fails to find the
    marker -- which then reads as a missing verse rather than a parsing fault.
    """
    text: str = paragraph.get_text("", strip=False)  # type: ignore[attr-defined]
    return text.replace("\xa0", " ").replace("\u2009", " ").replace("\u202f", " ")


def parse_book(
    html: str, *, single_chapter: bool = False
) -> tuple[dict[int, dict[int, str]], dict[int, list[int]]]:
    """Read one book page into ``({chapter: {verse: text}}, {chapter: [omitted]})``.

    A chapter is identified only by its anchor -- a numeric one, or the Psalter's
    ``PSALMUS 23`` -- never by a leading digit. The pages open with a list of chapter
    numbers for navigation, and reading a bare digit as a heading turns that list into a
    fifty-verse Genesis 1.

    :param single_chapter: For the five one-chapter books, which have no anchors at all.
    """
    chapters: dict[int, dict[int, str]] = {}
    omissions: dict[int, list[int]] = {}

    for paragraph in _paragraphs(html):
        text = _text_of(paragraph)
        if len(text) < 80:
            continue

        chapter = _chapter_of(paragraph)
        if chapter is None and single_chapter and not chapters:
            chapter = 1
        if chapter is None:
            continue

        text = _drop_heading(text)

        verses, omitted = _split_verses(text)
        if verses:
            chapters[chapter] = verses
            omissions[chapter] = omitted

    return chapters, omissions


#: A chapter heading opening a paragraph: a bare number, or "PSALMUS 12 (11)" giving the
#: Hebrew number and the Greek one it replaced.
_HEADING_RE: Final = re.compile(
    r"^[ \t]*(?:PSALMUS|CAPUT|CAP\.)?[ \t]*\d+[ \t]*(?:\([^)]*\))?[ \t]*\n"
)


def _drop_heading(text: str) -> str:
    """Remove the chapter heading, so that it cannot be read as verse text.

    The Psalter's headings matter here beyond tidiness. ``PSALMUS 12 (11)`` carries the
    old Greek number in parentheses, and the parenthesised form is exactly how this
    edition marks a verse it omits -- so an unremoved heading makes Psalm 12 appear to be
    missing its eleventh verse.
    """
    match = _HEADING_RE.match(text)
    return text[match.end() :] if match else text


def _chapter_of(paragraph: object) -> int | None:
    """The chapter a paragraph belongs to, by its anchor alone."""
    for anchor in paragraph.find_all("a", attrs={"name": True}):  # type: ignore[attr-defined]
        name = str(anchor["name"]).strip()
        if name.isdigit():
            return int(name)
        psalm = _PSALM_ANCHOR_RE.match(name)
        if psalm:
            return int(psalm.group(1))
    return None


def _marker(text: str, number: int) -> re.Match[str] | None:
    """Where verse ``number`` begins, or ``None``.

    Usually a number opening a line. In verse it can also follow the end of the previous
    sentence on the same line -- Job 6 runs "...contra me. 5 Numquid rugiet onager" -- so
    a line start is preferred and a mid-line marker accepted after it. Because the search
    is for one specific expected number rather than any number, a figure in the text can
    only interfere if it happens to be exactly that number.
    """
    at_line = re.search(rf"(?:^|\n)[ \t]*{number}\s+", text)
    if at_line is not None:
        return at_line
    return re.search(rf"(?<![\d,.:;-]){number}\s+(?=\S)", text)


def _split_verses(text: str) -> tuple[dict[int, str], list[int]]:
    verses: dict[int, str] = {}
    omitted: list[int] = []
    number = 1

    while True:
        present = _marker(text, number)
        absent = re.search(rf"\(\s*{number}\s*\)", text[: present.start()] if present else text)
        if absent is not None and (present is None or absent.start() < present.start()):
            omitted.append(number)
            text = text[absent.end() :]
            number += 1
            continue
        if present is None:
            break

        rest = text[present.end() :]
        following = _marker(rest, number + 1)
        skipped = re.search(rf"\(\s*{number + 1}\s*\)", rest)
        if skipped is not None and (following is None or skipped.start() < following.start()):
            following = skipped
        body = (rest[: following.start()] if following else rest).strip()
        if body:
            verses[number] = " ".join(body.split())
        if following is None:
            break
        text, number = rest, number + 1

    return verses, omitted


def build(archive: Path) -> Iterator[BuiltCorpus]:
    """Parse a fetched archive, checking every book against the pivot as it goes."""
    versification = Versification.load()
    verses: list[tuple[VerseRef, str]] = []
    notes: list[str] = []

    for slug, (_, code) in _BOOKS.items():
        path = archive / f"{slug}.html"
        if not path.exists():
            continue

        source_vrs = "vul" if code in _VULGATE_ARRANGEMENT else "org"
        chapters, omissions = parse_book(
            path.read_text(encoding="utf-8", errors="replace"),
            single_chapter=versification.chapter_count(source_vrs, code) == 1,
        )

        problem = _reconcile(versification, source_vrs, code, chapters)
        if problem is not None:
            notes.append(f"{code}: not indexed -- {problem}")
            continue

        for chapter, found in sorted(chapters.items()):
            for verse, text in sorted(found.items()):
                ref = VerseRef(book=code, chapter=chapter, verse=verse, vrs=source_vrs)
                verses.extend((target, text) for target in _to_pivot(versification, ref))

        gaps = {c: v for c, v in omissions.items() if v}
        if gaps:
            rendered = ", ".join(
                f"{c}:{', '.join(str(x) for x in v)}" for c, v in sorted(gaps.items())
            )
            notes.append(f"{code}: verses the edition itself omits -- {rendered}")

    notes.append(
        "Daniel and Baruch are read in Vulgate numbering and converted: the Nova Vulgata "
        "numbers by the Hebrew but keeps the Vulgate's arrangement of the additions, so "
        "its Daniel 13 and 14 are Susanna and Bel, and its Baruch 6 is the Letter of "
        "Jeremiah."
    )

    yield BuiltCorpus(
        id="novavulgata",
        label="Nova Vulgata",
        language="la",
        versification="org",
        verses=verses,
        notes=notes,
    )


def _to_pivot(versification: Versification, ref: VerseRef) -> list[VerseRef]:
    """Put a parsed verse into the pivot's numbering, or drop it if it will not go."""
    if ref.vrs == "org":
        return [ref]
    try:
        return versification.convert_all(ref, "org")
    except VersificationError:
        return []


def _reconcile(
    versification: Versification,
    vrs: str,
    book: str,
    chapters: dict[int, dict[int, str]],
) -> str | None:
    """Why this book should not be indexed, or ``None`` if it checks out.

    The test is the highest verse number of each chapter against the reference numbering,
    not the count: the edition omits verses on purpose, and a gap it declares is not an
    error.
    """
    if not chapters:
        return "no chapters parsed"

    expected = versification.chapter_count(vrs, book)
    if expected and len(chapters) != expected:
        return f"parsed {len(chapters)} chapters, {vrs} numbering has {expected}"

    for chapter, found in chapters.items():
        try:
            limit = versification.max_verse(vrs, book, chapter)
        except VerseOutOfRangeError:
            return f"chapter {chapter} is not in {vrs} numbering"
        highest = max(found)
        if highest != limit:
            return f"chapter {chapter} parsed to verse {highest}, {vrs} numbering has {limit}"
    return None
