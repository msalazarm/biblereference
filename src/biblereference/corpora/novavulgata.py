"""The Nova Vulgata, the Church's current official Latin text.

Two things about it matter more than they might seem to.

**It is numbered by the Hebrew, not by the Vulgate.** Its Psalm 23 is headed
``PSALMUS 23 (22)``, giving the old Greek number in parentheses. So a comparison against
the Clementine has to go through the pivot -- a verse-by-verse diff without it would line
Psalm 22 up against Psalm 22 and report the whole Psalter as divergent.

**It is a revision away from Jerome, not toward him.** Where the Clementine has *Dominus
regit me*, the Nova Vulgata has *Dominus pascit me*. For the question "what did a
fourth-century reader see", the Clementine is the better witness; the Nova Vulgata is the
interesting contrast.

It is under copyright, Libreria Editrice Vaticana, so it is fetched for personal study,
archived, never redistributed, and its notice is emitted -- the same footing as the
NRSVCE.

**It is stored whole, in its own numbering.** This is the Church's official Latin text,
and it numbers as it numbers. An earlier version of this module filed it under the
original-language frame and dropped the chapters that would not fit, which meant deciding
that seventy-odd chapters of an official text were not worth keeping because another
edition divides them differently. They are its chapters. The versification it actually
uses is recorded in ``versification/data/nvl.json``, read off these pages, and every verse
is stored exactly as printed.

Almost everywhere its numbering agrees with the original-language frame, so a citation
converts between them freely. Where it does not, conversion refuses and says so, while the
text stays perfectly citable in the numbering it has.

The pages are hand-built HTML rather than a data file, and inconsistent about everything a
parser might rely on: a verse number usually opens a line but may follow the previous
sentence mid-line, is usually followed by a space but may run straight into the word, and
where there is a space it is as often U+00A0 as a plain one. Genesis opens with a list of
chapter numbers for navigation, which read as a heading turns into a fifty-verse chapter
one. 1 Chronicles 11 prints verse 40 as "0", so the scan looks ahead rather than halting
at a gap. And the edition brackets the verse numbers it omits -- ``(21) 22
Conversantibus...`` at Matthew 17 -- which is recorded, because a verse the edition
deliberately lacks is a different fact from one the parser dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from ..versification import Versification

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

#: Chapters whose numbering was checked against an independent transcription of this
#: edition, and found to be genuinely its own rather than a parsing fault.
#:
#: Kept as provenance. Nothing depends on it now -- the edition is stored in its own
#: numbering throughout -- but it records that these divisions were confirmed from a
#: second source rather than assumed, and it is what caught the one case that was a fault:
#: 1 Chronicles 11 stopped at verse 39 because the Vatican's page prints verse 40 as "0".
VERIFIED_DIFFERENCES: Final[frozenset[tuple[str, int]]] = frozenset(
    {
        ("PSA", 12),
        ("PSA", 44),
        ("JOS", 4),
        ("JOS", 5),
        ("NUM", 24),
        ("NUM", 25),
        ("1SA", 7),
        ("1CH", 20),
        ("JOB", 42),
        ("HOS", 2),
        ("TOB", 5),
        ("1MA", 12),
        ("2MA", 12),
        ("SIR", 5),
    }
)

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

    The pages are inconsistent about all three things a pattern might rely on:

    - the number usually opens a line, but in verse it can follow the previous sentence
      on the same line -- Job 6 runs "...contra me. 5 Numquid rugiet onager";
    - it is usually followed by a space, but Acts 17 opens "1Cum autem perambulassent"
      and Ezekiel 31 has "2“ Fili hominis" with nothing between;
    - the space, where there is one, is as often U+00A0 as a plain space, which
      :func:`_text_of` has already flattened.

    A line start is preferred and a mid-line marker accepted only if there is none.
    Because the search is for one specific expected number rather than any number, a
    figure in the text can only interfere if it happens to be exactly that number.
    """
    at_line = re.search(rf"(?:^|\n)[ \t]*{number}(?!\d)[ \t]*(?=\S)", text)
    if at_line is not None:
        return at_line
    # Not inside parentheses: "(21)" is how this edition marks a verse it omits, and a
    # mid-line pattern loose enough to catch "5 Numquid" will otherwise read the 21 out
    # of the brackets and store the stray ")" as verse 21.
    return re.search(rf"(?<![\d,.:;\-(])(?<!\w){number}(?!\d)[ \t]*(?=[^\s)])", text)


def _split_verses(text: str) -> tuple[dict[int, str], list[int]]:
    verses: dict[int, str] = {}
    omitted: list[int] = []
    number = 1

    # Some chapters leave the first verse unnumbered -- Numbers 1 opens straight into
    # "Locutusque est Dominus ad Moysen" -- so if there is no marker for verse 1 but
    # there is one for verse 2, everything before it is verse 1.
    if _marker(text, 1) is None:
        second = _marker(text, 2)
        if second is not None and second.start() > 0:
            opening = text[: second.start()].strip()
            if opening:
                verses[1] = " ".join(opening.split())
                text = text[second.start() :]
                number = 2

    while True:
        present = _marker(text, number)
        absent = re.search(rf"\(\s*{number}\s*\)", text[: present.start()] if present else text)
        if absent is not None and (present is None or absent.start() < present.start()):
            omitted.append(number)
            text = text[absent.end() :]
            number += 1
            continue
        if present is None:
            # The page may simply have lost a number -- 1 Chronicles 11 prints verse 40
            # as "0" -- so look a little way ahead before giving up. Stopping at the
            # first gap would have cost that chapter its last eight verses.
            ahead = _look_ahead(text, number)
            if ahead is None:
                break
            number = ahead
            continue

        rest = text[present.end() :]
        following, next_number = _next_marker(rest, number)
        body = (rest[: following.start()] if following else rest).strip()
        if body:
            verses[number] = " ".join(body.split())
        if following is None:
            break
        text, number = rest, next_number

    return verses, omitted


#: How far past a missing verse number to keep looking before deciding the chapter is
#: over. Small, so that a genuine end of chapter is not read as a run of gaps.
_LOOKAHEAD: Final = 3


def _look_ahead(text: str, number: int) -> int | None:
    """The next verse number that is actually present, within a few of ``number``."""
    for candidate in range(number + 1, number + 1 + _LOOKAHEAD):
        if _marker(text, candidate) is not None:
            return candidate
    return None


def _next_marker(rest: str, number: int) -> tuple[re.Match[str] | None, int]:
    """Where the next verse starts, and which verse it is."""
    for candidate in range(number + 1, number + 2 + _LOOKAHEAD):
        marker = _marker(rest, candidate)
        skipped = re.search(rf"\(\s*{candidate}\s*\)", rest)
        if skipped is not None and (marker is None or skipped.start() < marker.start()):
            marker = skipped
        if marker is not None:
            return marker, candidate
    return None, number + 1


def build(archive: Path) -> Iterator[BuiltCorpus]:
    """Parse a fetched archive into the corpus, whole.

    The text is stored exactly as the Vatican prints it, in its own numbering. Nothing is
    excluded, renumbered or converted: this is the Church's official Latin text, and
    bending it to another edition's verse divisions would mean either dropping the
    chapters that do not fit or silently moving their seams.

    Where its numbering agrees with the original-language frame -- which is almost
    everywhere -- a citation converts between them freely. Where it does not, the
    versification data says so and conversion refuses, while the text itself stays
    perfectly citable in the numbering it actually has.
    """
    versification = Versification.load()
    verses: list[tuple[VerseRef, str]] = []
    notes: list[str] = []
    done: set[str] = set()

    for slug, (_, code) in _BOOKS.items():
        path = archive / f"{slug}.html"
        if not path.exists() or code in done:
            continue
        done.add(code)

        chapters, omissions = parse_book(
            path.read_text(encoding="utf-8", errors="replace"),
            single_chapter=versification.chapter_count("nvl", code) == 1,
        )
        if not chapters:
            notes.append(f"{code}: nothing parsed")
            continue

        expected = versification.chapter_count("nvl", code)
        if expected and len(chapters) != expected:
            notes.append(
                f"{code}: parsed {len(chapters)} chapters where its own versification "
                f"records {expected} -- the pages may have changed"
            )

        for chapter, found in sorted(chapters.items()):
            for verse, text in sorted(found.items()):
                verses.append((VerseRef(book=code, chapter=chapter, verse=verse, vrs="nvl"), text))

        gaps = {c: v for c, v in omissions.items() if v}
        if gaps:
            rendered = ", ".join(
                f"{c}:{', '.join(str(x) for x in v)}" for c, v in sorted(gaps.items())
            )
            notes.append(f"{code}: verses the edition itself omits -- {rendered}")

    blocked = versification.unmappable_chapters("nvl")
    if blocked:
        books = sorted({book for book, _ in blocked})
        notes.append(
            f"{len(blocked)} chapter(s) of this edition are numbered differently from the "
            f"original-language frame and so cannot be cross-referenced to it, in "
            f"{', '.join(books)}. They are stored in full and citable in Nova Vulgata "
            f"numbering."
        )

    yield BuiltCorpus(
        id="novavulgata",
        label="Nova Vulgata",
        language="la",
        versification="nvl",
        verses=verses,
        notes=notes,
    )
