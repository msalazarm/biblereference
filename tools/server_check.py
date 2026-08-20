"""Are the model servers up, fast enough, and answering the same way?

Three questions, because a server can fail any one of them while passing the others:

1. **Is it there, and what is it serving?** A refused connection is obvious. A server
   quietly serving a *different model* than you think is not, and it is the one that
   corrupts a run -- :data:`biblereference.judge.DEFAULT_SERVERS` pools two endpoints on the
   assumption they are the same build, so the assumption is checked rather than trusted.

2. **How fast, under the concurrency a real run uses?** The overnight judge round-robins,
   so what matters is throughput per server at several requests in flight, not the latency
   of one.

3. **Does it answer correctly?** :func:`~biblereference.adjudicate.calibrate` puts 96
   mappings whose answer is already known to a judge. Run against *one* server at a time it
   says whether that server is fit to judge at all -- which is the measurement the pool
   cannot make for you, because ``calibrate`` round-robins like any other question and
   averages whatever is in the pool.

That third point is why the remote's gemma4 E4B is not in ``DEFAULT_SERVERS``. Point this
tool at it to find out what it would cost:

    venv/bin/python tools/server_check.py --calibrate
    venv/bin/python tools/server_check.py --servers http://10.0.0.182:8081 --calibrate
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Final

from biblereference.judge import BIG, DEFAULT_SERVERS, DEFAULT_TEMPERATURE, Judge, tier
from biblereference.store import DataHome

#: Both boxes' second port. Named so a reader knows the omission from the judge pool is a
#: decision rather than an oversight: measured on 2026-08-19, E4B answered 100% correctly on
#: the 96 calibration rows but was informative on only 82% of them against the 26b's 89-91%,
#: and on Church Slavonic on 1 of 3 rows against 3 of 3. Accurate, less decisive.
E4B: Final = ("http://127.0.0.1:8081", "http://10.0.0.182:8081")

#: A question shaped like the ones a real run asks: two short verses and a yes/no.
_PROBE: Final = {
    "messages": [
        {"role": "system", "content": "You compare Bible verses. Answer YES or NO."},
        {
            "role": "user",
            "content": (
                "Verse A: In the beginning God created the heaven and the earth.\n\n"
                "Verse B: In principio creavit Deus caelum et terram.\n\n"
                "Do these render the same verse of scripture? Answer YES or NO."
            ),
        },
    ],
    "temperature": DEFAULT_TEMPERATURE,
    "max_tokens": 4,
    "model": "local",
}


def identify(server: str, timeout: float = 8.0) -> tuple[bool, str]:
    """``(healthy, model name)``. The model name is the part worth reading."""
    try:
        with urllib.request.urlopen(f"{server}/health", timeout=timeout) as response:
            healthy = response.status == 200
    except (urllib.error.URLError, OSError) as error:
        return False, f"unreachable: {error}"
    try:
        with urllib.request.urlopen(f"{server}/v1/models", timeout=timeout) as response:
            models = json.load(response).get("data", [])
        name = ", ".join(str(m.get("id", "?")).split("/")[-1] for m in models) or "unnamed"
    except (urllib.error.URLError, OSError, ValueError):
        name = "unnamed"
    return healthy, name


def _ask(server: str, timeout: float) -> float | None:
    """One probe; seconds taken, or None if it failed.

    **The answer is read, not just the status.** A first version timed whatever came back
    and called a parseable body a success -- so a server erroring in 20ms would have
    reported the best throughput of the three. An empty completion counts as a failure
    here for the same reason a judge counts YES-to-both as uninformative: the request
    returning is not the question.
    """
    body = json.dumps(_PROBE).encode()
    request = urllib.request.Request(
        f"{server}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    began = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        answered = payload["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, AttributeError):
        return None
    return time.monotonic() - began if answered else None


def throughput(server: str, *, requests: int, concurrency: int, timeout: float) -> None:
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        times = list(pool.map(lambda _: _ask(server, timeout), range(requests)))
    elapsed = time.monotonic() - began
    good = [t for t in times if t is not None]
    failed = len(times) - len(good)
    if not good:
        print(f"    throughput: all {requests} requests failed")
        return
    good.sort()
    print(
        f"    {len(good)}/{requests} ok"
        + (f" ({failed} FAILED)" if failed else "")
        + f" in {elapsed:.1f}s"
        f"  ->  {len(good) / elapsed:.2f} req/s at {concurrency} in flight"
    )
    print(
        f"    latency  median {statistics.median(good):.2f}s"
        f"  p90 {good[int(len(good) * 0.9)]:.2f}s  max {good[-1]:.2f}s"
    )


def accuracy(server: str, *, timeout: float) -> None:
    """The real calibration, against this server alone."""
    from biblereference.adjudicate import calibrate
    from biblereference.versification import Versification

    home = DataHome()
    judge = Judge((server,), timeout=timeout)
    began = time.monotonic()
    result = calibrate(judge, home, Versification.load())
    elapsed = time.monotonic() - began
    asked = sum(result.asked.values())
    informative = sum(result.informative.values())
    correct = sum(result.correct.values())
    if not asked:
        print("    calibration: no task could be built (no witness pairs)")
        return
    print(
        f"    calibration: {asked} asked, {informative} informative "
        f"({100 * informative / asked:.0f}%), {correct} correct "
        f"({100 * correct / max(informative, 1):.0f}% of informative) in {elapsed:.0f}s"
    )
    for languages in sorted(result.asked, key=lambda k: -result.asked[k]):
        n, inf, ok = (
            result.asked[languages],
            result.informative[languages],
            result.correct[languages],
        )
        if n:
            print(f"      {languages!s:<16} {ok}/{inf} correct of {n} asked")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servers", nargs="*", default=[*DEFAULT_SERVERS, *E4B])
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="also run the 96-row calibration against each server alone (slow)",
    )
    args = parser.parse_args()

    for server in args.servers:
        healthy, name = identify(server)
        # Labelled by the tier the server reports, not by whether its address happens to be
        # in a list. The address list is the thing that goes stale.
        rank = tier(name)
        flag = "" if rank == BIG else f"   [{rank or 'unknown tier'} -- not for judging]"
        print(f"\n{server}{flag}")
        print(f"    health {'ok' if healthy else 'DOWN'}   model {name}")
        if not healthy:
            continue
        throughput(
            server, requests=args.requests, concurrency=args.concurrency, timeout=args.timeout
        )
        if args.calibrate:
            accuracy(server, timeout=args.timeout)
    print()


if __name__ == "__main__":
    main()
