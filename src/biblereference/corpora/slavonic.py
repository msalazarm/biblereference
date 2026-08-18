"""The Elizabeth Bible (1751/1757): the Church Slavonic scripture of the Orthodox world.

quotes.md §11's breadth ledger calls it the only fully open Slavonic scripture found —
CrossWire's ``CSlElizabeth`` module, public domain, from rusbible.ru with modernised
spelling. It positions the Slavonic extension the way Van Dyck positions the Arabic one:
no father quotes it, but the tradition that quotes the fathers reads it.

The upstream is a SWORD **zText** module, decoded here directly rather than through a
GPL dependency: three files per testament — ``.bzv`` (10 bytes per verse slot: block,
offset, length), ``.bzs`` (12 bytes per block: where its zlib stream lies), ``.bzz``
(the streams) — with one block per book (``BlockType=BOOK``). Slot order follows the
module's Synodal canon, but the canon table itself is not needed: the OSIS text carries
its own ``<div osisID="Gen">`` and ``<chapter osisID="Gen.1">`` markers in the heading
slots, and the walk validates them as it goes — a book marker must open at chapter 0, a
chapter marker must name the open book and the next chapter number, and anything that
breaks the pattern refuses the build rather than misfiling a verse. Verse numbers are
positional within the open chapter, which is exactly what the canon's slots mean.
"""

from __future__ import annotations

import re
import struct
import zipfile
import zlib
from collections.abc import Iterator
from html import unescape
from pathlib import Path
from typing import Final

from ..canon import AmbiguousBookError, UnknownBookError, resolve_book
from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_ZIP: Final = "CSlElizabeth.zip"
_BASE: Final = "modules/texts/ztext/cslelizabeth/"

_BOOK_RE: Final = re.compile(r'<div osisID="([^".]+)"[^>]*type="book"')
_CHAPTER_RE: Final = re.compile(r'<chapter osisID="([^".]+)\.(\d+)"')
_NOTE_RE: Final = re.compile(r"<note[^>]*>.*?</note>", re.S)
_TAG_RE: Final = re.compile(r"<[^>]+>")


def _plain(markup: str) -> str:
    """OSIS to text: notes go whole -- they are the editor's voice, not scripture --
    then every tag, then entities, then whitespace."""
    return " ".join(unescape(_TAG_RE.sub(" ", _NOTE_RE.sub(" ", markup))).split())


def _slots(archive: Path, testament: str) -> Iterator[str]:
    """Every verse slot's raw markup, in canon order. Empty slots yield ``""``."""
    with zipfile.ZipFile(archive / _ZIP) as bundle:
        index = bundle.read(f"{_BASE}{testament}.bzv")
        blocks = bundle.read(f"{_BASE}{testament}.bzs")
        data = bundle.read(f"{_BASE}{testament}.bzz")
    held: dict[int, bytes] = {}
    for at in range(0, len(index) - 9, 10):
        block, start, size = struct.unpack("<IIH", index[at : at + 10])
        if not size:
            yield ""
            continue
        if block not in held:
            offset, packed, _ = struct.unpack("<III", blocks[block * 12 : block * 12 + 12])
            held.clear()  # one block per book; the walk never looks back
            held[block] = zlib.decompress(data[offset : offset + packed])
        yield held[block][start : start + size].decode("utf-8")


def _walk(archive: Path, testament: str) -> Iterator[tuple[str, int, int, str]]:
    """``(osis book, chapter, verse, text)`` from one testament, marker-validated."""
    book = ""
    chapter = 0
    verse = 0
    for markup in _slots(archive, testament):
        opened = _BOOK_RE.search(markup)
        if opened:
            book, chapter, verse = opened.group(1), 0, 0
            continue
        turned = _CHAPTER_RE.search(markup)
        if turned:
            if turned.group(1) != book or int(turned.group(2)) != chapter + 1:
                raise ValueError(
                    f"chapter marker {turned.group(0)!r} does not follow "
                    f"{book} {chapter} -- the slot walk is off, refusing to misfile"
                )
            chapter, verse = chapter + 1, 0
            continue
        if not book or not chapter:
            continue  # module and testament headings live before any open chapter
        verse += 1
        text = _plain(markup)
        if text:
            yield (book, chapter, verse, text)


def build(archive: Path) -> Iterator[BuiltCorpus]:
    verses: list[tuple[VerseRef, str]] = []
    unknown: set[str] = set()
    for testament in ("ot", "nt"):
        for osis, chapter, verse, text in _walk(archive, testament):
            try:
                book = resolve_book(osis)
            except (UnknownBookError, AmbiguousBookError):
                unknown.add(osis)
                continue
            verses.append((VerseRef(book, chapter, verse, vrs="rso"), text))
    notes = [
        "Synodal (Orthodox) numbering as the module's own canon lays it out: Greek "
        "Psalm numbers, the Orthodox deuterocanon in place",
        "decoded from the SWORD zText directly; book and chapter markers in the text "
        "validated the slot walk at every step",
    ]
    if unknown:
        notes.append(
            "book codes outside this library's canon, not indexed: "
            + ", ".join(sorted(unknown))
        )
    yield BuiltCorpus(
        id="chuelz",
        label="Elizabeth Bible (Church Slavonic, 1757)",
        language="chu",
        versification="rso",
        verses=verses,
        notes=notes,
    )


SOURCE: Final = Source(
    id="slavonic",
    label="Elizabeth Bible, Church Slavonic (CrossWire CSlElizabeth)",
    homepage="https://crosswire.org/sword/modules/ModInfo.jsp?modName=CSlElizabeth",
    license="Public domain, per the module's .conf (DistributionLicense).",
    terms=get("public-domain"),
    files=(
        RemoteFile(
            url="https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/CSlElizabeth.zip",
            name=_ZIP,
        ),
    ),
    build=build,
    note="The Orthodox world's received Slavonic text; the Slavonic breadth row of "
    "quotes.md §11.",
)
