"""The Fellegi–Sunter composite: the artifact is the interface, and it must not lie.

What is tested: the weight math against hand sums, the artifact round-trip, the three-zone
rule at its boundaries, E-values with their decimation correction, and the compatibility
promise — a control-evidence file with no ``fields`` key is the four-axis order the
consumer's runs have always written, and a v2 field activates only when a file declares it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from biblereference.composite import (
    BINS,
    DEFAULT_ROW_FIELDS,
    SCHEMA,
    Composite,
    bin_of,
    field_weights,
)
from biblereference.emphasis import FOLD_VERSION


def artifact_dict(**overrides: object) -> dict:
    """A minimal valid artifact, hand-computable: one field, two bins."""
    base = {
        "schema": SCHEMA,
        "fold_version": FOLD_VERSION,
        "fields": ["bits"],
        "bins": {"bits": [10.0]},
        "weights": {"bits": [-2.0, 3.0]},
        "m": {"sample": 4, "held_out": 0, "source": "test", "seed": 0},
        # No collection gate: this synthetic u-sample was never truncated, so every bin
        # has support and `supported()` admits everything. The truncated case is its own
        # test below.
        "u": {"sample": 8, "words": 1000, "windows": 100, "collect_gate": ""},
        "thresholds": {"upper": 3.0, "lower": -1.0, "fp_target": 0.0, "miss_target": 0.05},
        "null_tail": {"scores": [-2.0, -2.0, 3.0], "exact_above": 0.0, "decimation": 2,
                      "total": 7},
        "gumbel": None,
    }
    base.update(overrides)
    return base


def write_artifact(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "composite.json"
    path.write_text(json.dumps(artifact_dict(**overrides)), "utf-8")
    return path


def test_weights_are_the_hand_summed_log_odds() -> None:
    """log2(m/u) per bin, Laplace-smoothed, columns found by name -- a transposed column
    here would be a calibrated-looking lie in every score downstream."""
    columns = {name: i for i, name in enumerate(DEFAULT_ROW_FIELDS)}
    true_rows = [(0, 0, 0, 50.0)] * 3
    false_rows = [(0, 0, 0, 1.0)] * 5
    weights = field_weights(true_rows, false_rows, ["bits"], columns)["bits"]
    size = len(BINS["bits"]) + 1
    top = math.log2(((3 + 0.5) / (3 + size / 2)) / ((0 + 0.5) / (5 + size / 2)))
    low = math.log2(((0 + 0.5) / (3 + size / 2)) / ((5 + 0.5) / (5 + size / 2)))
    assert weights[bin_of(BINS["bits"], 50.0)] == pytest.approx(top)
    assert weights[bin_of(BINS["bits"], 1.0)] == pytest.approx(low)


def test_the_artifact_round_trips_and_scores_by_its_own_bins(tmp_path: Path) -> None:
    loaded = Composite.load(write_artifact(tmp_path))
    assert loaded.fields == ("bits",)
    assert loaded.score(0, 0, 0, 5.0) == -2.0, "below the single edge"
    assert loaded.score(0, 0, 0, 15.0) == 3.0, "at or above it"


def test_the_three_zones_at_their_boundaries(tmp_path: Path) -> None:
    """Accept means at-or-above upper; reject means strictly below lower; the review zone
    is what 1969 called clerical."""
    loaded = Composite.load(write_artifact(tmp_path))
    assert loaded.zone(3.0) == "accept"
    assert loaded.zone(2.999) == "review"
    assert loaded.zone(-1.0) == "review"
    assert loaded.zone(-1.001) == "reject"


def test_e_values_correct_for_decimation(tmp_path: Path) -> None:
    """The tail keeps one in `decimation` below `exact_above` and every score at or
    above it, so counts in the decision region are exact and counts below scale up."""
    loaded = Composite.load(write_artifact(tmp_path))
    # tail [-2, -2, 3], exact_above 0, decimation 2: one exact score (3.0), two retained
    # decimated entries each standing for 2.
    assert loaded.null_at_or_above(3.0) == 1
    assert loaded.null_at_or_above(4.0) == 0
    assert loaded.null_at_or_above(-2.0) == 1 + 2 * 2
    # windows scaling: at the control's own window count, E is the raw count.
    assert loaded.e_value(3.0, windows=100) == pytest.approx(1.0)
    assert loaded.e_value(3.0, windows=1.0) == pytest.approx(0.01)
    assert loaded.e_value(4.0) == 0.0, "below the null's resolution, never impossible"


def test_a_v2_field_activates_only_when_the_artifact_carries_it(tmp_path: Path) -> None:
    v1 = Composite.load(write_artifact(tmp_path))
    assert v1.score(0, 0, 0, 15.0, formula=True) == 3.0, "v1 ignores offered v2 evidence"
    v2 = Composite.load(
        write_artifact(
            tmp_path,
            fields=["bits", "formula"],
            bins={"bits": [10.0], "formula": [1.0]},
            weights={"bits": [-2.0, 3.0], "formula": [-0.5, 1.5]},
        )
    )
    assert v2.score(0, 0, 0, 15.0) == 3.0, "evidence not offered contributes nothing"
    assert v2.score(0, 0, 0, 15.0, formula=True) == 4.5
    assert v2.score(0, 0, 0, 15.0, formula=False) == 2.5


def test_a_wrong_schema_is_refused_and_a_stale_fold_warned_about(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else/9"}), "utf-8")
    with pytest.raises(ValueError, match="not a composite artifact"):
        Composite.load(bad)
    with pytest.warns(UserWarning, match="different normalisation"):
        Composite.load(write_artifact(tmp_path, fold_version=FOLD_VERSION - 1))


def test_an_axes_only_control_file_is_the_four_axis_order() -> None:
    """The consumer's in-flight 3M-word u-file has no `fields` key. That absence IS the
    format: the order `calibrate_inflected.axes()` has always written, pinned here so the
    file drops in unchanged the moment it lands."""
    assert DEFAULT_ROW_FIELDS == ("run", "lemma_run", "chain", "bits")


REAL_EVIDENCE = Path(
    "/tmp/claude-1000/-home-marcollm-biblereference/cf75d9f5-8888-4553-a1c7-15903b7f648a"
    "/scratchpad/control-evidence.json"
)


@pytest.mark.skipif(not REAL_EVIDENCE.exists(), reason="no control evidence on this machine")
def test_the_two_refused_citations_clear_the_real_upper_threshold(tmp_path: Path) -> None:
    """The measurement this module exists for: Didache 16:7 against Zechariah 14:5 and
    1 Clement 13:2 against Matthew 7 are both refused by the calibrated gate union and
    both clear the composite's zero-false-positive line. Consumes the saved evidence
    file; never rescans anything."""
    import os
    import subprocess
    import sys

    out = tmp_path / "real.json"
    # The suite runs under an isolated data home; the tool must see the developer's real
    # one, since the m-sample and lexicon live there.
    env = {k: v for k, v in os.environ.items() if k != "BIBLEREFERENCE_HOME"}
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "fs_composite.py"),
            "--sample", "400",
            "--control-evidence", str(REAL_EVIDENCE),
            "--weights", str(out),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if "no grc lexicon" in result.stderr:
        pytest.skip("real lexicon not built on this machine")
    if "no ground truth" in result.stderr:
        pytest.skip("churchfathers marks not on this machine")
    assert result.returncode == 0, result.stderr
    loaded = Composite.load(out)
    assert loaded.lower <= loaded.upper
    didache = loaded.score(6, 6, 8, 19.7)
    clement = loaded.score(3, 3, 8, 29.9)
    assert loaded.zone(didache) == "accept"
    assert loaded.zone(clement) == "accept"


# -- the truncated-null guard -----------------------------------------------------------


def test_evidence_below_the_collection_gate_is_unscored(tmp_path: Path) -> None:
    """The bug this guard exists for, pinned.

    A control sample collected through `chain>=2 bits>=10` holds **no rows** below that
    gate, so those bins carry an m count against a u count of zero and the smoothed
    ratio explodes -- the real 3M-word artifact gave `chain<2` +18.1 bits and `bits<5`
    +17.7. Unguarded, a match with one shared word collected +35.8 bits of pure absence
    and outranked a genuine eight-word chain. Below the gate the honest answer is not a
    number.
    """
    artifact = {
        "schema": SCHEMA,
        "fold_version": FOLD_VERSION,
        "fields": ["run", "chain", "bits"],
        "bins": {f: list(BINS[f]) for f in ("run", "chain", "bits")},
        # Deliberately the pathological shape: huge positive weights in the empty bins.
        "weights": {
            "run": [0.0] * (len(BINS["run"]) + 1),
            "chain": [18.1] + [0.0] * len(BINS["chain"]),
            "bits": [17.7, 18.5] + [0.0] * (len(BINS["bits"]) - 1),
        },
        "m": {"sample": 100},
        "u": {
            "sample": 1000,
            "words": 3_000_000,
            "windows": 474_021,
            "collect_gate": "chain>=2 bits>=10",
        },
        "thresholds": {"upper": 29.8, "lower": -3.5},
        "null_tail": {"scores": [0.0], "exact_above": 0.0, "decimation": 50, "total": 1},
        "gumbel": None,
    }
    path = tmp_path / "composite.json"
    path.write_text(json.dumps(artifact), "utf-8")
    loaded = Composite.load(path)

    assert loaded.collect_gate == "chain>=2 bits>=10"
    assert not loaded.supported(run=1, lemma_run=1, chain=1, bits=3.9)
    assert loaded.score(1, 1, 1, 3.9) is None, "one shared word scores nothing, not +35.8"
    assert not loaded.supported(run=9, lemma_run=9, chain=9, bits=4.0), "bits floor too"
    assert loaded.supported(run=0, lemma_run=0, chain=2, bits=10.0), "on the gate is inside"
    assert loaded.score(0, 0, 2, 10.0) is not None


# -- the monotone recalibration ---------------------------------------------------------


def test_the_calibration_map_is_monotone_clamped_and_optional(tmp_path: Path) -> None:
    """The summed weight ranks well and lies about its magnitude -- measured on the real
    artifact, a claimed +30 paid +14.8. The remedy is a monotone map, and monotone is the
    whole safety argument: it cannot reorder two matches, so it repairs the number's claim
    about itself and nothing else. Past the end knots it is flat, because extrapolating a
    calibration is inventing evidence exactly where the sample ran out."""
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps(artifact_dict(calibration=[[0.0, 0.0], [10.0, 5.0], [20.0, 6.0]])), "utf-8"
    )
    loaded = Composite.load(path)
    assert loaded.calibrate(0.0) == 0.0
    assert loaded.calibrate(10.0) == 5.0
    assert loaded.calibrate(5.0) == pytest.approx(2.5), "piecewise linear between knots"
    assert loaded.calibrate(15.0) == pytest.approx(5.5)
    assert loaded.calibrate(-100.0) == 0.0, "flat below the first knot, never extrapolated"
    assert loaded.calibrate(1e6) == 6.0, "flat above the last"
    rungs = [loaded.calibrate(v) for v in range(-30, 60)]
    assert rungs == sorted(rungs), "monotone: no pair of matches can swap order"

    (tmp_path / "plain.json").write_text(json.dumps(artifact_dict()), "utf-8")
    plain = Composite.load(tmp_path / "plain.json")
    assert plain.calibration == ()
    assert plain.calibrate(7.5) == 7.5, "no map: the raw sum, exactly as before"


def test_the_isotonic_fit_drops_unresolved_bins_and_enforces_order() -> None:
    """Bins empty on one side carry a smoothing bound rather than a measurement, and
    fitting a bound is how a calibration invents evidence. What survives is pooled into
    monotone order."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from fs_composite import calibration_knots

    # Gold high, control low, with a deliberate inversion in the middle to be pooled.
    held = [1.0] * 40 + [5.0] * 10 + [9.0] * 40
    control = [1.0] * 400 + [5.0] * 40 + [9.0] * 4
    knots = calibration_knots(held, control, width=4.0)
    assert knots, "resolved bins produce a map"
    assert [value for _, value in knots] == sorted(value for _, value in knots)
    assert calibration_knots([], control) == [], "no gold, no map"
    assert calibration_knots(held, []) == [], "no control, no map"
    # A bin with gold but no control is a bound, so it must not become a knot.
    lonely = calibration_knots([100.0] * 50, control, width=4.0)
    assert all(at < 90 for at, _ in lonely), "the unresolved high bin is dropped"
