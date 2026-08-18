"""Recovering the scribally corrupted, exactly: every known form within edit distance k.

The lemma lexicon knows 1.1 million spellings, and a copyist's slip or an itacism the
classes do not cover produces a spelling it has never seen. The itacised tier recovers
one bounded family of those; this tier recovers the rest the way §4.4 specifies —
**exact, deterministic, provably nothing missed at the stated bound**: every form in the
lexicon within Levenshtein distance k of the unknown token, enumerated, their dictionary
forms taken as the token's reading. It feeds the lexicon, not the gates: a recovered form
is then matched normally, and whatever gate would admit the correctly-spelled word admits
the slip on the same evidence.

Exactness is cheap to promise and easy to lose, so the pruning is stated with its proof:
a candidate is skipped only when the character-bag difference exceeds 2k — each edit
changes the bag by at most two (one out, one in) — and survivors go through the full
banded DP. Nothing else is filtered. The cost is real (a second or so per *distinct*
unknown token, cached for the process) and the tier is opt-in until the control corpus
prices it, like every loosening before it.

The bound adapts to what it bounds: k=1 for tokens of four letters or fewer, k=2 above —
at distance 2 a three-letter word reaches a third of the dictionary, and a recovery that
liberal is a different word generator wearing a helpful name.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from functools import lru_cache
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .store import DataHome

__all__ = ["Recovery"]

#: Distance allowed, by token length: short words over-recover catastrophically at 2.
_SHORT: Final = 4

#: Tokens longer than this are not recovered at all -- they are more likely compounds or
#: foreign matter than slips, and the DP over the whole length band stops being cheap.
_LONGEST: Final = 24


def _edit_within(a: str, b: str, k: int) -> bool:
    """Banded Levenshtein: True iff distance(a, b) <= k. Exact within the band."""
    if abs(len(a) - len(b)) > k:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        best = i
        for j, cb in enumerate(b, 1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            )
            best = min(best, current[j])
        if best > k:
            return False
        previous = current
    return previous[len(b)] <= k


def _bag(token: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for ch in token:
        out[ch] = out.get(ch, 0) + 1
    return out


def _bag_distance(a: dict[str, int], b: dict[str, int]) -> int:
    total = 0
    for ch in a.keys() | b.keys():
        total += abs(a.get(ch, 0) - b.get(ch, 0))
    return total


class Recovery:
    """The lexicon's forms, held by length, answering "what could this have been"."""

    def __init__(self, home: DataHome, language: str) -> None:
        self.language = language
        self._by_length: dict[int, list[str]] = {}
        with closing(
            sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        ) as db:
            for (form,) in db.execute(
                "SELECT DISTINCT form FROM lemma_form WHERE language = ?", (language,)
            ):
                text = str(form)
                self._by_length.setdefault(len(text), []).append(text)

    @property
    def held(self) -> bool:
        return bool(self._by_length)

    def bound(self, token: str) -> int:
        return 1 if len(token) <= _SHORT else 2

    @lru_cache(maxsize=50_000)  # noqa: B019 -- one Recovery per Searcher, same lifetime
    def candidates(self, token: str) -> tuple[str, ...]:
        """Every known form within the token's bound, exactly.

        The only skip is the character-bag prune, and it cannot lose a candidate: one
        edit moves at most one character out of the bag and one in, so distance <= k
        implies bag difference <= 2k. Survivors face the full DP.
        """
        if not token or len(token) > _LONGEST:
            return ()
        k = self.bound(token)
        bag = _bag(token)
        out: list[str] = []
        for length in range(max(1, len(token) - k), len(token) + k + 1):
            for form in self._by_length.get(length, ()):
                if form == token:
                    continue
                if _bag_distance(bag, _bag(form)) > 2 * k:
                    continue
                if _edit_within(token, form, k):
                    out.append(form)
        return tuple(sorted(out))

    def lemmas_for(
        self, token: str, lookup: Callable[[list[str], str], dict[str, frozenset[str]]]
    ) -> frozenset[str]:
        """The union of dictionary forms behind every recoverable spelling.

        ``lookup`` is `Lexicon.of`-shaped: called with the candidate forms, returning
        their lemma sets -- the recovery feeds the lexicon, never replaces it.
        """
        found = self.candidates(token)
        if not found:
            return frozenset()
        readings = lookup(list(found), self.language)
        out: set[str] = set()
        for lemmas in readings.values():
            out |= lemmas
        return frozenset(out)
