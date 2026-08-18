"""The Fellegi–Sunter calibration: weights, thresholds, and the artifact both sides load.

The math lives in `biblereference.composite` — this tool collects the samples, derives
the two thresholds, writes the artifact (`--weights`), and renders the human report.

- **m** — the axes of true pairs, measured over editor-marked quotations (each mark's
  quoted words against the verse the editor named). A deterministic held-out split (seed
  0) prices the lower threshold on marks the weights never saw.
- **u** — the axes of false pairs, from the control corpus where every match is false by
  construction: the file `calibrate_inflected.py --control N --save PATH` writes. Read
  exactly as written — an axes-only file with no ``fields`` key is the four-axis order
  `axes()` has always used, so the consumer's control runs drop in unchanged.

`lemma_run` is collapsed into `chain` (nested axes; Winkler); §5.6's `formula` and
`rivalry` fields activate only when a u-file declares them, by name, never by position.

    venv/bin/python tools/fs_composite.py --sample 0 \\
        --control-evidence control-evidence.json \\
        --weights composite.json --report fs-composite.md
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_inflected import COLLECT, MARKS, ROW_FIELDS, full_row, marks

from biblereference.composite import (
    BINS,
    DEFAULT_ROW_FIELDS,
    SCHEMA,
    Composite,
    bin_label,
    bin_of,
    field_weights,
)
from biblereference.emphasis import FOLD_VERSION
from biblereference.lemmata import Lexicon
from biblereference.search import LemmaWeights
from biblereference.store import DataHome

#: Below this composite score the null tail keeps one score in `_DECIMATION`; at or
#: above, every score. The decision region stays exact and the artifact stays small.
_EXACT_ABOVE = 0.0
_DECIMATION = 50


def true_axes(home: DataHome, sample: int) -> list[tuple]:
    """The m-sample: every editor-marked quotation's `ROW_FIELDS` row against its named
    verse. `formula` reuses `mark.announced` -- `marks()` already judged it with the
    recorded-offset-plus-fallback logic, and re-deriving it here would be a second
    opinion pretending to be the first."""
    import sqlite3

    lexicon = Lexicon(home)
    lexicon.require("grc")
    weigh = LemmaWeights(home).of("grc")
    verses = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    out: list[tuple] = []
    for mark in marks(sample):
        corpus = "n1904" if mark.vrs == "org" else "rahlfs"
        row = verses.execute(
            "SELECT text FROM verse WHERE corpus=? AND book=? AND chapter=? AND verse=?",
            (corpus, mark.book, mark.chapter, mark.verse),
        ).fetchone()
        if row:
            out.append(full_row(mark.quoted, str(row[0]), lexicon, weigh, mark.announced))
    return out


def score_rows(
    rows: Sequence[Sequence[float]],
    fields: Sequence[str],
    columns: dict[str, int],
    weights: dict[str, list[float]],
) -> list[float]:
    return [
        sum(weights[f][bin_of(BINS[f], row[columns[f]])] for f in fields) for row in rows
    ]


def _gumbel_fit(exact_tail: Sequence[float]) -> tuple[float, float] | None:
    """Method-of-moments Gumbel over the exact tail, kept only if it roughly agrees with
    the empirical counts it extends -- a fit that contradicts its own data is worse than
    the honest 0.0."""
    if len(exact_tail) < 30:
        return None
    n = len(exact_tail)
    mean = sum(exact_tail) / n
    variance = sum((s - mean) ** 2 for s in exact_tail) / (n - 1)
    beta = math.sqrt(6 * variance) / math.pi
    if beta <= 0:
        return None
    mu = mean - 0.5772156649 * beta
    top = sorted(exact_tail)[-max(3, n // 20) :]
    predicted = n * (1.0 - math.exp(-math.exp(-(top[0] - mu) / beta)))
    observed = float(len(top))
    if predicted <= 0 or not (1 / 3 <= predicted / observed <= 3):
        return None
    return (mu, beta)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1200, help="marks for m (0 = all)")
    parser.add_argument(
        "--control-evidence",
        required=True,
        metavar="PATH",
        help="the u-sample, from `calibrate_inflected.py --control N --save PATH`",
    )
    parser.add_argument("--weights", metavar="PATH", help="write the artifact here as JSON")
    parser.add_argument("--report", metavar="PATH", help="write the report here as markdown")
    parser.add_argument(
        "--fp-target",
        type=float,
        default=0.0,
        help="expected false links per control window tolerated at/above the upper "
        "threshold (0 = the zero-false-positive line)",
    )
    parser.add_argument(
        "--miss-target",
        type=float,
        default=0.05,
        help="share of held-out true matches tolerated below the lower threshold",
    )
    parser.add_argument(
        "--held-out",
        type=int,
        default=200,
        help="marks withheld from the weights to price the lower threshold honestly",
    )
    parser.add_argument(
        "--gumbel",
        action="store_true",
        help="fit a Gumbel tail past the empirical maximum; kept only if it agrees "
        "with the counts it extends",
    )
    args = parser.parse_args()

    if not MARKS.exists():
        print(f"no ground truth at {MARKS}", file=sys.stderr)
        return 1
    record = json.loads(Path(args.control_evidence).read_text("utf-8"))
    u_fields = tuple(record.get("fields", DEFAULT_ROW_FIELDS))
    u_columns = {name: index for index, name in enumerate(u_fields)}
    false_rows = [tuple(row) for row in record["axes"]]

    home = DataHome()
    all_true = true_axes(home, args.sample)
    m_fields = ROW_FIELDS
    m_columns = {name: index for index, name in enumerate(m_fields)}

    # Which fields the artifact carries: the collapsed v1 core, plus any §5.6 field both
    # samples measured. A field only one side holds cannot have an honest m/u ratio.
    fields = [
        f
        for f in ("run", "chain", "bits", "offset_peak", "formula", "rivalry")
        if f in u_columns and f in m_columns
    ]

    # The held-out split, deterministic, so the lower threshold is priced on marks the
    # weights never saw and two runs of this tool agree to the digit.
    order = list(range(len(all_true)))
    random.Random(0).shuffle(order)
    held_count = min(args.held_out, len(all_true) // 3)
    held_rows = [all_true[i] for i in order[:held_count]]
    train_rows = [all_true[i] for i in order[held_count:]]

    weights = field_weights(train_rows, false_rows, fields, m_columns, u_columns)
    # u rows are scored through their own column map -- by name, never by position.
    u_scores = sorted(score_rows(false_rows, fields, u_columns, weights))
    held_scores = sorted(score_rows(held_rows, fields, m_columns, weights))
    windows = int(record["windows"]) or 1
    words = int(record["words"])

    # Upper: at or above it, the control corpus offers at most fp_target expected false
    # links per window. Lower: below it, at most miss_target of held-out gold is lost.
    allowed = math.floor(args.fp_target * windows)
    upper = (
        u_scores[-1 - allowed] + 1e-9 if allowed < len(u_scores) else u_scores[0] - 1e-9
    )
    lower_index = math.floor(args.miss_target * len(held_scores)) if held_scores else 0
    lower = held_scores[lower_index] if held_scores else upper

    # The null tail: exact in the decision region, decimated below.
    tail = [s for s in u_scores if s >= _EXACT_ABOVE]
    tail = [s for i, s in enumerate(u_scores) if s < _EXACT_ABOVE and i % _DECIMATION == 0] + tail
    exact_tail = [s for s in u_scores if s >= _EXACT_ABOVE]
    fitted = _gumbel_fit(exact_tail) if args.gumbel else None

    artifact = {
        "schema": SCHEMA,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "language": "grc",
        "fold_version": FOLD_VERSION,
        "fields": fields,
        "bins": {f: list(BINS[f]) for f in fields},
        "weights": {f: weights[f] for f in fields},
        "m": {
            "sample": len(train_rows),
            "held_out": len(held_rows),
            "source": "editor-marks",
            "seed": 0,
        },
        "u": {
            "sample": len(false_rows),
            "words": words,
            "windows": windows,
            "collect_gate": str(COLLECT),
            "source": str(args.control_evidence),
        },
        "thresholds": {
            "upper": upper,
            "lower": lower,
            "fp_target": args.fp_target,
            "miss_target": args.miss_target,
        },
        "null_tail": {
            "scores": tail,
            "exact_above": _EXACT_ABOVE,
            "decimation": _DECIMATION,
            "total": len(u_scores),
        },
        "gumbel": list(fitted) if fitted else None,
    }

    if args.weights:
        Path(args.weights).write_text(json.dumps(artifact), "utf-8")
        print(f"artifact written to {args.weights}")
        loaded = Composite.load(args.weights)  # fail fast on our own output
        assert loaded.upper == upper

    lines: list[str] = []
    say = lines.append
    say("# Fellegi–Sunter composite calibration\n")
    say(
        f"m-sample: **{len(train_rows):,}** editor-marked quotations "
        f"(+{len(held_rows):,} held out, seed 0); "
        f"u-sample: **{len(false_rows):,}** control pairs over {words:,} words / "
        f"{windows:,} windows, collected through `{COLLECT}` — the null is truncated "
        f"below that gate and E-values there are unsupported.\n"
    )
    say(f"Fields: `{' + '.join(fields)}` (lemma_run collapsed into chain; Winkler).\n")
    say("## Field weights\n")
    for field in fields:
        say(f"### {field}\n")
        say("| bin | weight (bits of evidence) |")
        say("|---|---|")
        for index, weight in enumerate(weights[field]):
            say(f"| {bin_label(BINS[field], index)} | {weight:+.2f} |")
        say("")
    say("## Thresholds\n")
    pod_upper = sum(1 for s in held_scores if s >= upper) / (len(held_scores) or 1)
    say(
        f"| zone | threshold | operating point |\n|---|---|---|\n"
        f"| accept | ≥ {upper:+.2f} | ≤ {args.fp_target:g} expected false links per "
        f"control window; held-out POD {100 * pod_upper:.1f}% |\n"
        f"| reject | < {lower:+.2f} | ≤ {100 * args.miss_target:g}% of held-out gold "
        f"lost |\n"
        f"| review | between | the clerical zone, 1969's own |\n"
    )
    say("## Threshold curve\n")
    say("| composite ≥ | POD (held-out) | PFA (per control window) |")
    say("|---|---|---|")
    for threshold in range(-10, 26, 2):
        pod = sum(1 for s in held_scores if s >= threshold) / (len(held_scores) or 1)
        false_hits = sum(1 for s in u_scores if s >= threshold)
        say(f"| {threshold:+d} | {100 * pod:5.1f}% | {false_hits / windows:.6f} |")
    say("")
    say(
        "*The artifact is the interface: `Searcher(composite=...)` reports `composite` "
        "and `e_value` on every graded match, and nothing here changes what any gate "
        "admits.*"
    )
    text = "\n".join(lines)
    if args.report:
        Path(args.report).write_text(text, "utf-8")
        print(f"report written to {args.report}")
    elif not args.weights:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
