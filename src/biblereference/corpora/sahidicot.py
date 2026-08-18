"""The Sahidic Old Testament: Coptic Scriptorium's CoptOT corpus, whole.

Before this the library's entire Coptic holding was 45 verses of Mark; quotes.md §11
lists this corpus — Pentateuch through Jeremiah with the full Psalter, CC BY-SA 4.0 —
as the Coptic breadth row. The Sahidic version is a third-century translation of the
Septuagint: Shenoute quotes toward this wording, and the Greek fathers' Egyptian
readers read it.

The upstream distributes one TreeTagger (TT) file per chapter, tokenised to
morph-level ``<norm>`` elements inside ``<norm_group>`` bound groups inside
``<verse_n>`` elements whose ``vname`` names the verse ("Genesis 1:1"). The verse text
here is the sequence of *bound groups* — ``norm_group="ϩⲛⲧⲁⲣⲭⲏ"`` — which is how Coptic
is conventionally printed; the morph splits are the annotators' layer, not the text.
Their own header warns "versification may not always align with traditional Septuagint
versification": the coordinates are stored as ``lxx`` (the books are Septuagint books;
the translation column is Brenton) and the warning is kept as a note.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from html import unescape
from pathlib import Path
from typing import Final

from ..canon import AmbiguousBookError, UnknownBookError, resolve_book
from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_ZIP: Final = "sahidic.ot_TT.zip"

_VERSE_RE: Final = re.compile(r'<verse_n [^>]*vname="([^"]+)"')
_GROUP_RE: Final = re.compile(r'<norm_group [^>]*norm_group="([^"]+)"')
_NAME_RE: Final = re.compile(r"^(.*\S) (\d+):(\d+)$")


def _verses(body: str) -> Iterator[tuple[str, int, int, str]]:
    """``(book name, chapter, verse, text)`` from one chapter file."""
    name = ""
    held: list[str] = []

    def flush() -> Iterator[tuple[str, int, int, str]]:
        mark = _NAME_RE.match(name)
        # Chapter 0 is the upstream's slot for paratext -- a book's incipit line, a
        # subscriptio -- one pseudo-verse each, not scripture coordinates.
        if mark and held and int(mark.group(2)) > 0 and int(mark.group(3)) > 0:
            yield (mark.group(1), int(mark.group(2)), int(mark.group(3)), " ".join(held))

    for line in body.splitlines():
        opened = _VERSE_RE.match(line)
        if opened:
            yield from flush()
            name = unescape(opened.group(1))
            held = []
            continue
        grouped = _GROUP_RE.match(line)
        if grouped:
            held.append(unescape(grouped.group(1)))
    yield from flush()


def build(archive: Path) -> Iterator[BuiltCorpus]:
    verses: list[tuple[VerseRef, str]] = []
    unknown: set[str] = set()
    with zipfile.ZipFile(archive / _ZIP) as bundle:
        for member in sorted(bundle.namelist()):
            if not member.endswith(".tt"):
                continue
            for name, chapter, verse, text in _verses(bundle.read(member).decode("utf-8")):
                try:
                    book = resolve_book(name)
                except (UnknownBookError, AmbiguousBookError):
                    unknown.add(name)
                    continue
                verses.append((VerseRef(book, chapter, verse, vrs="lxx"), text))
    notes = [
        "text is the bound-group layer (norm_group), the conventional printed form; "
        "the morph tokenisation is the annotators' layer and is not stored",
        'the upstream warns "versification may not always align with traditional '
        'Septuagint versification"; coordinates are stored as the lxx they declare',
        "chapter-0 paratext (incipits, the Isaiah subscriptio) skipped: one "
        "pseudo-verse each, not scripture",
    ]
    if unknown:
        notes.append(
            "books outside this library's canon, not indexed: " + ", ".join(sorted(unknown))
        )
    yield BuiltCorpus(
        id="sahot",
        label="Sahidic Old Testament (Coptic Scriptorium CoptOT)",
        language="cop",
        versification="lxx",
        verses=verses,
        notes=notes,
    )


SOURCE: Final = Source(
    id="sahidicot",
    label="Coptic Scriptorium Sahidic Old Testament (CoptOT)",
    homepage="https://copticscriptorium.org/download/corpora/sahidic_bible_ot.html",
    license="CC BY-SA 4.0, declared in every file's own metadata header. ShareAlike "
    "binds published derivative datasets, tracked in licences.py; the search index is "
    "internal and nothing from it is redistributed.",
    terms=get("cc-by-sa-4.0"),
    attribution="CoptOT / Coptic SCRIPTORIUM / KELLIA (Feder, Miyagawa, Platte, "
    "Schroeder, Zeldes), used under CC BY-SA 4.0.",
    files=(
        RemoteFile(
            url="https://raw.githubusercontent.com/CopticScriptorium/corpora/master/"
            "sahidic.ot/sahidic.ot_TT.zip",
            name=_ZIP,
        ),
    ),
    build=build,
    note="The Coptic breadth row of quotes.md §11; the library's Coptic holding grows "
    "from 45 verses to the Old Testament.",
)
