"""Measure what inflected matching actually finds, against quotations editors marked by hand.

The thresholds in `Searcher` are two numbers with a great deal resting on them, and there is
exactly one honest way to choose them: run the matcher over quotations somebody who reads
Greek has already identified, and count. Nineteen fixtures cannot calibrate two thresholds.

The ground truth is the Patristic Text Archive's `editor_reference` table, held by the
sibling `churchfathers` project. Every row is an editor saying *this span quotes this verse*.

    venv/bin/python tools/calibrate_inflected.py --sample 1200
    venv/bin/python tools/calibrate_inflected.py --full

The first thing it prints is the baseline at `inflected=False`. If that does not land near
the 38.6% the request reports, the harness is wrong and nothing below it means anything --
so it is printed first and compared out loud rather than assumed.

Not shipped as a command: it needs a corpus this library does not own, and a number measured
against somebody else's data belongs in a report rather than in a CLI.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.canon import AmbiguousBookError, UnknownBookError, resolve_book
from biblereference.search import GRADES, Searcher
from biblereference.store import DataHome

MARKS = Path.home() / ".local/share/churchfathers/db/corpus.sqlite"

#: The tuning `churchfathers` actually runs Greek at, so the baseline is *their* baseline
#: rather than a number reached with settings nobody uses.
GREEK = {"coverage": 0.50, "min_run": lambda n: max(4, min(6, n // 2))}

#: How the editors' reference prefixes map onto this library's numbering systems.
SYSTEMS = {"NA": "org", "LXX": "lxx"}


@dataclass(frozen=True, slots=True)
class Mark:
    book: str
    chapter: int
    verse: int
    vrs: str
    quoted: str


def marks(limit: int | None, seed: int = 0) -> list[Mark]:
    """Editor-marked Greek quotations that name a verse this library could hold."""
    db = sqlite3.connect(f"file:{MARKS}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT e.raw, e.quoted FROM editor_reference e JOIN witness w ON w.id = e.witness "
        "WHERE w.language = 'grc' AND e.quoted IS NOT NULL AND e.quoted <> ''"
    ).fetchall()
    out: list[Mark] = []
    for raw, quoted in rows:
        parts = str(raw).split(":")
        if len(parts) != 4 or parts[0] not in SYSTEMS:
            continue
        system, book, chapter, verse = parts
        try:
            usfm = resolve_book(book)
        except (UnknownBookError, AmbiguousBookError):
            continue
        if not chapter.isdigit() or not verse.isdigit():
            continue
        out.append(Mark(usfm, int(chapter), int(verse), SYSTEMS[system], str(quoted)))
    if limit and len(out) > limit:
        # Sampled deterministically, so two runs of the same size are comparable.
        out = random.Random(seed).sample(out, limit)
    return out


def run(home: DataHome, found: list[Mark], **options: object) -> dict[str, int]:
    """How many marks the searcher lands on, by grade of the match that found them."""
    tally = {"marks": len(found), "hit": 0, "book": 0, **{grade: 0 for grade in GRADES}}
    with Searcher(home, languages=["grc"], **GREEK, **options) as searcher:  # type: ignore[arg-type]
        for mark in found:
            for match in searcher.search(mark.quoted, limit=5):
                span = match.passage
                if span.book != mark.book:
                    continue
                tally["book"] += 1
                if span.start.verse <= mark.verse <= span.end.verse:
                    tally["hit"] += 1
                    tally[match.grade] += 1
                break
    return tally


def show(label: str, tally: dict[str, int]) -> None:
    total = tally["marks"] or 1
    print(
        f"  {label:28} {tally['hit']:>5}/{total:<5} {100 * tally['hit'] / total:5.1f}%   "
        f"book {100 * tally['book'] / total:5.1f}%   "
        + "  ".join(f"{grade} {tally[grade]}" for grade in GRADES)
    )


def sweep(home: DataHome, found: list[Mark]) -> Iterator[tuple[str, dict[str, int]]]:
    for lemma_run in (2, 3):
        for bits in (10.0, 12.0, 15.0, 20.0):
            label = f"run>={lemma_run} bits>={bits:g}"
            yield label, run(home, found, inflected=True, min_lemma_run=lemma_run, min_bits=bits)


def additive(home: DataHome, found: list[Mark]) -> tuple[int, int]:
    """Whether every passage found with the feature off is still found with it on.

    The promise the consumer cares about most, checked at scale rather than asserted. The
    fixed-corpus guard in `tests/test_regression.py` proves the fields do not move; this
    proves the *match set* does not shrink over thousands of real quotations.

    :returns: ``(marks checked, passages lost)``. The second must be zero.
    """
    lost = 0
    with (
        Searcher(home, languages=["grc"], **GREEK) as plain,  # type: ignore[arg-type]
        Searcher(home, languages=["grc"], inflected=True, **GREEK) as rich,  # type: ignore[arg-type]
    ):
        for mark in found:
            before = {str(m.passage) for m in plain.search(mark.quoted, limit=5)}
            after = {str(m.passage) for m in rich.search(mark.quoted, limit=5)}
            lost += len(before - after)
    return len(found), lost


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1200, help="marks to measure (0 = all)")
    parser.add_argument("--full", action="store_true", help="every mark; slow")
    args = parser.parse_args()

    if not MARKS.exists():
        print(f"no ground truth at {MARKS}", file=sys.stderr)
        return 1

    home = DataHome()
    found = marks(None if args.full or not args.sample else args.sample)
    print(f"{len(found):,} editor-marked Greek quotations naming a verse\n")

    print("baseline -- this must reproduce what the request reports, or nothing below counts")
    show("inflected=False", run(home, found))

    _, lost = additive(home, found)
    print(f"\nadditive: {lost} passage(s) found with the feature off and lost with it on")

    print("\ninflected, by gate")
    for label, tally in sweep(home, found):
        show(label, tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
