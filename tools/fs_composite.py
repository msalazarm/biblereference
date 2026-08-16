"""The first Fellegi–Sunter calibration: composite weights from measured m and u.

The gate union asks four questions and admits a match if any one answer is strong enough.
Record linkage has scored this exact problem since 1969 the other way: every axis answers,
each answer carries a weight of log2(m/u) — how much more often true matches score in this
bin than false ones — and the *sum* decides, against two thresholds instead of one (link,
review, non-link). The union's calibration data is exactly what teaches the composite:

- **m** — the axes of true pairs, measured over editor-marked quotations (each mark's
  quoted words against the verse the editor named), the same instrument the gate
  calibration used.
- **u** — the axes of false pairs, measured over the control corpus where every match is
  false by construction: the file `calibrate_inflected.py --control --save` writes. The
  census literature estimates u; this library measures it, which is the one advantage no
  census has.

Winkler's caveat is applied: `lemma_run` is nested inside `chain` (a lemma run *is* a
chain with no gaps), and summing both would count the same evidence twice — so the
composite uses `run`, `chain` and `bits`, three fields with defensible independence, and
reports the collapse out loud.

Ships as a report, not a gate: the output is the weight table, the two score
distributions, and the threshold curve with POD beside PFA. Nothing here changes what any
`Searcher` admits.

    venv/bin/python tools/fs_composite.py --sample 1200 \\
        --control-evidence control-evidence.json --report fs-composite.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_inflected import MARKS, axes, marks

from biblereference.lemmata import Lexicon
from biblereference.search import LemmaWeights
from biblereference.store import DataHome

#: Bin edges per field, half-open on the right, last bin unbounded. Chosen to put the
#: decision region -- where the gates argue -- into single-unit bins, and the tails into
#: broad ones that smoothing can support.
BINS: dict[str, Sequence[float]] = {
    "run": (1, 2, 3, 4, 6),
    "chain": (2, 3, 4, 5, 6, 7, 8, 10),
    "bits": (5, 10, 15, 20, 25, 30, 35, 40, 50, 60),
}


def _bin(field: str, value: float) -> int:
    for index, edge in enumerate(BINS[field]):
        if value < edge:
            return index
    return len(BINS[field])


def _bin_label(field: str, index: int) -> str:
    edges = BINS[field]
    if index == 0:
        return f"<{edges[0]:g}"
    if index == len(edges):
        return f">={edges[-1]:g}"
    return f"{edges[index - 1]:g}-{edges[index]:g}"


def _weights(
    true_rows: Sequence[tuple], false_rows: Sequence[tuple]
) -> dict[str, list[float]]:
    """log2(m/u) per field bin, Laplace-smoothed so an empty bin is a strong signal
    rather than an infinite one."""
    fields = {"run": 0, "chain": 2, "bits": 3}
    out: dict[str, list[float]] = {}
    for field, column in fields.items():
        size = len(BINS[field]) + 1
        m_counts = [0] * size
        u_counts = [0] * size
        for row in true_rows:
            m_counts[_bin(field, row[column])] += 1
        for row in false_rows:
            u_counts[_bin(field, row[column])] += 1
        out[field] = [
            math.log2(
                ((m_counts[i] + 0.5) / (len(true_rows) + size / 2))
                / ((u_counts[i] + 0.5) / (len(false_rows) + size / 2))
            )
            for i in range(size)
        ]
    return out


def composite(row: tuple, weights: dict[str, list[float]]) -> float:
    """The summed field weights of one pair's axes ``(run, lemma_run, chain, bits)``."""
    return (
        weights["run"][_bin("run", row[0])]
        + weights["chain"][_bin("chain", row[2])]
        + weights["bits"][_bin("bits", row[3])]
    )


def true_axes(home: DataHome, sample: int) -> list[tuple]:
    """The m-sample: every editor-marked quotation's axes against its named verse."""
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
            out.append(axes(mark.quoted, str(row[0]), lexicon, weigh))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1200, help="marks for the m-sample")
    parser.add_argument(
        "--control-evidence",
        required=True,
        metavar="PATH",
        help="the u-sample: axes over control text, from `calibrate_inflected.py "
        "--control N --save PATH`",
    )
    parser.add_argument("--report", metavar="PATH", help="write the report here as markdown")
    args = parser.parse_args()

    if not MARKS.exists():
        print(f"no ground truth at {MARKS}", file=sys.stderr)
        return 1
    record = json.loads(Path(args.control_evidence).read_text("utf-8"))
    false_rows = [tuple(row) for row in record["axes"]]
    home = DataHome()
    true_rows = true_axes(home, args.sample)

    weights = _weights(true_rows, false_rows)
    m_scores = sorted(composite(row, weights) for row in true_rows)
    u_scores = sorted(composite(row, weights) for row in false_rows)

    lines: list[str] = []
    say = lines.append
    say("# Fellegi–Sunter composite: first calibration\n")
    say(
        f"m-sample: **{len(true_rows):,}** editor-marked quotations; "
        f"u-sample: **{len(false_rows):,}** control-corpus pairs over "
        f"{int(record['words']):,} words / {int(record['windows']):,} windows.\n"
    )
    say("`lemma_run` is collapsed into `chain` (nested axes; Winkler), and the")
    say("composite sums `run + chain + bits` field weights of log2(m/u).\n")

    say("## Field weights\n")
    for field, table in weights.items():
        say(f"### {field}\n")
        say("| bin | weight (bits of evidence) |")
        say("|---|---|")
        for index, weight in enumerate(table):
            say(f"| {_bin_label(field, index)} | {weight:+.2f} |")
        say("")

    say("## Threshold curve\n")
    say("| composite ≥ | POD (of marks) | PFA (per control window) |")
    say("|---|---|---|")
    windows = int(record["windows"]) or 1
    curve = []
    for threshold in range(-10, 26, 2):
        pod = sum(1 for s in m_scores if s >= threshold) / (len(m_scores) or 1)
        false_hits = sum(1 for s in u_scores if s >= threshold)
        curve.append((threshold, pod, false_hits / windows))
        say(f"| {threshold:+d} | {100 * pod:5.1f}% | {false_hits / windows:.6f} |")
    say("")

    clean = next((t for t, _, pfa in curve if pfa == 0.0), None)
    if clean is not None:
        pod_at = next(pod for t, pod, _ in curve if t == clean)
        say(
            f"**Upper threshold candidate:** composite ≥ {clean:+d} admits nothing on the "
            f"control corpus and keeps POD {100 * pod_at:.1f}%. The lower threshold — the "
            f"review zone's floor — is a policy choice this report only charts.\n"
        )
    say(
        "*A report, not a gate: nothing here changes what any `Searcher` admits. The "
        "weight table is the artefact the composite rule would consume, and its shelf "
        "life is the calibration data's.*"
    )

    text = "\n".join(lines)
    if args.report:
        Path(args.report).write_text(text, "utf-8")
        print(f"report written to {args.report}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
