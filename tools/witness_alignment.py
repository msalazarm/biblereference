"""Find witnesses that share a chapter's verse numbers but not its contents.

`faithful_chapters` asks whether a corpus holds the number of verses its system declares.
That question has a blind spot its own docstring names twice -- a verse *swap* leaves counts
identical, and a psalm title numbered 1 instead of 0 does too -- and
`adjudicate._disputed_chapters` closes a third, where one witness renumbers over a gap
another leaves open. All three are about *which numbers exist*. None can see a chapter where
both witnesses hold verses 1..25 and put different text in them.

Judith 16 is that case. `brenton` carries an incipit at 16:1 that the Greek puts at 15:14, so
its 16:2-7 are the Greek's 16:1-6, its 16:8 merges the Greek's 7 and 8, and 16:9 resynchronises.
Both hold exactly 1..25. Counting cannot tell, and reading 25 verses in three languages does
not scale to 1,189 chapters.

**Verse length does tell, and it needs no lexicon and no shared language.** A chapter's verses
have a shape -- a long one here, two short ones there -- and two witnesses to the same chapter
share it whatever language they are in. Measured across every pair this library uses, the
median correlation is 0.80 to 0.99, and that holds for Hebrew against Syriac (0.91) as
readily as for English against English (0.99). A misaligned chapter falls off a cliff:
Judith 16 scores 0.15, Song 6 -0.27, Greek Exodus 25 -0.06.

**Two guards, both calibrated against known cases rather than chosen.**

*Enough verses*: at least 12, or the correlation is a coin toss.

*Enough variation to correlate*: acrostics, proverb couplets and short psalms have verses of
near-equal length by form, so their correlation is noise. Measured, the coefficient of
variation separates them cleanly -- Lamentations 1 is 0.14, Psalm 112 is 0.12, Proverbs 12 is
0.19, and the highest noise case found is Lamentations 3 at 0.221; while every chapter known
to be misaligned starts at 0.283. The threshold is 0.25, in the gap.

The first version of this used 0.35, which was a guess, and it **excluded Judith 16** -- the
one chapter whose misalignment had been confirmed by reading. A filter that removes the noise
and the answer together is worse than no filter.

Run:  venv/bin/python tools/witness_alignment.py [--threshold 0.45]
"""

from __future__ import annotations

import argparse
import collections
import sqlite3
import statistics
from contextlib import closing
from typing import Final

from biblereference.adjudicate import WITNESSES
from biblereference.store import DataHome

#: Below this, two witnesses are not describing the same chapter. Baselines run 0.80-0.99.
SUSPECT: Final = 0.45

#: Fewer verses than this and a correlation means nothing.
MIN_VERSES: Final = 12

#: Coefficient of variation below this and the chapter is uniform by form -- acrostic,
#: couplets, a short psalm -- so its correlation is noise. See the module docstring for how
#: 0.25 was chosen, and for what happened when it was guessed at instead.
MIN_SPREAD: Final = 0.25


def _spread(values: list[int]) -> float:
    mean = statistics.mean(values)
    return statistics.pstdev(values) / mean if mean else 0.0


def lengths(home: DataHome) -> dict[str, dict[tuple[str, int], dict[int, int]]]:
    """Words per verse, per chapter, for every corpus any system uses as a witness."""
    out: dict[str, dict[tuple[str, int], dict[int, int]]] = collections.defaultdict(dict)
    wanted = {corpus for pairs in WITNESSES.values() for corpus, _ in pairs}
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as db:
        for corpus in sorted(wanted):
            rows = db.execute(
                "SELECT book, chapter, verse, "
                "LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1 "
                "FROM verse WHERE corpus = ?",
                (corpus,),
            )
            for book, chapter, verse, words in rows:
                out[corpus].setdefault((str(book), int(chapter)), {})[int(verse)] = int(words)
    return out


def compare(
    held: dict[str, dict[tuple[str, int], dict[int, int]]], threshold: float
) -> tuple[dict[str, list], dict[tuple[str, str, str], list[float]]]:
    """Every suspect chapter, and every pair's own baseline to read it against."""
    suspect: dict[str, list] = collections.defaultdict(list)
    baseline: dict[tuple[str, str, str], list[float]] = collections.defaultdict(list)
    for system, pairs in WITNESSES.items():
        corpora = [corpus for corpus, _ in pairs if held.get(corpus)]
        for index, left in enumerate(corpora):
            for right in corpora[index + 1 :]:
                for key in set(held[left]) & set(held[right]):
                    here, there = held[left][key], held[right][key]
                    # A different verse *set* is the fault `_disputed_chapters` already
                    # catches; this tool is only about equal sets with unequal contents.
                    if set(here) != set(there) or len(here) < MIN_VERSES:
                        continue
                    verses = sorted(here)
                    x = [here[v] for v in verses]
                    y = [there[v] for v in verses]
                    if _spread(x) < MIN_SPREAD or _spread(y) < MIN_SPREAD:
                        continue
                    r = statistics.correlation(x, y)
                    baseline[(system, left, right)].append(r)
                    if r < threshold:
                        suspect[system].append((r, key, left, right, len(here)))
    return suspect, baseline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=SUSPECT)
    args = parser.parse_args()

    held = lengths(DataHome())
    suspect, baseline = compare(held, args.threshold)

    print("Each pair's own baseline, so a low score is read against its own tradition:\n")
    for (system, left, right), scores in sorted(baseline.items()):
        if len(scores) < 30:
            continue
        scores.sort()
        low = sum(1 for r in scores if r < args.threshold)
        print(
            f"  {system:<5} {left:<12} vs {right:<12} n={len(scores):>4} "
            f"median {scores[len(scores) // 2]:.2f}  below {args.threshold}: "
            f"{low} ({100 * low / len(scores):.1f}%)"
        )

    print("\nChapters where the two disagree about what is in the verses:\n")
    for system in sorted(suspect):
        chapters = {key for _, key, _, _, _ in suspect[system]}
        print(f"  {system}: {len(suspect[system])} pairs across {len(chapters)} chapters")
        for r, (book, chapter), left, right, n in sorted(suspect[system])[:12]:
            print(f"      r={r:5.2f}  {book} {chapter:<4} {n:>3}v   {left} vs {right}")
        print()


if __name__ == "__main__":
    main()
