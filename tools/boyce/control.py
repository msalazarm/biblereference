"""The false-positive price of an arbitration change, on Greek nobody was quoting.

The project's standing veto: a change that materially raises the false-positive rate on
pre-Christian Greek is refused whatever it recalls. `gate_first` changes which match wins a
contested span, so it can only alter results where two matches competed -- but "can only" is
the kind of reasoning this document set out to stop trusting, so it is measured.

The corpus is the one `calibrate_inflected.py` built and defended: classical, pre-Christian
and pre-Septuagint Greek from churchfathers' store, shuffled deterministically and capped at
six per cent per *person* so that no single author becomes the control. That cap exists
because an uncapped draw came back 19.7% Aristotle, and Aristotle is not neutral for being
pagan -- *De generatione animalium* collides with Romans 1 on θῆλυ and ἄρρεν.

**Processes, not threads.** A first version used a thread pool and sat at 537% of a
thirty-two-thread machine: scanning is CPU-bound Python, so the GIL is the ceiling and more
threads buy nothing. It ran forty-five minutes without finishing one of three passes, which
is long enough that the veto stops being run at all -- and a measurement nobody runs is the
same as one nobody made. Each worker builds its own read-only searcher, the same
spawn-safe shape `calibrate_inflected._worker_init` uses.

    tools/boyce/control.py --words 120000
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

GATES = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))

#: Per-process state, built once by `_setup`. A spawned child inherits nothing but the
#: environment, so each builds its own searcher against the read-only library.
_W: dict[str, Any] = {}


def _setup(options: dict[str, bool]) -> None:
    from biblereference.search import Gate, Searcher
    from biblereference.store import DataHome

    _W["gates"] = [Gate(*one) for one in GATES]
    _W["searcher"] = Searcher(
        DataHome(),
        languages=["grc"],
        coverage=0.5,
        min_run=lambda n: max(4, min(6, n // 2)),
        inflected=True,
        gates=_W["gates"],
        **options,
    )


def _scan(text: str) -> list[str]:
    """The books this passage claims, gate applied to exact matches as the consumer does."""
    out: list[str] = []
    for match in _W["searcher"].scan(text):
        axes = (match.run, match.lemma_run, match.chain, match.bits)
        if any(axes) and not any(one.admits(*axes) for one in _W["gates"]):
            continue
        out.append(match.passage.book)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=120_000)
    parser.add_argument("--workers", type=int, default=14)
    arguments = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from calibrate_inflected import control_text

    passages, words = control_text(arguments.words)
    print(f"{len(passages):,} control passages, {words:,} words, "
          f"{arguments.workers} processes", flush=True)

    rates: dict[str, tuple[int, Counter]] = {}
    for label, options in (
        ("today", {}),
        ("gate_first", {"gate_first": True}),
        ("gate_first + covering_rivals", {"gate_first": True, "covering_rivals": True}),
    ):
        started = time.monotonic()
        books: Counter = Counter()
        done = 0
        with ProcessPoolExecutor(
            max_workers=arguments.workers, initializer=_setup, initargs=(options,)
        ) as pool:
            for claimed in pool.map(_scan, passages, chunksize=8):
                books.update(claimed)
                done += 1
                if done % 200 == 0:
                    rate = done / (time.monotonic() - started)
                    left = (len(passages) - done) / rate
                    print(f"    {label}: {done}/{len(passages)}  "
                          f"{rate:.1f}/s  ~{left / 60:.1f} min left", flush=True)
        found = sum(books.values())
        rates[label] = (found, books)
        print(f"  {label:<30} {found:>5} matches   "
              f"{found / (words / 1000):.2f} per 1,000 words   "
              f"[{(time.monotonic() - started) / 60:.1f} min]", flush=True)

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
