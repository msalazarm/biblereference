"""The Byzantine Textform: the Greek New Testament most Greek fathers quote toward.

Every Greek New Testament this library held before this — Nestle 1904, SBLGNT,
Westcott–Hort — is a critical eclectic edition, and they agree with each other far more
than any of them agrees with the text the manuscript tradition actually carried. Eight
documented places in one hand-tabulated corpus have a father's wording agreeing with the
Byzantine reading against all three, and at those places the quotation was unrecoverable at
any threshold, because the text was simply absent from the library.

Robinson and Pierpont's *The New Testament in the Original Greek: Byzantine Textform* is
that text, maintained by its editor in machine-readable form and placed in the public
domain in so many words: "The text and its analysis are in the Public Domain." The CSV form
imported here is the plain text without variant apparatus; the same repository carries the
apparatus and a morphological analysis, which the lexicon may want later.

Two files in the upstream are variant renderings of passages the main files already carry
— ``PA.csv`` is the Pericope Adulterae, present in ``JOH.csv``, and ``ACT24.csv`` is the
longer Byzantine form of Acts 24:6–8, whose verses ``ACT.csv`` also holds — so both are
skipped, with a note rather than silently.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_RAW: Final = (
    "https://raw.githubusercontent.com/byztxt/byzantine-majority-text/master/"
    "csv-unicode/ccat/no-variants"
)

#: Upstream file stem to USFM book code. The stems are CCAT's, not USFM's, and the
#: differences (JAM, JOH, MAR, 1JO) are exactly the ones worth writing down.
_BOOKS: Final = {
    "MAT": "MAT",
    "MAR": "MRK",
    "LUK": "LUK",
    "JOH": "JHN",
    "ACT": "ACT",
    "ROM": "ROM",
    "1CO": "1CO",
    "2CO": "2CO",
    "GAL": "GAL",
    "EPH": "EPH",
    "PHP": "PHP",
    "COL": "COL",
    "1TH": "1TH",
    "2TH": "2TH",
    "1TI": "1TI",
    "2TI": "2TI",
    "TIT": "TIT",
    "PHM": "PHM",
    "HEB": "HEB",
    "JAM": "JAS",
    "1PE": "1PE",
    "2PE": "2PE",
    "1JO": "1JN",
    "2JO": "2JN",
    "3JO": "3JN",
    "JUD": "JUD",
    "REV": "REV",
}

#: Variant renderings of passages the main files already hold. Skipped, and said.
_DUPLICATES: Final = ("PA.csv", "ACT24.csv")


def build(archive: Path) -> Iterator[BuiltCorpus]:
    verses: list[tuple[VerseRef, str]] = []
    notes = [
        f"{name} skipped: a variant rendering of verses the main files carry"
        for name in _DUPLICATES
    ]
    for stem, book in sorted(_BOOKS.items()):
        path = archive / f"{stem}.csv"
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                text = row["text"].replace("¶", " ").strip()
                if not text:
                    continue
                verses.append(
                    (VerseRef(book, int(row["chapter"]), int(row["verse"]), vrs="org"), text)
                )
    yield BuiltCorpus(
        id="grcbyz",
        label="Byzantine Textform — Robinson–Pierpont 2018",
        language="grc",
        versification="org",
        verses=verses,
        notes=notes,
    )


SOURCE: Final = Source(
    id="byzantine",
    label="The New Testament in the Original Greek: Byzantine Textform (Robinson–Pierpont)",
    homepage="https://github.com/byztxt/byzantine-majority-text",
    license="Public domain. The repository states: "
    '"The text and its analysis are in the Public Domain."',
    terms=get("public-domain"),
    files=tuple(
        RemoteFile(url=f"{_RAW}/{stem}.csv", name=f"{stem}.csv") for stem in sorted(_BOOKS)
    ),
    build=build,
)
