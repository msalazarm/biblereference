"""Work out which book each TEI file holds, once, and commit the answer.

The corpus modules need a map from a file to a USFM code before they can parse anything,
and working it out at import time would mean either a network round trip or shipping a
parser that guesses. So this does it here and writes ``data/tei_books.json``, in the same
spirit as ``tools/gen_ebible_english.py``.

**Keyed on the full CTS URN, not on the work number, and that is not tidiness.** The
Patristic Text Archive numbers a *work slot* rather than a book, and the slot means
different things in different languages: ``pta016`` is 1 Esdras in Greek and **Ezra** in
Syriac; ``pta031`` is the Psalter in Greek and three sets of apocryphal psalms in the
Syriac versions; ``pta023`` is 1 Maccabees in two recensions. A table keyed on ``pta016``
alone would file the Syriac Ezra as 1 Esdras -- 456 verses into the wrong book, with
nothing to notice it.

Anything that cannot be resolved is written out with ``"book": null`` and its raw title,
so an unimported file is visible in the committed artefact and shows up in a diff. Silence
would be the alternative, and this repository has been bitten by that before.

    venv/bin/python tools/gen_tei_books.py ~/.local/share/churchfathers/sources/pta
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Final

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from biblereference.canon import AmbiguousBookError, NamingScheme, UnknownBookError, resolve_book
from biblereference.corpora.tei import flatten

TEI: Final = "{http://www.tei-c.org/ns/1.0}"

#: Titles ``canon.resolve_book`` cannot read, which is most of them: it knows English,
#: Latin and Douay names, and the Patristic Text Archive titles its Greek in Greek and its
#: Syriac in Syriac.
#:
#: Kept as data rather than folded into ``canon.py`` because these are one archive's
#: house style -- ``ΒΑΣΙΛΕΙΩΝ Αʹ`` for 1 Samuel is the Septuagint's own name for it, and
#: teaching the library's general name resolver to accept it would make ``1 Kingdoms``
#: ambiguous everywhere else.
ALIASES: Final[dict[str, str]] = {
    # -- Greek, the Septuagint's own titles ------------------------------------------
    "ΓΕΝΕΣΙΣ": "GEN",
    "ΕΞΟΔΟΣ": "EXO",
    "ΛΕΥΙΤΙΚΟΝ": "LEV",
    "ΑΡΙΘΜΟΙ": "NUM",
    "ΔΕΥΤΕΡΟΝΟΜΙΟΝ": "DEU",
    "ΙΗΣΟΥΣ": "JOS",
    "ΚΡΙΤΑΙ": "JDG",
    "ΡΟΥΘ": "RUT",
    # The four books of Kingdoms are Samuel and Kings. This is the pair canon.py raises
    # AmbiguousBookError over, and rightly: "1 Kings" is 1 Samuel in the Douay.
    "ΒΑΣΙΛΕΙΩΝ Αʹ": "1SA",
    "ΒΑΣΙΛΕΙΩΝ Βʹ": "2SA",
    "ΒΑΣΙΛΕΙΩΝ Γʹ": "1KI",
    "ΒΑΣΙΛΕΙΩΝ Δʹ": "2KI",
    "ΠΑΡΑΛΕΙΠΟΜΕΝΩΝ Αʹ": "1CH",
    "ΠΑΡΑΛΕΙΠΟΜΕΝΩΝ Βʹ": "2CH",
    "ΕΣΔΡΑΣ Αʹ": "1ES",  # the apocryphal Greek Esdras, not Ezra
    "ΕΣΔΡΑΣ Βʹ": "EZR",  # Esdras B is Ezra-Nehemiah; its Ezra half is what org calls EZR
    "ΕΣΘΗΡ": "ESG",  # the Greek Esther, with its additions
    "ΙΟΥΔΙΘ": "JDT",
    "ΤΩΒΙΤ": "TOB",
    "ΜΑΚΚΑΒΑΙΩΝ Αʹ": "1MA",
    "ΜΑΚΚΑΒΑΙΩΝ Βʹ": "2MA",
    "ΜΑΚΚΑΒΑΙΩΝ Γʹ": "3MA",
    "ΜΑΚΚΑΒΑΙΩΝ Δʹ": "4MA",
    "ΨΑΛΜΟΙ": "PSA",
    "ΩΔΑΙ": "ODA",
    "ΠΑΡΟΙΜΙΑΙ": "PRO",
    "ΕΚΚΛΗΣΙΑΣΤΗΣ": "ECC",
    "ΑΣΜΑ": "SNG",
    "ΙΩΒ": "JOB",
    "ΣΟΦΙΑ ΣΑΛΩΜΩΝΟΣ": "WIS",
    "Siracides": "SIR",
    "ΨΑΛΜΟΙ ΣΟΛΟΜΩΝΤΟΣ": "PSS",
    "ΩΣΗΕ": "HOS",
    "ΑΜΩΣ": "AMO",
    "ΜΙΧΑΙΑΣ": "MIC",
    "ΙΩΗΛ": "JOL",
    "ΑΒΔΙΟΥ": "OBA",
    "ΙΩΝΑΣ": "JON",
    "ΝΑΟΥΜ": "NAM",
    "ΑΜΒΑΚΟΥΜ": "HAB",
    "ΣΟΦΟΝΙΑΣ": "ZEP",
    "ΑΓΓΑΙΟΣ": "HAG",
    "ΖΑΧΑΡΙΑΣ": "ZEC",
    "ΜΑΛΑΧΙΑΣ": "MAL",
    "ΗΣΑΙΑΣ": "ISA",
    "ΙΕΡΕΜΙΑΣ": "JER",
    "ΒΑΡΟΥΧ": "BAR",
    "ΘΡΗΝΟΙ": "LAM",
    "ΕΠΙΣΤΟΛΗ ΙΕΡΕΜΙΟΥ": "LJE",
    "ΙΕΖΕΚΙΗΛ": "EZK",
    "ΣΟΥΣΑΝΝΑ": "SUS",
    "ΔΑΝΙΗΛ": "DAN",
    "ΒΗΛ ΚΑΙ ΔΡΑΚΩΝ": "BEL",
    # -- named manuscripts and recensions, which the canon already has codes for -------
    "Judices (Codex Vaticanus)": "JDB",
    "Tobias (Codex Sinaiticus)": "TBS",
    "Bel et Draco (Theodotionis versio)": "BLT",
    # -- Latin, the New Testament ------------------------------------------------------
    "Evangelium secundum Matthaeum": "MAT",
    "Evangelium secundum Marcum": "MRK",
    "Evangelium secundum Lucam": "LUK",
    "Evangelium secundum Ioannem": "JHN",
    "Acta apostolorum": "ACT",
    "Epistula Pauli ad Romanos": "ROM",
    "Epistula Pauli ad Corinthios I": "1CO",
    "Epistula Pauli ad Corinthios II": "2CO",
    "Epistula Pauli ad Galatas": "GAL",
    "Epistula Pauli ad Ephesios": "EPH",
    "Epistula Pauli ad Philippenses": "PHP",
    "Epistula Pauli ad Colossenses": "COL",
    "Epistula Pauli ad Thessalonicenses I": "1TH",
    "Epistula Pauli ad Thessalonicenses II": "2TH",
    "Epistula Pauli ad Timotheum I": "1TI",
    "Epistula Pauli ad Timotheum II": "2TI",
    "Epistula Pauli ad Titum": "TIT",
    "Epistula Pauli ad Philemonem": "PHM",
    "Epistula Pauli ad Hebraeos": "HEB",
    "Epistula Iacobi": "JAS",
    "Epistula Petri I": "1PE",
    "Epistula Petri II": "2PE",
    "Epistula Ioannis I": "1JN",
    "Epistula Ioannis II": "2JN",
    "Epistula Ioannis III": "3JN",
    "Epistula Iuda": "JUD",
    "Apocalypsis Ioannis": "REV",
    # -- English, as the Syriac Old Testament titles itself -----------------------------
    "Samuel 1": "1SA",
    "Samuel 2": "2SA",
    "Kings 1": "1KI",
    "Kings 2": "2KI",
    "Chronicles 1": "1CH",
    "Chronicles 2": "2CH",
    "Nehemia": "NEH",
    "Prayer of Manasseh A": "MAN",
    "Prayer of Manasseh B": "MAN",
    "Esdras 3": "1ES",  # Syriac numbering: 3 Esdras is the Greek 1 Esdras
    "Esdras 4": "EZA",  # and 4 Esdras is the Ezra Apocalypse
    "Tobit A": "TOB",
    "Tobit B": "TOB",
    "Maccabees 1 A": "1MA",
    "Maccabees 1 B": "1MA",
    "Maccabees 2": "2MA",
    "Maccabees 3": "3MA",
    "Maccabees 4": "4MA",
    "Apocryphal Psalms A": "PS2",
    "Apocryphal Psalms B": "PS2",
    "Apocryphal Psalms": "PS2",
    # -- Syriac, the New Testament ------------------------------------------------------
    "ܐܘܢܓܠܝܘܢ ܕܡܬܝ": "MAT",
    "ܐܘܢܓܠܝܘܢ ܩܕܝܫܐ ܟܪܘܙܘܬܐ ܕܡܪܩܘܣ": "MRK",
    "ܐܘܢܓܠܝܘܢ ܩܕܝܫܐ ܟܪܘܙܘܬܐ ܕܠܘܩܐ": "LUK",
    "ܐܘܢܓܠܝܘܢ ܩܕܝܫܐ ܟܪܘܙܘܬܐ ܕܝܘܚܢܢ": "JHN",
    "ܦܪܟܣܣ ܕܬܪܥܣܪ ܫܠܝ̈ܚܐ ܛܘܒ̈ܢܐ": "ACT",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܪ̈ܗܘܡܝܐ": "ROM",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܩܘܪ̈ܝܢܬܝܐ ܩܕܡܝܬܐ": "1CO",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܩܘܪ̈ܝܢܬܝܐ ܕܬܪܬܝܢ": "2CO",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܓܠܛܝ̈ܐ": "GAL",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܐܦܣܝ̈ܐ": "EPH",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܦܝܠܝܦܣܝ̈ܐ": "PHP",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܩܘܠ̈ܣܝܐ": "COL",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܬܣܠ̈ܘܢܝܩܝܐ ܩܕܡܝܬܐ": "1TH",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܬܣܠ̈ܘܢܝܩܝܐ ܕܬܪܬܝܢ": "2TH",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܛܝܡܬܐܘܣ ܩܕܡܝܬܐ": "1TI",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܛܝܡܬܐܘܣ ܕܬܪܬܝܢ": "2TI",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܛܝܛܘܣ": "TIT",
    "ܐܓܪܬܐ ܕܦܘܠܘܣ ܕܠܘܬ ܦܝܠܝܡܘܢ": "PHM",
    "ܐܓܪܬܐ ܕܠܘܬ ܥܒܪ̈ܝܐ": "HEB",
    "ܐܓܪܬܐ ܕܝܥܩܘܒ ܫܠܝܚܐ": "JAS",
    "ܐܓܪܬܐ ܕܦܛܪܘܣ ܫܠܝܚܐ": "1PE",
    "ܐܓܪܬܐ ܕܬܪ̈ܬܝܢ ܕܦܛܪܘܣ ܫܠܝܚܐ": "2PE",
    "ܐܓܪܬܐ ܕܝܘܚܢܢ ܫܠܝܚܐ": "1JN",
    "ܐܓܪܬܐ ܕܬܪ̈ܬܝܢ ܕܝܘܚܢܢ ܫܠܝܚܐ": "2JN",
    "ܐܓܪܬܐ ܕܬܠܬ ܕܝܘܚܢܢ ܫܠܝܚܐ": "3JN",
    "ܐܓܪܬܐ ܕܝܗܘܕܐ ܫܠܝܚܐ": "JUD",
    "ܓܠܝܢܐ ܕܝܘܚܢܢ": "REV",
}

#: Which corpus each PTA version belongs to. The Old/New Testament split is not editorial
#: neatness: it is where the licences change, and a corpus has to be able to state one.
#:
#: ``pta-grc1`` is Rahlfs' Septuagint over the Old Testament (CC BY-SA) and the SBL Greek
#: New Testament over the New (CC BY, though the edition's own terms are not CC BY).
#: ``pta-syc1`` is the ETCBC Peshitta Old Testament (CC BY-NC) and the Peshitta New
#: Testament (CC BY).
CORPUS_OF: Final[dict[tuple[str, bool], str]] = {
    ("pta-grc1", False): "rahlfs",
    ("pta-grc1", True): "sblgnt",
    ("pta-syc1", False): "peshitta-ot",
    ("pta-syc1", True): "peshitta-nt",
    ("pta-grc2", False): "rahlfs-alt",
    ("pta-syc2", False): "peshitta-alt",
    ("pta-syc3", False): "peshitta-alt",
    ("pta-syc4", False): "peshitta-alt",
}

_NT: Final = frozenset(
    "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE "
    "2PE 1JN 2JN 3JN JUD REV".split()
)


def titles_of(tree: etree._ElementTree) -> list[str]:
    """Every name this file gives itself, best first.

    Two of them, and neither is reliably the better one. The printed title is what the
    edition calls the book -- ``ΓΕΝΕΣΙΣ`` -- and the catalogued one is the archive's
    Latin. The Septuagint files put the printed title in plain text; the Greek New
    Testament writes it as ``<title><w>ΚΑΤΑ</w><w>ΜΑΘΘΑΙΟΝ</w></title>``, one element per
    word, which is why this flattens rather than reading ``.text``.

    Returning both and letting the caller try each in turn beats choosing here: whichever
    resolves is the right one, and a file with neither is a real gap worth printing.
    """
    found: list[str] = []
    body = tree.find(f".//{TEI}body")
    if body is not None:
        head = body.find(f".//{TEI}head/{TEI}title")
        if head is not None:
            found.append(flatten(head))
    catalogued = tree.find(f".//{TEI}titleStmt/{TEI}title")
    if catalogued is not None and catalogued.text:
        found.append(str(catalogued.text).strip())
    return [title for title in found if title]


def _key(title: str) -> str:
    """A title in a form two files can be compared in.

    NFKC and nothing more, but it is load-bearing: the Septuagint's book numbers are
    written with U+0374 GREEK NUMERAL SIGN in some files and U+02B9 MODIFIER LETTER PRIME
    in others. The two are indistinguishable on screen, and without folding them
    ``ΒΑΣΙΛΕΙΩΝ Αʹ`` matches an alias written the other way not at all -- which is twelve
    books of Kingdoms, Chronicles, Esdras and Maccabees silently unresolved.
    """
    return unicodedata.normalize("NFKC", title).strip()


_BY_KEY: Final = {_key(name): code for name, code in ALIASES.items()}


def resolve(title: str) -> str | None:
    """A USFM code for this title, by alias first and the canon's own resolver second."""
    alias = _BY_KEY.get(_key(title))
    if alias is not None:
        return alias
    for scheme in (NamingScheme.MODERN, NamingScheme.LXX, NamingScheme.DR):
        try:
            return resolve_book(title, scheme)
        except (AmbiguousBookError, UnknownBookError):
            continue
    return None


def scan_pta(root: Path) -> dict[str, dict[str, object]]:
    """Every scripture file in a ``pta_data`` checkout, by CTS URN."""
    out: dict[str, dict[str, object]] = {}
    for path in sorted(root.glob("data/pta9999/pta*/pta9999.*.xml")):
        stem = path.name.removesuffix(".xml")
        _, work, version = stem.split(".", 2)
        tree = etree.parse(str(path))
        titles = titles_of(tree)
        book = next((found for title in titles if (found := resolve(title))), None)
        title = titles[0] if titles else ""
        corpus = None
        if book is not None:
            corpus = CORPUS_OF.get((version, book in _NT))
        out[f"{work}.{version}"] = {
            "book": book,
            "corpus": corpus,
            "title": title,
            "file": path.name,
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pta", type=Path, help="a pta_data checkout, or a fetched archive")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src/biblereference/data/tei_books.json",
    )
    args = parser.parse_args()

    table = {"pta": scan_pta(args.pta)}
    args.out.write_text(
        json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    entries = table["pta"]
    unresolved = [key for key, row in entries.items() if row["book"] is None]
    print(f"{len(entries)} files, {len(entries) - len(unresolved)} resolved")
    for key in unresolved:
        print(f"  unresolved: {key:24} {entries[key]['title']}")
    counts: dict[str, int] = {}
    for row in entries.values():
        name = str(row["corpus"] or "(none)")
        counts[name] = counts.get(name, 0) + 1
    print("by corpus:", dict(sorted(counts.items())))
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
