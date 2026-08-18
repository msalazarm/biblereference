"""The verification stage: cheap proposals, then an explicit test per candidate.

The blind-identification sciences share one architecture the matcher lacked.
Astrometry.net's quad-hashes only *propose* a sky location; every candidate then passes a
sequential Bayes-factor test, evidence accumulating multiplicatively until posterior odds
cross a bar chosen in the currency that matters — expected false positives over the whole
survey — which is how millions of hypotheses are scanned with no false positives. Shazam's
half is the free per-candidate statistic: hash pairs of spectral peaks, and a genuine
match makes the histogram of offset differences spike at one value while coincidence
scatters.

Both transfer whole. The matcher's gates are the cheap proposal; this module is the
explicit second look. The offset histogram runs over rare-lemma position pairs — a
quotation aligns its content words at one constant offset, a coincidence cannot — and the
verification odds are a sum of per-evidence log-likelihood ratios in the same log₂
currency as ``bits``.

One honesty rule governs v1: **only calibrated terms are summed.** The composite artifact
is the m/u table store, and a term without measured tables — the offset peak, the formula
flag — is *reported* as raw evidence but never folded into odds, because an uncalibrated
likelihood ratio presented as posterior odds is exactly the transposed-conditional sin the
forensic reporting stack (ENFSI) exists to forbid. Under a v1 artifact the odds therefore
*equal* the composite score; the extra terms activate the moment an artifact carries
their tables, and nothing else changes shape.

Opt-in (`Searcher(verify=True)`), because it costs a lexicon pass per candidate — which
is the two-stage economics working as designed: the expensive look is paid only on the
few the cheap one proposed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .composite import Composite

if TYPE_CHECKING:
    from .lemmata import Lexicon
    from .search import Match, Reading

__all__ = ["VerificationResult", "offset_histogram", "verify"]

#: Lemmas cheaper than this many bits do not pair. Shazam hashes *peaks*, not the noise
#: floor: καί and ὁ co-occur at every offset and would bury the spike the statistic
#: exists to see. Rare words carry the alignment, exactly as they carry the match.
_PAIR_FLOOR = 4.0


def offset_histogram(
    mine: Sequence[Reading],
    theirs: Sequence[Reading],
    weigh: Callable[[str], float] | None = None,
    *,
    floor: float = _PAIR_FLOOR,
) -> tuple[float, int]:
    """The offset-difference spike: ``(peak share, pairs it was built from)``.

    Every co-lemma position pair ``(i, j)`` votes for offset ``i - j``; a genuine match
    concentrates the votes at one value. Deliberately *not* the chain's own alignment —
    the chain keeps no traceback, and the whole worth of this statistic is that it is an
    independent second look rather than the first look repeated.

    The pair count is reported beside the share because a peak over three pairs and a
    peak over thirty are different kinds of evidence, and hiding the denominator is how
    a statistic learns to lie.
    """
    votes: Counter[int] = Counter()
    for i, reading in enumerate(mine):
        for j, other in enumerate(theirs):
            shared = reading & other
            if not shared:
                continue
            if weigh is not None and max(weigh(lemma) for lemma in shared) < floor:
                continue
            votes[i - j] += 1
    total = sum(votes.values())
    if not total:
        return (0.0, 0)
    return (max(votes.values()) / total, total)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """One candidate's second look, with every term named."""

    odds: float | None
    """The artifact's calibrated log₂ likelihood ratio for this candidate's whole
    evidence — the axes plus the verification terms, summed once and mapped once. Not a
    posterior probability and never presented as one: P(findings | proposition), the
    direction ENFSI's never-transpose rule permits. ``None`` where the evidence sits
    below the control sample's collection gate and the artifact has no counts to speak
    from — unscored, which is not the same as zero."""
    offset_peak: float
    """The offset histogram's peak share, 0..1. Raw evidence until an artifact carries
    its m/u tables; a likelihood term afterwards."""
    offset_pairs: int
    """How many rare-lemma pairs the peak stands on."""
    terms: tuple[tuple[str, float], ...]
    """What the sum was made of, by name, in the artifact's **raw** field weights — the
    audit trail. Once a calibration is in play these do not add to :attr:`odds`, and are
    not meant to: the calibration maps a complete raw sum to what the held-out data
    actually paid, so the parts and the whole are different quantities by design."""

    def to_dict(self) -> dict[str, object]:
        return {
            "odds": None if self.odds is None else round(self.odds, 2),
            "offset_peak": round(self.offset_peak, 4),
            "offset_pairs": self.offset_pairs,
            "terms": {name: round(value, 2) for name, value in self.terms},
        }


def verify(
    match: Match,
    *,
    language: str,
    lexicon: Lexicon,
    weigh: Callable[[str], float],
    composite: Composite,
) -> VerificationResult:
    """The explicit second look at one proposed match.

    Recomputes the readings from the match's own quoted words and its best witness —
    one lexicon pass, the price of the expensive stage — and sums only what the artifact
    has calibrated. The offset term joins the sum when the artifact names
    ``offset_peak`` in its fields; the formula term when it names ``formula``; until
    then both are reported and neither is claimed as odds.
    """
    from .search import _tokens, lemma_readings

    source = match.witnesses[0].text if match.witnesses else ""
    mine = lemma_readings(_tokens(match.quoted, language), language, lexicon)
    theirs = lemma_readings(_tokens(source, language), language, lexicon)
    peak, pairs = offset_histogram(mine, theirs, weigh)

    # One sum, scored once. The artifact's calibration is a map from a *complete* summed
    # weight to observed log-odds, so the verification terms are handed to `score` rather
    # than added to its output: adding a raw field weight to a calibrated total would put
    # two different quantities on one scale and call the result odds.
    #
    # Below the u-sample's collection gate the composite is not defined at all (the
    # artifact has no control counts there), and `score` returns None; a verification
    # that invented a number there would be worse than one that declines.
    odds = composite.score(
        match.run,
        match.lemma_run,
        match.chain,
        match.bits,
        formula=bool(match.formula) if "formula" in composite.fields else None,
        offset_peak=peak if "offset_peak" in composite.fields else None,
    )

    # The per-field contributions, in the artifact's own raw weights, so a reader can see
    # what the sum was made of. They do not add up to `odds` once a calibration is in
    # play, and the field name says which is which.
    from .composite import bin_of

    terms: list[tuple[str, float]] = []
    offered: dict[str, float] = {
        "run": float(match.run),
        "chain": float(match.chain),
        "bits": match.bits,
        "offset_peak": peak,
        "formula": 1.0 if match.formula else 0.0,
    }
    for field in composite.fields:
        if field in offered:
            terms.append(
                (field, composite.weights[field][bin_of(composite.bins[field], offered[field])])
            )
    return VerificationResult(
        odds=odds,
        offset_peak=peak,
        offset_pairs=pairs,
        terms=tuple(terms),
    )
