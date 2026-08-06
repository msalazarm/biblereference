"""The Greek New Testament: Nestle 1904.

NA28 is under copyright and cannot be redistributed. Nestle 1904 is the closest public
domain text: the OpenGNT project's own comparison puts it 61 words from NA28 across the
whole New Testament. This is the transcription by Diego Santos with morphology by Ulrik
Sandborg-Petersen, published by biblicalhumanities.

The file is one tab-separated row per word, keyed by a ``Book C:V`` reference, so a verse
is its rows joined in order. Only the reference and the word are used here; the
morphology, lemma and Strong's columns are left for later.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_URL: Final = (
    "https://raw.githubusercontent.com/biblicalhumanities/Nestle1904/master/morph/Nestle1904.csv"
)
_FILE: Final = "Nestle1904.csv"

#: The file's book names, which are not USFM codes.
_BOOKS: Final[dict[str, str]] = {
    "Matt": "MAT",
    "Mark": "MRK",
    "Luke": "LUK",
    "John": "JHN",
    "Acts": "ACT",
    "Rom": "ROM",
    "1Cor": "1CO",
    "2Cor": "2CO",
    "Gal": "GAL",
    "Eph": "EPH",
    "Phil": "PHP",
    "Col": "COL",
    "1Thess": "1TH",
    "2Thess": "2TH",
    "1Tim": "1TI",
    "2Tim": "2TI",
    "Titus": "TIT",
    "Phlm": "PHM",
    "Heb": "HEB",
    "Jas": "JAS",
    "1Pet": "1PE",
    "2Pet": "2PE",
    "1John": "1JN",
    "2John": "2JN",
    "3John": "3JN",
    "Jude": "JUD",
    "Rev": "REV",
}

_BCV_RE: Final = re.compile(r"^(?P<book>[\w ]+?)\s+(?P<chapter>\d+):(?P<verse>\d+)$")

SOURCE: Final = Source(
    id="nestle1904",
    label="Nestle 1904 Greek New Testament",
    homepage="https://github.com/biblicalhumanities/Nestle1904",
    license=(
        "Nestle 1904 text is public domain. The repository declares no single licence; "
        "see the README in each of its directories."
    ),
    # The 1904 text itself, which is what is stored.
    terms=get("public-domain"),
    attribution=(
        "Greek New Testament: Eberhard Nestle, Novum Testamentum Graece (1904); "
        "transcription by Diego Santos, morphology by Ulrik Sandborg-Petersen, markup by "
        "Jonathan Robie (https://github.com/biblicalhumanities/Nestle1904)."
    ),
    files=(RemoteFile(url=_URL, name=_FILE),),
    build=lambda archive: build(archive),
    note="Public domain, and 61 words from NA28 across the whole New Testament.",
)


def build(archive: Path) -> Iterator[BuiltCorpus]:
    """Parse a fetched archive into the Greek New Testament corpus."""
    path = archive / _FILE
    grouped: dict[tuple[str, int, int], list[str]] = {}
    order: list[tuple[str, int, int]] = []
    unknown: set[str] = set()

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2 or not row[0].strip():
                continue
            match = _BCV_RE.match(row[0].strip())
            if not match:
                continue
            book = _BOOKS.get(match["book"])
            if book is None:
                unknown.add(match["book"])
                continue
            key = (book, int(match["chapter"]), int(match["verse"]))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            word = row[1].strip()
            if word:
                grouped[key].append(word)

    verses = [
        (VerseRef(book=b, chapter=c, verse=v, vrs="org"), " ".join(grouped[(b, c, v)]))
        for b, c, v in order
        if grouped[(b, c, v)]
    ]

    yield BuiltCorpus(
        id="n1904",
        label="Nestle 1904",
        language="grc",
        versification="org",
        verses=verses,
        notes=(
            [f"unrecognised book names, not indexed: {', '.join(sorted(unknown))}"]
            if unknown
            else []
        ),
    )
