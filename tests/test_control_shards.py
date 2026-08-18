"""The control harness's window sharding: identical work, bounded memory.

The bug this exists for: the control corpus holds a text of 66,461 words, and an
unsharded task builds every row for it as one list and returns it as one pickle. That
killed a 3M-word run outright, and froze the progress counter for half an hour before
it did — the ordered `imap` that makes `--resume` exact cannot yield past a slow task.

Sharding is only safe if it changes nothing. These tests pin that: the same windows, in
the same order, with the same preceding context, producing the same rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from calibrate_inflected import _shards, _window_count

from biblereference.store import DataHome

#: Captured at import, before conftest's isolation fixture redirects the data home --
#: the same discipline `test_entities` uses, and for the same reason: these checks are
#: about the real corpus, and a temp home would make them silently vacuous.
REAL = DataHome()


def test_a_short_text_is_one_shard() -> None:
    """The common case must be untouched: 18,000-odd control texts are a few windows
    long and must still be exactly one task each."""
    texts = ["α " * 40, "β " * 12]
    plan = _shards(texts)
    assert [(index, first, last) for index, _, first, last in plan] == [
        (0, 0, _window_count(texts[0])),
        (1, 0, _window_count(texts[1])),
    ]


def test_a_long_text_splits_at_window_boundaries_and_covers_exactly_once() -> None:
    """No window duplicated, none dropped, and the pieces are in corpus order."""
    long_text = " ".join(f"w{i}" for i in range(20_000))
    plan = _shards([long_text], most=400)
    assert len(plan) > 1, "the point of the exercise"
    covered: list[int] = []
    for index, text, first, last in plan:
        assert index == 0 and text == long_text, "each shard carries the whole text"
        covered.extend(range(first, last))
    assert covered == list(range(_window_count(long_text))), (
        "every window scored exactly once, in order"
    )


def test_shard_boundaries_do_not_change_the_window_stream() -> None:
    """A window's identity is its start offset in the *whole* text, so a shard scores
    windows the unsharded run would have scored, with the same context behind them."""
    text = " ".join(f"w{i}" for i in range(5_000))
    starts = list(range(0, max(1, len(text.split()) - 12 + 1), 6))
    plan = _shards([text], most=100)
    from_shards = [starts[first:last] for _, _, first, last in plan]
    assert [start for piece in from_shards for start in piece] == starts


def test_the_planner_is_deterministic() -> None:
    texts = [" ".join(f"w{i}" for i in range(n)) for n in (10, 9_000, 30)]
    assert _shards(texts) == _shards(texts)


def test_sharding_reproduces_the_unsharded_rows_exactly() -> None:
    """The acceptance test: real control prose, real matches, split six ways, and every
    row identical to the unsharded run. Sharding that changed one row would silently
    change the null the composite is calibrated against."""
    import pytest
    from calibrate_inflected import _W, COLLECT, GREEK, MARKS, _evidence_one, control_text

    from biblereference.lemmata import Lexicon
    from biblereference.search import LemmaWeights, Searcher

    if not MARKS.exists() or not REAL.database.exists() or not Lexicon(REAL).holds("grc"):
        pytest.skip("needs the built library, the lexicon, and the marks database")

    texts, _ = control_text(60_000)
    text = max(texts[:400], key=lambda t: len(t.split()))
    _W["searcher"] = Searcher(
        REAL, languages=["grc"], inflected=True, min_query=3, gates=[COLLECT], **GREEK
    )
    _W["lexicon"] = Lexicon(REAL)
    _W["weigh"] = LemmaWeights(REAL).of("grc")
    whole_rows, whole_windows, _, whole_cut = _evidence_one(text)
    if not whole_rows:
        pytest.skip("the chosen control text yielded no candidates to compare")

    count = _window_count(text)
    step = max(1, count // 5)
    pieces = [
        _evidence_one(text, first_window=at, last_window=min(at + step, count))
        for at in range(0, count, step)
    ]
    assert [row for rows, _, _, _ in pieces for row in rows] == whole_rows
    assert sum(windows for _, windows, _, _ in pieces) == whole_windows
    assert sum(cut for _, _, _, cut in pieces) == whole_cut
