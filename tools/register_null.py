"""The Monte-Carlo max-scan null for Stratum R: what chance's best window looks like.

`register_spans` scores thousands of sliding windows per document, and the maximum of
thousands of chance scores is not a chance score — scanning manufactures significance
unless the null is the distribution of the *maximum*. This tool measures that
distribution the only honest way available: replicates of classical, pre-Christian
Greek — text that cannot be quoting scripture — drawn seeded from the same control
stream the composite's u-sample uses, each scored by its single best window LLR under
the same two models, geometry, and order the live scan runs with.

The artifact is banded by document length, because a longer document offers chance more
windows and its maximum rises with them. `RegisterNull.threshold(words, level)` rounds a
document *up* to the next measured band — the conservative direction — and refuses fold
drift outright.

    venv/bin/python tools/register_null.py \\
        --father ~/churchfathers/data/ngrams-grc.sqlite3 \\
        --replicates 400 --save ~/.local/share/biblereference/db/register-null-grc.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_inflected import control_text

from biblereference.emphasis import FOLD_VERSION
from biblereference.ngram_models import NgramModel
from biblereference.register import _STRIDE, _WINDOW, _evidence
from biblereference.store import DataHome

#: Document lengths measured, in words. The consumer's documents are chapter-sized;
#: the bands bracket everything from an apostolic-fathers chapter to a whole treatise.
_LENGTHS = (500, 1_000, 2_000, 5_000, 10_000)

#: Order statistics reported per band. 0.999 needs ~1,000 replicates to be an order
#: statistic rather than an extrapolation; with fewer, trust 0.99 and below.
_LEVELS = (0.9, 0.95, 0.99, 0.999)


def max_llr(
    tokens: list[str], scripture: NgramModel, father: NgramModel, order: int
) -> float:
    """The replicate's statistic: its single best window, the same geometry live."""
    best = float("-inf")
    for start in range(0, max(1, len(tokens) - _WINDOW + 1), _STRIDE):
        best = max(best, _evidence(tokens[start : start + _WINDOW], scripture, father, order))
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--father", required=True, metavar="PATH",
                        help="the consumer's patristic model artifact")
    parser.add_argument("--scripture", metavar="PATH",
                        help="scripture model (default: the library's own)")
    parser.add_argument("--replicates", type=int, default=400, help="per length band")
    parser.add_argument("--order", type=int, default=3, help="n-gram order, as live")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--control-words", type=int, default=3_000_000,
                        help="how much classical Greek to draw replicates from")
    parser.add_argument("--save", required=True, metavar="PATH")
    args = parser.parse_args()

    home = DataHome()
    scripture = NgramModel(args.scripture or home.root / "db" / "ngrams-scripture-grc.sqlite3")
    father = NgramModel(args.father)

    texts, words = control_text(args.control_words)
    tokens = [token for text in texts for token in scripture.grams(text)]
    print(f"control stream: {len(tokens):,} folded tokens from {words:,} words")

    rng = random.Random(args.seed)
    bands: dict[int, dict[str, float]] = {}
    for length in _LENGTHS:
        if length > len(tokens):
            print(f"  {length}: stream too short, skipped")
            continue
        maxima = sorted(
            max_llr(
                tokens[offset : offset + length],
                scripture,
                father,
                args.order,
            )
            for offset in (
                rng.randrange(len(tokens) - length + 1) for _ in range(args.replicates)
            )
        )
        bands[length] = {
            str(level): maxima[min(int(level * len(maxima)), len(maxima) - 1)]
            for level in _LEVELS
        }
        print(f"  {length}: " + ", ".join(f"q{k}={v:.1f}" for k, v in bands[length].items()))

    artifact = {
        "schema": "biblereference-register-null/1",
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "language": "grc",
        "fold_version": FOLD_VERSION,
        "window": _WINDOW,
        "stride": _STRIDE,
        "order": args.order,
        "seed": args.seed,
        "replicates": args.replicates,
        "control_words": words,
        "scripture": {"path": str(scripture.path), "tokens": scripture.tokens(1)},
        "father": {"path": str(father.path), "tokens": father.tokens(1)},
        "bands": bands,
    }
    Path(args.save).write_text(json.dumps(artifact), "utf-8")
    print(f"artifact written to {args.save}")

    from biblereference.register import RegisterNull  # fail fast on our own output

    loaded = RegisterNull.load(args.save)
    assert loaded.threshold(1, 0.95) == float(bands[min(bands)]["0.95"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
