"""The Septuagint: Swete's edition of 1930.

Rahlfs-Hanhart is under copyright; Swete is not. Swete is a diplomatic edition following
Vaticanus where Rahlfs is eclectic, and it prints sixty books -- the whole deuterocanon,
plus the Old Greek *and* Theodotion of Daniel, Susanna and Bel.

The data is two tab-separated files: one numbering every word in the edition, one saying
which word each verse starts at. A verse is therefore the words between its own start and
the next verse's -- exact, with no parsing of the Greek at all.

**Two corpora, not one.** Swete numbers Greek Daniel chapter 3 to verse 100, which is the
Vulgate's division; the Septuagint versification this library uses ends that chapter at
97 and opens chapter 4 with the material the Hebrew calls 3:31-33. Filing Swete's Daniel
under the Septuagint numbering would misplace ten verses, so it becomes its own corpus
with the Vulgate's numbering declared honestly.

**Theodotion, not the Old Greek.** For Daniel, Susanna and Bel, Swete prints both. The
Church received Theodotion -- it is the text behind the Vulgate's Daniel and every
Catholic Bible -- and it is also the one whose verse counts match the versification data
(Theodotion Susanna has 64 verses, the Old Greek 60). The Old Greek is left in the archive
but not indexed, because no verse mapping for it exists to index it against.
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

_RAW: Final = "https://raw.githubusercontent.com/eliranwong/LXX-Swete-1930/master"

_VERSIFICATION_FILE: Final = "00-Swete_versification.csv"
_WORDS_FILE: Final = "01-Swete_word_with_punctuations.csv"

#: Swete's book abbreviations to USFM codes, for the books this library can place.
#: Where Swete prints a book twice, the Theodotion column wins -- see the module
#: docstring.
_BOOKS: Final[dict[str, str]] = {
    "Gen": "GEN",
    "Exo": "EXO",
    "Lev": "LEV",
    "Num": "NUM",
    "Deu": "DEU",
    "Jos": "JOS",
    "Jdg": "JDG",
    "Rut": "RUT",
    "1Sa": "1SA",
    "2Sa": "2SA",
    "1Ki": "1KI",
    "2Ki": "2KI",
    "1Ch": "1CH",
    "2Ch": "2CH",
    "1Es": "1ES",
    "Ezr": "EZR",
    "Neh": "NEH",
    "Psa": "PSA",
    "Pro": "PRO",
    "Ecc": "ECC",
    "Sol": "SNG",
    "Job": "JOB",
    "Wis": "WIS",
    "Sir": "SIR",
    "Est": "ESG",
    "Jdt": "JDT",
    "Tob": "TOB",
    "Hos": "HOS",
    "Amo": "AMO",
    "Mic": "MIC",
    "Joe": "JOL",
    "Oba": "OBA",
    "Jon": "JON",
    "Nah": "NAM",
    "Hab": "HAB",
    "Zep": "ZEP",
    "Hag": "HAG",
    "Zec": "ZEC",
    "Mal": "MAL",
    "Isa": "ISA",
    "Jer": "JER",
    "Bar": "BAR",
    "Lam": "LAM",
    "Epj": "LJE",
    "Eze": "EZK",
    "Sut": "SUS",
    "Bet": "BEL",
    "1Ma": "1MA",
    "2Ma": "2MA",
    "3Ma": "3MA",
    "4Ma": "4MA",
    "Pss": "PSS",
    "Ode": "ODA",
}

#: Daniel, which Swete numbers like the Vulgate. Theodotion only.
_DANIEL: Final[dict[str, str]] = {"Dat": "DAN"}

#: Printed by Swete but not indexed, with the reason.
_SKIPPED: Final[dict[str, str]] = {
    "Sip": "the translator's prologue to Sirach, which has no verse reference",
    "Dan": "Old Greek Daniel; the Church received Theodotion, and no verse mapping "
    "for the Old Greek exists",
    "Sus": "Old Greek Susanna (60 verses); Theodotion's 64 are the mapped text",
    "Bel": "Old Greek Bel; Theodotion is the mapped text",
    "Tbs": "Tobit in Codex Sinaiticus, a distinct recension with no verse mapping",
    # Was "outside every canon this library resolves against", which stopped being true:
    # `ENO` is a registered appendix code in `canon.py` and `org` declares it. The live
    # blocker is narrower and is the same one as `Jsa` -- **`lxx.json` does not declare
    # `ENO` at all**, and this corpus is `lxx`. Swete prints 353 verse references for it
    # (247 non-empty): chapters 1-32 with 4 an empty stub, 89 at 49 verses, 97 at 5, and
    # 33-88 and 90-96 present as one-verse stubs. `org` declares 42 chapters with counts
    # that are a placeholder rather than a description -- chapter 4 at 88 verses, where the
    # text has one. Importing this wants `ENO` declared in `lxx`, which is an editorial act
    # on a shipped scheme and is not one to slip in beside a corpus import.
    "1En": "1 Enoch; `lxx.json` declares no ENO, so there is nothing to map it onto",
    "Jsa": "Joshua A, an alternative recension with no verse mapping",
}

_REF_RE: Final = re.compile(r"^(?P<book>\w+)\.(?P<chapter>\d+):(?P<verse>\d+)$")

SOURCE: Final = Source(
    id="swete",
    label="Septuagint — Swete 1930",
    homepage="https://github.com/eliranwong/LXX-Swete-1930",
    license=(
        "Text public domain (H. B. Swete, d. 1917). The compilation is GPL-3.0, so it is "
        "fetched rather than redistributed."
    ),
    # Swete died in 1917; the words are out of copyright. The GPL applies to the
    # repository's compilation of them, which is why this fetches rather than vendors.
    terms=get("public-domain"),
    attribution=(
        "Septuagint: H. B. Swete, The Old Testament in Greek (1930), digitised by "
        "Eliran Wong (https://github.com/eliranwong/LXX-Swete-1930)."
    ),
    files=(
        RemoteFile(url=f"{_RAW}/{_VERSIFICATION_FILE}", name=_VERSIFICATION_FILE),
        RemoteFile(url=f"{_RAW}/{_WORDS_FILE}", name=_WORDS_FILE),
    ),
    build=lambda archive: build(archive),
    note="Sixty books, including the whole deuterocanon.",
)


def _read_words(path: Path) -> dict[int, str]:
    words: dict[int, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) >= 2 and row[0].isdigit():
                words[int(row[0])] = row[1]
    return words


def _read_starts(path: Path) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) >= 2 and row[0].isdigit():
                starts.append((int(row[0]), row[1]))
    return starts


#: Critical-apparatus markers, not text. Swete brackets a substituted reading with U+2E02
#: and U+2E03 and marks an interpolation with U+2E06, and this digitisation keeps them --
#: 634 of them across 402 verses, where Rahlfs, Brenton, Nestle 1904, the SBLGNT and
#: Westcott-Hort carry none at all.
#:
#: They matter because they are in the text that gets searched, folded and quote-checked: a
#: reader looking for ὅτι τέθνηκεν ὁ κύριος ὑμῶν Σαούλ does not expect ⸂⸆⸃ in the middle of
#: it. Found by diffing this digitisation against First1KGreek's of the same edition, which
#: is what holding two copies is for.
_SIGLA: Final = str.maketrans("", "", "\u2e02\u2e03\u2e06")


def _without_sigla(word: str) -> str:
    """One word with its apparatus markers removed, or empty if it was only markers."""
    return word.translate(_SIGLA)


def build(archive: Path) -> Iterator[BuiltCorpus]:
    """Parse a fetched archive into the Septuagint corpora."""
    words = _read_words(archive / _WORDS_FILE)
    starts = _read_starts(archive / _VERSIFICATION_FILE)
    if not words or not starts:
        raise FileNotFoundError(f"Swete data missing or empty under {archive}")

    last_word = max(words)
    main: list[tuple[VerseRef, str]] = []
    daniel: list[tuple[VerseRef, str]] = []
    unknown: set[str] = set()

    for index, (first, reference) in enumerate(starts):
        match = _REF_RE.match(reference)
        if not match:
            continue
        abbreviation = match["book"]
        target = _BOOKS.get(abbreviation)
        into = main
        if target is None:
            target = _DANIEL.get(abbreviation)
            into = daniel
        if target is None:
            if abbreviation not in _SKIPPED:
                unknown.add(abbreviation)
            continue

        last = starts[index + 1][0] - 1 if index + 1 < len(starts) else last_word
        text = " ".join(
            cleaned
            for k in range(first, last + 1)
            if k in words and (cleaned := _without_sigla(words[k]))
        ).strip()
        if not text:
            continue
        into.append(
            (
                VerseRef(
                    book=target,
                    chapter=int(match["chapter"]),
                    verse=int(match["verse"]),
                    vrs="lxx" if into is main else "vul",
                ),
                text,
            )
        )

    notes = [f"{code}: not indexed -- {why}" for code, why in sorted(_SKIPPED.items())]
    if unknown:
        notes.append(f"unrecognised Swete book codes, not indexed: {', '.join(sorted(unknown))}")

    yield BuiltCorpus(
        id="swete",
        label="Septuagint — Swete 1930",
        language="grc",
        versification="lxx",
        verses=main,
        notes=notes,
    )
    yield BuiltCorpus(
        id="swete-daniel",
        label="Greek Daniel, Theodotion — Swete 1930",
        language="grc",
        versification="vul",
        verses=daniel,
        notes=[
            "Swete numbers Greek Daniel chapter 3 to verse 100, the Vulgate's division "
            "rather than the Septuagint's, so this corpus declares Vulgate numbering.",
            "Theodotion, the text the Church received and the one behind the Vulgate's "
            "Daniel. Swete's Old Greek Daniel is in the archive but not indexed.",
        ],
    )
