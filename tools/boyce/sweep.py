"""Sweep Boyce's nine works locally, recording what overlap suppression deleted.

Forked from `churchfathers/tools/score_boyce_now.py` with Marco's agreement, because the
question this has to answer is not one their sweep can be asked: *what did the matcher
generate and then throw away?* Their tool sees `scan()`'s return value, which is precisely
the set after :func:`~biblereference.search._without_overlaps` has run.

The settings are theirs exactly -- `GREEK` in `churchfathers/scan.py`, gates
``(3,0,0,35) | (0,6,0,25) | (0,0,8,40)`` -- so that a number measured here is comparable
with `boycesofar.md` line for line. Anything that differs is a bug in this file.

Writes one JSON with two sections per locus: `kept`, what the sweep would have reported,
and `dropped`, what `_without_overlaps` deleted. Scoring is `tools/boyce/score.py`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

CHURCHFATHERS = Path("/home/marcollm/churchfathers")

#: Their gate for Greek, copied rather than imported so this file states what it measures.
GATES = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))
FLOOR = ((1, 1, 2, 1.0),)

_LOCK = threading.Lock()


def passages() -> list[tuple[str, str, str]]:
    """The nine works' Greek text, from churchfathers' own store."""
    sys.path.insert(0, str(CHURCHFATHERS / "src"))
    from churchfathers.scan import SCORED_WORKS
    from churchfathers.store import DataHome as TheirHome

    home = TheirHome()
    connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True, timeout=240)
    rows = connection.execute(
        f"""SELECT w.work, p.locus, p.text FROM passage p JOIN witness w ON w.id = p.witness
             WHERE w.language = 'grc' AND w.work IN ({','.join('?' * len(SCORED_WORKS))})
               AND (w.redundant_of IS NULL OR w.redundant_of = '')""",
        list(SCORED_WORKS)).fetchall()
    connection.close()
    return [(str(a), str(b), str(c)) for a, b, c in rows if str(c).strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="review/boyce-suppressed.json")
    parser.add_argument("--floor", action="store_true", help="collect at the floor gate")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--covering-rivals", action="store_true",
                        help="ask the searcher for the opt-in tier that keeps a rival "
                             "covering at least as much of the span as the winner "
                             "(quotes2.md 4.2). Adds alternates; moves no reported passage")
    parser.add_argument("--gate-first", action="store_true",
                        help="let a match that clears the gate win a contested span over "
                             "one that does not, before either similarity or coverage is "
                             "consulted. quotes2.md 4.3: suppression runs before the gate "
                             "and arbitrates on a statistic unrelated to it, so a "
                             "gate-passing match is deleted for a gate-failing one and the "
                             "span is then thrown away by the gate that would have kept it")
    parser.add_argument("--coverage-first", action="store_true",
                        help="arbitrate overlapping claims on coverage rather than on the "
                             "symmetric similarity, which is quotes2.md 4.1. Implemented "
                             "by re-sorting what `_without_overlaps` is handed: the "
                             "function is first-come-wins over its input, so its input's "
                             "order *is* the arbitration rule")
    arguments = parser.parse_args()

    from biblereference import search as module
    from biblereference.search import Gate, Searcher
    from biblereference.store import DataHome

    gates = [Gate(*one) for one in (FLOOR if arguments.floor else GATES)]

    # The spy. `_without_overlaps` has exactly one call site, inside `scan`, so recording
    # around it is complete: every deletion the scan performs passes through here.
    original = module._without_overlaps
    seen = threading.local()

    def identity(match: Any) -> tuple:
        """What makes two matches the same claim, for telling kept from deleted.

        Not `id()`. Overlap suppression returns `replace(...)` copies so that it can
        attach `alternates`, so every surviving match is a *different object* from the
        one that went in -- and an identity test therefore reports the entire input as
        deleted. That error is why this helper exists rather than a set of ids.
        """
        return (str(match.passage), match.span)

    def spy(matches: Any, **rest: Any) -> Any:
        # `**rest` rather than a named parameter: this stands in for a library function
        # whose signature is not this tool's to know, and the last time it was spelled out
        # the sweep died on the first passage when an option was added.
        before = list(matches)
        if arguments.gate_first:
            def clears(one: Any) -> bool:
                axes = (one.run, one.lemma_run, one.chain, one.bits)
                if not any(axes):
                    return True
                return any(
                    all(need <= have for need, have in zip(gate, axes, strict=True) if need)
                    for gate in GATES)

            before = sorted(
                before, key=lambda m: (not clears(m), -m.similarity, m.span or (0, 0)))
        if arguments.coverage_first:
            before = sorted(
                before, key=lambda m: (-m.coverage, -m.similarity, m.span or (0, 0)))
        after = original(before, **rest)
        surviving = {identity(one) for one in after}
        seen.dropped = [one for one in before if identity(one) not in surviving]
        return after

    module._without_overlaps = spy

    jobs = passages()
    print(f"{len(jobs)} passages, {sum(len(j[2].split()) for j in jobs):,} words", flush=True)

    local = threading.local()
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"kept": [], "dropped": []})
    done = [0]

    def consider(job: tuple[str, str, str]) -> None:
        work, locus, text = job
        searcher = getattr(local, "searcher", None)
        if searcher is None:
            searcher = Searcher(
                DataHome(), languages=["grc"], coverage=0.5,
                min_run=lambda n: max(4, min(6, n // 2)), inflected=True, gates=gates,
                covering_rivals=arguments.covering_rivals)
            local.searcher = searcher
        seen.dropped = []
        kept = searcher.scan(text)
        dropped = list(getattr(seen, "dropped", ()))
        with _LOCK:
            key = f"{work}|{locus}"
            out[key]["kept"] = [one.to_dict() for one in kept]
            out[key]["dropped"] = [one.to_dict() for one in dropped]
            done[0] += 1
            if done[0] % 200 == 0:
                print(f"  {done[0]}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        list(pool.map(consider, jobs))

    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "gates": [list(one) for one in (FLOOR if arguments.floor else GATES)],
        "coverage_first": bool(arguments.coverage_first),
        "gate_first": bool(arguments.gate_first),
        "covering_rivals": bool(arguments.covering_rivals),
        "sections": out,
    }, ensure_ascii=False), encoding="utf-8")
    total_kept = sum(len(v["kept"]) for v in out.values())
    total_dropped = sum(len(v["dropped"]) for v in out.values())
    print(f"kept {total_kept:,}  dropped {total_dropped:,}  -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
