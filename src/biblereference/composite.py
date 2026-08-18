"""The Fellegi–Sunter composite: one calibrated weight over all the axes.

The gate union asks four questions and admits a match if any one answer is strong
enough. Record linkage has scored this exact problem since 1969 the other way: every
axis answers, each answer carries a weight of log₂(m/u) — how much more often true
matches land in this bin than false ones — and the *sum* decides, against two thresholds
instead of one. Six ordinary words in a row is what no arm of a union can price and a
sum prices naturally, and the two citations the calibrated union refuses at chain 8 —
Didache 16:7 against Zechariah 14:5, 1 Clement 13:2 against Matthew 7 — both clear the
summed weight's zero-false-positive line. That measurement is why this module exists.

The calibration lives in an **artifact**, a JSON file `tools/fs_composite.py --weights`
writes: the bins, the per-field weight tables, both thresholds with the targets that
chose them, and the null tail — the sorted composite scores of the control corpus, where
every match is false by construction. The artifact is the whole interface: the consumer
regenerates it from their own control run, both sides load the same file, and its shelf
life is the calibration data's. E-values ride on the same tail: *"0.03 expected chance
hits this good"* is a defensible sentence in a way *"41 bits"* is not.

Reported, never gated. `Searcher(composite=...)` fills :attr:`Match.composite` and
:attr:`Match.e_value` beside the axes; the gates keep working unchanged until the
composite has earned, on the consumer's own corpus, the right to replace them.
"""

from __future__ import annotations

import json
import math
import re
import warnings
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Final

from .emphasis import FOLD_VERSION

__all__ = ["BINS", "Composite", "bin_of", "field_weights"]

#: The artifact schema this module writes and reads. The major number breaks loading;
#: growth that old readers can ignore does not bump it.
SCHEMA: Final = "biblereference-composite/1"

#: Bin edges per field, half-open on the right, last bin unbounded. The decision region
#: -- where the gates argue -- sits in single-unit bins; the tails are broad enough for
#: smoothing to support. `formula` and `rivalry` are the §5.6 fields a v2 u-file can
#: activate; an artifact only carries weights for the fields its u-sample measured.
BINS: Final[dict[str, tuple[float, ...]]] = {
    "run": (1, 2, 3, 4, 6),
    "chain": (2, 3, 4, 5, 6, 7, 8, 10),
    "bits": (5, 10, 15, 20, 25, 30, 35, 40, 50, 60),
    "formula": (1,),
    "rivalry": (1, 3),
    # The verification stage's offset-histogram concentration (see `verification.py`):
    # a genuine match aligns its rare lemmas at one constant offset and coincidence
    # scatters, so the peak's share of all pairs is a likelihood term the moment a
    # calibration measures its m/u tables.
    "offset_peak": (0.25, 0.5, 0.75, 0.9),
}

#: The axes order a control-evidence file uses when it declares no ``fields`` key: the
#: order `calibrate_inflected.axes()` has always written. The consumer's control runs
#: produce exactly this shape, and accepting it unchanged is a compatibility promise.
DEFAULT_ROW_FIELDS: Final = ("run", "lemma_run", "chain", "bits")


def bin_of(edges: Sequence[float], value: float) -> int:
    """Which bin a value falls in, for edges half-open on the right."""
    for index, edge in enumerate(edges):
        if value < edge:
            return index
    return len(edges)


def bin_label(edges: Sequence[float], index: int) -> str:
    if index == 0:
        return f"<{edges[0]:g}"
    if index == len(edges):
        return f">={edges[-1]:g}"
    return f"{edges[index - 1]:g}-{edges[index]:g}"


def field_weights(
    true_rows: Sequence[Sequence[float]],
    false_rows: Sequence[Sequence[float]],
    fields: Sequence[str],
    columns: Mapping[str, int],
    false_columns: Mapping[str, int] | None = None,
) -> dict[str, list[float]]:
    """log₂(m/u) per field bin, Laplace-smoothed so an empty bin is a strong signal
    rather than an infinite one.

    ``columns`` maps each field to its position in the rows -- by name, never by a
    hard-coded index, because a transposed column here would be a calibrated-looking lie
    in every score downstream. The two samples may lay their rows out differently -- an
    old four-field u-file against six-field m rows -- so the false side may bring its
    own map; omitted, it shares the true side's.
    """
    theirs = columns if false_columns is None else false_columns
    out: dict[str, list[float]] = {}
    for field in fields:
        edges = BINS[field]
        size = len(edges) + 1
        m_counts = [0] * size
        u_counts = [0] * size
        for row in true_rows:
            m_counts[bin_of(edges, row[columns[field]])] += 1
        for row in false_rows:
            u_counts[bin_of(edges, row[theirs[field]])] += 1
        out[field] = [
            math.log2(
                ((m_counts[i] + 0.5) / (len(true_rows) + size / 2))
                / ((u_counts[i] + 0.5) / (len(false_rows) + size / 2))
            )
            for i in range(size)
        ]
    return out


#: The recorded ``collect_gate`` string, as `calibrate_inflected.Gate.__str__` writes it:
#: ``chain>=2 bits>=10``, any subset of the four axis names.
_GATE_RE: Final = re.compile(r"(run|lemma_run|chain|bits)>=([0-9.]+)")


@dataclass(frozen=True, slots=True)
class Composite:
    """A loaded calibration artifact: score, zone, and expected chance hits."""

    fields: tuple[str, ...]
    """Which fields this artifact carries weights for. The versioning mechanism: v1 is
    ``run, chain, bits`` (``lemma_run`` collapsed into ``chain``, nested axes counting
    the same evidence twice -- Winkler's caveat); ``formula`` and ``rivalry`` join by
    appearing here, and :meth:`score` ignores what the artifact does not name."""
    bins: dict[str, tuple[float, ...]]
    weights: dict[str, tuple[float, ...]]
    upper: float
    """Auto-accept at or above this: the control false-link rate meets the target the
    artifact records. Their two refused citations clearing this line is the argument."""
    lower: float
    """Reject below this: the held-out miss rate meets the recorded target. Between the
    two is the clerical-review zone -- not an analogy to the consumer's human-verdict
    workflow but the same object, published in 1969."""
    control_words: int
    control_windows: int
    null_tail: tuple[float, ...]
    """Composite scores of the control corpus, ascending. Exact at and above
    :attr:`tail_exact_above`; one retained per :attr:`tail_decimation` below, so
    E-values in the decision region are exact counts and the file stays small."""
    tail_exact_above: float
    tail_decimation: int
    collect_gate: str
    """The gate the control evidence was collected through. The null is truncated below
    it -- E-values there are not supported by the data, and this is what says so."""
    fold_version: int
    calibration: tuple[tuple[float, float], ...] = ()
    """Knots of a monotone map from the summed weight to *observed* log-odds, fitted on
    held-out gold against the control sample.

    The summed weight is a good ranker whose magnitude lies: `run`, `chain` and `bits`
    measure overlapping evidence, and a naive-Bayes sum over correlated fields
    over-counts -- measured on the first real artifact, a claimed +30 paid +14.8. This is
    the textbook remedy (Platt/isotonic score recalibration) rather than a restructuring
    of the fields, and being **monotone** it is free: every ranking and every operating
    point survives unchanged, and only the number's claim about itself is repaired.
    Empty on an artifact built before this existed, and then :meth:`score` returns the
    raw sum as it always did."""
    gumbel: tuple[float, float] | None = None
    """(mu, beta) of a Gumbel tail fit past the empirical maximum, or None where the fit
    failed or was not asked for. §5.1's fallback doctrine: the empirical percentile is
    what is already trusted; the fit is the refinement."""

    @classmethod
    def load(cls, path: str | Path) -> Composite:
        """Read an artifact, refusing what it cannot honestly score."""
        raw = json.loads(Path(path).read_text("utf-8"))
        schema = str(raw.get("schema", ""))
        if not schema.startswith("biblereference-composite/"):
            raise ValueError(f"not a composite artifact: schema {schema!r} in {path}")
        if schema.split("/")[1].split(".")[0] != SCHEMA.split("/")[1]:
            raise ValueError(f"composite artifact schema {schema!r} is not readable here")
        if int(raw["fold_version"]) != FOLD_VERSION:
            warnings.warn(
                f"composite artifact was calibrated on fold {raw['fold_version']} and this "
                f"library folds at {FOLD_VERSION}; its weights describe axes measured under "
                f"a different normalisation",
                stacklevel=2,
            )
        thresholds = raw["thresholds"]
        tail = raw["null_tail"]
        fitted = raw.get("gumbel")
        return cls(
            fields=tuple(raw["fields"]),
            bins={k: tuple(v) for k, v in raw["bins"].items()},
            weights={k: tuple(v) for k, v in raw["weights"].items()},
            upper=float(thresholds["upper"]),
            lower=float(thresholds["lower"]),
            control_words=int(raw["u"]["words"]),
            control_windows=int(raw["u"]["windows"]),
            null_tail=tuple(tail["scores"]),
            tail_exact_above=float(tail["exact_above"]),
            tail_decimation=int(tail["decimation"]),
            collect_gate=str(raw["u"].get("collect_gate", "")),
            fold_version=int(raw["fold_version"]),
            calibration=tuple(
                (float(at), float(value)) for at, value in raw.get("calibration") or ()
            ),
            gumbel=(float(fitted[0]), float(fitted[1])) if fitted else None,
        )

    def supported(self, run: int, lemma_run: int, chain: int, bits: float) -> bool:
        """Whether this evidence lies inside the region the control sample measured.

        The u-sample was collected through :attr:`collect_gate`, so **nothing below that
        gate has a control count** -- and a bin with no control count and any m count at
        all produces an enormous positive weight out of pure absence. Left unguarded that
        inverts the whole instrument: a match with one shared word and four bits collects
        the empty ``chain<2`` and ``bits<5`` bins and outscores a genuine eight-word
        chain. Below the gate the honest answer is not a number.
        """
        floors = {
            name: float(value) for name, value in _GATE_RE.findall(self.collect_gate)
        }
        held = {"run": run, "lemma_run": lemma_run, "chain": chain, "bits": bits}
        return all(held[name] >= floor for name, floor in floors.items())

    def score(
        self,
        run: int,
        lemma_run: int,
        chain: int,
        bits: float,
        *,
        formula: bool | None = None,
        rivalry: int | None = None,
    ) -> float | None:
        """The summed field weights of one match's evidence, or ``None`` where the
        control sample never measured evidence this weak (see :meth:`supported`).

        Takes all four axes so no call site ever changes shape; uses only the fields the
        artifact names. The keyword fields are v2 evidence -- ``None`` means "not
        offered", and a v1 artifact ignores them even when offered.
        """
        if not self.supported(run, lemma_run, chain, bits):
            return None
        values: dict[str, float | None] = {
            "run": float(run),
            "lemma_run": float(lemma_run),
            "chain": float(chain),
            "bits": float(bits),
            "formula": None if formula is None else float(formula),
            "rivalry": None if rivalry is None else float(rivalry),
        }
        total = 0.0
        for field in self.fields:
            value = values.get(field)
            if value is None:
                continue
            total += self.weights[field][bin_of(self.bins[field], value)]
        return self.calibrate(total)

    def calibrate(self, total: float) -> float:
        """The summed weight mapped to the log-odds the held-out data actually paid.

        Piecewise-linear between the fitted knots and flat past the ends -- extrapolating
        a calibration is inventing evidence, and the ends are exactly where the sample ran
        out. Identity where the artifact carries no map.
        """
        knots = self.calibration
        if not knots:
            return total
        if total <= knots[0][0]:
            return knots[0][1]
        if total >= knots[-1][0]:
            return knots[-1][1]
        for (left, low), (right, high) in pairwise(knots):
            if left <= total <= right:
                if right == left:
                    return high
                return low + (high - low) * (total - left) / (right - left)
        return knots[-1][1]

    def zone(self, score: float) -> str:
        """``accept`` | ``review`` | ``reject`` -- the three-zone rule."""
        if score >= self.upper:
            return "accept"
        if score < self.lower:
            return "reject"
        return "review"

    def null_at_or_above(self, score: float) -> float:
        """How many control-corpus scores stand at or above this one, decimation-corrected."""
        boundary = bisect_left(self.null_tail, self.tail_exact_above)
        if score >= self.tail_exact_above:
            return float(len(self.null_tail) - bisect_left(self.null_tail, score, boundary))
        exact = len(self.null_tail) - boundary
        decimated = boundary - bisect_left(self.null_tail, score, 0, boundary)
        return float(exact + decimated * self.tail_decimation)

    def e_value(self, score: float, windows: float = 1.0) -> float:
        """Expected chance hits at or above this score, over ``windows`` opportunities.

        The null was measured per window, so windows is the honest unit: a scan passes
        how many windows the document presented, a single search passes 1.0. Past the
        empirical maximum the Gumbel tail answers where one was fitted; otherwise 0.0,
        which means *below the null's resolution* -- fewer than one in
        ``control_windows`` -- and never "impossible". Below the collect gate's
        truncation the tail holds no data and the number underestimates; see
        :attr:`collect_gate`.
        """
        count = self.null_at_or_above(score)
        if count == 0.0 and self.gumbel is not None:
            mu, beta = self.gumbel
            survival = 1.0 - math.exp(-math.exp(-(score - mu) / beta))
            count = len(self.null_tail) * survival
        return count * windows / self.control_windows
