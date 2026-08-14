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
from biblereference.lemmata import Lexicon
from biblereference.search import (
    GRADES,
    Gate,
    LemmaWeights,
    Searcher,
    _tokens,
    lemma_chain,
    lemma_readings,
    lemma_run,
    longest_run,
    shared_bits,
)
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
    """Recall for each candidate gate, one gate at a time, so the union can be read off."""
    for gate in CANDIDATES:
        yield str(gate), run(home, found, inflected=True, gates=[gate])
    yield "union of all", run(home, found, inflected=True, gates=CANDIDATES)


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


#: Eras whose authors were dead before there was a New Testament to quote, so every match in
#: them is a false positive by construction. Read from `churchfathers`' own dating table --
#: the consumer's control group, not one invented here to be flattered by.
CONTROL_ERAS = {"classical", "pre-christian", "pre-septuagint"}

#: The permissive gate the sweep collects through. Every candidate gate below is stricter, so
#: one pass gathers the evidence for all of them and the sweep costs one scan, not twenty.
COLLECT = Gate(chain=2, bits=10.0)


def control_text(cap: int) -> tuple[list[str], int]:
    """Greek by authors who cannot be quoting the New Testament, up to ``cap`` words."""
    import json

    dating = json.loads(
        (Path.home() / "churchfathers/src/churchfathers/data/dating.json").read_text("utf-8")
    )
    eras = {key: value.get("era") for key, value in dating.items() if isinstance(value, dict)}
    db = sqlite3.connect(f"file:{MARKS}?mode=ro", uri=True)
    witnesses = [
        wid
        for wid, work, _ in db.execute(
            "SELECT id, work, words FROM witness WHERE language = 'grc' AND words > 0"
        )
        if eras.get((work or "").split(".")[0]) in CONTROL_ERAS
    ]
    random.Random(11).shuffle(witnesses)
    out: list[str] = []
    words = 0
    for wid in witnesses:
        for (text,) in db.execute(
            "SELECT text FROM passage WHERE witness = ? AND text IS NOT NULL", (wid,)
        ):
            out.append(str(text))
            words += len(str(text).split())
            if words >= cap:
                return out, words
    return out, words


def evidence(home: DataHome, texts: list[str], window: int = 12, stride: int = 6) -> list[tuple]:
    """Every graded match the permissive gate finds, with all four axes measured.

    One pass, because the axes are properties of a match rather than of a gate: collecting
    them once lets twenty candidate gates be scored offline instead of twenty scans.
    """
    lexicon, weights = Lexicon(home), LemmaWeights(home)
    weigh = weights.of("grc")
    verses = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    searcher = Searcher(
        home, languages=["grc"], inflected=True, min_query=3, gates=[COLLECT], **GREEK
    )
    found: list[tuple] = []
    with searcher:
        for text in texts:
            tokens = text.split()
            for start in range(0, max(1, len(tokens) - window + 1), stride):
                chunk = " ".join(tokens[start : start + window])
                for match in searcher.search(chunk, limit=3):
                    if match.grade == "direct":
                        continue
                    row = verses.execute(
                        "SELECT text FROM verse WHERE corpus = ? AND book = ? "
                        "AND chapter = ? AND verse = ?",
                        (
                            match.witnesses[0].corpus,
                            match.passage.book,
                            match.passage.start.chapter,
                            match.passage.start.verse,
                        ),
                    ).fetchone()
                    if not row:
                        continue
                    found.append(axes(chunk, str(row[0]), lexicon, weigh))
    return found


def axes(text: str, verse: str, lexicon: Lexicon, weigh: object) -> tuple[int, int, int, float]:
    """``(run, lemma_run, chain, bits)`` for one text against one verse."""
    query, spelled = _tokens(text, "grc"), _tokens(verse, "grc")
    mine = lemma_readings(query, "grc", lexicon)
    theirs = lemma_readings(spelled, "grc", lexicon)
    chained = lemma_chain(mine, theirs, weigh)  # type: ignore[arg-type]
    first, last = chained.span
    weight = shared_bits(mine[first:last], theirs, weigh) if last > first else 0.0  # type: ignore[arg-type]
    return (
        longest_run(query, spelled),
        lemma_run(mine, theirs, weigh).length,  # type: ignore[arg-type]
        chained.length,
        weight,
    )


CANDIDATES = [
    Gate(lemma_run=2, bits=60.0),
    Gate(lemma_run=4, bits=40.0),
    Gate(lemma_run=5, bits=35.0),
    Gate(chain=4, bits=50.0),
    Gate(chain=5, bits=40.0),
    Gate(chain=6, bits=35.0),
    Gate(chain=8, bits=40.0),
    Gate(chain=8, bits=30.0),
    Gate(chain=10, bits=25.0),
    Gate(run=3, bits=20.0),
    Gate(run=4, bits=15.0),
]


def cmd_control(args: argparse.Namespace) -> int:
    home = DataHome()
    texts, words = control_text(args.control)
    print(f"control: {words:,} words of classical / pre-christian / pre-septuagint Greek\n")
    found = evidence(home, texts)
    print(f"collected at {COLLECT}: {len(found):,} graded matches, all of them false\n")
    print(f"{'gate':34} {'false positives':>15} {'per 1,000 words':>16}")
    for gate in CANDIDATES:
        n = sum(1 for row in found if gate.admits(*row))
        print(f"  {gate!s:32} {n:>15,} {n / words * 1000:>16.4f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1200, help="marks to measure (0 = all)")
    parser.add_argument("--full", action="store_true", help="every mark; slow")
    parser.add_argument(
        "--control",
        type=int,
        default=0,
        metavar="WORDS",
        help="instead, measure false positives over this many words of pre-Christian Greek",
    )
    parser.add_argument("--save", metavar="PATH", help="write/read the collected evidence")
    args = parser.parse_args()
    if args.control:
        return cmd_control(args)

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
