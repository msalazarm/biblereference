"""Try to read the Old Latin gospels, and measure whether the reading can be trusted.

    venv/bin/python tools/oldlatin_probe.py cc-6898.xml
    venv/bin/python tools/oldlatin_probe.py cc-6898.xml --show Vercellensis MAT 2

Migne prints four Old Latin gospel manuscripts -- Vercellensis, Veronensis, Corbeiensis,
Brixianus -- collated in one file, under the wrong author (Eusebius of Vercelli, by an old
attribution). It would be this library's first pre-Vulgate Latin, which is why it is worth
the trouble.

**It is the import with the most ways to manufacture a reading**, and this is a probe rather
than an importer for that reason. Three hazards, all of them present:

*The manuscripts are mutilated and Migne set the holes rather than filling them*, as runs of
spaced dots. A dot run is indistinguishable from a sentence stop followed by a space, and
whole verses vanish inside one -- Vercellensis Matthew 1 loses verses 6 and 7 entirely
between `Jesse a . . .` and `8. . .`.

*There is no verse markup*, and no line markup either: verse numbers are bare `N.` in the
middle of a paragraph, which is the same shape as an abbreviation or a lacuna beside a
digit.

*The manuscript changes without warning.* Some `div1` name a manuscript and not a gospel,
inheriting the gospel from before; some `div2` are a manuscript change rather than a
chapter; and two sections are collations of a *fifth* manuscript against the Vulgate rather
than text at all.

What this prints is what an importer would have to be judged on: how many verses each
manuscript yields, how that compares with what `vul` declares, and how much of what it
yields is lacuna rather than text.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from biblereference.corpora.tei import flatten
from biblereference.versification import Versification

GAP = "…"

#: A run of spaced dots: the editor's mark for a hole in the manuscript. Two or more,
#: because a single `. ` is a sentence.
LACUNA = re.compile(r"(?:\.\s+){2,}\.?")

#: `CAPUT XVII.`, and `CAPUT PRIMUM.` for the first.
CAPUT = re.compile(r"^CAPUT\s+(PRIMUM|[IVXLC]+)\s*\.?\s*$", re.IGNORECASE)

#: A manuscript name, wherever it appears -- in a book head, on its own, or as a `div2`.
CODEX = re.compile(r"CODEX\s+([A-Z]+)", re.IGNORECASE)

#: A gospel, from `INCIPIT EVANGELIUM SECUNDUM MATTHAEUM.`
GOSPEL = {"MATTHAEUM": "MAT", "MARCUM": "MRK", "LUCAM": "LUK", "JOHANNEM": "JHN"}

#: Sections that are apparatus rather than text: a collation of a fifth manuscript against
#: the Vulgate, and the prefatory argument. Importing either as scripture would put a list
#: of variant readings where a gospel should be.
APPARATUS = re.compile(r"LECTIONES|ABEUNTES|ARGUMENTUM|PRAEFATIO|MONITUM", re.IGNORECASE)

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman(text: str) -> int:
    if text.upper() == "PRIMUM":
        return 1
    total = 0
    for index, letter in enumerate(text.upper()):
        value = _ROMAN[letter]
        after = _ROMAN[text.upper()[index + 1]] if index + 1 < len(text) else 0
        total += -value if value < after else value
    return total


@dataclass
class Verse:
    book: str
    chapter: int
    verse: int
    codex: str
    text: str

    @property
    def only_gap(self) -> bool:
        """Nothing survives but the hole. Not a reading, and must not be stored as one."""
        return not self.text.replace(GAP, "").strip(" .,;:")


@dataclass
class Reading:
    verses: list[Verse] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


def read(path: Path) -> Reading:
    root = etree.parse(str(path)).getroot()
    out = Reading()
    book = ""
    codex = ""
    chapter = 0

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = element.tag.split("}")[-1]
        if name == "head":
            text = flatten(element)
            if APPARATUS.search(text):
                codex = ""  # stop storing until a real manuscript head resumes
                out.skipped[text[:48]] += 1
                continue
            for word, code in GOSPEL.items():
                if word in text.upper():
                    book = code
                    chapter = 0
            found = CODEX.search(text)
            if found:
                codex = found.group(1).title()
            caput = CAPUT.match(text.strip())
            if caput:
                chapter = roman(caput.group(1))
            continue
        if name != "p" or not book or not codex or not chapter:
            continue
        for verse, text in _verses(flatten(element)):
            out.verses.append(Verse(book, chapter, verse, codex, text))
    return out


def _verses(text: str) -> list[tuple[int, str]]:
    """Split a paragraph on its bare verse numbers, marking the holes first.

    The lacunae are replaced *before* the numbers are looked for, which is the only order
    that works: a hole beside a digit otherwise reads as a verse number, and a verse number
    inside a hole otherwise disappears.
    """
    marked = LACUNA.sub(f" {GAP} ", text)
    parts = re.split(r"(?:(?<=^)|(?<=[\s…]))(\d{1,3})\.\s", " " + marked)
    if len(parts) < 3:
        return []
    out = []
    for index in range(1, len(parts) - 1, 2):
        number = int(parts[index])
        body = re.sub(r"\s+", " ", parts[index + 1]).strip()
        out.append((number, body))
    return out


def measure(reading: Reading) -> None:
    vrs = Versification.load()
    by_codex: dict[str, list[Verse]] = {}
    for verse in reading.verses:
        by_codex.setdefault(verse.codex, []).append(verse)

    print(f"\n{len(reading.verses)} verses read, across {len(by_codex)} manuscripts\n")
    print(
        f"{'manuscript':16s} {'verses':>7s} {'only a hole':>12s} {'books':>6s} "
        f"{'past vul':>9s} {'out of order':>13s}"
    )
    for codex, verses in sorted(by_codex.items(), key=lambda kv: -len(kv[1])):
        holes = sum(1 for v in verses if v.only_gap)
        books = {v.book for v in verses}
        past = 0
        for verse in verses:
            try:
                if verse.verse > vrs.max_verse("vul", verse.book, verse.chapter):
                    past += 1
            except Exception:
                past += 1
        disordered = 0
        seen: dict[tuple[str, int], int] = {}
        for verse in verses:
            key = (verse.book, verse.chapter)
            if key in seen and verse.verse <= seen[key]:
                disordered += 1
            seen[key] = verse.verse
        print(
            f"{codex:16s} {len(verses):7d} {holes:12d} {len(books):6d} {past:9d} {disordered:13d}"
        )

    print("\nagainst what vul declares, per manuscript and gospel:")
    for codex, verses in sorted(by_codex.items(), key=lambda kv: -len(kv[1])):
        for book in ("MAT", "MRK", "LUK", "JHN"):
            here = [v for v in verses if v.book == book]
            if not here:
                continue
            chapters = {v.chapter for v in here}
            expected = sum(
                vrs.max_verse("vul", book, c)
                for c in chapters
                if c <= vrs.chapter_count("vul", book)
            )
            print(
                f"  {codex:14s} {book}  {len(here):5d} read   {expected:5d} declared "
                f"over {len(chapters):3d} chapters   {len(here) / max(expected, 1):5.1%}"
            )

    if reading.skipped:
        print("\nsections skipped as apparatus:")
        for name, count in reading.skipped.most_common(8):
            print(f"  {count:3d}x {name!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--show", nargs=3, metavar=("CODEX", "BOOK", "CHAPTER"))
    args = parser.parse_args()
    if not args.path.exists():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 1

    reading = read(args.path)
    if args.show:
        codex, book, chapter = args.show[0], args.show[1], int(args.show[2])
        for verse in reading.verses:
            if verse.codex == codex and verse.book == book and verse.chapter == chapter:
                mark = "  (hole only)" if verse.only_gap else ""
                print(f"{verse.verse:3d}{mark}  {verse.text[:150]}")
        return 0
    measure(reading)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
