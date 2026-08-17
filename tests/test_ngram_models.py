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
        [("language", "grc"), ("orders", "1,2,3,4,5"), ("min_count", "2"),
         ("fold_version", str(fold_version))],
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
    model = NgramModel(
        build_model(tmp_path / "m.sqlite3", {(3, "α β γ"): 50, (4, "α β γ δ"): 5})
    )
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
    scripture_grams = {(3, f"σ{i} σ{i+1} σ{i+2}"): 20 for i in range(12)}
    scripture = NgramModel(build_model(tmp_path / "s.sqlite3", scripture_grams,
                                       tokens={n: 1_000 for n in range(1, 6)}))
    father = NgramModel(build_model(tmp_path / "f.sqlite3", {},
                                    tokens={n: 100_000 for n in range(1, 6)}))
    prose = " ".join(f"π{i}" for i in range(24))
    quotation = " ".join(f"σ{i}" for i in range(14))
    text = f"{prose} {quotation} {prose}"
    spans = register_spans(text, scripture, father)
    assert spans, "the planted run is flagged"
    at = text.find("σ0 ")
    assert any(s.at <= at < s.end for s in spans), "the span covers the plant"
    assert all(s.source is None for s in spans), "v1 is the unresolved ledger"
    assert not any(s.end <= at - 40 for s in spans), "the leading prose alone is not a span"


@pytest.mark.skipif(not REAL_PATRISTIC.exists(), reason="consumer's model not on this machine")
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
