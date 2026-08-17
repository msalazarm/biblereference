"""The verification stage: an independent second look, honest about what it knows.

The offset histogram must spike where a quotation aligns and stay flat where words merely
co-occur; the odds must sum only calibrated terms, so that under a v1 artifact they equal
the composite exactly -- an uncalibrated likelihood ratio presented as odds being the
transposed-conditional sin the whole reporting stack exists to forbid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from biblereference.composite import SCHEMA, Composite
from biblereference.emphasis import FOLD_VERSION
from biblereference.verification import offset_histogram

R = frozenset


def weigh(lemma: str) -> float:
    return {"και": 1.0, "ο": 0.5}.get(lemma, 8.0)


def test_a_planted_quotation_spikes_at_one_offset() -> None:
    """The verse's words at a constant shift vote for one offset; the peak is total."""
    theirs = [R({x}) for x in ("α", "β", "γ", "δ", "ε")]
    mine = [R({"x1"}), R({"x2"}), R({"x3"})] + [R({x}) for x in ("α", "β", "γ", "δ", "ε")]
    peak, pairs = offset_histogram(mine, theirs, weigh)
    assert peak == 1.0 and pairs == 5


def test_scattered_agreement_stays_flat() -> None:
    theirs = [R({x}) for x in ("α", "β", "γ", "δ")]
    mine = [R({"α"}), R({"j"}), R({"j"}), R({"β"}), R({"j"}), R({"δ"}), R({"γ"})]
    peak, pairs = offset_histogram(mine, theirs, weigh)
    assert pairs == 4
    assert peak <= 0.5, "no offset collects a majority"


def test_common_lemmas_do_not_pair() -> None:
    """Shazam hashes peaks, not the noise floor: καί at every position would bury the
    spike the statistic exists to see."""
    theirs = [R({"και"}), R({"α"}), R({"και"})]
    mine = [R({"και"}), R({"α"}), R({"και"}), R({"και"})]
    peak, pairs = offset_histogram(mine, theirs, weigh)
    assert pairs == 1, "only the rare lemma paired"
    assert peak == 1.0


def test_no_pairs_is_zero_not_an_error() -> None:
    assert offset_histogram([R({"α"})], [R({"β"})], weigh) == (0.0, 0)


def _artifact(tmp_path: Path, fields: list[str], weights: dict[str, list[float]]) -> Composite:
    bins = {"run": [1, 2, 3, 4, 6], "chain": [2, 3, 4, 5, 6, 7, 8, 10],
            "bits": [5, 10, 15, 20, 25, 30, 35, 40, 50, 60],
            "formula": [1.0], "offset_peak": [0.25, 0.5, 0.75, 0.9]}
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({
        "schema": SCHEMA, "fold_version": FOLD_VERSION,
        "fields": fields, "bins": {f: bins[f] for f in fields},
        "weights": weights,
        "m": {"sample": 1}, "u": {"sample": 1, "words": 100, "windows": 10,
                                  "collect_gate": "chain>=2 bits>=10"},
        "thresholds": {"upper": 5.0, "lower": -5.0, "fp_target": 0.0, "miss_target": 0.05},
        "null_tail": {"scores": [0.0], "exact_above": 0.0, "decimation": 1, "total": 1},
        "gumbel": None,
    }), "utf-8")
    return Composite.load(path)


class _Witness:
    text = "α β γ δ ε"
    corpus = "n1904"


class _Match:
    quoted = "α β γ δ ε"
    witnesses = (_Witness(),)
    run, lemma_run, chain, bits = 5, 5, 5, 42.0
    formula = "γεγραπται"


class _EmptyLexicon:
    """Every form unknown, so `lemma_readings` falls back to each token standing for
    itself -- which is exactly what the synthetic single-letter fixtures want."""

    def of(self, forms: list[str], language: str) -> dict[str, frozenset[str]]:
        return {form: frozenset() for form in forms}


def test_v1_odds_equal_the_composite_and_name_their_one_term(tmp_path: Path) -> None:
    from biblereference.verification import verify

    artifact = _artifact(tmp_path, ["bits"], {"bits": [0.0] * 11})
    result = verify(
        _Match(),  # type: ignore[arg-type]
        language="grc",
        lexicon=_EmptyLexicon(),  # type: ignore[arg-type]
        weigh=lambda lemma: 8.0,
        composite=artifact,
    )
    assert [name for name, _ in result.terms] == ["composite"]
    assert result.odds == artifact.score(5, 5, 5, 42.0)
    assert result.offset_pairs == 5 and result.offset_peak == 1.0, (
        "reported as raw evidence even while uncalibrated"
    )


def test_v2_terms_activate_when_the_artifact_carries_their_tables(tmp_path: Path) -> None:
    from biblereference.verification import verify

    artifact = _artifact(
        tmp_path,
        ["bits", "offset_peak", "formula"],
        {"bits": [0.0] * 11, "offset_peak": [-1.0, -0.5, 0.0, 0.5, 2.0],
         "formula": [-0.5, 1.5]},
    )
    result = verify(
        _Match(),  # type: ignore[arg-type]
        language="grc",
        lexicon=_EmptyLexicon(),  # type: ignore[arg-type]
        weigh=lambda lemma: 8.0,
        composite=artifact,
    )
    names = [name for name, _ in result.terms]
    assert names == ["composite", "offset_peak", "formula"]
    contributions = dict(result.terms)
    assert contributions["offset_peak"] == 2.0, "a total spike lands in the top bin"
    assert contributions["formula"] == 1.5, "the announcement is present"
    assert result.odds == pytest.approx(sum(contributions.values()))


def test_verify_without_an_artifact_is_refused_at_construction(tmp_path: Path) -> None:
    from biblereference.search import Searcher
    from biblereference.store import DataHome

    with pytest.raises(ValueError, match="needs a composite artifact"):
        Searcher(DataHome(tmp_path), verify=True)
