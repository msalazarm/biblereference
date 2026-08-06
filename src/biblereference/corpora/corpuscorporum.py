"""Corpus Corporum: a second Rahlfs, and the one Latin Bible that is not Jerome's.

Two texts, and each is here for a different reason.

**Rahlfs again.** The Patristic Text Archive already supplies this edition, and a second
independent transcription of one printed book is worth having precisely because the two
can disagree: where they do, one of them is wrong, and finding out costs a diff rather
than a download. This one is also the better labelled of the two -- it names ``Dan`` and
``Dan Th``, ``Sus`` and ``Sus Th``, ``Bel`` and ``Bel Th``, ``Idc`` and ``Idc B``, where
the archive's files print the same Greek titles for both members of each pair and leave
the reader to work out which recension is which.

**Castellio.** Sebastian Castellio translated from the Hebrew and Greek in 1551 owing
nothing to the Vulgate, and this library's two Latin Bibles are both Vulgate -- the
Clementine and the Nova Vulgata. For asking whether a Latin father's wording follows
Jerome or something else, an independent Latin translation is the control. Only Genesis
and the four Gospels survive in this transcription.

**The markup is the hazard.** Corpus Corporum is TEI P4 wearing the P5 namespace, and its
verses are *loose text between empty markers* rather than the content of any element::

    <div1 n="1" id="Gen"><head>ΓΕΝΕΣΙΣ</head>
    <div2 n="1"><head>Caput 1</head>
    <p><milestone unit="verse" n="1"/>Ἐν ἀρχῇ ... <milestone unit="verse" n="2"/>ἡ δὲ γῆ ...

A reader that looks for an element holding a verse finds every verse *number* correctly
and extracts nothing at all. :func:`~biblereference.corpora.tei.milestone_verses` walks
the chapter in document order instead, accumulating against whichever marker was last
seen.

**And neither file declares a licence.** There is an ``<availability>`` element with
nothing in it, so ``read_licence`` has nothing to read and the source's own terms stand
in. That is recorded on each corpus as a note rather than passed over: the site grants its
files for non-commercial use with provenance stated as a best effort, and the printed
editions behind them -- Rahlfs 1935, Castellio 1726 -- are out of copyright in their own
right, so a copy obtained elsewhere may well be freer than this one.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

from lxml import etree

from ..canon import is_known
from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .tei import TEI_NS, milestone_verses, read_licence

__all__ = ["SOURCE", "build"]

_DOWNLOAD: Final = "https://mlat.uzh.ch/php_modules/download.php?type=file-xml&idno="

#: ``div1/@id`` to USFM, for the Septuagint. Read off the file's own headings, which is
#: why the recensions can be told apart: ``Dan`` heads ΔΑΝΙΗΛ (LXX) and ``Dan Th`` heads
#: ΔΑΝΙΗΛ (Θεοδοτίων).
#:
#: ``Neh`` is a misleading id and the heading settles it: ΕΣΔΡΑΣ Β is the Greek
#: Ezra-Nehemiah, which ``org`` calls EZR, and ``Esd`` heading ΕΣΔΡΑΣ Α is the apocryphal
#: 1 Esdras. Trusting the id here would swap them.
SEPTUAGINT: Final[Mapping[str, str]] = {
    "Gen": "GEN",
    "Ex": "EXO",
    "Lev": "LEV",
    "Num": "NUM",
    "Dtn": "DEU",
    "Ios": "JOS",
    "Idc": "JDG",
    "Idc B": "JDB",
    "Rt": "RUT",
    "1Rg": "1SA",
    "2Rg": "2SA",
    "3Rg": "1KI",
    "4Rg": "2KI",
    "1Par": "1CH",
    "2Par": "2CH",
    "Esd": "1ES",
    "Neh": "EZR",
    "Est": "ESG",
    "Idt": "JDT",
    "Tob": "TOB",
    "1Mac": "1MA",
    "2Mac": "2MA",
    "3Mac": "3MA",
    "4Mac": "4MA",
    "Ps": "PSA",
    "Od": "ODA",
    "Pro": "PRO",
    "Ecl": "ECC",
    "Cant": "SNG",
    "Iob": "JOB",
    "Sap": "WIS",
    "Sir": "SIR",
    "PsSal": "PSS",
    "Os": "HOS",
    "Am": "AMO",
    "Mich": "MIC",
    "Ioel": "JOL",
    "Abd": "OBA",
    "Ion": "JON",
    "Nah": "NAM",
    "Hab": "HAB",
    "Soph": "ZEP",
    "Agg": "HAG",
    "Zach": "ZEC",
    "Mal": "MAL",
    "Is": "ISA",
    "Ier": "JER",
    "Bar": "BAR",
    "Lam": "LAM",
    "Ep Ier": "LJE",
    "Ez": "EZK",
    "Sus": "SUS",
    "Sus Th": "SST",
    "Dan": "DAG",
    "Dan Th": "DNT",
    "Bel": "BEL",
    "Bel Th": "BLT",
}

CASTELLIO: Final[Mapping[str, str]] = {
    "Gen": "GEN",
    "Mt": "MAT",
    "Mc": "MRK",
    "Lc": "LUK",
    "Io": "JHN",
}

#: ``corpus id -> (idno, book map, label, language, versification)``.
TEXTS: Final[Mapping[str, tuple[str, Mapping[str, str], str, str, str]]] = {
    "rahlfs-cc": (
        "17104",
        SEPTUAGINT,
        "Septuaginta — Rahlfs 1935, the Corpus Corporum transcription",
        "grc",
        "lxx",
    ),
    "castellio": (
        "21332",
        CASTELLIO,
        "Biblia Sacra — Castellio 1551, Genesis and the Gospels",
        "la",
        # Measured against every shipped system and it fits none of them well: around 90%
        # each way, which is what an independent 1551 translation looks like. `eng` wins
        # narrowly, and Genesis 31/32 decides it -- 55 verses and 32, the English
        # tradition's division, where the Hebrew has 54 and 33. It is emphatically *not*
        # the org witness in Latin one might hope for from a translation made from the
        # originals.
        "eng",
    ),
}


def build(archive: Path) -> Iterator[BuiltCorpus]:
    for corpus, (idno, mapping, label, language, versification) in TEXTS.items():
        path = archive / f"cc-{idno}.xml"
        if not path.exists():
            continue
        tree = etree.parse(str(path))
        verses: list[tuple[VerseRef, str]] = []
        unknown: set[str] = set()
        for division in tree.iter(f"{{{TEI_NS}}}div1"):
            identifier = (division.get("id") or "").strip()
            book = mapping.get(identifier)
            if book is None or not is_known(book):
                if identifier:
                    unknown.add(identifier)
                continue
            for chapter, verse, subverse, text in milestone_verses(division):
                verses.append((VerseRef(book, chapter, verse, subverse), text))

        notes = [
            "The file declares no licence -- its <availability> element is empty -- so the "
            "distributor's own non-commercial terms are recorded instead. The printed "
            "edition behind it is out of copyright in its own right, so a copy obtained "
            "elsewhere may be freer."
        ]
        if corpus == "rahlfs-cc":
            notes.append(
                "This transcription renumbers Rahlfs's lettered pluses as plain verses "
                "where the Patristic Text Archive's keeps the letters. Job 42 runs to 19 "
                "rather than 17 with 17a-17e, Joshua 24 to 62 rather than 33 with 33a and "
                "33b, Esther 10 to 11 rather than 3 with 3a-3l. `lxx` declares the lettered "
                "form, so those extra verses are outside what any shipped system has and "
                "cannot be cited or validated -- fifteen chapters in all, and the reason "
                "this corpus seeds its own family rather than joining `rahlfs`. Prefer "
                "`rahlfs` for anything that has to resolve; this one is here for the diff."
            )
        if unknown:
            notes.append(
                f"divisions with no book mapping, not indexed: {', '.join(sorted(unknown))}"
            )
        yield BuiltCorpus(
            id=corpus,
            label=label,
            language=language,
            versification=versification,
            verses=verses,
            notes=notes,
            licence=read_licence(path) or get("site-terms-nc"),
            licences=(read_licence(path) or get("site-terms-nc"),),
        )


SOURCE: Final = Source(
    id="corpuscorporum",
    label="Corpus Corporum — Rahlfs and Castellio",
    homepage="https://mlat.uzh.ch",
    license=(
        "Granted by the distributor for non-commercial use, with provenance stated as a "
        "best effort. The editions themselves -- Rahlfs 1935, Castellio 1726 -- are out of "
        "copyright, so the constraint is on these files rather than on the texts."
    ),
    terms=get("site-terms-nc"),
    files=tuple(
        RemoteFile(url=f"{_DOWNLOAD}{idno}", name=f"cc-{idno}.xml") for idno, *_ in TEXTS.values()
    ),
    # A university's public endpoint behind a PHP front end, not a CDN. The harvest that
    # found these used 0.6s between requests and it never complained.
    crawl_delay=0.6,
    build=lambda archive: build(archive),
)
