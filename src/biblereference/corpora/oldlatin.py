"""The Old Latin gospels: Latin scripture from before Jerome, and two of four manuscripts.

Migne prints four Vetus Latina gospel manuscripts collated in one file — Vercellensis,
Veronensis, Corbeiensis, Brixianus — under an old and wrong attribution to Eusebius of
Vercelli, which is why searching the catalogue for *Biblia* or *Vulgata* never finds it.
Codex Vercellensis is 4th-century and usually called the oldest surviving Old Latin gospel
manuscript. This library held no pre-Vulgate Latin at all.

**What is actually printed under each of the four names is not the same kind of thing**, and
the difference decides how each is imported:

    Vercellensis   verse numbers, CAPUT divisions              3,580 verses
    Veronensis     verse numbers, CAPUT divisions              3,427 verses
    Brixianus      continuous prose, no numbers, four gospels  58,207 words
    Corbeiensis    continuous prose for MATTHEW only           16,602 words
                   a collation of variant readings for the other three

**Corbeiensis is only a gospel text in Matthew.** Under `CODEX CORBEIENSIS` in Mark, Luke and
John, Bianchini prints not the manuscript but his apparatus to it: 759 numbered fragments
averaging twelve words, given only where ff2 diverges, and 7% of them are notes *about* the
manuscript rather than readings *from* it —

    13. Omittit et quadraginta noctibus.
    27. Neman + Syrus

*Omittit* — "it omits". Importing those as verses would put editorial Latin in the corpus
where scripture belongs, and would do it invisibly, since a fragment of a real clause beside
a real verse number is indistinguishable from a short reading. Only Matthew is taken, and
:data:`SKIPPED` records the other three with the reason.

**The verse divisions of the two unnumbered manuscripts are ours, not Bianchini's.** He set
them as unbroken paragraphs, so they are aligned against the Clementine and cut where its
verses fall, by ``tools/derive_oldlatin.py``, which writes the cut points to a data file so
the import itself does no guessing and the guess can be read in version control. That is the
thing this module previously refused to do, and the refusal was right in one respect: it is
inventing a versification and attributing it to a manuscript. What makes it publishable is
that the invention is measured, declared in the corpus label, and confined — the alternative
was holding no pre-Vulgate Latin for these two at all.

**How well the derivation works, measured against held-out truth.** Scoring derived
boundaries by similarity to the Vulgate scores the objective the derivation maximised; it
returns a median 0.86 and 0.0% drift, which look excellent and mean nothing. The honest test
throws away Bianchini's numbers on Vercellensis and Veronensis, re-derives them the same way,
and asks how often the boundary lands back where the editor put it:

    Veronensis     68.9-76.6% exact     92.1-96.8% within two words
    Vercellensis   61.1-65.5% exact     87.8-93.7% within two words

So roughly a third of boundaries are off, and almost all of those by a word or two at the
seam rather than by a verse. Brixianus and Corbeiensis-Matthew match the Clementine on
83.2-84.7% of its word stream against Veronensis' 52.8-79.7%, so the alignment is working on
easier material than either validation case — except Brixianus Mark at 65.2%, which sits
mid-pack and is the weakest of the five.

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

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Final

from lxml import etree

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .tei import GAP, flatten

__all__ = ["DERIVED", "SKIPPED", "SOURCE", "build", "read_continuous"]

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

#: The manuscripts Bianchini printed without verse numbers, and the gospels of each that are
#: continuous text rather than apparatus. Their divisions come from
#: :data:`_BOUNDS`; see the module docstring for what that costs.
DERIVED: Final[Mapping[str, tuple[str, str, tuple[str, ...]]]] = {
    "Brixianus": (
        "oldlatin-f",
        "Old Latin Gospels — Codex Brixianus (f), 6th c. [verse divisions derived, not printed]",
        ("MAT", "MRK", "LUK", "JHN"),
    ),
    "Corbeiensis": (
        "oldlatin-ff2",
        "Old Latin Gospels — Codex Corbeiensis (ff2), 5th c., Matthew only "
        "[verse divisions derived, not printed]",
        ("MAT",),
    ),
}

#: Recorded rather than dropped silently, the way ``swete._SKIPPED`` is. An absence with no
#: reason beside it is indistinguishable from a bug.
SKIPPED: Final[Mapping[str, str]] = {
    "Corbeiensis Mark, Luke and John": (
        "Not the manuscript but Bianchini's apparatus to it: 759 numbered fragments "
        "averaging twelve words, printed only where ff2 diverges, of which 7% are notes "
        "about the manuscript rather than readings from it -- 'Omittit et quadraginta "
        "noctibus', 'it omits and forty nights'. Importing them would file editorial Latin "
        "as scripture, and a fragment of a real clause beside a real verse number gives "
        "nothing away. Matthew, which is continuous text, is imported."
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


def read_continuous(path: Path) -> dict[tuple[str, str], list[str]]:
    """``(manuscript, book) -> word stream`` for the manuscripts printed without numbers.

    The same apparatus rule the numbered read uses, and for a sharper reason: the
    Vindobonensis collation follows Corbeiensis in both Luke and Mark, so without the reset
    it is read *as* Corbeiensis and adds 759 paragraphs of variant readings to a manuscript
    that has none there.
    """
    root = etree.parse(str(path)).getroot()
    book = codex = ""
    out: dict[tuple[str, str], list[str]] = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = element.tag.split("}")[-1]
        if name == "head":
            text = flatten(element)
            if _APPARATUS.search(text):
                codex = ""
                continue
            for word, code in _GOSPEL.items():
                if word in text.upper():
                    book = code
            found = _CODEX.search(text)
            if found:
                codex = found.group(1).title()
            continue
        if name == "p" and book and codex:
            out.setdefault((codex, book), []).extend(flatten(element).split())
    return out


@dataclass(frozen=True, slots=True)
class _Bound:
    """Where one gospel's verses begin in one manuscript's word stream."""

    digest: str
    cuts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _Bounds:
    """``tools/derive_oldlatin.py``'s output, read back."""

    by_codex: dict[str, dict[str, _Bound]]
    recovery: dict[str, dict[str, float]]
    """The held-out test: how often re-deriving Bianchini's own numbering reproduces it."""


def _bounds() -> _Bounds:
    """The derived cut points, or empty if they were never generated."""
    source = files("biblereference.data").joinpath("oldlatin_bounds.json")
    if not source.is_file():
        return _Bounds({}, {})
    raw = json.loads(source.read_text(encoding="utf-8"))
    return _Bounds(
        by_codex={
            codex: {
                book: _Bound(str(entry["digest"]), {k: int(v) for k, v in entry["cuts"].items()})
                for book, entry in books.items()
            }
            for codex, books in raw.get("bounds", {}).items()
        },
        recovery={
            name: {key: float(value) for key, value in score.items()}
            for name, score in raw.get("recovery", {}).items()
        },
    )


def _derived_verses(
    stream: list[str], book: str, record: _Bound
) -> tuple[list[tuple[VerseRef, str]], str]:
    """Cut a word stream at the recorded offsets.

    The digest is checked rather than trusted. The offsets were measured against one exact
    reading of the XML, and a change to the parser that shifts the stream by a single word
    would otherwise move every verse in the manuscript silently -- which is the failure this
    whole module is written against.
    """
    digest = hashlib.sha256(" ".join(stream).encode()).hexdigest()[:16]
    if digest != record.digest:
        raise ValueError(
            f"oldlatin_bounds.json was measured on a different reading of {book}: "
            f"expected {record.digest}, parsed {digest}. Re-run tools/derive_oldlatin.py."
        )
    cuts = sorted(
        ((int(ref.split(":")[0]), int(ref.split(":")[1])), start)
        for ref, start in record.cuts.items()
    )
    verses = []
    for index, ((chapter, verse), start) in enumerate(cuts):
        end = cuts[index + 1][1] if index + 1 < len(cuts) else len(stream)
        text = " ".join(stream[start:end]).strip()
        if text:
            verses.append((VerseRef(book, chapter, verse), text))
    # Whatever precedes the first verse the Clementine has. Returned rather than dropped:
    # Corbeiensis opens Matthew with sixty-one words of genealogy from Adam that the
    # Vulgate has no verse for, and a reading this divergent going missing without a word
    # is the failure this module exists to avoid.
    return verses, " ".join(stream[: cuts[0][1]]).strip() if cuts else ""


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

    record = _bounds()
    if not record.by_codex:
        return
    streams = read_continuous(path)
    recovery = record.recovery
    for codex, (corpus, label, books) in DERIVED.items():
        stored = record.by_codex.get(codex)
        if not stored:
            continue
        cut: list[tuple[VerseRef, str]] = []
        prologues: list[str] = []
        for book in books:
            stream = streams.get((codex, book))
            if stream and book in stored:
                verses, prologue = _derived_verses(stream, book, stored[book])
                cut.extend(verses)
                if prologue:
                    prologues.append(f"{book}: {prologue}")
        if not cut:
            continue
        yield BuiltCorpus(
            id=corpus,
            label=label,
            language="la",
            # Not a claim that the manuscript follows `vul`: it has no divisions of its own,
            # and `vul` is where the ones it has been given came from. Declaring anything
            # else would imply a numbering somebody printed.
            versification="vul",
            verses=cut,
            notes=[
                f"{len(cut):,} verses across {len(books)} gospel(s). Migne's collation, "
                f"under an old and wrong attribution to Eusebius of Vercelli.",
                "THE VERSE DIVISIONS ARE DERIVED, NOT PRINTED. Bianchini set this manuscript "
                "as continuous prose with no verse numbers and no chapter heads. The text is "
                "his; the places it is cut are this library's, obtained by aligning it "
                "against the Clementine and cutting where the Clementine's verses fall "
                "(tools/derive_oldlatin.py). A reference into this corpus locates a reading; "
                "it does not quote a numbering anyone ever printed.",
                "Measured against held-out truth rather than against itself: re-deriving the "
                "two manuscripts that DO carry Bianchini's numbers puts the boundary exactly "
                "where he put it "
                + (
                    f"{min(s['exact'] for s in recovery.values()):.0f}-"
                    f"{max(s['exact'] for s in recovery.values()):.0f}% of the time, and "
                    f"within two words "
                    f"{min(s['within_2_words'] for s in recovery.values()):.0f}-"
                    f"{max(s['within_2_words'] for s in recovery.values()):.0f}% of the time. "
                    if recovery
                    else ""
                )
                + "So about a third of boundaries are off, nearly all by a word or two at the "
                "seam. Scoring these against the Vulgate instead would report a median 0.86 "
                "and no drift at all, because that is the objective the alignment maximised.",
                *(
                    [
                        "Not everything under this manuscript's name is imported: "
                        + "; ".join(f"{name} -- {why}" for name, why in SKIPPED.items())
                    ]
                    if codex == "Corbeiensis"
                    else []
                ),
                *(
                    [
                        "Text standing before the first verse the Vulgate has, and so with "
                        "nowhere to be stored, recorded here rather than dropped -- "
                        + "; ".join(prologues)
                    ]
                    if prologues
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
