"""The false-positive price of an arbitration change, on Greek nobody was quoting.

The project's standing veto: a change that materially raises the false-positive rate on
pre-Christian Greek is refused whatever it recalls. `gate_first` changes which match wins a
contested span, so it can only alter results where two matches competed -- but "can only"
is the kind of reasoning this document set out to stop trusting, so it is measured.

The corpus is the one `calibrate_inflected.py` built and defended: classical,
pre-Christian and pre-Septuagint Greek from churchfathers' store, shuffled deterministically
and capped at six per cent per *person* so that no single author becomes the control. That
cap exists because an uncapped draw came back 19.7% Aristotle, and Aristotle is not neutral
for being pagan -- *De generatione animalium* collides with Romans 1 on θῆλυ and ἄρρεν.

    tools/boyce/control.py --words 200000
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

GATES = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=200_000)
    arguments = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from calibrate_inflected import control_text

    from biblereference.search import Gate, Searcher
    from biblereference.store import DataHome

    passages, words = control_text(arguments.words)
    print(f"{len(passages):,} control passages, {words:,} words", flush=True)

    gates = [Gate(*one) for one in GATES]
    rates: dict[str, tuple[int, Counter]] = {}
    for label, options in (
        ("today", {}),
        ("gate_first", {"gate_first": True}),
        ("gate_first + covering_rivals", {"gate_first": True, "covering_rivals": True}),
    ):
        found = 0
        books: Counter = Counter()
        with Searcher(
            DataHome(),
            languages=["grc"],
            coverage=0.5,
            min_run=lambda n: max(4, min(6, n // 2)),
            inflected=True,
            gates=gates,
            **options,
        ) as searcher:
            for text in passages:
                for match in searcher.scan(text):
                    axes = (match.run, match.lemma_run, match.chain, match.bits)
                    if any(axes) and not any(one.admits(*axes) for one in gates):
                        continue  # the consumer gates exact matches too; so does this
                    found += 1
                    books[match.passage.book] += 1
        rates[label] = (found, books)
        print(f"  {label:<30} {found:>5} matches   "
              f"{found / (words / 1000):.2f} per 1,000 words", flush=True)

    base = rates["today"][0]
    print()
    for label, (found, _) in rates.items():
        if label == "today":
            continue
        delta = found - base
        share = (delta / base * 100) if base else 0.0
        print(f"  {label:<30} {delta:+d} against today ({share:+.1f}%)")
    print()
    print("  most-claimed books, today vs gate_first:")
    today, after = rates["today"][1], rates["gate_first"][1]
    for book, _ in today.most_common(8):
        print(f"    {book:<6} {today[book]:>4} -> {after[book]:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
