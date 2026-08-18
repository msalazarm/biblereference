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

import json
import math
import re
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .emphasis import FOLD_VERSION, fold
from .ngram_models import NgramModel

__all__ = ["DeltaMarkers", "RegisterNull", "RegisterSpan", "delta_markers", "register_spans"]

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
    delta: float | None = None
    """The rolling function-word Delta at the peak window, where markers were offered:
    positive means the window's function-word profile sits nearer scripture's than the
    father's. A second opinion beside ``llr`` from evidence the LLR barely uses -- the
    LLR is dominated by rare content grams, the Delta by the commonest words -- and
    never a gate."""

    def to_dict(self) -> dict[str, object]:
        return {
            "register_span": True,
            "at": self.at,
            "end": self.end,
            "llr": round(self.llr, 2),
            "order": self.order,
            "source": self.source,
            "delta": None if self.delta is None else round(self.delta, 3),
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
    """Summed per-gram ``log2( rate_scripture / rate_father )``, add-half smoothed.

    **The rate, not the count.** The first version of this compared raw counts, centred so
    that a gram neither model had seen scored exactly zero, to remove the corpus-size bias
    that hands scripture free bits on every unknown gram. It removed the signal instead.
    The patristic corpus holds 13.4M order-3 positions against scripture's 2.25M, so a
    gram appearing at the *same rate* in both scored log2(1/6) = −2.6, and the fathers
    quote scripture constantly, which puts scriptural grams in the patristic corpus at
    counts several times scripture's own. Measured consequence: **verbatim Isaiah 53
    scored negative in every window** and the scan flagged nothing anywhere. An instrument
    that cannot see scripture in scripture is not conservative, it is broken, and it was
    shipped that way for a day.

    The size bias the centring existed to fight is real -- an unseen gram is worth
    ``log2(N_father / N_scripture)`` here, about +2.6 -- and the answer is not to subtract
    it but to let the **max-scan null absorb it**: control prose collects the same free
    bits on the same unseen grams, so it lands in the threshold rather than in the claim.
    That null is exactly what `tools/register_null.py` measures, and its existence is what
    makes the honest statistic usable where the hack was not.
    """
    scripture_total = scripture.tokens(order) or 1
    father_total = father.tokens(order) or 1
    total = 0.0
    for start in range(0, len(tokens) - order + 1):
        gram = " ".join(tokens[start : start + order])
        total += math.log2(
            ((scripture.count(gram, order) + 0.5) / scripture_total)
            / ((father.count(gram, order) + 0.5) / father_total)
        )
    return total


@dataclass(frozen=True, slots=True)
class DeltaMarkers:
    """The marker-word profiles a rolling Burrows Delta compares against.

    Burrows' Delta is an L1 distance over the *commonest* words -- the function words an
    author cannot help but use at their own rates -- in z-score units (Argamon 2008).
    The classic z uses a standard deviation across a reference set of texts; with
    exactly two profiles in hand the scale here is the mean of the two rates, which
    keeps every marker's contribution dimensionless and comparable without pretending
    to a corpus of samples that does not exist. Both models' order-1 tables already
    hold everything needed -- no new data."""

    words: tuple[str, ...]
    scripture_rate: tuple[float, ...]
    father_rate: tuple[float, ...]
    scale: tuple[float, ...]


def delta_markers(
    scripture: NgramModel, father: NgramModel, limit: int = 150
) -> DeltaMarkers:
    """Marker words from the father's commonest order-1 grams -- the top of any word
    list is function words -- kept only where scripture's table also has a rate, so a
    marker never scores on pruning silence."""
    s_total = scripture.tokens(1) or 1
    f_total = father.tokens(1) or 1
    words: list[str] = []
    s_rates: list[float] = []
    f_rates: list[float] = []
    scales: list[float] = []
    for gram, count in father.top_grams(1, limit * 2):
        s_count = scripture.count(gram, 1)
        if not s_count:
            continue
        s_rate = s_count / s_total
        f_rate = count / f_total
        words.append(gram)
        s_rates.append(s_rate)
        f_rates.append(f_rate)
        scales.append((s_rate + f_rate) / 2)
        if len(words) == limit:
            break
    return DeltaMarkers(tuple(words), tuple(s_rates), tuple(f_rates), tuple(scales))


def _rolling_delta(tokens: list[str], markers: DeltaMarkers) -> float:
    """Delta(father) - Delta(scripture) for one window: positive when the window's
    function-word usage is nearer scripture's profile."""
    if not markers.words or not tokens:
        return 0.0
    share = 1 / len(tokens)
    rates: dict[str, float] = {}
    for token in tokens:
        if token in rates:
            rates[token] += share
        else:
            rates[token] = share
    toward = 0.0
    for index, word in enumerate(markers.words):
        rate = rates.get(word, 0.0)
        toward += (
            abs(rate - markers.father_rate[index]) - abs(rate - markers.scripture_rate[index])
        ) / markers.scale[index]
    return toward / len(markers.words)


class RegisterNull:
    """The Monte-Carlo max-scan null, loaded from the artifact `tools/register_null.py`
    writes: the distribution of the MAXIMUM window LLR over control replicates, banded
    by document length, because scanning more windows raises the maximum chance gets to
    reach. Per-window p-values are exactly what this exists to refuse."""

    def __init__(
        self,
        bands: dict[int, dict[float, float]],
        window: int,
        stride: int,
        order: int,
        replicates: int,
        fold_version: int,
    ) -> None:
        self.bands = bands
        self.window = window
        self.stride = stride
        self.order = order
        self.replicates = replicates
        self.fold_version = fold_version

    @classmethod
    def load(cls, path: str | Path) -> RegisterNull:
        raw = json.loads(Path(path).read_text("utf-8"))
        schema = str(raw.get("schema", ""))
        if not schema.startswith("biblereference-register-null/1"):
            raise ValueError(f"not a register-null artifact: schema {schema!r} in {path}")
        if int(raw["fold_version"]) != FOLD_VERSION:
            raise ValueError(
                f"register null was measured under fold {raw['fold_version']}; this "
                f"library folds at {FOLD_VERSION}. Re-run tools/register_null.py."
            )
        return cls(
            bands={
                int(words): {float(level): float(value) for level, value in table.items()}
                for words, table in raw["bands"].items()
            },
            window=int(raw["window"]),
            stride=int(raw["stride"]),
            order=int(raw["order"]),
            replicates=int(raw["replicates"]),
            fold_version=int(raw["fold_version"]),
        )

    def threshold(self, words: int, level: float = 0.95) -> float:
        """The max-LLR a document of this length clears by chance with probability
        ``1 - level``. The band chosen is the smallest measured length at or above
        ``words`` -- more windows raise the chance maximum, so rounding the document
        *up* is the conservative direction. A document longer than the longest band
        gets the longest band's threshold, which under-covers; measure a longer band
        rather than trusting that edge."""
        lengths = sorted(self.bands)
        at = bisect_left(lengths, words)
        band = lengths[min(at, len(lengths) - 1)]
        table = self.bands[band]
        if level not in table:
            raise KeyError(f"level {level} not measured; artifact holds {sorted(table)}")
        return table[level]

    def exceeds(self, llr: float, words: int, level: float = 0.95) -> bool:
        """Whether a span's peak clears the calibrated line for a document this long."""
        return llr > self.threshold(words, level)


def register_spans(
    text: str,
    scripture: NgramModel,
    father: NgramModel,
    *,
    window: int = _WINDOW,
    stride: int = _STRIDE,
    order: int = 3,
    markers: DeltaMarkers | None = None,
) -> list[RegisterSpan]:
    """Every stretch the scripture model explains better, adjacent windows merged.

    Returns spans with ``source=None`` -- the unresolved ledger entries. A caller who
    has scan results can fill ``source`` for spans a match covers; what stays ``None``
    is the measured miss. With ``markers`` (see :func:`delta_markers`) each span also
    carries the rolling function-word Delta measured at its peak window -- the second
    opinion, from the words the LLR barely weighs.
    """
    spans: list[RegisterSpan] = []
    open_at: int | None = None
    open_end = 0
    open_peak = 0.0
    open_delta: float | None = None
    for start, end, tokens in _windows(text, scripture.language or None, window, stride):
        llr = _evidence(tokens, scripture, father, order)
        if llr > 0:
            if open_at is None or llr > open_peak:
                open_delta = _rolling_delta(tokens, markers) if markers else None
            if open_at is None:
                open_at, open_peak = start, llr
            else:
                open_peak = max(open_peak, llr)
            open_end = end
        elif open_at is not None:
            spans.append(RegisterSpan(open_at, open_end, open_peak, order, delta=open_delta))
            open_at = None
            open_peak = 0.0
            open_delta = None
    if open_at is not None:
        spans.append(RegisterSpan(open_at, open_end, open_peak, order, delta=open_delta))
    return spans
