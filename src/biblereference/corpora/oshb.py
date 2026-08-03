"""The Hebrew Bible: Westminster Leningrad Codex, via Open Scriptures.

The WLC is a diplomatic edition of Leningrad B19A -- the same manuscript BHS prints,
without BHS's apparatus, which is under copyright. Open Scriptures marks it up as OSIS
XML with one file per book.

Reconstructing a verse is a matter of walking its children in order. ``<w>`` elements
hold words, in which ``/`` divides morphemes and is not part of the text; ``<seg>``
elements hold the maqqef and sof pasuq, which attach to the preceding word without a
space. The markup encodes that spacing in its own whitespace, so the tail of each element
says whether a space follows -- which is more reliable than guessing from the character.

``<note>`` elements carry Ketiv/Qere apparatus and are skipped: this is a text, not an
edition.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lxml import etree

from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build", "parse_book"]

_RAW: Final = "https://raw.githubusercontent.com/openscriptures/morphhb/master/wlc"

#: OSHB filename stem to USFM code. Thirty-nine books: the Hebrew canon.
_BOOKS: Final[dict[str, str]] = {
    "Gen": "GEN",
    "Exod": "EXO",
    "Lev": "LEV",
    "Num": "NUM",
    "Deut": "DEU",
    "Josh": "JOS",
    "Judg": "JDG",
    "Ruth": "RUT",
    "1Sam": "1SA",
    "2Sam": "2SA",
    "1Kgs": "1KI",
    "2Kgs": "2KI",
    "1Chr": "1CH",
    "2Chr": "2CH",
    "Ezra": "EZR",
    "Neh": "NEH",
    "Esth": "EST",
    "Job": "JOB",
    "Ps": "PSA",
    "Prov": "PRO",
    "Eccl": "ECC",
    "Song": "SNG",
    "Isa": "ISA",
    "Jer": "JER",
    "Lam": "LAM",
    "Ezek": "EZK",
    "Dan": "DAN",
    "Hos": "HOS",
    "Joel": "JOL",
    "Amos": "AMO",
    "Obad": "OBA",
    "Jonah": "JON",
    "Mic": "MIC",
    "Nah": "NAM",
    "Hab": "HAB",
    "Zeph": "ZEP",
    "Hag": "HAG",
    "Zech": "ZEC",
    "Mal": "MAL",
}

_OSIS_NS: Final = "http://www.bibletechnologies.net/2003/OSIS/namespace"
_VERSE_ID: Final = re.compile(r"^(?P<book>[\w.]+?)\.(?P<chapter>\d+)\.(?P<verse>\d+)$")

SOURCE: Final = Source(
    id="oshb",
    label="Westminster Leningrad Codex",
    homepage="https://github.com/openscriptures/morphhb",
    license="Text: public domain. Lemma and morphology: CC BY 4.0.",
    attribution=(
        "Hebrew: Westminster Leningrad Codex, via the Open Scriptures Hebrew Bible "
        "(https://github.com/openscriptures/morphhb). Text public domain."
    ),
    files=tuple(RemoteFile(url=f"{_RAW}/{stem}.xml", name=f"{stem}.xml") for stem in _BOOKS),
    build=lambda archive: build(archive),
    note="One OSIS XML file per book of the Hebrew canon.",
)


def parse_book(path: Path, book: str) -> Iterator[tuple[VerseRef, str]]:
    """Read one OSIS book file into verses."""
    tree = etree.parse(str(path))
    for element in tree.iter(f"{{{_OSIS_NS}}}verse"):
        osis_id = element.get("osisID")
        if not osis_id:
            continue
        match = _VERSE_ID.match(osis_id)
        if not match:
            continue
        text = _verse_text(element)
        if text:
            yield (
                VerseRef(
                    book=book,
                    chapter=int(match["chapter"]),
                    verse=int(match["verse"]),
                    vrs="org",
                ),
                text,
            )


def _verse_text(verse: etree._Element) -> str:
    """Join a verse's words and punctuation, honouring the markup's own spacing."""
    parts: list[str] = []
    for child in verse:
        tag = etree.QName(child).localname
        if tag == "w":
            parts.append(_word(child))
        elif tag == "seg":
            parts.append("".join(child.itertext()))
        else:
            continue  # <note>: Ketiv/Qere apparatus, not the text
        if child.tail is not None:
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _word(element: etree._Element) -> str:
    """A word's consonants and points, with the morpheme dividers removed."""
    return "".join(element.itertext()).replace("/", "")


def build(archive: Path) -> Iterator[BuiltCorpus]:
    """Parse a fetched archive into the Hebrew corpus."""
    verses: list[tuple[VerseRef, str]] = []
    notes: list[str] = []
    for stem, book in _BOOKS.items():
        path = archive / f"{stem}.xml"
        if not path.exists():
            notes.append(f"missing {stem}.xml, so {book} is absent")
            continue
        verses.extend(parse_book(path, book))

    yield BuiltCorpus(
        id="wlc",
        label="Westminster Leningrad Codex",
        language="hbo",
        versification="org",
        verses=verses,
        notes=notes,
    )
