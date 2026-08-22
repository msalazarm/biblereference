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
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

GATES = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=200_000)
    parser.add_argument("--workers", type=int, default=8,
                        help="threads. A searcher holds a sqlite connection and sqlite "
                             "refuses cross-thread use, so each thread builds its own -- "
                             "the same pattern sweep.py uses. Single-threaded this had not "
                             "finished one of three passes over 971 passages in half an "
                             "hour, which is long enough that the veto stops being run")
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
        books: Counter = Counter()
        lock = threading.Lock()
        local = threading.local()

        # `options` and `local` bound as defaults rather than closed over: the pool below
        # finishes inside this iteration so closing over them would be safe today, and
        # would silently stop being safe the moment anything here became lazy.
        def searcher_here(local: Any = local, options: Any = options) -> Searcher:
            got = getattr(local, "searcher", None)
            if got is None:
                got = Searcher(
                    DataHome(),
                    languages=["grc"],
                    coverage=0.5,
                    min_run=lambda n: max(4, min(6, n // 2)),
                    inflected=True,
                    gates=gates,
                    **options,
                )
                local.searcher = got
            return got

        def consider(text: str, books: Counter = books, lock: Any = lock) -> int:
            here: Counter = Counter()
            for match in searcher_here().scan(text):
                axes = (match.run, match.lemma_run, match.chain, match.bits)
                if any(axes) and not any(one.admits(*axes) for one in gates):
                    continue  # the consumer gates exact matches too; so does this
                here[match.passage.book] += 1
            with lock:
                books.update(here)
            return sum(here.values())

        with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
            found = sum(pool.map(consider, passages))
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
