"""The Old Latin gospels: Latin scripture from before Jerome, and two of four manuscripts.

Migne prints four Vetus Latina gospel manuscripts collated in one file — Vercellensis,
Veronensis, Corbeiensis, Brixianus — under an old and wrong attribution to Eusebius of
Vercelli, which is why searching the catalogue for *Biblia* or *Vulgata* never finds it.
Codex Vercellensis is 4th-century and usually called the oldest surviving Old Latin gospel
manuscript. This library held no pre-Vulgate Latin at all.

**Two of the four are imported and two are not**, and the reason is not fastidiousness:

    Vercellensis   verse numbers, CAPUT divisions      3,463 verses
    Veronensis     verse numbers, CAPUT divisions      3,420 verses
    Corbeiensis    continuous prose, no numbers        —
    Brixianus      continuous prose, no numbers        —

Corbeiensis and Brixianus are printed as unbroken paragraphs — *"Liber generationis Jesu
Christi, filii David, filii Abraham. Abraham genuit Isaac…"* — with no verse numbers and no
chapter heads anywhere in them. Giving them verses would mean aligning them against the
Vulgate and numbering them by where the Vulgate's verses fall, which is not reading a
versification but inventing one and attributing it to a manuscript. They are left out, and
:data:`SKIPPED` says so rather than letting their absence look like an oversight.

**The holes are kept.** Both manuscripts are mutilated and Migne set the damage rather than
conjecturing through it, as runs of spaced dots — 5,615 of them. Vercellensis loses Matthew
1:6 and 1:7 entirely inside one. A dot run is indistinguishable from a sentence stop
followed by a space, so they are marked *before* verse numbers are looked for: the other
order lets a hole beside a digit read as a verse number, and a verse number inside a hole
disappear. What is stored carries :data:`GAP` where the manuscript is gone, because a gap
silently closed is a manufactured reading and this text would be full of them.

**What the numbering was checked against.** There is no facsimile here, so the check is
scale rather than a hand-read sample: every verse with four or more surviving words was
compared against the Clementine *at the same reference*, and then against the next verse.

    Veronensis     median 0.79 similarity   96.2% at 0.45+   0.4% match verse n+1 better
    Vercellensis   median 0.67              85.4%            1.1%

The last column is the one that matters. A misparsed verse number drifts, and drift shows up
as a run of verses matching *n+1*; under 1% is noise, not drift. Vercellensis scores lower
throughout because it is the more mutilated manuscript and the more divergent text — a real
Old Latin against a revised Vulgate — which is the reason to want it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

from lxml import etree

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .tei import GAP, flatten

__all__ = ["SKIPPED", "SOURCE", "build"]

#: Corpus Corporum work 343 is the *work*; the file hangs off the text nested inside it.
#: Asking for the work answers "this XML file doesn't exist", which is the two-step this
#: catalogue is easy to get wrong on.
_TEXT: Final = "6898"
_DOWNLOAD: Final = "https://mlat.uzh.ch/php_modules/download.php?type=file-xml&idno="

#: The manuscripts that can be read, with the corpus each becomes. Named by siglum because
#: that is how they are cited; the Beuron numbers are in the labels.
CORPORA: Final[Mapping[str, tuple[str, str]]] = {
    "Vercellensis": ("oldlatin-a", "Old Latin Gospels — Codex Vercellensis (a), 4th c."),
    "Veronensis": ("oldlatin-b", "Old Latin Gospels — Codex Veronensis (b), 5th c."),
}

#: Recorded rather than dropped silently, the way ``swete._SKIPPED`` is. An absence with no
#: reason beside it is indistinguishable from a bug.
SKIPPED: Final[Mapping[str, str]] = {
    "Corbeiensis": (
        "Printed as continuous prose with no verse numbers and no chapter heads. Numbering "
        "it would mean aligning against the Vulgate and calling the result the manuscript's "
        "own versification."
    ),
    "Brixianus": (
        "The same: 94 unbroken paragraphs, no verse numbers, no chapter heads. Its readings "
        "are legible and its verse divisions do not exist to be read."
    ),
}

#: A run of spaced dots: the editor's mark for a hole. Two or more, because one `. ` is a
#: sentence.
_LACUNA: Final = re.compile(r"(?:\.\s+){2,}\.?")

#: `CAPUT XVII.`, and `CAPUT PRIMUM.` for the first.
_CAPUT: Final = re.compile(r"^CAPUT\s+(PRIMUM|[IVXLC]+)\s*\.?\s*$", re.IGNORECASE)

_CODEX: Final = re.compile(r"CODEX\s+([A-Z]+)", re.IGNORECASE)

_GOSPEL: Final[Mapping[str, str]] = {
    "MATTHAEUM": "MAT",
    "MARCUM": "MRK",
    "LUCAM": "LUK",
    "JOHANNEM": "JHN",
}

#: Sections that are apparatus rather than scripture: a collation of a fifth manuscript
#: (Vindobonensis) against the Vulgate, and the prefatory argument. Importing either would
#: put a list of variant readings where a gospel should be.
_APPARATUS: Final = re.compile(r"LECTIONES|ABEUNTES|ARGUMENTUM|PRAEFATIO|MONITUM", re.IGNORECASE)

_ROMAN: Final[Mapping[str, int]] = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman(text: str) -> int:
    if text.upper() == "PRIMUM":
        return 1
    letters = text.upper()
    total = 0
    for index, letter in enumerate(letters):
        value = _ROMAN[letter]
        after = _ROMAN[letters[index + 1]] if index + 1 < len(letters) else 0
        total += -value if value < after else value
    return total


#: A verse number: `N.` opening a verse, at the start or after a space or a hole. Marked
#: before the holes are, and the order is the whole trick -- see :func:`_verses`.
_NUMBER: Final = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,3})\.(?=\s)")

#: Stands in for a verse number while the lacunae are marked. A control character, because
#: nothing in Migne's Latin can contain one and so nothing can be mistaken for it.
_MARK: Final = "\x00"


def _verses(text: str) -> list[tuple[int, str]]:
    """A paragraph split on its bare verse numbers, with the holes marked.

    **The verse numbers are set aside first.** Marking the lacunae first is the obvious
    order and it silently loses verses: `2. . . . . . Abraham` is a verse number followed by
    a hole, and the hole pattern begins at the number's own full stop and eats it, leaving a
    bare `2` that no longer looks like anything. Vercellensis Matthew 1:2 and 1:3 disappeared
    into 1:1 that way -- into a verse already so damaged that the loss did not show.

    The reverse hazard does not exist: a hole is only dots, so it cannot manufacture a
    digit, and a number can only be lost, never invented.
    """
    marked = _NUMBER.sub(lambda m: f"{_MARK}{m.group(1)}{_MARK}", text)
    marked = _LACUNA.sub(f" {GAP} ", marked)
    parts = marked.split(_MARK)
    if len(parts) < 3:
        return []
    return [
        (int(parts[index]), re.sub(r"\s+", " ", parts[index + 1]).strip())
        for index in range(1, len(parts) - 1, 2)
    ]


def _readable(text: str) -> bool:
    """Whether anything of the manuscript survives here, or only the hole.

    A verse that is nothing but dots is not a short reading; it is the editor saying the
    page is gone. Storing it would put an empty verse where a reader would take it for one
    the manuscript omits.
    """
    return bool(text.replace(GAP, "").strip(" .,;:·"))


def read(path: Path) -> Iterator[tuple[str, VerseRef, str]]:
    """``(manuscript, ref, text)`` for every verse that can be read and located.

    The manuscript is running state rather than a property of any one element: some ``div1``
    name a manuscript and not a gospel, inheriting the gospel from the division before;
    some ``div2`` are a manuscript change rather than a chapter; and the apparatus sections
    end one without beginning another.
    """
    root = etree.parse(str(path)).getroot()
    book, codex, chapter = "", "", 0

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = element.tag.split("}")[-1]
        if name == "head":
            text = flatten(element)
            if _APPARATUS.search(text):
                codex = ""  # nothing is stored again until a manuscript head resumes
                continue
            for word, code in _GOSPEL.items():
                if word in text.upper():
                    book, chapter = code, 0
            found = _CODEX.search(text)
            if found:
                codex = found.group(1).title()
            caput = _CAPUT.match(text.strip())
            if caput:
                chapter = _roman(caput.group(1))
            continue
        if name != "p" or not (book and codex and chapter) or codex not in CORPORA:
            continue
        for number, body in _verses(flatten(element)):
            if _readable(body):
                yield (codex, VerseRef(book, chapter, number), body)


def build(archive: Path) -> Iterator[BuiltCorpus]:
    path = archive / f"cc-{_TEXT}.xml"
    if not path.exists():
        return

    from ..versification import Versification, VersificationError

    vrs = Versification.load()
    held: dict[str, list[tuple[VerseRef, str]]] = {}
    beyond: dict[str, list[str]] = {}
    for codex, ref, text in read(path):
        try:
            # The declared system is the arbiter of what can be cited, so a verse number
            # past the end of its chapter is refused rather than moved. Migne's John 14 in
            # Vercellensis skips 31 and labels its last verse 32: verses 1-30 align with
            # the Clementine exactly and the content of "32" is verbatim its 31, so the
            # number is a slip in the edition rather than a manuscript reading. Renumbering
            # on that reasoning would be guessing, and guessing at scale is how a corpus
            # comes to hold verses nobody ever printed.
            vrs.validate(ref.in_vrs("vul"))
        except VersificationError:
            beyond.setdefault(codex, []).append(str(ref))
            continue
        held.setdefault(codex, []).append((ref, text))

    for codex, (corpus, label) in CORPORA.items():
        rows = held.get(codex)
        if not rows:
            continue
        yield BuiltCorpus(
            id=corpus,
            label=label,
            language="la",
            # Declared `vul` and not measured into a family of its own. These are the
            # manuscripts the Vulgate was revised *from*, and Migne prints them under the
            # Vulgate's own chapter and verse divisions -- the numbering is the editor's
            # apparatus for comparison, not the manuscript's, which has none.
            versification="vul",
            verses=rows,
            notes=[
                f"{len(rows):,} verses. Migne's collation, under an old and wrong "
                f"attribution to Eusebius of Vercelli.",
                f"The manuscript is damaged and the damage is kept: {GAP} marks a hole the "
                f"editor set rather than conjectured through. A verse that survives only as "
                f"a hole is left out entirely rather than stored empty, which a reader "
                f"would take for an omission in the manuscript.",
                "The verse numbers are Migne's editorial apparatus for comparing the "
                "manuscripts against the Vulgate. They were checked at scale rather than "
                "by facsimile: every verse with four or more surviving words against the "
                "Clementine at the same reference, and then against the next one. Under 1% "
                "match the next verse better, which is noise rather than drift.",
                "Two further manuscripts are in the same file and are not here: "
                + "; ".join(f"{name} -- {why}" for name, why in SKIPPED.items()),
                *(
                    [
                        f"{len(beyond[codex])} verse(s) numbered past the end of their "
                        f"chapter in `vul` and refused rather than renumbered: "
                        f"{', '.join(beyond[codex])}."
                    ]
                    if beyond.get(codex)
                    else []
                ),
            ],
            licence=get("site-terms-nc"),
        )


SOURCE: Final = Source(
    id="oldlatin",
    label="Old Latin Gospels — Migne's four-manuscript collation",
    homepage="https://mlat.uzh.ch",
    license=(
        "Granted by the distributor for non-commercial use. Migne's Patrologia Latina "
        "(1844-55) is long out of copyright, so the constraint is on Zurich's file rather "
        "than on the text; PL 12 is on the Internet Archive if that matters."
    ),
    terms=get("site-terms-nc"),
    files=(RemoteFile(url=f"{_DOWNLOAD}{_TEXT}", name=f"cc-{_TEXT}.xml"),),
    crawl_delay=0.6,
    build=lambda archive: build(archive),
    note=(
        "Work 343 in the catalogue; the downloadable text inside it is 6898. Asking for the "
        "work answers 'this XML file doesn't exist'."
    ),
)
