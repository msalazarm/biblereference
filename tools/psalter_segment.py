"""Segment Jerome's *Psalterium iuxta Hebraeos* and measure whose divisions it follows.

    venv/bin/python tools/psalter_segment.py cc-7213.xml
    venv/bin/python tools/psalter_segment.py cc-7213.xml --psalm 3

The library has no Latin witness to ``org``, so ``nvl`` is checked at 0% by the coverage
walk: its only witnesses are Latin and the pivot has none. Jerome's second psalter is the
obvious candidate -- translated from the Hebrew rather than revised against the Greek, and
covering exactly the book where the systems diverge most.

**Two signals were expected and one of them turned out not to be needed.** The plan for this
assumed the psalms would have to be found by aligning against the Gallican psalter, because
Migne prints only 49 headings for 150 psalms and they are Hebrew superscriptions rather than
numbers. But the *numbers are in the text*, set as Roman numerals in brackets -- ``[ I.]``,
``[ XXXVIII]``, ``[ XLVIII].`` -- so 149 of the 150 boundaries are printed rather than
inferred, and the alignment is a check rather than the method.

Verses are the ``<l>`` structure. Migne sets the psalter as poetry, one colon per line, and
a line with no ``@rend`` opens a verse while ``indent`` and ``indent(1)`` continue it.

What this prints is the comparison that decides whether the corpus is worth having: the
verse counts per psalm against ``org``, ``eng`` and ``vul``. A psalter that turns out to
follow the English or the Gallican divisions is not the witness ``nvl`` needs, and saying so
is the point -- Castellio looked like the answer too, and measured wrong.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from biblereference.corpora.tei import TEI_NS, flatten
from biblereference.versification import Versification

#: A psalm number as Migne sets it. The brackets and the stop are both unreliable -- the
#: file has `[ XXXVIII]` and `[ XLVIII].` as well as the usual `[ XXXIX.]` -- so both are
#: optional and the numeral itself carries the match.
NUMERAL = re.compile(
    r"^\[?\s*(C{0,3}(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))\s*\.?\s*\]?\s*\.?(?=\s|$)"
)

_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman(text: str) -> int:
    total = 0
    for index, letter in enumerate(text):
        value = _VALUES[letter]
        after = _VALUES[text[index + 1]] if index + 1 < len(text) else 0
        total += -value if value < after else value
    return total


@dataclass
class Psalm:
    number: int
    verses: list[str] = field(default_factory=list)
    numbered: bool = True
    """Whether a printed numeral opened it, or it was inferred."""


def segment(path: Path) -> list[Psalm]:
    """Every psalm, with its verses, in the order the file prints them."""
    root = etree.parse(str(path)).getroot()
    psalms: list[Psalm] = []
    current: Psalm | None = None
    parts: list[str] = []

    def close() -> None:
        if current is not None and parts:
            current.verses.append(" ".join(parts).strip())

    for line in root.iter(f"{{{TEI_NS}}}l"):
        text = flatten(line)
        if not text:
            continue
        rend = line.get("rend") or ""
        found = NUMERAL.match(text)
        if found:
            close()
            parts = []
            number = roman(found.group(1))
            # Strictly increasing, not consecutive. The numerals run 1..150 and never
            # repeat, so anything that does not advance is a stray capital rather than a
            # psalm -- but requiring +1 exactly would refuse the whole rest of the book at
            # the first psalm Migne left unnumbered, and there is one.
            if psalms and number <= psalms[-1].number:
                if current is not None:
                    parts = [text]
                continue
            current = Psalm(number)
            psalms.append(current)
            parts = [NUMERAL.sub("", text).strip()]
            continue
        if current is None:
            continue  # the preface, before the first psalm
        if rend.startswith("indent"):
            parts.append(text)
        else:
            close()
            parts = [text]
    close()
    return psalms


def compare(psalms: list[Psalm]) -> None:
    vrs = Versification.load()
    systems = ("org", "eng", "vul", "lxx", "nvl")
    held = {p.number: p for p in psalms}

    agree = dict.fromkeys(systems, 0)
    checked = 0
    rows = []
    for number in range(1, 151):
        psalm = held.get(number)
        if psalm is None:
            continue
        mine = len(psalm.verses)
        theirs = {}
        for system in systems:
            try:
                # `max_verse` is the highest number; a chapter whose superscription is a
                # numbered verse 0 has one more verse than that, which is the whole
                # distinction being measured here.
                top = vrs.max_verse(system, "PSA", number)
                first = vrs.first_verse(system, "PSA", number)
                theirs[system] = top - first + 1
            except Exception:
                theirs[system] = 0
        checked += 1
        for system in systems:
            if theirs[system] == mine:
                agree[system] += 1
        rows.append((number, mine, theirs))

    print(f"\n{len(psalms)} psalms segmented, {checked} compared\n")
    print("verse counts agreeing with each system:")
    for system in systems:
        share = agree[system] / checked if checked else 0
        print(f"  {system}  {agree[system]:4d} / {checked}   {share:6.1%}")

    print("\nthe psalms that decide Hebrew against Greek:")
    for number in (9, 10, 114, 115, 116, 117, 146, 147):
        psalm = held.get(number)
        if psalm is None:
            print(f"  {number:3d}  absent")
            continue
        row = next(r for r in rows if r[0] == number)
        print(
            f"  {number:3d}  this {row[1]:3d}   "
            + "  ".join(f"{s} {row[2][s]:3d}" for s in systems)
        )

    worst = sorted(rows, key=lambda r: -abs(r[1] - r[2]["org"]))[:12]
    print("\nfurthest from org:")
    for number, mine, theirs in worst:
        print(
            f"  Psalm {number:3d}  this {mine:3d}   "
            + "  ".join(f"{s} {theirs[s]:3d}" for s in ("org", "eng", "vul"))
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--psalm", type=int, help="print one psalm's verses and stop")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 1
    psalms = segment(args.path)

    if args.psalm:
        for psalm in psalms:
            if psalm.number == args.psalm:
                print(f"Psalm {psalm.number}: {len(psalm.verses)} verses")
                for index, verse in enumerate(psalm.verses, 1):
                    print(f"  {index:3d}  {verse}")
                return 0
        print(f"psalm {args.psalm} was not segmented", file=sys.stderr)
        return 1

    numbers = [p.number for p in psalms]
    missing = sorted(set(range(1, 151)) - set(numbers))
    print(f"{len(psalms)} psalms, {numbers[0]}..{numbers[-1]}")
    print(f"missing: {missing or 'none'}")
    print(f"total verses: {sum(len(p.verses) for p in psalms)}")
    compare(psalms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
