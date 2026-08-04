"""Checking a quotation the author supplied against the verse it claims to be.

``context="..."`` lets you print your own preferred translation rather than the one this
library holds. That is a feature, not a discrepancy -- so the check cannot demand an exact
match. What it can do is notice when the words have nothing to do with each other, which
is what a mistyped verse number or a stray copy-paste looks like.

The comparison is on words, with case, punctuation and accents removed, so two honest
translations of the same verse score high and two different verses score low. The default
threshold is deliberately loose; ``strict`` in :class:`~biblereference.render.Config`
turns a low score from a warning into an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from .emphasis import fold

__all__ = ["DEFAULT_THRESHOLD", "QuoteCheck", "check_quotation"]

#: Below this, a supplied quotation is reported. Two translations of one verse usually
#: score well above it; two different verses well below.
DEFAULT_THRESHOLD: Final = 0.45

_WORD_RE: Final = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """The result of comparing a supplied quotation with the resolved verse."""

    ratio: float
    threshold: float
    supplied: str
    actual: str

    @property
    def plausible(self) -> bool:
        """Whether the supplied text is recognisably the same passage."""
        return self.ratio >= self.threshold

    def message(self, reference: str) -> str:
        """A report an author can act on, showing both texts."""
        return (
            f"the quotation supplied for {reference} does not look like that passage "
            f"({self.ratio:.0%} of the words match)\n"
            f"    supplied: {_ellipsis(self.supplied)}\n"
            f"    {reference}: {_ellipsis(self.actual)}"
        )


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(fold(text))


def check_quotation(
    supplied: str, actual: str, *, threshold: float = DEFAULT_THRESHOLD
) -> QuoteCheck:
    """Compare a supplied quotation with the text of the verse it cites."""
    supplied_words, actual_words = _words(supplied), _words(actual)
    if not supplied_words or not actual_words:
        ratio = 0.0
    else:
        # autojunk=False for the same reason search.py gives: difflib otherwise treats any
        # element occurring in more than 1% of a sequence of 200 or more as noise and drops
        # it, and the elements it discards are "the", "and", "of" -- the connective tissue
        # that tells a quotation from a bag of shared vocabulary. A supplied quotation of a
        # whole psalm is that long, so without this the check got *looser* the longer the
        # quotation, which is precisely backwards.
        ratio = SequenceMatcher(None, supplied_words, actual_words, autojunk=False).ratio()
    return QuoteCheck(
        ratio=ratio, threshold=threshold, supplied=supplied.strip(), actual=actual.strip()
    )


def _ellipsis(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
