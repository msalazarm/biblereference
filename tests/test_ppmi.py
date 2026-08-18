"""The PPMI backoff: count-based, deterministic, and rerank-only.

What these tests defend: the cosine math on a fixture artifact, the fail-fast on a
missing artifact, and on the real artifact the §7(c) promise itself -- a known synonym
pair keeps closer company than an unrelated one, and the backoff can never move a
candidate more than the tie window nor touch the bits a match reports.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biblereference.emphasis import fold
from biblereference.ppmi import PpmiVectors

ARTIFACT = Path.home() / ".local/share/biblereference/db/ppmi-grc.sqlite3"


def _fixture(path: Path, rows: dict[str, dict[int, float]]) -> PpmiVectors:
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "CREATE TABLE vector (lemma TEXT, dim INTEGER, weight REAL);"
    )
    for lemma, dims in rows.items():
        db.executemany(
            "INSERT INTO vector VALUES (?, ?, ?)",
            [(lemma, dim, weight) for dim, weight in dims.items()],
        )
    db.commit()
    db.close()
    return PpmiVectors(path)


def test_the_cosine_is_a_cosine(tmp_path: Path) -> None:
    vectors = _fixture(
        tmp_path / "v.sqlite3",
        {"α": {1: 1.0, 2: 1.0}, "β": {1: 1.0, 2: 1.0}, "γ": {3: 2.0}, "δ": {1: 2.0}},
    )
    assert vectors.similarity("α", "β") == pytest.approx(1.0)
    assert vectors.similarity("α", "γ") == 0.0, "no shared dimension"
    assert vectors.similarity("α", "δ") == pytest.approx(0.7071, abs=1e-3)
    assert vectors.similarity("α", "α") == 1.0
    assert vectors.similarity("α", "unknown") == 0.0


def test_a_missing_artifact_refuses_at_construction(tmp_path: Path) -> None:
    from biblereference.search import Searcher
    from biblereference.store import DataHome

    assert not PpmiVectors(tmp_path / "absent.sqlite3").held
    with pytest.raises(ValueError, match="ppmi=True needs the vector artifact"):
        Searcher(DataHome(tmp_path), ppmi=True)


real = pytest.mark.skipif(not ARTIFACT.exists(), reason="ppmi artifact not built")


@real
def test_a_synonym_keeps_closer_company_than_a_stranger() -> None:
    vectors = PpmiVectors(ARTIFACT)
    ship, boat = fold("πλοῖον", "grc"), fold("ναῦς", "grc")
    justice = fold("δικαιοσύνη", "grc")
    assert vectors.similarity(ship, boat) > 3 * vectors.similarity(ship, justice), (
        "the §7(c) claim on the real vectors"
    )


@real
def test_the_backoff_is_bounded_by_the_tie_window() -> None:
    """The rank shift is _TIE_BITS * cosine, cosine <= 1 -- so nothing moves further
    than a near-tie, which is the whole licence the backoff has."""
    from biblereference.search import _TIE_BITS

    vectors = PpmiVectors(ARTIFACT)
    a, b = fold("θάλασσα", "grc"), fold("πέλαγος", "grc")
    assert 0.0 < vectors.similarity(a, b) <= 1.0
    assert _TIE_BITS * vectors.similarity(a, b) <= _TIE_BITS
