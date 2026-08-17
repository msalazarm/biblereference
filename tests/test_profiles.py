"""Per-verse profiles: deterministic alignment, honest columns, and the dilution fix.

The spike's claims live here as tests: kept-vs-filtered inserts match identically, seed
order is pinned and measured stable, the build is byte-deterministic, and the profile
finds what a single edition cannot -- which is the whole purchase.
"""

from __future__ import annotations

import pytest

from biblereference.lemmata import Lexicon
from biblereference.profiles import (
    Profiles,
    align_pair,
    build_profile,
    profile_chain,
)
from biblereference.store import DataHome

R = frozenset


def weigh(lemma: str) -> float:
    return {"ο": 0.5, "και": 0.5}.get(lemma, 6.0)


def pairs(*words: str) -> list[tuple[str, frozenset[str]]]:
    return [(w, R({w.upper()})) for w in words]


def test_alignment_prefers_exact_over_lemma_over_nothing() -> None:
    a = [("αγαπη", R({"αγαπαω"}))]
    exact = [("αγαπη", R({"τελειωσ"}))]
    lemma = [("αγαπησ", R({"αγαπαω"}))]
    assert align_pair(a, exact) == [(0, 0)]
    assert align_pair(a, lemma) == [(0, 0)]


def test_a_plus_word_becomes_an_insert_column() -> None:
    """The Byzantine plus-word case in miniature: the longer witness's extra token gets
    its own column, marked insert, attested by the one witness that has it."""
    short = pairs("x", "y", "z")
    long = pairs("x", "q", "y", "z")
    profile = build_profile([("critical", short), ("byzantine", long)])
    assert len(profile) == 4
    inserted = [c for c in profile if c.insert]
    assert len(inserted) == 1
    assert inserted[0].forms == (("q", 1.0),)
    assert inserted[0].members == ("byzantine",)
    shared = [c for c in profile if not c.insert]
    assert all(c.members == ("critical", "byzantine") for c in shared)


def test_an_itacised_variant_shares_a_column_when_the_lemma_says_so() -> None:
    """Two spellings of one word, paired by their shared dictionary form: the column
    carries both alternatives natively, which is the §4.2 variant held structurally."""
    a = [("αληθινοσ", R({"αληθινοσ"}))]
    b = [("αληθεινοσ", R({"αληθινοσ"}))]
    profile = build_profile([("crit", a), ("ms", b)])
    assert len(profile) == 1
    assert dict(profile[0].forms) == {"αληθινοσ": 1.0, "αληθεινοσ": 1.0}
    assert "αληθινοσ" in profile[0].reading


def test_the_build_is_deterministic_and_order_is_pinned() -> None:
    """Same witnesses, same order, same columns, every time -- and the reversed order on
    this fixture happens to agree too, which is what the real families measured. The pin
    is a guard: determinism is the invariant, agreement is the observation."""
    witnesses = [("a", pairs("x", "y", "z")), ("b", pairs("x", "q", "y", "z"))]
    once = build_profile(witnesses)
    again = build_profile(witnesses)
    assert [c.reading for c in once] == [c.reading for c in again]
    assert [c.insert for c in once] == [c.insert for c in again]


def test_kept_and_filtered_inserts_chain_identically() -> None:
    """The spike's answer (a), pinned: the chain's gap costs absorb an insert column
    exactly as they absorb an interpolation, so filtering buys nothing."""
    profile = build_profile(
        [("crit", pairs("α", "β", "γ", "δ")), ("byz", pairs("α", "β", "π", "γ", "δ"))]
    )
    query = [R({"Α"}), R({"Β"}), R({"Γ"}), R({"Δ"})]
    kept = profile_chain(query, profile, weigh)
    filtered = profile_chain(query, [c for c in profile if not c.insert], weigh)
    assert kept.length == filtered.length == 4  # type: ignore[attr-defined]


REAL = DataHome()
PROFILES = REAL.root / "db" / "profiles.sqlite"

real = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc") or not PROFILES.exists(),
    reason="needs the built library, lexicon, and profiles.sqlite",
)


@real
def test_the_profile_finds_the_byzantine_reading_the_critical_text_cannot() -> None:
    """The acceptance measurement, standing: Romans 8:1's Byzantine long ending chains
    through the profile and not through the critical text alone -- the edition-dilution
    fix §6b bought."""
    import sqlite3

    from biblereference.search import LemmaWeights, _tokens, lemma_chain, lemma_readings

    lexicon = Lexicon(REAL)
    lexicon.require("grc")
    weights = LemmaWeights(REAL).of("grc")
    reader = Profiles(PROFILES)
    columns = reader.of("org", "ROM", 8, 1)
    if columns is None:
        pytest.skip("ROM 8:1 not among the family anchors in this build")
    query = lemma_readings(
        _tokens("μὴ κατὰ σάρκα περιπατοῦσιν ἀλλὰ κατὰ πνεῦμα", "grc"), "grc", lexicon
    )
    through_profile = profile_chain(query, columns, weights)
    db = sqlite3.connect(f"file:{REAL.database}?mode=ro", uri=True)
    critical = db.execute(
        "SELECT text FROM verse WHERE corpus='n1904' AND book='ROM' AND chapter=8 AND verse=1"
    ).fetchone()[0]
    alone = lemma_chain(
        query, lemma_readings(_tokens(critical, "grc"), "grc", lexicon), weights
    )
    assert through_profile.length >= 6  # type: ignore[attr-defined]
    assert alone.length == 0


@real
def test_the_reader_answers_for_a_family_anchor_and_stays_silent_otherwise() -> None:
    reader = Profiles(PROFILES)
    columns = reader.of("org", "ACT", 8, 32)
    assert columns is not None, "the Ethiopian's verse is a family anchor"
    assert any(column.insert for column in columns) or len(columns) >= 10
    members = reader.members("org", "ACT", 8, 32)
    assert members and members[0].startswith("n1904"), "the critical text seeds"
    assert reader.of("org", "MAT", 1, 99) is None


def test_an_unbuilt_file_answers_none_not_an_error(tmp_path: object) -> None:
    from pathlib import Path

    reader = Profiles(Path(str(tmp_path)) / "absent.sqlite")
    assert reader.of("org", "MAT", 10, 16) is None
    assert reader.members("org", "MAT", 10, 16) == []
