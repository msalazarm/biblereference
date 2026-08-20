"""The n-gram model reader and the register ledger, against synthetic and real artifacts.

The reader must refuse a stale fold loudly, count what the schema holds, and take its
peak at the orders where the class separation survives; the register scan must flag a
planted rarity and stay silent over the prose around it, with the centring that keeps a
corpus-size asymmetry from manufacturing spans.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biblereference.emphasis import FOLD_VERSION
from biblereference.ngram_models import NgramModel
from biblereference.register import register_spans

REAL_PATRISTIC = Path("/home/marcollm/churchfathers/data/ngrams-grc.sqlite3")


def build_model(
    path: Path,
    grams: dict[tuple[int, str], int],
    *,
    tokens: dict[int, int] | None = None,
    fold_version: int = FOLD_VERSION,
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE totals (author TEXT, "order" INTEGER, tokens INTEGER);
        CREATE TABLE ngram (author TEXT, "order" INTEGER, fold TEXT, count INTEGER);
        CREATE TABLE works (author TEXT, work TEXT, witness TEXT, words INTEGER);
        """
    )
    db.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [
            ("language", "grc"),
            ("orders", "1,2,3,4,5"),
            ("min_count", "2"),
            ("fold_version", str(fold_version)),
        ],
    )
    orders = {order for order, _ in grams}
    totals = tokens or dict.fromkeys(orders | {1, 2, 3, 4, 5}, 1_000)
    db.executemany(
        'INSERT INTO totals (author, "order", tokens) VALUES (?, ?, ?)',
        [("", order, n) for order, n in totals.items()],
    )
    db.executemany(
        'INSERT INTO ngram (author, "order", fold, count) VALUES (?, ?, ?, ?)',
        [("", order, gram, count) for (order, gram), count in grams.items()],
    )
    db.commit()
    db.close()
    return path


def test_the_reader_counts_what_the_schema_holds(tmp_path: Path) -> None:
    model = NgramModel(build_model(tmp_path / "m.sqlite3", {(3, "α β γ"): 50, (4, "α β γ δ"): 5}))
    assert model.count("α β γ", 3) == 50
    assert model.count("nothing here", 3) == 0
    assert model.rate_per_million("α β γ", 3) == pytest.approx(50 / 1000 * 1e6)
    assert model.tokens(3) == 1000


def test_a_stale_fold_is_refused_loudly(tmp_path: Path) -> None:
    """A model whose keys were made under an older fold answers every query with silence
    that looks like rarity -- the exact staleness `meta`'s field exists to catch."""
    path = build_model(tmp_path / "stale.sqlite3", {}, fold_version=FOLD_VERSION - 1)
    with pytest.raises(ValueError, match="Rebuild the model"):
        NgramModel(path)
    assert NgramModel(path, check=False).count("α", 1) == 0, "explicitly unchecked still reads"


def test_the_peak_is_taken_where_phrases_start_being_phrases(tmp_path: Path) -> None:
    """A common trigram inside a genuine citation must not make it a stock phrase: the
    default orders are 4-5, where the doxology holds 18.9/M against the citations'
    0.9-1.0 on the consumer's own model."""
    model = NgramModel(
        build_model(
            tmp_path / "m.sqlite3",
            {(3, "ο κυριοσ και"): 300, (4, "ηξει ο κυριοσ και"): 1},
        )
    )
    assert model.peak_rate("Ἥξει ὁ κύριος καὶ") == pytest.approx(1 / 1000 * 1e6)
    assert model.peak_rate("Ἥξει ὁ κύριος καὶ", orders=(3,)) == pytest.approx(300 / 1000 * 1e6)


def test_the_register_scan_flags_the_planted_rarity_and_nothing_else(tmp_path: Path) -> None:
    """The centring rule at work: the father's own prose -- unseen by both models --
    contributes zero, so a smaller scripture corpus cannot make everything look like
    scripture; the planted grams, seen by scripture and not by the father, are the only
    thing that scores."""
    scripture_grams = {(3, f"σ{i} σ{i + 1} σ{i + 2}"): 20 for i in range(12)}
    scripture = NgramModel(
        build_model(tmp_path / "s.sqlite3", scripture_grams, tokens={n: 1_000 for n in range(1, 6)})
    )
    father = NgramModel(
        build_model(tmp_path / "f.sqlite3", {}, tokens={n: 100_000 for n in range(1, 6)})
    )
    prose = " ".join(f"π{i}" for i in range(24))
    quotation = " ".join(f"σ{i}" for i in range(14))
    text = f"{prose} {quotation} {prose}"
    spans = register_spans(text, scripture, father)
    assert spans, "the planted run is flagged"
    at = text.find("σ0 ")
    assert any(s.at <= at < s.end for s in spans), "the span covers the plant"
    assert all(s.source is None for s in spans), "v1 is the unresolved ledger"
    assert not any(s.end <= at - 40 for s in spans), "the leading prose alone is not a span"


def _consumer_model_is_current() -> bool:
    """Whether the consumer's model can be read at all under this library's fold.

    Two ways it cannot: the file is not here, or it was built under a different
    `FOLD_VERSION`, in which case `NgramModel.check` refuses it by design -- its keys no
    longer meet these queries. The second is not a failure of anything in this repository,
    so it skips rather than fails; but it is owed work, not a shrug. See the skip reason.
    """
    if not REAL_PATRISTIC.exists():
        return False
    try:
        NgramModel(REAL_PATRISTIC).check()
    except ValueError:
        return False
    return True


@pytest.mark.skipif(
    not _consumer_model_is_current(),
    reason=(
        "consumer's n-gram model is absent or was built under an older FOLD_VERSION. "
        "biblereference folds at 3 as of 2026-08-20; churchfathers must rebuild "
        "data/ngrams-{grc,lat}.sqlite3 with tools/patristic_ngrams.py before this reads."
    ),
)
def test_the_consumers_own_measurement_reproduces_through_the_reader() -> None:
    """Their §6, read back through our reader: the doxology's peak in the tens per
    million, a genuine citation's in the ones -- the sanity bound that says both sides
    mean the same thing by the number."""
    model = NgramModel(REAL_PATRISTIC)
    doxology = model.peak_rate("ᾧ ἡ δόξα εἰς τοὺς αἰῶνας τῶν αἰώνων ἀμήν")
    citation = model.peak_rate("γίνεσθε οὖν φρόνιμοι ὡς οἱ ὄφεις καὶ ἀκέραιοι ὡς αἱ περιστεραί")
    assert doxology > 10.0
    assert citation < 3.0
    assert doxology / max(citation, 0.1) > 5.0


# -- Stratum R completion (V8): rolling Delta and the max-scan null ---------------------


def test_top_grams_enumerate_deterministically(tmp_path: Path) -> None:
    model = NgramModel(
        build_model(tmp_path / "m.sqlite3", {(1, "και"): 50, (1, "δε"): 50, (1, "ο"): 90})
    )
    assert model.top_grams(1, 2) == [("ο", 90), ("δε", 50)], "count desc, ties by gram"


def _delta_pair(tmp_path: Path) -> tuple[NgramModel, NgramModel]:
    scripture = NgramModel(
        build_model(
            tmp_path / "s.sqlite3",
            {(1, "και"): 100, (1, "δε"): 100},
            tokens={n: 200 for n in range(1, 6)},
        )
    )
    father = NgramModel(
        build_model(
            tmp_path / "f.sqlite3",
            {(1, "και"): 100, (1, "δε"): 100, (1, "μεν"): 400},
            tokens={n: 2_000 for n in range(1, 6)},
        )
    )
    return scripture, father


def test_delta_markers_come_from_shared_vocabulary(tmp_path: Path) -> None:
    from biblereference.register import delta_markers

    scripture, father = _delta_pair(tmp_path)
    markers = delta_markers(scripture, father, limit=10)
    assert "μεν" not in markers.words, "a gram scripture never saw cannot be a marker"
    assert set(markers.words) == {"και", "δε"}
    at = markers.words.index("και")
    assert markers.scripture_rate[at] == pytest.approx(0.5)
    assert markers.father_rate[at] == pytest.approx(0.05)


def test_the_rolling_delta_signs_toward_the_nearer_profile(tmp_path: Path) -> None:
    from biblereference.register import _rolling_delta, delta_markers

    scripture, father = _delta_pair(tmp_path)
    markers = delta_markers(scripture, father, limit=10)
    scriptural = ["και", "δε"] * 6
    fatherly = [f"π{i}" for i in range(11)] + ["και"]
    assert _rolling_delta(scriptural, markers) > 0, "scripture-rate function words"
    assert _rolling_delta(fatherly, markers) < 0, "father-rate function words"


def test_spans_carry_the_delta_at_the_peak_window_only_when_asked(tmp_path: Path) -> None:
    from biblereference.register import delta_markers

    scripture_grams = {(3, f"σ{i} σ{i + 1} σ{i + 2}"): 20 for i in range(12)}
    scripture_grams.update({(1, "και"): 100, (1, "δε"): 100})
    scripture = NgramModel(
        build_model(tmp_path / "s.sqlite3", scripture_grams, tokens={n: 1_000 for n in range(1, 6)})
    )
    father = NgramModel(
        build_model(
            tmp_path / "f.sqlite3",
            {(1, "και"): 10, (1, "δε"): 10},
            tokens={n: 100_000 for n in range(1, 6)},
        )
    )
    text = " ".join(f"π{i}" for i in range(24)) + " " + " ".join(f"σ{i}" for i in range(14))
    bare = register_spans(text, scripture, father)
    assert bare and all(s.delta is None for s in bare)
    assert bare[0].to_dict()["delta"] is None
    markers = delta_markers(scripture, father, limit=10)
    opined = register_spans(text, scripture, father, markers=markers)
    assert [s.at for s in opined] == [s.at for s in bare], "the second opinion moves nothing"
    assert all(s.delta is not None for s in opined)


def test_the_null_loader_rounds_documents_up_and_refuses_drift(tmp_path: Path) -> None:
    import json

    from biblereference.register import RegisterNull

    artifact = {
        "schema": "biblereference-register-null/1",
        "fold_version": FOLD_VERSION,
        "window": 12,
        "stride": 6,
        "order": 3,
        "seed": 0,
        "replicates": 400,
        "bands": {"500": {"0.95": 30.0}, "2000": {"0.95": 38.0}},
    }
    path = tmp_path / "null.json"
    path.write_text(json.dumps(artifact), "utf-8")
    null = RegisterNull.load(path)
    assert null.threshold(400, 0.95) == 30.0
    assert null.threshold(501, 0.95) == 38.0, "rounding up is the conservative direction"
    assert null.threshold(99_999, 0.95) == 38.0, (
        "beyond the longest band: documented under-coverage"
    )
    assert null.exceeds(38.5, 2_000) and not null.exceeds(37.5, 2_000)
    with pytest.raises(KeyError):
        null.threshold(500, 0.5)
    artifact["fold_version"] = FOLD_VERSION - 1
    path.write_text(json.dumps(artifact), "utf-8")
    with pytest.raises(ValueError, match="folds at"):
        RegisterNull.load(path)


def test_the_register_scan_can_see_scripture_in_scripture(tmp_path: Path) -> None:
    """The regression that shipped for a day, pinned.

    The first `_evidence` compared raw counts and centred them, so a gram appearing at the
    *same rate* in a corpus six times larger scored −2.6 bits. Since the fathers quote
    scripture constantly, scriptural grams stand at higher raw counts in patristic prose
    than in scripture itself — and verbatim Isaiah 53 scored **negative in every window**.
    The scan flagged nothing, anywhere, and read as "these passages are not scriptural"
    when it was saying nothing at all.

    Here the father corpus is ten times the scripture corpus and holds every gram at the
    *same rate*. A count comparison calls that father-idiom; a rate comparison calls it a
    draw, and only the rate answer is true."""
    grams = {(3, f"σ{i} σ{i + 1} σ{i + 2}"): 10 for i in range(12)}
    scripture = NgramModel(
        build_model(tmp_path / "s.sqlite3", grams, tokens={n: 1_000 for n in range(1, 6)})
    )
    # Same grams, ten times the count, ten times the corpus: identical rates throughout.
    father = NgramModel(
        build_model(
            tmp_path / "f.sqlite3",
            {(order, g): 100 for order, g in grams},
            tokens={n: 10_000 for n in range(1, 6)},
        )
    )

    from biblereference.register import _evidence

    tokens = [f"σ{i}" for i in range(14)]
    llr = _evidence(tokens, scripture, father, 3)
    assert abs(llr) < 1.0, (
        "equal rates must score about zero; the count version scored this "
        "strongly negative and could not have found scripture anywhere"
    )

    # And a gram scripture holds at ten times the father's rate must score positive.
    richer = NgramModel(
        build_model(
            tmp_path / "r.sqlite3", {(3, "α β γ"): 100}, tokens={n: 1_000 for n in range(1, 6)}
        )
    )
    poorer = NgramModel(
        build_model(
            tmp_path / "p.sqlite3", {(3, "α β γ"): 100}, tokens={n: 10_000 for n in range(1, 6)}
        )
    )
    assert _evidence(["α", "β", "γ"], richer, poorer, 3) > 3.0


def test_unseen_by_both_is_a_draw_and_classical_prose_does_not_outscore_scripture(
    tmp_path: Path,
) -> None:
    """The second wrong version, pinned beside the first.

    Smoothing add-half *inside each corpus* gives an unseen gram the rate 0.5/N, which is
    larger for the smaller corpus — so every gram neither model knows hands scripture
    log2(N_father/N_scripture) free bits. Classical Greek is mostly such grams, and under
    that version control prose outscored scripture itself. A shared floor makes
    unseen-by-both an honest draw."""
    from biblereference.register import _evidence

    # Scripture's corpus a tenth the size, and a window of grams neither model has seen.
    scripture = NgramModel(
        build_model(
            tmp_path / "s.sqlite3", {(3, "α β γ"): 5}, tokens={n: 1_000 for n in range(1, 6)}
        )
    )
    father = NgramModel(
        build_model(
            tmp_path / "f.sqlite3", {(3, "α β γ"): 50}, tokens={n: 10_000 for n in range(1, 6)}
        )
    )
    unknown = [f"ξ{i}" for i in range(14)]
    assert abs(_evidence(unknown, scripture, father, 3)) < 0.5, (
        "grams neither corpus knows must be a draw, not free bits for the smaller one"
    )
    # And the shared gram, held at the same rate in both, is likewise a draw.
    assert abs(_evidence(["α", "β", "γ"], scripture, father, 3)) < 0.5
