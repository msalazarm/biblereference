"""English Bibles with the deuterocanon, from eBible.org.

The ASV and KJV stop at the sixty-six books of the Protestant canon, so a Catholic
treatise citing Tobit or Sirach in English needs another text. Two are used, because they
number the deuterocanon differently and each is right for different citations:

**World English Bible, Catholic Edition** -- translated from the Greek and numbered the
way the Greek is numbered, so it answers a citation written as ``Sir 24:1`` or
``Tob 1:1``. Modern English. This is the default fallback.

**Douay-Rheims 1899** -- translated from the Vulgate and numbered the way the Vulgate is
numbered. Jerome's Tobit, Judith and Sirach come from source texts that differ from the
Greek by whole clauses, which is exactly why the versification data refuses to map them;
so the Douay-Rheims answers citations written in Vulgate numbering, and only those.

Both are public domain.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..canon import is_known
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .usfm import parse_usfm

__all__ = ["DRA", "WEBC", "build_dra", "build_webc"]


def _build(archive: Path, name: str, corpus: BuiltCorpus) -> BuiltCorpus:
    """Read every USFM file in a downloaded eBible zip."""
    verses: list[tuple[VerseRef, str]] = []
    unknown: set[str] = set()

    with zipfile.ZipFile(archive / name) as bundle:
        for entry in sorted(bundle.namelist()):
            if not entry.lower().endswith(".usfm"):
                continue
            content = bundle.read(entry).decode("utf-8-sig")
            for book, chapter, verse, text in parse_usfm(content):
                if not is_known(book):
                    unknown.add(book)
                    continue
                verses.append(
                    (
                        VerseRef(
                            book=book,
                            chapter=chapter,
                            verse=verse,
                            vrs=corpus.versification,
                        ),
                        text,
                    )
                )

    notes = list(corpus.notes)
    if unknown:
        notes.append(
            f"book codes outside this library's canon, not indexed: {', '.join(sorted(unknown))}"
        )
    return BuiltCorpus(
        id=corpus.id,
        label=corpus.label,
        language=corpus.language,
        versification=corpus.versification,
        verses=verses,
        notes=notes,
    )


_DRA_FILE: Final = "engDRA_usfm.zip"
_WEBC_FILE: Final = "eng-web-c_usfm.zip"


def build_dra(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _DRA_FILE,
        BuiltCorpus(
            id="dra",
            label="Douay-Rheims 1899",
            language="en",
            versification="vul",
            verses=[],
            notes=[
                "Vulgate numbering throughout, including Esther 10:4-16:24 and Daniel "
                "13-14 for Susanna and Bel.",
            ],
        ),
    )


def build_webc(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _WEBC_FILE,
        BuiltCorpus(
            id="webc",
            label="World English Bible, Catholic Edition",
            language="en",
            versification="eng",
            verses=[],
            notes=[
                "The deuterocanon is translated from the Greek and numbered accordingly, "
                "which is what lets it answer a citation written as Sirach 24:1.",
            ],
        ),
    )


DRA: Final = Source(
    id="dra",
    label="Douay-Rheims 1899 American Edition",
    homepage="https://ebible.org/find/details.php?id=engDRA",
    license="Public domain.",
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_DRA_FILE}", name=_DRA_FILE),),
    build=build_dra,
    note="English of the Vulgate, in Vulgate numbering.",
)

WEBC: Final = Source(
    id="webc",
    label="World English Bible, Catholic Edition",
    homepage="https://ebible.org/find/details.php?id=eng-web-c",
    license="Public domain.",
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_WEBC_FILE}", name=_WEBC_FILE),),
    build=build_webc,
    note="The English deuterocanon, in Greek numbering.",
)
