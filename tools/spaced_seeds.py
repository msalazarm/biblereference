"""The spaced-seed experiment: can a gapped lemma pattern out-find the contiguous run?

PatternHunter's result, tested on this library's own ground truth: a seed like ``11*1*11``
requires lemma agreement only at its ``1`` positions, and at *equal weight* — equal
expected random-hit rate — an optimally spaced seed is markedly more sensitive than a
contiguous one, because scattered substitutions rarely hit every required position while
one substitution kills a contiguous run. Our ``lemma_run`` gate is the degenerate
contiguous case; re-inflected quotations that break contiguity are exactly the miss class
a spaced seed could reach with an actual sensitivity theory behind it instead of
hand-tuning.

This harness measures the **sensitivity half now**: over editor-marked quotations, does
each candidate pattern fire somewhere against the named verse? The equal-weight framing
is what makes the comparison meaningful before the FP half runs — the theory says
random-hit rates match at equal weight, and the theory is not the measurement: per the
standing rule, **no pattern ships as a gate axis until the control corpus prices it**.

**The measurement, 2026-08-17, 396 marks: every spaced pattern loses.** Weight-4 spaced
seeds run 11–24 points *behind* contiguous ``1111``; weights 5 and 6 the same shape. The
genomics result reverses here for a structural reason worth recording: DNA noise is
substitution-shaped — a base changes, the positions around it stand still, and a spaced
seed steps over the change. Greek re-inflection is **indel-shaped** — particles appear,
word order shifts, endings lengthen — so a fixed-offset pattern demands a lockstep
alignment the text does not keep, while the chain's variable gaps absorb exactly that.
The chain was already the right tool; this experiment is how we know rather than
believe, and no candidate has earned a control-corpus pricing run.

    venv/bin/python tools/spaced_seeds.py --sample 400
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_inflected import MARKS, marks

from biblereference.lemmata import Lexicon
from biblereference.search import Reading, _tokens, lemma_readings
from biblereference.store import DataHome

#: Candidates grouped by weight, the contiguous seed first as each group's baseline.
#: Patterns follow PatternHunter's convention: `1` requires a shared lemma at that
#: offset, `*` is free. Equal weight within a group = comparable random-hit rate, so any
#: sensitivity gap inside a group is the spacing's own doing.
PATTERNS: dict[int, tuple[str, ...]] = {
    4: ("1111", "11*11", "1*1*11", "11**11"),
    5: ("11111", "11*111", "111*1*1", "11*1*11"),
    6: ("111111", "11*11*11", "111**111", "1*11*1*11"),
}


def fires(mine: Sequence[Reading], theirs: Sequence[Reading], pattern: str) -> bool:
    """Whether the pattern matches anywhere: every `1` offset shares a lemma, in order,
    at one (i, j) anchor. Exhaustive over the pair -- the sequences are a quotation and
    a verse, and exact is affordable where it is honest."""
    ones = [k for k, mark in enumerate(pattern) if mark == "1"]
    span = len(pattern)
    for i in range(len(mine) - span + 1):
        for j in range(len(theirs) - span + 1):
            if all(mine[i + k] & theirs[j + k] for k in ones):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=400, help="marks to measure (0 = all)")
    args = parser.parse_args()
    if not MARKS.exists():
        print(f"no ground truth at {MARKS}", file=sys.stderr)
        return 1

    home = DataHome()
    lexicon = Lexicon(home)
    lexicon.require("grc")
    verses = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)

    pairs: list[tuple[list[Reading], list[Reading]]] = []
    for mark in marks(args.sample):
        corpus = "n1904" if mark.vrs == "org" else "rahlfs"
        row = verses.execute(
            "SELECT text FROM verse WHERE corpus=? AND book=? AND chapter=? AND verse=?",
            (corpus, mark.book, mark.chapter, mark.verse),
        ).fetchone()
        if row:
            pairs.append(
                (
                    lemma_readings(_tokens(mark.quoted, "grc"), "grc", lexicon),
                    lemma_readings(_tokens(str(row[0]), "grc"), "grc", lexicon),
                )
            )
    print(f"{len(pairs):,} editor-marked pairs\n")
    print(f"{'weight':>6}  {'pattern':12} {'fires':>8}  {'sensitivity':>11}  vs contiguous")
    for weight, group in PATTERNS.items():
        baseline = None
        for pattern in group:
            hit = sum(1 for mine, theirs in pairs if fires(mine, theirs, pattern))
            share = hit / (len(pairs) or 1)
            if baseline is None:
                baseline = share
                delta = "(baseline)"
            else:
                delta = f"{100 * (share - baseline):+.1f} points"
            print(f"{weight:>6}  {pattern:12} {hit:>8,}  {100 * share:>10.1f}%  {delta}")
        print()
    print(
        "Sensitivity only. Equal weight makes the within-group comparison meaningful,\n"
        "and nothing here gates anything: a pattern that beats its baseline earns a\n"
        "control-corpus pricing run, not a place in the defaults."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
