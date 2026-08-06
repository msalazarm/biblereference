"""Westcott and Hort's Greek New Testament, from Perseus.

    B. F. Westcott and F. J. A. Hort, *The New Testament in the Original Greek*.
    New York: Harper and Brothers, 1882-1892.

The edition modern New Testament textual criticism is built on, and the library held
nothing of it: for the Greek New Testament it had Nestle 1904 and, since the Patristic
Text Archive arrived, the SBLGNT. Having Westcott-Hort beside them makes a variant
visible where two texts would only make it arguable.

It sits under ``tlg0031`` in the *Greek* Perseus repository, nowhere near anything called
a Bible, which is why three passes over the catalogue missed it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lxml import etree

from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .tei import cts_verses, read_licence

__all__ = ["SOURCE", "build"]

_RAW: Final = "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0031"

#: ``tlg001`` to ``tlg027`` in canonical order, verified by reading each file's own title:
#: Ματθαίος, Μάρκον, Λουκᾶν, Ἰωάννην, Πράξεις, then the epistles with Hebrews at
#: ``tlg019`` where the tradition puts it, and Ἀποκάλυψις last.
BOOKS: Final[tuple[str, ...]] = tuple(
    (
        "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS "
        "1PE 2PE 1JN 2JN 3JN JUD REV"
    ).split()
)


def _name(index: int) -> str:
    return f"tlg0031.tlg{index:03d}.perseus-grc2.xml"


def build(archive: Path) -> Iterator[BuiltCorpus]:
    verses: list[tuple[VerseRef, str]] = []
    licences = set()
    missing: list[str] = []
    for index, book in enumerate(BOOKS, start=1):
        path = archive / _name(index)
        if not path.exists():
            missing.append(book)
            continue
        found = read_licence(path)
        if found is not None:
            licences.add(found)
        for chapter, verse, subverse, text in cts_verses(etree.parse(str(path))):
            verses.append((VerseRef(book, chapter, verse, subverse), text))

    notes = []
    if missing:
        notes.append(f"absent from the archive: {', '.join(missing)}")
    yield BuiltCorpus(
        id="wh",
        label="The New Testament in the Original Greek — Westcott and Hort 1881",
        language="grc",
        # The New Testament is numbered alike everywhere; `org` is the frame `n1904` and
        # the SBLGNT already use, so the three are directly comparable.
        versification="org",
        verses=verses,
        notes=notes,
        licence=next(iter(licences), None),
        licences=tuple(sorted(licences, key=lambda item: item.id)),
    )


SOURCE: Final = Source(
    id="perseus-wh",
    label="Westcott-Hort Greek New Testament — Perseus",
    homepage="https://github.com/PerseusDL/canonical-greekLit",
    license="CC BY-SA 4.0.",
    files=tuple(
        RemoteFile(url=f"{_RAW}/tlg{index:03d}/{_name(index)}", name=_name(index))
        for index in range(1, len(BOOKS) + 1)
    ),
    build=lambda archive: build(archive),
)
