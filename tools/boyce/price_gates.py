"""What several candidate gates cost on Greek nobody was quoting, in one pass.

`control.py` answers one gate at a time and sweeps three arbitration settings while doing
it, which is the wrong shape for calibration: the question here is one arbitration and many
gates. Scanning is the expensive part and it does not depend on the gate at all, so this
scans once at the floor, keeps every match with its four axes, and then applies each
candidate gate to the same set. Ten gates cost what one used to.

    tools/boyce/price_gates.py --words 120000
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

#: Collect at the floor so one scan can answer for every gate above it.
FLOOR = ((1, 1, 2, 1.0),)

#: The gate as churchfathers ships it, and the candidates measured against it.
TODAY = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))
CANDIDATES: dict[str, tuple] = {
    "today": TODAY,
    "lemma-run arm 6 -> 4": ((3, 0, 0, 35.0), (0, 4, 0, 25.0), (0, 0, 8, 40.0)),
    "+ (3,0,0,30)": (*TODAY, (3, 0, 0, 30.0)),
    "+ (0,0,6,30)": (*TODAY, (0, 0, 6, 30.0)),
    "+ (0,4,0,24)": (*TODAY, (0, 4, 0, 24.0)),
    "+ (0,4,0,22)": (*TODAY, (0, 4, 0, 22.0)),
    "+ (0,8,0,20)": (*TODAY, (0, 8, 0, 20.0)),
    "arm to 4 + (3,0,0,30)": ((3, 0, 0, 35.0), (0, 4, 0, 25.0), (0, 0, 8, 40.0), (3, 0, 0, 30.0)),
}

_W: dict[str, Any] = {}


def _setup() -> None:
    """Per-process state. The gate is deliberately *not* a parameter: this scans at the
    floor and gates afterwards, so a worker needs no gate at all."""
    from biblereference.search import Gate, Searcher
    from biblereference.store import DataHome

    _W["searcher"] = Searcher(
        DataHome(),
        languages=["grc"],
        coverage=0.5,
        min_run=lambda n: max(4, min(6, n // 2)),
        inflected=True,
        gates=[Gate(*one) for one in FLOOR],
        gate_first=True,
    )


def _axes(text: str) -> list[tuple[int, int, int, float]]:
    return [
        (m.run, m.lemma_run, m.chain, m.bits) for m in _W["searcher"].scan(text)
    ]


def admits(axes: tuple, gates: tuple) -> bool:
    if not any(axes):
        return True
    return any(
        all(need <= have for need, have in zip(gate, axes, strict=True) if need)
        for gate in gates
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=120_000)
    parser.add_argument("--workers", type=int, default=10)
    arguments = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from calibrate_inflected import control_text

    passages, words = control_text(arguments.words)
    print(f"{len(passages):,} control passages, {words:,} words, "
          f"{arguments.workers} processes, collected at the floor", flush=True)

    started = time.monotonic()
    every: list[tuple] = []
    done = 0
    with ProcessPoolExecutor(max_workers=arguments.workers, initializer=_setup) as pool:
        for found in pool.map(_axes, passages, chunksize=8):
            every.extend(found)
            done += 1
            if done % 200 == 0:
                rate = done / (time.monotonic() - started)
                print(f"    {done}/{len(passages)}  {rate:.1f}/s  "
                      f"~{(len(passages) - done) / rate / 60:.1f} min left", flush=True)
    print(f"  {len(every):,} matches at the floor, {(time.monotonic() - started) / 60:.1f} min\n",
          flush=True)

    base = sum(1 for a in every if admits(a, TODAY))
    print(f"  {'gate':<26}{'matches':>9}{'per 1,000 w':>13}{'vs today':>11}")
    for label, gates in CANDIDATES.items():
        n = sum(1 for a in every if admits(a, gates))
        delta = "" if label == "today" else f"{n - base:+d} ({(n - base) / base * 100:+.0f}%)"
        print(f"  {label:<26}{n:>9}{n / (words / 1000):>13.2f}{delta:>11}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
