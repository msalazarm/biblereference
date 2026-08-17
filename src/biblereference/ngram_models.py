"""Reading n-gram model artifacts: the consumer's patristic models, and our own.

The interface between the two projects is a model file, not a coupling — SQLite, one file
per language, four tables (``meta``, ``totals``, ``ngram``, ``works``), folds produced by
:func:`biblereference.emphasis.fold` and space-joined. The consumer builds the patristic
side from their corpus; `tools/scripture_ngrams.py` builds the scripture side in the same
schema; this one reader serves both, read-only.

Two facts about the numbers that a caller must not forget:

* Orders 3–5 are pruned at ``min_count`` (2, recorded in ``meta``) — a count of 0 there
  means *at most min_count − 1*, never "unattested". Rates near zero are floors.
* The folds were made under a specific :data:`~biblereference.emphasis.FOLD_VERSION`,
  recorded in ``meta``. A model on a stale fold is silently wrong — its keys simply stop
  meeting the queries — which is why :meth:`NgramModel.check` exists and why the
  constructor runs it by default.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from .emphasis import FOLD_VERSION, fold

__all__ = ["NgramModel"]

#: Orders the peak is taken over. Measured against the consumer's own model: at order 3
#: a genuine citation peaks at 21.9/M because it contains `ο κυριοσ και`, and the class
#: separation their §6 reports collapses; at orders 4-5 the doxology holds 18.9/M against
#: the citations' 0.9-1.0 and the separation is theirs again. A stock phrase is a
#: *phrase*, and four words is where phrases start being ones.
_PEAK_ORDERS: Final = (4, 5)


class NgramModel:
    """One language's n-gram counts, from an artifact in the shared schema."""

    def __init__(self, path: str | Path, author: str = "", *, check: bool = True) -> None:
        """
        :param author: Whose counts to read. ``""`` is the pooled corpus -- for the
            patristic artifact, everything a shelf or an author contributed; for the
            scripture one, every held corpus together.
        """
        self.path = Path(path)
        self.author = author
        self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.meta: dict[str, str] = {
            str(k): str(v) for k, v in self._db.execute("SELECT key, value FROM meta")
        }
        self.language = self.meta.get("language", "")
        self.orders = tuple(int(n) for n in self.meta.get("orders", "1,2,3,4,5").split(","))
        self.min_count = int(self.meta.get("min_count", "1"))
        self._totals: dict[int, int] = {
            int(order): int(tokens)
            for order, tokens in self._db.execute(
                'SELECT "order", tokens FROM totals WHERE author = ?', (author,)
            )
        }
        if check:
            self.check()

    def check(self) -> None:
        """Refuse a model folded under a different rule than this library folds by.

        The staleness the `meta` field was added for: the fold changed twice in one
        month, and a model whose keys were made under the old rule answers every query
        with silence that looks like rarity.
        """
        recorded = self.meta.get("fold_version")
        if recorded is not None and int(recorded) != FOLD_VERSION:
            raise ValueError(
                f"{self.path.name} was built on fold {recorded} and this library folds at "
                f"{FOLD_VERSION}; its keys no longer meet these queries. Rebuild the model."
            )

    def tokens(self, order: int) -> int:
        """The denominator: how many order-``n`` positions the corpus offered."""
        return self._totals.get(order, 0)

    def count(self, gram: str, order: int) -> int:
        """How often this folded, space-joined n-gram occurs. For pruned orders, 0 means
        *at most min_count - 1*, not unattested."""
        row = self._db.execute(
            'SELECT count FROM ngram WHERE author = ? AND "order" = ? AND fold = ?',
            (self.author, order, gram),
        ).fetchone()
        return int(row[0]) if row else 0

    def rate_per_million(self, gram: str, order: int) -> float:
        total = self.tokens(order)
        if not total:
            return 0.0
        return self.count(gram, order) / total * 1_000_000

    def grams(self, text: str) -> list[str]:
        """The text as the model's own token stream: folded whole, split on space --
        exactly the convention the builders use, so a span a caller holds can be looked
        up without either side re-normalising."""
        return fold(text, self.language or None).split()

    def peak_rate(self, text: str, orders: Iterable[int] = _PEAK_ORDERS) -> float:
        """The most frequent phrase inside the text, in occurrences per million.

        The consumer's §6 measurement, made portable: the doxology's densest n-gram runs
        at tens per million of Christian prose while a genuine citation's runs at ones,
        and the *peak* is what separates them -- a stock phrase is a phrase somebody
        keeps saying, however ordinary its words.
        """
        tokens = self.grams(text)
        best = 0.0
        for order in orders:
            if order not in self._totals:
                continue
            for start in range(0, len(tokens) - order + 1):
                gram = " ".join(tokens[start : start + order])
                best = max(best, self.rate_per_million(gram, order))
        return best

    def log_prob(self, tokens: Sequence[str], order: int) -> float:
        """log2 probability of the token stream under order-``n`` counts, add-half
        smoothed. Deliberately simple: the register scan's v1 is instrumentation, and a
        smoothing scheme worth arguing about belongs to the calibrated version."""
        total = self.tokens(order)
        if not total or len(tokens) < order:
            return 0.0
        out = 0.0
        for start in range(0, len(tokens) - order + 1):
            gram = " ".join(tokens[start : start + order])
            out += math.log2((self.count(gram, order) + 0.5) / (total + 1))
        return out

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> NgramModel:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
