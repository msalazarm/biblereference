"""The Antoniades 1904/1912 Patriarchal text: the Greek NT the Orthodox church reads.

Roadmap row 1's last member. The library's other Greek New Testaments are critical
editions plus the Byzantine Textform; this is the *received liturgical text* — the
edition a Greek father's medieval copyist and a modern lectionary both stand nearest —
in the Robinson/Ala-Konni collation, "thoroughly compared to the 1904 edition and
double-checked against the 1912", public domain by the repository's own statement.

The upstream is betacode-only in its primary files — the reason quotes.md's §11 ledger
deferred it — in the Online Bible ASCII scheme, *not* TLG betacode: ``y`` is θ where TLG
says ψ, ``c`` is χ where TLG says ξ, ``q`` is ψ, and final sigma is spelled ``v``
explicitly. The mapping below was pinned empirically against the text itself, and the
build then verifies it **totally**: the upstream also carries its own Unicode
conversion of every book, and every verse this build emits must equal that conversion
byte for byte (after whitespace normalisation) or the build refuses to ship. A
transliterator wrong anywhere in 7,943 verses cannot get through.

Both forms upstream are unaccented; the note on the corpus says so. The fold discards
diacritics before any search, so recall is untouched — what is lost is only display
polish, and inventing accents would be editing scripture.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build", "transliterate"]

_RAW: Final = "https://raw.githubusercontent.com/byztxt/greektext-antoniades/master/textonly"

#: Upstream stem (Online Bible book codes) to USFM.
_BOOKS: Final = {
    "MT": "MAT", "MR": "MRK", "LU": "LUK", "JOH": "JHN", "AC": "ACT",
    "RO": "ROM", "1CO": "1CO", "2CO": "2CO", "GA": "GAL", "EPH": "EPH",
    "PHP": "PHP", "COL": "COL", "1TH": "1TH", "2TH": "2TH", "1TI": "1TI",
    "2TI": "2TI", "TIT": "TIT", "PHM": "PHM", "HEB": "HEB", "JAS": "JAS",
    "1PE": "1PE", "2PE": "2PE", "1JO": "1JN", "2JO": "2JN", "3JO": "3JN",
    "JUDE": "JUD", "RE": "REV",
}

#: The Online Bible ASCII scheme, pinned against the upstream's own Unicode files.
#: ``v`` spells final sigma explicitly, so no positional logic exists to get wrong.
_LETTERS: Final = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η",
    "y": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "x": "ξ",
    "o": "ο", "p": "π", "r": "ρ", "s": "σ", "v": "ς", "t": "τ", "u": "υ",
    "f": "φ", "c": "χ", "q": "ψ", "w": "ω",
    # Punctuation as the upstream's Unicode conversion renders it: the colon is the
    # Greek ano teleia, and a doubled hyphen is their em-dash (every hyphen in the text
    # comes paired -- 112 hyphens, 56 dashes). The rest passes through by membership,
    # never silently.
    ":": "·", ",": ",", ".": ".", ";": ";", "!": "!", "<": "<", ">": ">",
    "[": "[", "]": "]",
}


def transliterate(text: str) -> str:
    """Online-Bible ASCII to unaccented Greek. An unmapped character is an error, not a
    pass-through -- a silent gap here would put wrong letters in scripture."""
    out: list[str] = []
    for ch in text.replace("--", "\u2014"):
        if ch.isspace() or ch.isdigit() or ch == "\u2014":
            out.append(ch)
            continue
        mapped = _LETTERS.get(ch.lower())
        if mapped is None:
            raise ValueError(f"no Greek for {ch!r} in {text[:60]!r}")
        out.append(mapped)
    # Their converter's rendering: the dash closes up to the word before it.
    return "".join(out).replace(" \u2014", "\u2014")


_REF_RE: Final = re.compile(r"(\d+):(\d+)")


def _verses(path: Path) -> Iterator[tuple[int, int, str]]:
    """``(chapter, verse, text)`` from one upstream file: ``C:V text`` lines with
    indented continuations, blank lines between paragraphs.

    The reference pattern is matched anywhere, not only at line starts, because the
    upstream's Unicode converter once jammed a verse onto the previous line
    (John 4:2 ends 4:1's line in ``JOH.txt``) -- and neither form of the text contains
    any digit outside a reference, so the general split cannot misfire."""
    text = path.read_text("utf-8")
    marks = list(_REF_RE.finditer(text))
    for mark, next_mark in zip(marks, [*marks[1:], None], strict=False):
        stretch = text[mark.end() : next_mark.start() if next_mark else len(text)]
        yield (int(mark.group(1)), int(mark.group(2)), " ".join(stretch.split()))


def build(archive: Path) -> Iterator[BuiltCorpus]:
    verses: list[tuple[VerseRef, str]] = []
    spacing: list[str] = []
    for stem, book in sorted(_BOOKS.items()):
        greek = {
            (chapter, verse): text
            for chapter, verse, text in _verses(archive / f"{stem}.txt")
        }
        for chapter, verse, ascii_text in _verses(archive / f"{stem}.ANT"):
            ours = transliterate(ascii_text)
            theirs = greek.get((chapter, verse))
            # The letters must agree to the byte; spacing may not, because the
            # upstream's own converter drops the occasional space ("εαυτουπαρακαλουντεσ"
            # spelled solid in their 1TH 2:11) and the betacode side, the primary text,
            # has it right. A letter difference is still a refusal.
            if (
                theirs is not None
                and ours != theirs
                and ours.replace(" ", "") == theirs.replace(" ", "")
            ):
                spacing.append(f"{book} {chapter}:{verse}")
                theirs = ours
            if theirs is None or ours != theirs:
                raise ValueError(
                    f"transliteration of {book} {chapter}:{verse} disagrees with the "
                    f"upstream's own Unicode conversion:\n  ours:   {ours!r}\n"
                    f"  theirs: {theirs!r}"
                )
            verses.append((VerseRef(book, chapter, verse, vrs="org"), ours))
    yield BuiltCorpus(
        id="grcant",
        label="Antoniades 1904/1912 Patriarchal Text",
        language="grc",
        versification="org",
        verses=verses,
        notes=[
            "unaccented: the upstream distributes the text without diacritics in both "
            "its ASCII and Unicode forms; the fold discards diacritics before search, "
            "so only display is plainer",
            "every verse's letters verified against the upstream's own Unicode "
            "conversion at build time; a letter divergence refuses to build"
            + (
                f"; spacing follows the betacode side where the two disagree "
                f"({', '.join(spacing)})"
                if spacing
                else ""
            ),
            "movable nu regularised by the upstream (always present); a third near-copy "
            "of the Byzantine text raises the exact path's edition count -- the "
            "profiles, which pool editions per verse, are the fix of record",
        ],
    )


SOURCE: Final = Source(
    id="antoniades",
    label="Antoniades 1904/1912 Patriarchal Greek New Testament (Robinson/Ala-Konni collation)",
    homepage="https://github.com/byztxt/greektext-antoniades",
    license="Public domain, per the repository's README and collation notes.",
    terms=get("public-domain"),
    files=tuple(
        RemoteFile(url=f"{_RAW}/{stem}.ANT", name=f"{stem}.ANT") for stem in sorted(_BOOKS)
    )
    + tuple(
        RemoteFile(url=f"{_RAW}/unicode/{stem}.txt", name=f"{stem}.txt")
        for stem in sorted(_BOOKS)
    ),
    build=build,
    note="The received Orthodox liturgical text; closes quotes.md roadmap row 1.",
)
