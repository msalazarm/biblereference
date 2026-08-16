"""Codex Bezae's Latin column: a fifth Old Latin witness, and the first with Acts.

Bezae is the famous bilingual — Greek on the verso, Latin on the recto, 5th century, the
principal witness to the "Western" text. The library's two Old Latin codices (Vercellensis,
Veronensis) are gospels only; Bezae's Latin brings a third gospel witness *and the book of
Acts*, which no pre-Vulgate Latin here covered at all. A Latin father quoting a Western
reading of Acts had nothing to match against before this.

The transcription is the International Greek New Testament Project's, published by the
University of Birmingham as TEI (epapers.bham.ac.uk/1664). Its own header licenses it
**CC BY-NC-SA** — the survey that found it reported plain CC BY, and the header is what
governs. Non-commercial share-alike is a licence class this library already records and
reports; the text is fetched, never redistributed.

What is taken is the **first hand**: where the manuscript's correctors intervene the TEI
carries both readings in an ``app``, and the ``orig`` reading is the manuscript as written,
which is what a father contemporary with it could have read. Running titles, quire
signatures and marginal chapter numbers are apparatus of the page, not of the text, and are
dropped. The manuscript is lacunose — Matthew begins at 1:12 — and the holes stay holes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lxml import etree

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_TEI: Final = "{http://www.tei-c.org/ns/1.0}"

#: The TEI's book names to USFM codes.
_BOOKS: Final = {
    "Matthew": "MAT",
    "Mark": "MRK",
    "Luke": "LUK",
    "John": "JHN",
    "Acts": "ACT",
    # 3 John survives only as a fragment of its Latin ending in Bezae; if the div appears,
    # take it.
    "3 John": "3JN",
}

#: Page furniture, not text.
_SKIP: Final = frozenset({f"{_TEI}fw", f"{_TEI}note", f"{_TEI}num"})


def _words(element: etree._Element) -> Iterator[str]:
    """The first hand's words of one verse, in order.

    Walked rather than ``itertext``, because three kinds of children lie about being text:
    page furniture (running titles, quire marks), marginal chapter numbers, and the
    correctors' readings — an ``app`` holds the verse's word twice, and taking both would
    print every corrected word doubled.

    Within a ``w``, only letters are the word. Everything else the transcription puts
    there is *about* the word: the newline of a ``lb`` splitting it across lines
    (``con⏎seruo``), a lacuna's extent inside ``supplied`` (``6-7`` for "six or seven
    letters lost", leaving the surviving ``te``), the omission sign ``⸆`` standing as an
    ``orig`` reading's whole content ("the first hand has nothing here"), rows of ``∫``
    that transcribe the scribe's red-ink line fillers, and verse-number artefacts like
    ``19>``. Dropping non-letters reconstitutes the split words and makes the pure
    notation words vanish, which is what a searchable text wants.
    """
    for child in element:
        if child.tag in _SKIP:
            continue
        if child.tag == f"{_TEI}app":
            for reading in child.findall(f"{_TEI}rdg"):
                if reading.get("type") == "orig":
                    yield from _words(reading)
            continue
        if child.tag == f"{_TEI}w":
            word = "".join(ch for ch in "".join(child.itertext()) if ch.isalpha())
            if word:
                yield word
            continue
        yield from _words(child)


def build(archive: Path) -> Iterator[BuiltCorpus]:
    tree = etree.parse(str(archive / "Bezae-Latin.xml"))
    verses: list[tuple[VerseRef, str]] = []
    notes: list[str] = []
    unknown: set[str] = set()

    for div in tree.iter(f"{_TEI}div"):
        if div.get("type") != "book":
            continue
        name = div.get("n") or ""
        book = _BOOKS.get(name)
        if book is None:
            unknown.add(name)
            continue
        for ab in div.iter(f"{_TEI}ab"):
            # IGNTP reference: B01K1V12 -> book 01, chapter 1, verse 12.
            n = ab.get("n") or ""
            if "K" not in n or "V" not in n:
                continue
            chapter, _, verse = n.partition("K")[2].partition("V")
            if not chapter.isdigit() or not verse.isdigit():
                notes.append(f"{name}: unreadable reference {n!r}, skipped")
                continue
            text = " ".join(_words(ab))
            if text:
                verses.append((VerseRef(book, int(chapter), int(verse), vrs="org"), text))

    for name in sorted(unknown):
        notes.append(f"book {name!r} not imported: no USFM mapping")
    yield BuiltCorpus(
        id="bezae-lat",
        label="Codex Bezae, Latin column (IGNTP transcription)",
        language="la",
        versification="org",
        verses=verses,
        notes=notes,
    )


SOURCE: Final = Source(
    id="bezae",
    label="Codex Bezae Cantabrigiensis, Latin column — IGNTP/Birmingham",
    homepage="https://epapers.bham.ac.uk/1664/",
    license="CC BY-NC-SA, per the TEI header: "
    '"licensed as ShareAlike (Creative Commons by-nc-sa)".',
    terms=get("cc-by-nc-sa-4.0"),
    attribution=(
        "Latin transcription of Codex Bezae by the International Greek New Testament "
        "Project, University of Birmingham, used under CC BY-NC-SA."
    ),
    files=(
        RemoteFile(
            url="http://epapers.bham.ac.uk/id/eprint/1664/1/Bezae-Latin.xml",
            name="Bezae-Latin.xml",
        ),
    ),
    build=build,
)
