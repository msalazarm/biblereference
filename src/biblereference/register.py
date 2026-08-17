"""Stratum R, instrumentation first: spans that sound like scripture, sourced or not.

The one capability no quotation stratum has: seeing scripture as *foreign material in the
father's prose* with no source match at all. Two count-based language models — scripture's,
built by `tools/scripture_ngrams.py` from the held corpora, and the father's own, built by
the consumer from his securely-attested prose — and a sliding window scored as
``log₂ P(window | scripture) − log₂ P(window | father)``. A window his own model explains
is his idiom; a window jointly improbable under his and probable under scripture's is
inherited.

**v1 is a ledger, not a detector.** A flagged span with no resolved source joins the
unmatched-formula ledger as the second self-updating measured miss — that alone justifies
the build — and every span carries its raw LLR with no claim attached. The claim needs the
Monte-Carlo max-scan null: a threshold calibrated against the distribution of the
*maximum* window score over control replicates, never against per-window p-values, or
scanning thousands of windows manufactures the significance it reports. That calibration
is a big compute job, deferred past the consumer's sweep window, and until it runs this
module's default is *never* — the design's own words.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from .emphasis import fold
from .ngram_models import NgramModel

__all__ = ["RegisterSpan", "register_spans"]

#: The same window geometry the matcher sweeps with and the control evidence was
#: measured in, so a later calibration speaks a unit that already exists.
_WINDOW: Final = 12
_STRIDE: Final = 6

_TOKEN_RE: Final = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class RegisterSpan:
    """One stretch of prose the scripture model explains better than the father's own."""

    at: int
    """Character offset where the span begins, as written."""
    end: int
    """Character offset just past it."""
    llr: float
    """Peak window log2 P(scripture) - log2 P(father) inside the span. Raw evidence:
    until the max-scan null is calibrated, no magnitude here means anything beyond
    ordering, and the docstring is where that is said."""
    order: int
    """The n-gram order the peak was measured at."""
    source: str | None = None
    """The resolved passage, where a quotation stratum found one -- or ``None``, which
    is the ledger entry: announced by its own register, matched by nothing."""

    def to_dict(self) -> dict[str, object]:
        return {
            "register_span": True,
            "at": self.at,
            "end": self.end,
            "llr": round(self.llr, 2),
            "order": self.order,
            "source": self.source,
        }


def _windows(text: str, language: str | None, window: int, stride: int) -> Iterator[
    tuple[int, int, list[str]]
]:
    """(char start, char end, folded tokens) per window, offsets from the text as written.

    Tokens are folded word by word rather than the text being folded whole, which gives
    the same stream -- the fold works character by character within a word -- while
    keeping the offsets the ledger points back at.
    """
    words = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    folded = [(fold(word, language), start, end) for word, start, end in words]
    folded = [(token, start, end) for token, start, end in folded if token]
    if not folded:
        return
    for first in range(0, max(1, len(folded) - window + 1), stride):
        chunk = folded[first : first + window]
        yield (chunk[0][1], chunk[-1][2], [token for token, _, _ in chunk])


def _evidence(
    tokens: list[str], scripture: NgramModel, father: NgramModel, order: int
) -> float:
    """Summed per-gram log2((count_s + 0.5) / (count_f + 0.5)) -- centred so that a gram
    *neither* model has seen contributes exactly zero.

    The naive rate LLR carries a corpus-size bias: with 2.4M scripture positions against
    13.6M patristic ones, every unseen gram hands scripture +2.5 bits, and a whole
    document of the father's own prose comes out "scripture-shaped". Centring at the
    both-unseen case removes it, at a stated cost: a gram merely *proportionally*
    commoner in the smaller corpus scores zero too, so this v1 under-claims -- the right
    direction for an instrument whose thresholds are not yet calibrated.
    """
    total = 0.0
    for start in range(0, len(tokens) - order + 1):
        gram = " ".join(tokens[start : start + order])
        total += math.log2(
            (scripture.count(gram, order) + 0.5) / (father.count(gram, order) + 0.5)
        )
    return total


def register_spans(
    text: str,
    scripture: NgramModel,
    father: NgramModel,
    *,
    window: int = _WINDOW,
    stride: int = _STRIDE,
    order: int = 3,
) -> list[RegisterSpan]:
    """Every stretch the scripture model explains better, adjacent windows merged.

    Returns spans with ``source=None`` -- the unresolved ledger entries. A caller who
    has scan results can fill ``source`` for spans a match covers; what stays ``None``
    is the measured miss.
    """
    spans: list[RegisterSpan] = []
    open_at: int | None = None
    open_end = 0
    open_peak = 0.0
    for start, end, tokens in _windows(text, scripture.language or None, window, stride):
        llr = _evidence(tokens, scripture, father, order)
        if llr > 0:
            if open_at is None:
                open_at, open_peak = start, llr
            else:
                open_peak = max(open_peak, llr)
            open_end = end
        elif open_at is not None:
            spans.append(RegisterSpan(open_at, open_end, open_peak, order))
            open_at = None
            open_peak = 0.0
    if open_at is not None:
        spans.append(RegisterSpan(open_at, open_end, open_peak, order))
    return spans
