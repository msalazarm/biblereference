"""The inverse question: here is some text -- which verse is it, and whose translation?

Everything else in this library starts from a reference and produces words. This starts
from words and produces a reference, which is a harder problem for three reasons.

**People quote from memory.** *I can do all things through Christ who strengthens me* is
not quite any translation, and a preacher mid-sentence is further from the page than that.
So matching is on folded word tokens, with an edit-distance score rather than equality,
and the retrieval step asks only for the words that narrow the field.

**Translations are not all distinguishable.** Fifty-odd English Bibles carry a great many
verses identically -- the World English Bible variants agree with each other almost
everywhere, and the American Standard Version with its Byzantine revision. Naming one of
them as *the* translation quoted would be invention. So a match carries a ranked set of
witnesses and reports a tie as a tie.

**The translation quoted is often one we do not have.** The New International Version, the
English Standard Version, the New American Standard and the New King James dominate
American preaching, and none can be lawfully bulk-downloaded. A quotation from one of them
still matches its passage well enough to locate it, and matches no indexed translation
closely. That gap is a signal, and it is reported rather than smoothed over: the passage is
named and the translation is left open. A study of who quotes what would otherwise inherit
a quiet bias toward whichever public-domain text happened to sit nearest the missing one.

The index is built from the verse store, so it needs no download and can be rebuilt at any
time. See :data:`biblereference.store.SEARCH_SCHEMA`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from difflib import Match as Match_
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .parallels import Parallels

from .corpora.base import CorpusError, VerseUnavailable
from .corpora.web import KNOWN_VERSIONS, BibleGatewayCorpus
from .dating import translated as _translated
from .emphasis import FOLD_VERSION, fold
from .lemmata import Lexicon
from .refs import VerseRange, VerseRef
from .store import DataHome, open_store, read_chapter
from .tags import resolve_language
from .versification import Versification, VersificationError

__all__ = [
    "COVERAGE",
    "DEFAULT_BUDGET",
    "DEFAULT_MARGIN",
    "IDENTIFIED",
    "QUOTATION",
    "RESOLUTION_ORDER",
    "FormulaDebt",
    "IndexCoverage",
    "IndexIncomplete",
    "IndexResult",
    "Match",
    "Resolution",
    "Resolver",
    "ScaledRun",
    "Searcher",
    "Witness",
    "build_index",
    "index_coverage",
    "index_is_stale",
    "indexed_corpora",
]

#: Below this, text is not treated as a quotation at all -- but see :data:`_MIN_RUN`, which
#: does most of the work of keeping noise out and is why this can afford to be as low as it
#: is. Higher than :data:`biblereference.quotecheck.DEFAULT_THRESHOLD`, which scores a
#: quotation whose reference the author already supplied; here nothing is known in advance
#: and a million verses are in scope.
#:
#: Calibrated against the built corpus over ten phrases of ordinary sermon language and
#: eight real quotations: 0.62 admitted no noise but lost *We all like sheep have gone
#: astray*, quoted as far as the clause and no further; 0.50 admitted *we are saved by
#: grace through faith alone* as Ephesians 2:8 at 51%. Between those, recall is flat and
#: noise is zero, so this sits in the middle of the clean band rather than at its edge.
#:
#: This is a floor on :func:`_ratio`, and it is no longer the only way to be a quotation:
#: see :data:`COVERAGE`, which is what admits the short exact quotation this measure cannot
#: reach.
QUOTATION: Final = 0.55

#: The other way to be a quotation: this share of the *searched words* accounted for, however
#: little the two texts resemble each other overall.
#:
#: :data:`QUOTATION` alone caps a short quotation of a long verse, because a symmetric ratio
#: divides by both lengths -- *he gave his only begotten Son* is every word of it taken from
#: John 3:16 and scores 0.39. Preachers quote whole verses and the ratio suits them;
#: patristic prose quotes a clause and argues from it, and on 4,549 hand-marked Greek
#: quotations the ratio finds 27% against 62% for coverage.
#:
#: The two gates are an **or**, so nothing the ratio used to find is lost. Measured on the
#: built corpus, they also fail differently, which is what makes the pair safe where either
#: alone is not:
#:
#: ==========================================  ==========  ==========
#: ..                                          coverage    ratio
#: ==========================================  ==========  ==========
#: *he gave his only begotten Son*             **1.00**    0.39
#: an unindexed rendering of Ephesians 2:8     0.82        **0.82**
#: *we are saved by grace through faith alone* 0.75        0.46
#: ==========================================  ==========  ==========
#:
#: The last is the one to keep out, and it is ordinary religious language rather than a
#: quotation -- but Darby reads "ye are saved by grace, through faith", so it really does
#: carry six consecutive words of the verse and the contiguity gate cannot see the
#: difference. Only requiring *both* measures to be unconvinced excludes it.
#:
#: Calibrated on English, like every constant here, over twelve real quotations, eight
#: recalled imperfectly (0.90 to 1.00) and ten phrases of ordinary religious language (0.75
#: and below). Nothing measured falls between, so this sits in the gap rather than at an
#: edge -- and it is a parameter because Greek carries inflectional variation English does
#: not. See :class:`Searcher`.
COVERAGE: Final = 0.90

#: At or above this, the wording is close enough to name the translation. Between this and
#: :data:`QUOTATION` the passage is identified and the translation is not: that is the
#: shape of a quotation from a Bible this corpus does not hold.
IDENTIFIED: Final = 0.86

#: Witnesses scoring within this of the best are reported as tied. Two translations that
#: differ in one word out of thirty are not evidence about which one was being read.
DEFAULT_MARGIN: Final = 0.03

#: Words too common to narrow a search. Deliberately short: it exists to stop a query
#: degenerating into a scan, not to do the work of the inverse-document-frequency
#: weighting that follows it.
_STOPWORDS: Final = frozenset(
    """
    a an and are as at be been but by for from had has have he her him his i in is it
    its me my not of on or our shall she so that the their them then there they this
    to unto up us was we were what when which who will with you your
    """.split()
)

#: How many query words to actually search on, rarest first.
_QUERY_TERMS: Final = 14

#: How many indexed texts to pull back before scoring properly.
_CANDIDATES: Final = 400

#: How many assembled passages to score in full.
_PASSAGES: Final = 12

#: Words per window when sweeping a document, and how far each window advances. Twelve is
#: about the length of a clause, long enough to carry distinctive words and short enough
#: that a quotation is not buried in the speaker's own sentences; the half-window stride
#: means every quotation of that length or more falls wholly inside some window.
_WINDOW: Final = 12
_STRIDE: Final = 6

#: Windows this far apart still count as one quotation. One window's gap absorbs a clause
#: the speaker interpolated mid-quotation, which preachers do constantly.
_CLUSTER_GAP: Final = _STRIDE * 2

#: Candidates and terms per window while sweeping. Deliberately smaller than
#: :data:`_CANDIDATES` and :data:`_QUERY_TERMS`: the sweep only has to notice which chapter
#: a window points at, and it runs once per window over the whole document.
_SWEEP_CANDIDATES: Final = 60
_SWEEP_TERMS: Final = 6

#: Chapters a document sweep will score in full. A few dozen windows nominate hundreds of
#: chapters, almost all on one coincidental word; scoring them all costs minutes and finds
#: nothing. Raise it if a long document is losing quotations.
_SCAN_CHAPTERS: Final = 40

#: A word appearing in more than this share of the indexed texts is dropped from a query.
#: It cannot narrow the search, and asking for it is what makes a query slow.
_COMMON_SHARE: Final = 0.02

#: Two passages scoring within this of each other, over the same words, are rivals rather
#: than a winner and a duplicate.
_TIE: Final = 0.06

#: Words of the *searched text* that may fall between two agreements and still count as one
#: quotation. Wide enough for a clause the speaker interpolated, narrow enough that a
#: coincidental word half a paragraph later does not extend the span to meet it.
_SPAN_GAP: Final = 8

#: Words of the *verse* that may be skipped between two agreements. Much tighter than
#: :data:`_SPAN_GAP`, and asymmetric on purpose.
#:
#: A quotation and the verse it quotes advance together. A speaker interpolating a clause of
#: his own moves the text on while the verse stands still, which is what the wider gap above
#: is for; but the reverse -- the verse leaping several words ahead while the text has not
#: moved at all -- is not a quotation continuing. It is a different part of the verse
#: coincidentally agreeing with a different part of the text.
#:
#: Without this bound, *In the beginning was the Word. And God so loved the world...* was
#: reported as one quotation of John 1:1 running to "so loved the": the single words *God*
#: and *the*, which sit at positions 11 and 13 of John 1:1, were absorbed while the text had
#: already moved into John 3:16. Their verse-side gaps are 4 and 2; John 3:16's own closing
#: *Son*, separated from *only* by the verse's *begotten*, has a gap of 1.
_VERSE_GAP: Final = 2

#: The hard caps a *concave-cost* chain may reach, wider than the walls above because the
#: cost function is what holds the discipline: a long gap must be paid for, and past these
#: bounds no anchor could pay. The 4:1 asymmetry of the walls is kept -- see
#: :data:`_VERSE_COST`.
_SPAN_CAP: Final = 24
_VERSE_CAP: Final = 6

#: minimap2's concave gap cost, `0.01·w̄·|l| + 0.5·log₂(|l|+1)`: one long interpolated
#: clause costs far less per word than the same slack scattered across the span, which is
#: how fathers actually interrupt a quotation -- a clause of their own, then the verse
#: resumes. The linear term is scaled by the mean anchor weight so the cost speaks the
#: same unit the anchors earn in.
_GAP_LINEAR: Final = 0.01
_GAP_LOG: Final = 0.5

#: Verse-side slack costs four times text-side slack, the same asymmetric doctrine as the
#: 8/2 walls and for the same reason: a speaker interpolating moves the text on while the
#: verse stands still, but the verse leaping ahead of a stationary text is not a quotation
#: continuing -- it is a different part of the verse coincidentally agreeing.
_VERSE_COST: Final = 4.0

#: Disjoint chains reported per cluster before stopping. One sentence of 1 Clement weaves
#: five sayings; nobody weaves ten.
_MAX_CHAINS: Final = 6

#: Words a match must share consecutively with the text it claims to quote. Measured over
#: this corpus: formulaic sermon language aligns with a longest run of at most five, while
#: genuine quotations of the same length run nine and fourteen. See :func:`longest_run`.
_MIN_RUN: Final = 6


@dataclass(frozen=True, slots=True)
class ScaledRun:
    """A ``min_run`` proportional to the query's length, with a floor.

    Three words out of four is evidence; three out of forty is not. Measured on short
    Greek quotations, making the gate proportional took the four-to-six word band from 9%
    found to 72%, so this is the shape worth using rather than a fixed count -- and a
    *fixed* count is not an approximation of it, being looser than ``ScaledRun(4)`` for
    every query over eight words.

    A class rather than the ``lambda n: max(4, min(6, n // 2))`` the docstrings show,
    because a closure cannot be pickled and this has to cross a process boundary: the
    server's batch scan runs in worker processes, and the calibrated configuration was
    exactly the one it could not accept.
    """

    floor: int
    ceiling: int = _MIN_RUN

    def __post_init__(self) -> None:
        if self.floor < 1:
            raise ValueError(f"a run floor must be at least 1, not {self.floor}")

    def __call__(self, words: int) -> int:
        return max(self.floor, min(self.ceiling, words // 2))


#: Words below which a search is refused before scoring happens. At two words everything
#: matches something. Four is a safe default for English and is a parameter because it is
#: not one everywhere: a three-word Greek quotation can be perfectly distinctive, and this
#: floor alone accounted for every miss in the one-to-three word band of a patristic corpus.
_MIN_QUERY: Final = 4

#: Shorter than this and a run of words is not attributable. *God is love* is genuinely
#: 1 John 4:8, but three words appear across enough of the corpus, and enough of ordinary
#: religious speech, that calling them a quotation would be a guess.
_MIN_QUOTE_WORDS: Final = 5

#: Verses of a candidate run tried as starting points for the passage, and the longest
#: passage that will be assembled. Nobody quotes forty consecutive verses aloud, and the
#: cap stops a runaway extension walking a whole chapter.
_MAX_SEEDS: Final = 8
_MAX_PASSAGE: Final = 20

_WORD_RE: Final = re.compile(r"[^\W_]+", re.UNICODE)

#: The books whose first and last verses are a letter's frame -- salutation and farewell
#: blessing -- for :attr:`Match.positional_candidate`. The twenty-one epistles, and
#: Revelation, which is no epistle but opens and closes as one: χάρις ὑμῖν καὶ εἰρήνη at
#: 1:4 and a farewell grace at 22:21 are the very registers the flag exists to mark.
_EPISTLES: Final = frozenset(
    "ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT "
    "PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split()
)

#: How far into a letter its address runs, and how far back its farewell, in verses.
#: Measured rather than chosen: the consumer read all eight of their salutation findings
#: and the strict first-and-last rule missed three of them -- 2 Thessalonians 1:2 and
#: Philemon 1:3 sit past the first verse, and Ephesians' closing grace at 6:23 stands one
#: verse before the true last. Three and two catch all eight and nothing further in.
_OPENING: Final = 3
_CLOSING: Final = 2


def _tokens(text: str, language: str | None = None) -> list[str]:
    return _WORD_RE.findall(fold(text, language))


def _matcher(left: Sequence[str], right: Sequence[str]) -> SequenceMatcher[str]:
    # autojunk=False because difflib otherwise treats any element occurring in more than
    # 1% of a sequence of 200 or more as noise and drops it. A scan window is that long,
    # and the elements it would discard are "the", "and", "of" -- the connective tissue
    # that tells a quotation from a bag of shared vocabulary.
    return SequenceMatcher(None, left, right, autojunk=False)


def _ratio(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    return _matcher(left, right).ratio()


def _coverage(query: Sequence[str], passage: Sequence[str], *, min_block: int = 1) -> float:
    """What share of the *query* the passage accounts for.

    Asymmetric, and insensitive to how long the passage is. It answers "is what was written
    taken from this verse", where :func:`_ratio` answers "how alike are these two texts" --
    which is the right question for naming a translation and the wrong one for finding a
    quotation.

    The difference is not marginal. ``ratio`` is ``2 * matched / (len(query) + len(passage))``,
    so a short exact quotation of a long verse is capped by the verse's length however
    perfect it is: *he gave his only begotten Son* against John 3:16 scores 0.44 and is
    refused at :data:`QUOTATION`, while every word of it is present. Preachers quote whole
    verses and the ratio suits them; patristic prose quotes a clause and argues from it, and
    on 4,549 hand-marked Greek quotations the ratio finds 27% of them against this measure's
    62%.

    :param min_block: Ignore agreements shorter than this. At the default of 1 every
        matching word counts, which is what the quotation gate wants. Growth wants 2 -- see
        :data:`_GROWTH_BLOCK`.
    """
    if not query or not passage:
        return 0.0
    matcher = _matcher(query, passage)
    return sum(
        block.size for block in matcher.get_matching_blocks() if block.size >= min_block
    ) / len(query)


#: Agreements shorter than this do not justify extending a passage.
#:
#: Coverage cannot fall as a passage grows, so growth is decided on whether it *rises* --
#: and against a scan window, which carries the speaker's own prose as well as the
#: quotation, it rises for the wrong reason. Adding John 3:17 to John 3:16 picks up "him",
#: "the world" and "for God" from the surrounding sentence and coverage climbs from 0.543
#: to 0.587, so every quotation grew into its neighbour.
#:
#: Requiring two consecutive words separates the two cases exactly: a quotation genuinely
#: continuing into the next verse brings a run of words with it, while a neighbour that
#: merely shares vocabulary brings scattered singletons. Measured on the fixtures, the
#: John 3:16 window stops growing and a short quotation spanning Psalm 23:1-2 still grows.
_GROWTH_BLOCK: Final = 2


def longest_run(left: Sequence[str], right: Sequence[str]) -> int:
    """The longest stretch of words the two share consecutively.

    This is what separates a quotation from a coincidence, and it does so where the
    similarity ratio cannot. *Now brothers and sisters I want you* aligns with
    1 Corinthians 12:1 at a respectable 64%, because Paul opens a chapter that way and so
    does every preacher who has ever read him -- but it does so as three scattered
    fragments, the longest five words. A real quotation of the same length runs nine or
    fourteen words unbroken.

    Summed rarity was the obvious alternative and it does not work: measured over this
    corpus, formulaic religious speech carries 10 to 26 nats and genuine quotations 14 to
    32, which overlap almost completely. Contiguity separates them cleanly.
    """
    if not left or not right:
        return 0
    return max((block.size for block in _matcher(left, right).get_matching_blocks()), default=0)


#: One reading per position: the dictionary forms a word could belong to. Empty where the
#: lexicon has never heard of it.
Reading = frozenset[str]


@dataclass(frozen=True, slots=True)
class LemmaRun:
    """The longest stretch of words two passages share *as dictionary forms*."""

    length: int
    """Words in the run. The lemma counterpart of :func:`longest_run`."""
    bits: float
    """How surprising that run is, summed over its words, against the frequencies of the
    language it is in."""
    lemmas: tuple[str, ...]
    """The forms it ran on, in order, one per position."""

    @classmethod
    def none(cls) -> LemmaRun:
        return cls(0, 0.0, ())


def lemma_run(
    left: Sequence[Reading], right: Sequence[Reading], bits: Callable[[str], float]
) -> LemmaRun:
    """The longest run of positions whose readings intersect, and what it is worth.

    Exactly what :func:`longest_run` measures, one level of abstraction up, and for the same
    reason. Ignatius shares eleven words with Matthew 10:16 and not two of them in a row are
    spelled alike; as dictionary forms they run three deep. What makes the rule safe is that
    it is still a *run*: the two words a father shares with Acts 6:3 are `ἀνήρ` and
    `μαρτυρέω`, correctly paired and separated in the verse by `ἐξ ὑμῶν`, so they run one --
    and no scholar accepts that as a quotation either.

    Bits are carried because length alone cannot tell `ὡς ὁ` from `φρόνιμος ὄφις`. They do
    not replace the run: summed rarity was tried here before and overlaps almost completely
    between formula and quotation (see :func:`longest_run`). It is the pair that discriminates.

    Where a position has several readings the **least** surprising shared one is counted.
    That was the other way round to begin with, on the reasoning that an accidental collision
    is likeliest on the commonest reading and a real quotation on the rarest -- which is
    exactly backwards for the words that recur. The commonest preposition in Greek, `διά`,
    has no correct reading in this lexicon at all: it offers `Ζεύς` and `Διός`, and taking
    the rarer scored a preposition at 4.6 bits every time it occurred. The conservative
    reading cannot inflate, and a word that is genuinely rare has no common reading to fall
    back to, so nothing real is lost.
    """
    best = LemmaRun.none()
    for start in range(len(left)):
        for origin in range(len(right)):
            total, run, length = 0.0, [], 0
            while start + length < len(left) and origin + length < len(right):
                shared = left[start + length] & right[origin + length]
                if not shared:
                    break
                # The *least* surprising shared reading, not the most. This was the other
                # way round on the reasoning that "an accidental collision is likeliest on
                # the commonest reading and a real quotation on the rarest", which is
                # exactly backwards for the words that recur. `διά` -- the commonest
                # preposition in Greek -- carries no correct reading in the lexicon at all:
                # its two are `Ζεύς` and `Διός`, and taking the rarer scored the preposition
                # at 4.6 bits every time it appeared. Reading a rare word into a common one
                # is how a chain of function words came to outscore a real quotation.
                pick = min(shared, key=bits)
                total += bits(pick)
                run.append(pick)
                length += 1
            if (length, total) > (best.length, best.bits):
                best = LemmaRun(length, total, tuple(run))
    return best


@dataclass(frozen=True, slots=True)
class LemmaChain:
    """What two passages share *in the verse's own order*, gaps allowed.

    The measure a run cannot be. Ignatius reuses eleven of Matthew's words in Matthew's order
    and interrupts them constantly with his own, so his longest unbroken agreement is three
    and his chain is nine. Aristotle, writing about respiration three centuries earlier,
    brushes a verse twice and his chain is two. Contiguity cannot tell those apart -- both are
    short runs -- and 256,432 false positives in three million words of control text is what
    that cost when the run was the only gate.

    The gaps are bounded, by the same asymmetric doctrine as :func:`_continues`: a quotation
    and its verse advance together, and without a bound on the verse side a chain would stitch
    a whole window together out of agreements scattered across a chapter.
    """

    length: int
    """Positions shared, in order. Never less than the longest run, since a run is a chain
    with no gaps in it."""
    bits: float
    """Surprisal of those positions, summed."""
    lemmas: tuple[str, ...]
    """The dictionary forms, in the order they were used."""
    span: tuple[int, int]
    """First and last position of the chain in the *searched text*, half-open.

    This is the quotation's own extent, and it is why the chain is worth computing rather
    than merely counting: the weight of a match can be taken over what actually matched
    instead of over whatever window the sweep happened to slice. A score that depends on
    how a document was cut into windows is not a score of the quotation.
    """

    @classmethod
    def none(cls) -> LemmaChain:
        return cls(0, 0.0, (), (0, 0))


def lemma_chain(
    left: Sequence[Reading],
    right: Sequence[Reading],
    bits: Callable[[str], float],
    *,
    span_gap: int = _SPAN_GAP,
    verse_gap: int = _VERSE_GAP,
    concave: bool = False,
) -> LemmaChain:
    """The longest order-preserving agreement between a text and a verse, and its extent.

    A longest-common-subsequence over readings, where two positions agree if their sets of
    dictionary forms intersect at all, and where a step may skip at most ``span_gap`` words
    of the text and ``verse_gap`` of the verse. Ties are broken on bits, so where two chains
    are the same length the more surprising one is the one reported.

    With ``concave``, the hard walls become a cost function: a step may skip up to
    :data:`_SPAN_CAP` and :data:`_VERSE_CAP` words, but every word of slack is paid for
    out of the anchors' own bits, concavely, so one long interpolated clause is cheap and
    the same slack scattered is not. What is reported does not change its meaning --
    ``length`` is still positions shared and ``bits`` their surprisal -- only *which*
    chain is judged best. The exhaustive DP is the optimal chaining the literature asks
    for: at these window sizes nothing needs the O(n log n) machinery, and every pair
    within the caps is considered, so the maximum is the maximum.
    """
    if concave:
        return _concave_chain(left, right, bits)
    if not left or not right:
        return LemmaChain.none()

    # best[i][j] is the chain starting at exactly (i, j), which is what makes the gap bounds
    # expressible: a step is a jump forward within the two windows, not to anywhere later.
    best: list[list[tuple[int, float, int]]] = [
        [(0, 0.0, -1) for _ in range(len(right) + 1)] for _ in range(len(left) + 1)
    ]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            shared = left[i] & right[j]
            if not shared:
                continue
            weight = bits(min(shared, key=bits))
            length, total, end = 1, weight, i + 1
            for di in range(1, span_gap + 2):
                for dj in range(1, verse_gap + 2):
                    if i + di > len(left) - 1 or j + dj > len(right) - 1:
                        continue
                    ahead = best[i + di][j + dj]
                    if ahead[0] and (ahead[0] + 1, ahead[1] + weight) > (length, total):
                        length, total, end = ahead[0] + 1, ahead[1] + weight, ahead[2]
            best[i][j] = (length, total, end)

    start = max(
        ((cell[0], cell[1], i, cell[2]) for i, row in enumerate(best) for cell in row if cell[0]),
        default=None,
    )
    if start is None:
        return LemmaChain.none()
    length, total, first, last = start
    return LemmaChain(length, total, _chain_lemmas(left, right, bits, first, last), (first, last))


def _gap_cost(gap: int, anchor: float) -> float:
    """What a step over ``gap`` words of slack costs, in bits, concavely."""
    if gap <= 0:
        return 0.0
    return _GAP_LINEAR * anchor * gap + _GAP_LOG * math.log2(gap + 1)


def _concave_chain(
    left: Sequence[Reading],
    right: Sequence[Reading],
    bits: Callable[[str], float],
) -> LemmaChain:
    """The concave-cost arm of :func:`lemma_chain`: gaps paid for, not walled off.

    A link is taken only when what lies ahead is worth more than the slack costs -- so a
    chain never grows by stitching in a distant coincidence, however far the caps would
    let it look. That single rule is what replaces the walls.
    """
    if not left or not right:
        return LemmaChain.none()
    weights: dict[tuple[int, int], float] = {}
    for i, mine in enumerate(left):
        for j, theirs in enumerate(right):
            shared = mine & theirs
            if shared:
                weights[(i, j)] = bits(min(shared, key=bits))
    if not weights:
        return LemmaChain.none()
    anchor = sum(weights.values()) / len(weights)

    # best[(i, j)] is the chain starting at exactly (i, j): score after gap costs, then
    # length, then bits, then one past its final text position. Compared as a tuple, so
    # equal scores fall back to the classic length-then-bits order.
    best: dict[tuple[int, int], tuple[float, int, float, int]] = {}
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            weight = weights.get((i, j))
            if weight is None:
                continue
            cell = (weight, 1, weight, i + 1)
            for di in range(1, _SPAN_CAP + 2):
                if i + di > len(left) - 1:
                    break
                for dj in range(1, _VERSE_CAP + 2):
                    if j + dj > len(right) - 1:
                        break
                    ahead = best.get((i + di, j + dj))
                    if ahead is None:
                        continue
                    cost = _gap_cost(di - 1, anchor) + _VERSE_COST * _gap_cost(dj - 1, anchor)
                    if ahead[0] <= cost:
                        # The link cannot pay for its own slack: whatever lies there is
                        # a coincidence, not the quotation continuing.
                        continue
                    linked = (weight + ahead[0] - cost, 1 + ahead[1], weight + ahead[2], ahead[3])
                    if linked > cell:
                        cell = linked
            best[(i, j)] = cell

    (_, length, total, last), first = max(
        ((cell, i) for (i, _), cell in best.items()), key=lambda pair: (pair[0], -pair[1])
    )
    return LemmaChain(length, total, _chain_lemmas(left, right, bits, first, last), (first, last))


def lemma_chains(
    left: Sequence[Reading],
    right: Sequence[Reading],
    bits: Callable[[str], float],
    *,
    span_gap: int = _SPAN_GAP,
    verse_gap: int = _VERSE_GAP,
    concave: bool = False,
    most: int = _MAX_CHAINS,
) -> list[LemmaChain]:
    """Every disjoint chain worth reporting, best first.

    BLAST's answer to the conflation problem: take the best chain, mask its extent, and
    chain what remains, until nothing chains. One sentence of 1 Clement 13:2 weaves five
    sayings; a single best chain reports one of them and structurally misses four,
    however good its gates. Each chain returned here covers a different stretch of the
    text, carries its own evidence, and is gated by the caller on that evidence alone.
    """
    remaining = list(left)
    out: list[LemmaChain] = []
    while len(out) < most:
        chained = lemma_chain(
            remaining, right, bits, span_gap=span_gap, verse_gap=verse_gap, concave=concave
        )
        if not chained.length:
            break
        out.append(chained)
        first, last = chained.span
        for position in range(first, last):
            remaining[position] = frozenset()
    return out


def _chain_lemmas(
    left: Sequence[Reading],
    right: Sequence[Reading],
    bits: Callable[[str], float],
    first: int,
    last: int,
) -> tuple[str, ...]:
    """The dictionary forms the chain ran on, in order, read back off its span."""
    theirs: set[str] = set().union(*right) if right else set()
    out: list[str] = []
    for reading in left[first:last]:
        shared = reading & theirs
        if shared:
            out.append(min(shared, key=bits))
    return tuple(out)


def shared_bits(
    left: Sequence[Reading], right: Sequence[Reading], bits: Callable[[str], float]
) -> float:
    """How much surprisal the two share in total, wherever it falls.

    The run says the shared words are in the same order and next to each other; this says
    they are worth something. Both are needed and neither will do alone. Ignatius at Matthew
    10:16 runs only three deep -- `ὡς ὁ περιστερά`, two of them function words -- but carries
    57 bits across eleven positions, because `φρόνιμος`, `ὄφις`, `ἀκέραιος` and `περιστερά`
    cannot co-occur by accident. Gating on the run's own bits would refuse it while admitting
    `εἰς Θεὸν`, which is two of the commonest words in Christian Greek standing next to each
    other, and that is precisely the wrong way round.
    """
    theirs: set[str] = set().union(*right) if right else set()
    total = 0.0
    for reading in left:
        shared = reading & theirs
        if shared:
            total += bits(min(shared, key=bits))
    return total


def shared_lemmas(left: Sequence[Reading], right: Sequence[Reading]) -> tuple[str, ...]:
    """Every dictionary form the two have in common, rarest reading first per position.

    The evidence, rather than the verdict. The people who asked for this said they would
    rather weigh it themselves than be handed a judgement, and a caller who disagrees with
    the gates can re-decide from these.
    """
    theirs: set[str] = set().union(*right) if right else set()
    out: list[str] = []
    for reading in left:
        out.extend(sorted(reading & theirs))
    return tuple(dict.fromkeys(out))


# -- building ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexResult:
    """What one indexing run did."""

    corpora: tuple[tuple[str, int], ...]
    """``(corpus id, verses indexed)``."""
    texts: int
    """Distinct texts in the index afterwards."""

    @property
    def verses(self) -> int:
        return sum(count for _, count in self.corpora)


Reporter = Callable[[str], None]


def _silent(_: str) -> None:
    return None


def build_index(
    home: DataHome,
    *,
    corpora: Sequence[str] | None = None,
    report: Reporter = _silent,
) -> IndexResult:
    """Index the verse store for search.

    Derived data throughout: dropping the search tables and running this again costs
    nothing but time, and no network.

    :param corpora: Just these, by id. Defaults to every corpus in the store.
    """
    with open_store(home) as connection:
        wanted = _corpora_to_index(connection, corpora)
        done: list[tuple[str, int]] = []
        for corpus, language in wanted:
            count = _index_corpus(connection, corpus, language, report)
            done.append((corpus, count))
        recount_df(connection, report)
        texts = int(connection.execute("SELECT COUNT(*) FROM search_text").fetchone()[0])
    return IndexResult(tuple(done), texts)


def _corpora_to_index(
    connection: sqlite3.Connection, corpora: Sequence[str] | None
) -> list[tuple[str, str]]:
    rows = connection.execute("SELECT corpus, language FROM source_meta ORDER BY corpus")
    found = [(str(corpus), str(language)) for corpus, language in rows]
    if corpora is None:
        return found
    chosen = set(corpora)
    missing = chosen - {corpus for corpus, _ in found}
    if missing:
        raise KeyError(f"not in the store: {', '.join(sorted(missing))}")
    return [pair for pair in found if pair[0] in chosen]


def _index_corpus(
    connection: sqlite3.Connection, corpus: str, language: str, report: Reporter
) -> int:
    """Fold and index one corpus, replacing whatever was indexed for it before."""
    connection.execute("DELETE FROM search_ref WHERE corpus = ?", (corpus,))

    rows = connection.execute(
        "SELECT book, chapter, verse, subverse, text FROM verse WHERE corpus = ?", (corpus,)
    ).fetchall()

    count = 0
    for book, chapter, verse, subverse, text in rows:
        folded = fold(text, language)
        if not folded:
            continue
        digest = hashlib.sha1(folded.encode("utf-8")).digest()
        text_id = _text_id(connection, digest, folded)
        connection.execute(
            "INSERT OR REPLACE INTO search_ref "
            "(corpus, book, chapter, verse, subverse, text_id) VALUES (?, ?, ?, ?, ?, ?)",
            (corpus, book, chapter, verse, subverse, text_id),
        )
        count += 1

    connection.execute(
        "INSERT OR REPLACE INTO search_state "
        "(corpus, indexed_at, verses, source_verses, fold_version) VALUES (?, ?, ?, ?, ?)",
        (
            corpus,
            datetime.now(UTC).isoformat(timespec="seconds"),
            count,
            len(rows),
            FOLD_VERSION,
        ),
        # `count` and `len(rows)` differ where a verse folds away to nothing -- a line of
        # editorial sigla, a verse of pure punctuation. Both are recorded because only
        # `len(rows)` can be compared with the store to ask whether this is out of date.
    )
    report(f"search: indexed {corpus} ({count:,} verses)")
    return count


def _text_id(connection: sqlite3.Connection, digest: bytes, folded: str) -> int:
    """The id of this exact text, inserting it into the index the first time it is seen."""
    row = connection.execute("SELECT id FROM search_text WHERE hash = ?", (digest,)).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute("INSERT INTO search_text (hash) VALUES (?)", (digest,))
    text_id = int(cursor.lastrowid or 0)
    connection.execute("INSERT INTO search_fts (rowid, text) VALUES (?, ?)", (text_id, folded))
    return text_id


def prune_texts(connection: sqlite3.Connection, report: Reporter = _silent) -> int:
    """Drop indexed texts no verse points at any more, and say how many.

    A reindex rewrites ``search_ref`` but only ever *adds* to ``search_text``, so every
    text a corpus used to have and no longer does stayed behind: 14,087 of them by the
    time anyone looked, and 1,111 in the lemma index. They are unreachable through
    ``search_ref`` and so cannot be returned -- but :func:`recount_df` counts every row of
    ``search_fts``, which means the ghosts were inflating document frequency, and document
    frequency is what BM25 ranks on and what :attr:`Match.bits` is measured against. A
    superseded rendering of a verse was quietly making its own words look commoner.

    Safe whichever corpora were rebuilt: a text is only dropped when *no* verse of *any*
    corpus references it.
    """
    orphans = [
        int(row[0])
        for row in connection.execute(
            "SELECT id FROM search_text WHERE id NOT IN (SELECT text_id FROM search_ref)"
        )
    ]
    if orphans:
        connection.executemany("DELETE FROM search_fts WHERE rowid = ?", [(i,) for i in orphans])
        connection.executemany("DELETE FROM search_text WHERE id = ?", [(i,) for i in orphans])
        report(f"search: dropped {len(orphans):,} text(s) no verse points at")
    return len(orphans)


def recount_df(connection: sqlite3.Connection, report: Reporter = _silent) -> None:
    """Recount how many distinct texts each word appears in.

    Counted over whole texts rather than whole verses on purpose: a sentence carried
    identically by twenty translations is one piece of evidence about how common its words
    are, not twenty.

    Orphans are dropped first, or the count includes texts nothing can return.
    """
    prune_texts(connection, report)
    connection.execute("DELETE FROM search_df")
    counts: dict[str, int] = {}
    for (text,) in connection.execute("SELECT text FROM search_fts"):
        for token in set(_WORD_RE.findall(text)):
            counts[token] = counts.get(token, 0) + 1
    connection.executemany(
        "INSERT INTO search_df (token, docs) VALUES (?, ?)", sorted(counts.items())
    )
    report(f"search: {len(counts):,} distinct words")


# --------------------------------------------------------------------------------------
# The second index: the same verses keyed by dictionary form
#
# Everything below writes only to the `lemma_*` tables. Nothing here touches `search_fts`,
# `search_df`, `search_ref`, `search_text` or `search_state`, and that separation is the
# whole guarantee: half a million findings downstream rest on what the exact-form index
# returns, and a document frequency shifted by a lemma would move every score ever computed.
# --------------------------------------------------------------------------------------

#: Languages a lemma index is built for. English is excluded deliberately rather than for
#: want of a lexicon: it barely inflects, the Porter stemmer already covers what it does,
#: and folding it in could only move results that half a million findings depend on.
LEMMA_LANGUAGES: Final = ("grc", "la")


#: How a match was arrived at, strongest evidence first.
#:
#: These grade the *evidence*, not the quotation. An editor calls Ignatius at Matthew 10:16
#: a direct quotation and is right; this calls it :data:`INDIRECT` and is also right, because
#: his longest identically spelled run is one word. A caller wanting the old behaviour asks
#: for :data:`DIRECT` and gets exactly it.
DIRECT: Final = "direct"
"""A run of identically spelled words at least ``min_run`` long: today's rule, unchanged."""
PARTIAL: Final = "partial"
"""Identically spelled, but a shorter run than ``min_run`` asks for, and surprising enough
to be worth reporting. Ignatius' three verbatim words of Philippians 2:3 are refused today
for being short rather than for being different."""
INDIRECT: Final = "indirect"
"""The same words in different grammatical clothes: a run of shared dictionary forms, with
no identically spelled run long enough to have found it."""

#: Weakest first, so ``GRADES.index`` orders them and ``min_grade`` can be compared.
GRADES: Final = (INDIRECT, PARTIAL, DIRECT)


@dataclass(frozen=True, slots=True)
class Gate:
    """What a graded match must reach on at least one of three axes to be admitted.

    Three axes because they measure different things and no one of them will do:

    * ``run`` -- identically *spelled* words, unbroken. What the exact matcher has always used.
    * ``lemma_run`` -- shared dictionary forms, unbroken. The axis the first release gated on
      and the one the consumer's own map of false positives is drawn in.
    * ``chain`` -- shared dictionary forms in the verse's order, gaps allowed. This is what
      finds a quotation whose grammar has been rewritten, and what no run can see: Ignatius
      at Matthew 10:16 runs three and chains nine, Aristotle at Luke 4:14 runs two and chains
      two.
    * ``bits`` -- surprisal of everything shared. Two common words are not evidence however
      neatly they are arranged.

    A gate is a conjunction: every axis it names must be met. A :class:`Searcher` holds
    several and admits a match that satisfies **any** of them, because they are complementary
    rather than nested -- over 150,000 words the consumer measured, a run gate contributed 20
    findings a chain gate missed and the chain gate contributed 734 the run gate missed.
    """

    run: int = 0
    lemma_run: int = 0
    chain: int = 0
    bits: float = 0.0

    def admits(self, run: int, lemma_run: int, chain: int, bits: float) -> bool:
        return (
            run >= self.run
            and lemma_run >= self.lemma_run
            and chain >= self.chain
            and bits >= self.bits
        )

    def __str__(self) -> str:
        named = [
            f"{name}>={value:g}"
            for name, value in (
                ("run", self.run),
                ("lemma_run", self.lemma_run),
                ("chain", self.chain),
                ("bits", self.bits),
            )
            if value
        ]
        return " ".join(named) or "anything"

    @classmethod
    def parse(cls, text: str) -> Gate:
        """``"0:4:0:40"`` -- run, lemma_run, chain, bits -- as the command line spells it."""
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError(f"a gate is run:lemma_run:chain:bits, not {text!r}")
        return cls(int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3]))


#: What a graded match must reach by default: a union, because quotations come in shapes no
#: single gate covers, and because the three axes are complementary rather than nested.
#:
#: Measured over 40,103 words of Greek by authors who died before there was a New Testament,
#: where every match is false by construction:
#:
#: ===========================  ==================
#: gate                          false / 1,000
#: ===========================  ==================
#: ``lemma_run>=2 bits>=60``     0.0000
#: ``lemma_run>=4 bits>=40``     0.0000
#: ``lemma_run>=5 bits>=35``     0.0000
#: ``chain>=8 bits>=40``         0.0000
#: ``chain>=4 bits>=50``         0.0249
#: ``chain>=5 bits>=40``         0.0748
#: ``chain>=6 bits>=35``         0.1247
#: ``run>=3 bits>=20``           0.3491
#: ===========================  ==================
#:
#: The first three are the consumer's own recommendation and they are kept. The fourth is
#: the addition, and it is the one that matters: Ignatius quoting Matthew 10:16 -- the case
#: this whole feature was asked for -- chains nine at 57.6 bits and is admitted by nothing
#: else here. A low chain is *not* safe, whatever its bits: at chain 4, 5 and 6 the rate
#: climbs steeply, because order over a handful of words is cheap to come by. Eight is where
#: it stops being cheap.
#:
#: One caveat on the zeros, and it is the honest reading: 40,103 words can bound a rate at
#: 0.025 per thousand and no finer. The consumer measured their own union at 0.0187 over
#: three million words, which this sample cannot tell from zero. `tools/calibrate_inflected.py
#: --control` is what they should point at their full corpus.
DEFAULT_GATES: Final = (
    Gate(chain=8, bits=40.0),
    Gate(lemma_run=4, bits=40.0),
    Gate(lemma_run=5, bits=35.0),
    Gate(lemma_run=2, bits=60.0),
)


#: Shortest identically spelled run that may be graded :data:`PARTIAL`.
#:
#: Three, on the evidence of the case that argued for two. `εἰς θεὸν μετανοεῖν` against
#: `τὴν εἰς Θεὸν μετάνοιαν` shares `εἰς θεόν` exactly, and the editor who published it as a
#: quotation did not believe it was one: *repentance toward God* is the common property of
#: the whole New Testament. Two words is a phrase. Ignatius' three verbatim words of
#: Philippians 2:3 are the shortest thing here anyone defends as a quotation, so three is
#: where the floor goes.
_MIN_PARTIAL_RUN: Final = 3


def build_lemma_index(
    home: DataHome,
    *,
    corpora: Sequence[str] | None = None,
    report: Reporter = _silent,
) -> IndexResult:
    """Index the Greek and Latin verses by lemma. Derived data; drop and rebuild freely.

    Separate from :func:`build_index` rather than a flag on it, because the two must be able
    to run without each other: rebuilding this must never be a reason to rebuild that, and
    the promise that the exact-form index does not move is easier to keep when no code path
    can move both.
    """
    from .lemmata import Lexicon

    with open_store(home) as connection:
        # Reading the lexicon through the writer's own connection: a second one would be
        # locked out for the whole build.
        lexicon = Lexicon(home, connection)
        rows = connection.execute(
            "SELECT corpus, language FROM source_meta "
            f"WHERE language IN ({', '.join('?' * len(LEMMA_LANGUAGES))}) ORDER BY corpus",
            LEMMA_LANGUAGES,
        ).fetchall()
        wanted = [
            (str(corpus), str(language))
            for corpus, language in rows
            if corpora is None or corpus in set(corpora)
        ]
        for language in sorted({language for _, language in wanted}):
            lexicon.require(language)

        done: list[tuple[str, int]] = []
        for corpus, language in wanted:
            done.append((corpus, _index_lemmas(connection, corpus, language, lexicon, report)))
        recount_lemma_df(connection, report)
        texts = int(connection.execute("SELECT COUNT(*) FROM lemma_text").fetchone()[0])
    return IndexResult(tuple(done), texts)


def _index_lemmas(
    connection: sqlite3.Connection,
    corpus: str,
    language: str,
    lexicon: Lexicon,
    report: Reporter,
) -> int:
    """Fold one corpus into the lemma index, replacing whatever was there for it before."""
    connection.execute("DELETE FROM lemma_ref WHERE corpus = ?", (corpus,))

    rows = connection.execute(
        "SELECT book, chapter, verse, subverse, text FROM verse WHERE corpus = ?", (corpus,)
    ).fetchall()

    count = 0
    for book, chapter, verse, subverse, text in rows:
        written = _lemma_text(_tokens(text, language), language, lexicon)
        if not written:
            continue
        digest = hashlib.sha1(written.encode("utf-8")).digest()
        text_id = _lemma_text_id(connection, digest, written)
        connection.execute(
            "INSERT OR REPLACE INTO lemma_ref "
            "(corpus, book, chapter, verse, subverse, text_id) VALUES (?, ?, ?, ?, ?, ?)",
            (corpus, book, chapter, verse, subverse, text_id),
        )
        count += 1

    connection.execute(
        "INSERT OR REPLACE INTO lemma_state "
        "(corpus, indexed_at, verses, source_verses, fold_version) VALUES (?, ?, ?, ?, ?)",
        (
            corpus,
            datetime.now(UTC).isoformat(timespec="seconds"),
            count,
            len(rows),
            FOLD_VERSION,
        ),
    )
    report(f"lemmata: indexed {corpus} ({count:,} verses)")
    return count


def _lemma_text(tokens: Sequence[str], language: str, lexicon: Lexicon) -> str:
    """One verse as a bag of readings, for FTS to find candidates in.

    A word the lexicon does not know keeps its own spelling. That is not a fallback so much
    as the truth: an unanalysed word is its own best guess at its dictionary form, and
    dropping it would make proper names -- which are exactly the rare, distinctive words a
    quotation is found by -- invisible to this index.
    """
    known = lexicon.of(list(dict.fromkeys(tokens)), language)
    out: list[str] = []
    for token in tokens:
        out.extend(sorted(known.get(token) or {token}))
    return " ".join(out)


def _lemma_text_id(connection: sqlite3.Connection, digest: bytes, written: str) -> int:
    row = connection.execute("SELECT id FROM lemma_text WHERE hash = ?", (digest,)).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute("INSERT INTO lemma_text (hash) VALUES (?)", (digest,))
    text_id = int(cursor.lastrowid or 0)
    connection.execute("INSERT INTO lemma_fts (rowid, lemmas) VALUES (?, ?)", (text_id, written))
    return text_id


def recount_lemma_df(connection: sqlite3.Connection, report: Reporter = _silent) -> None:
    """Recount how many verses of each language each lemma appears in.

    Per language, and per *verse* rather than per distinct text. Both differ from
    :func:`recount_df` on purpose. Language, because how surprising a word is has to be
    measured against what its author could have written: `θεόσ` diluted by 900,000 English
    verses would read as far rarer than it is. Verses, because unlike the fifty English
    translations that render a sentence identically, the Greek and Latin corpora are
    different texts rather than different renderings of one, and their agreement is
    evidence about the language rather than a duplicate to be collapsed.
    """
    # Orphans here never reached `lemma_df`, which joins through `lemma_ref` and so has
    # always counted only reachable readings -- `bits` was never touched by this. They do
    # still sit in `lemma_fts`, where they spend candidate slots a retrieval could give to
    # a verse that exists, so they go too.
    orphans = [
        int(row[0])
        for row in connection.execute(
            "SELECT id FROM lemma_text WHERE id NOT IN (SELECT text_id FROM lemma_ref)"
        )
    ]
    if orphans:
        connection.executemany("DELETE FROM lemma_fts WHERE rowid = ?", [(i,) for i in orphans])
        connection.executemany("DELETE FROM lemma_text WHERE id = ?", [(i,) for i in orphans])
        report(f"lemmata: dropped {len(orphans):,} reading(s) no verse points at")
    connection.execute("DELETE FROM lemma_df")
    connection.execute("DELETE FROM lemma_total")
    counts: dict[tuple[str, str], int] = {}
    totals: dict[str, int] = {}
    for language, written in connection.execute(
        "SELECT m.language, t.lemmas FROM lemma_ref r "
        "JOIN source_meta m ON m.corpus = r.corpus "
        "JOIN lemma_fts t ON t.rowid = r.text_id"
    ):
        totals[str(language)] = totals.get(str(language), 0) + 1
        for lemma in set(_WORD_RE.findall(str(written))):
            counts[(str(language), lemma)] = counts.get((str(language), lemma), 0) + 1
    connection.executemany(
        "INSERT INTO lemma_df (language, lemma, docs) VALUES (?, ?, ?)",
        sorted((language, lemma, n) for (language, lemma), n in counts.items()),
    )
    connection.executemany(
        "INSERT INTO lemma_total (language, verses) VALUES (?, ?)", sorted(totals.items())
    )
    for language, verses in sorted(totals.items()):
        held = sum(1 for key in counts if key[0] == language)
        report(f"lemmata: {language} {held:,} distinct lemmas over {verses:,} verses")


class LemmaWeights:
    """How surprising each dictionary form is, per language, read once and kept.

    Surprisal against the language's own verses: ``-log2(docs / verses)``. What makes
    `φρόνιμος` evidence and `καί` not is that the first is in 152 Greek verses of 113,062
    and the second in 87,558, and no amount of the second adds up to the first.

    A lemma the index has never seen is treated as maximally surprising rather than as
    unknown. That is the right way round: a word absent from the whole Greek Bible cannot be
    what makes a false match, because a false match is made of words that *are* there.
    """

    def __init__(self, home: DataHome) -> None:
        self.home = home
        self._counts: dict[str, dict[str, int]] = {}
        self._verses: dict[str, int] = {}

    def _load(self, language: str) -> None:
        if language in self._counts:
            return
        counts: dict[str, int] = {}
        verses = 0
        with closing(sqlite3.connect(f"file:{self.home.database}?mode=ro", uri=True)) as db:
            try:
                counts = {
                    str(lemma): int(docs)
                    for lemma, docs in db.execute(
                        "SELECT lemma, docs FROM lemma_df WHERE language = ?", (language,)
                    )
                }
                row = db.execute(
                    "SELECT verses FROM lemma_total WHERE language = ?", (language,)
                ).fetchone()
                verses = int(row[0]) if row else 0
            except sqlite3.OperationalError:  # pragma: no cover - index not built
                counts, verses = {}, 0
        self._counts[language] = counts
        self._verses[language] = verses

    def verses(self, language: str) -> int:
        self._load(language)
        return self._verses[language]

    def bits(self, lemma: str, language: str) -> float:
        self._load(language)
        total = self._verses[language]
        if not total:
            return 0.0
        return math.log2(total / (self._counts[language].get(lemma, 0) + 1))

    def of(self, language: str) -> Callable[[str], float]:
        """A one-argument weigher, for :func:`lemma_run`."""
        self._load(language)
        return lambda lemma: self.bits(lemma, language)


def lemma_readings(tokens: Sequence[str], language: str, lexicon: Lexicon) -> list[Reading]:
    """One reading per token: its dictionary forms, or itself where none is known.

    An unanalysed word standing for itself is not a fallback but the truth of the case: it
    is its own best guess at its dictionary form, and dropping it would make proper names
    invisible -- and those are exactly the rare words a quotation is recognised by.
    """
    known = lexicon.of(list(dict.fromkeys(tokens)), language)
    return [known.get(token) or frozenset({token}) for token in tokens]


#: The itacism classes of `emphasis._ITACISM`, inverted for candidate generation: each
#: character an orthographic fold can produce, with every spelling a scribe writing by
#: ear could have meant by it. Exact by construction -- two spellings are itacism-variants
#: precisely when their orthographic folds agree, so expanding the fold enumerates the
#: whole equivalence class and nothing else.
_ITACISM_PREIMAGES: Final[dict[str, tuple[str, ...]]] = {
    "ι": ("ι", "ει", "οι", "υι", "η", "υ"),
    "ο": ("ο", "ω"),
    "ε": ("ε", "αι"),
}

#: Candidate spellings tried per unknown token before giving up. A long word of many
#: iotas multiplies past any use -- and a token that itacistic is better left unread than
#: matched against half the lexicon.
_MOST_SPELLINGS: Final = 512


def _itacism_spellings(token: str) -> list[str]:
    """Every plain-folded spelling whose orthographic fold is this token's, bounded."""
    collapsed = fold(token, "grc", orthographic=True)
    out = [""]
    for character in collapsed:
        options = _ITACISM_PREIMAGES.get(character, (character,))
        out = [prefix + option for prefix in out for option in options]
        if len(out) > _MOST_SPELLINGS:
            return []
    return [spelling for spelling in out if spelling != token]


def itacised_readings(
    tokens: Sequence[str],
    language: str,
    lexicon: Lexicon,
    plain: Sequence[Reading],
) -> tuple[list[Reading], frozenset[int]]:
    """The plain readings, with unknown spellings re-read through the itacism classes.

    The second tier the design asks for: exact fold first, and only where the lexicon
    declines -- an out-of-vocabulary token -- are the spellings a scribe writing by ear
    could have meant looked up in its place. ὑμεῖς and ἡμεῖς stay distinct wherever the
    text spells them; a spelling the lexicon has never seen is the one place the collapse
    can only add.

    :returns: The readings, and which positions were re-read -- the provenance
        :attr:`Match.itacised` is set from, so the looseness is visible on every match
        that used it.
    """
    out = list(plain)
    marked: list[int] = []
    for index, token in enumerate(tokens):
        if out[index] != frozenset({token}) or lexicon.lemmas(token, language):
            continue
        candidates = _itacism_spellings(token)
        if not candidates:
            continue
        found = lexicon.of(candidates, language)
        lemmas = frozenset().union(*found.values())
        if lemmas:
            out[index] = lemmas
            marked.append(index)
    return out, frozenset(marked)


class IndexIncomplete(UserWarning):
    """Some of the library is built but not folded into the search index.

    A warning rather than an error because the searcher still answers for everything else,
    and a category of its own so a caller running a sweep can turn it into one::

        warnings.simplefilter("error", IndexIncomplete)
    """


@dataclass(frozen=True, slots=True)
class IndexCoverage:
    """What the search index holds for one corpus, against what the store holds."""

    corpus: str
    stored: int
    """Rows this corpus has in ``verse`` -- counted, not read off ``source_meta``.

    The two are not the same number and never were: ``verse_count`` records the verses a
    build *offered*, and references that repeat collapse onto one row on the way in.
    ``castellio`` says 5,273 and holds 5,272; ``brenton`` says 29,004 and holds 28,690.
    Comparing the index against the recorded figure is what reported four corpora as
    permanently stale, and six more the moment they were freshly indexed."""
    indexed: int | None = None
    """Verses that produced a searchable text, or ``None`` where it was never indexed."""
    source_verses: int | None = None
    """What the store held when it was indexed, or ``None`` for an index built before this
    was recorded."""
    fold_version: int | None = None
    """Which :data:`~biblereference.emphasis.FOLD_VERSION` folded this index, or ``None``
    for an index built before it was recorded.

    The index keys on ``sha1(fold(text))``, so a change to the fold silently invalidates
    every entry: the stored token says ``μετʼ`` and the query now says ``μετ``, and the
    two never meet again. Counting verses cannot see that -- the count is identical --
    which is how the elision fix could have shipped and left Greek search quietly
    answering less, with `doctor` reporting every corpus current.
    """

    @property
    def searchable(self) -> bool:
        return self.indexed is not None and self.indexed > 0

    @property
    def state(self) -> str:
        """``missing`` | ``drifted`` | ``unknown`` | ``current``."""
        if self.indexed is None:
            return "missing"
        if self.fold_version is not None and self.fold_version != FOLD_VERSION:
            # Folded by a rule this code no longer applies. Said before the verse counts
            # are consulted, because they will agree and mean nothing.
            return "drifted"
        if self.source_verses is None:
            # Indexed before the store recorded what it indexed *from*. Nothing here can
            # say whether it has drifted, and guessing "stale" would send every existing
            # install off to rebuild a perfectly good index.
            return "unknown"
        return "current" if self.source_verses == self.stored else "drifted"


def index_coverage(home: DataHome) -> list[IndexCoverage]:
    """What the search index holds, corpus by corpus, in store order.

    Opened read-only, so it must cope with a database the migration has not reached yet:
    ``source_verses`` was added after the fact and only a write-mode ``open_store`` creates
    it. Asking for it unconditionally made this swallow an ``OperationalError`` and report
    that *nothing* was searchable, which is a worse answer than the one it replaced.
    """
    if not home.database.exists():
        # Read-only means read-only: SQLite will not conjure the file, and asking what an
        # absent library holds is a fair question with the answer "nothing".
        return []
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(search_state)")}
            source = "s.source_verses" if "source_verses" in columns else "NULL"
            folded = "s.fold_version" if "fold_version" in columns else "NULL"
            rows = connection.execute(
                f"SELECT m.corpus, s.verses, {source}, {folded} "
                "FROM source_meta m LEFT JOIN search_state s ON s.corpus = m.corpus "
                "ORDER BY m.corpus"
            ).fetchall()
            # A fifth of a second over 900,000 rows, and the only figure the comparison
            # below may honestly use. See `IndexCoverage.stored`.
            counted = dict(connection.execute("SELECT corpus, COUNT(*) FROM verse GROUP BY corpus"))
        except sqlite3.OperationalError:  # pragma: no cover - database not built yet
            return []
    return [
        IndexCoverage(str(corpus), int(counted.get(corpus, 0)), indexed, held, folded)
        for corpus, indexed, held, folded in rows
    ]


def indexed_corpora(home: DataHome) -> set[str]:
    """Which corpora a search can actually answer from.

    The distinction this module had been missing. A corpus is in the *library* as soon as
    it is built, and in the *index* only after it is folded -- and for thirteen corpora,
    including the whole Syriac Bible, the second never happened. Every filter validated
    against the first, so asking for Syriac was accepted and returned nothing.
    """
    return {row.corpus for row in index_coverage(home) if row.searchable}


def index_is_stale(home: DataHome) -> list[str]:
    """Corpora the index cannot answer for, or has fallen behind.

    Was a bare count comparison, and reported four corpora as stale forever: it measured
    ``search_state.verses``, which counts verses that folded to something, against
    ``source_meta.verse_count``, which counts all of them. `brenton` has 314 verses of
    editorial matter that fold away, so it was permanently 314 short of itself and no
    amount of reindexing could settle it. A warning on that predicate would have been wrong
    a quarter of the time it fired.
    """
    return [row.corpus for row in index_coverage(home) if row.state in {"missing", "drifted"}]


# -- results ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Witness:
    """One corpus's rendering of a matched passage, and how near the query it is."""

    corpus: str
    label: str
    text: str
    similarity: float
    """How alike this rendering and the query are, symmetrically. This is what names the
    translation, and :data:`IDENTIFIED` and :meth:`Match.translations` are calibrated on
    it."""
    translated: int | None = None
    """When this rendering's wording was made, or ``None`` where it is ancient. See
    :mod:`biblereference.dating`."""
    coverage: float = 0.0
    """Share of the query this rendering accounts for.

    Used to decide whether the text is a quotation at all, where :attr:`similarity` decides
    which translation it is. The two questions want different measures: a quotation of six
    words from a twenty-six-word verse is a complete quotation and a poor resemblance.
    """


@dataclass(frozen=True, slots=True)
class Match:
    """A passage the searched text was probably quoting."""

    passage: VerseRange
    witnesses: tuple[Witness, ...]
    """Every indexed rendering that was scored, best first."""
    span: tuple[int, int] | None = None
    """Where in the searched text this quotation sits, when scanning a document."""
    quoted: str = ""
    """The searched text this matched, when scanning a document."""
    alternates: tuple[VerseRange, ...] = ()
    """Other passages that fit these words about as well.

    Scripture repeats itself. *Let us not be weary in well doing* is Galatians 6:9 and
    2 Thessalonians 3:13 alike; the synoptic gospels tell the same episodes in the same
    words; Psalm 14 and Psalm 53 are one poem printed twice. Where the words alone cannot
    say which was meant, naming one and discarding the rest would put a fabricated
    precision into a count of who quotes what.
    """
    composed: int | None = None
    """When the searched text was written, where the caller said so.

    Set from :class:`Searcher`'s ``composed``. It is what lets :attr:`anachronistic` tell a
    quotation from a translation the author was reading from a translation his *translator*
    was reading.
    """
    identified_at: float = IDENTIFIED
    """The similarity at which this match's translation may be named.

    Carried on the match rather than read from the module constant, so that a
    :class:`Searcher` configured with a different threshold produces matches which agree
    with it. Defaults to :data:`IDENTIFIED`, so a hand-built ``Match`` behaves as before.
    """
    grade: str = DIRECT
    """On what footing this was found: :data:`DIRECT`, :data:`PARTIAL` or :data:`INDIRECT`.

    A record of the evidence, not a literary judgement. The scholarly scheme these names
    borrow from classifies what a writer was *doing* -- quoting, adapting, alluding -- and
    no index can see that. What this can see is whether the words were spelled alike, how
    many of them, and how surprising. Ignatius at Matthew 10:16 is a *direct* quotation to
    an editor and :data:`INDIRECT` here, because his longest identically spelled run is one
    word. Both answers are right about different questions.
    """
    run: int = 0
    """The longest run of identically spelled words. Today's whole rule, kept visible on
    every match so a caller can see what a grade rests on and reproduce it."""
    lemma_run: int = 0
    """The longest *unbroken* run of words shared as dictionary forms."""
    chain: int = 0
    """The longest run of shared dictionary forms **in the verse's order**, gaps allowed.

    Never less than :attr:`lemma_run`, and the one that tells a re-inflected quotation from a
    coincidence: Ignatius reuses nine of Matthew 10:16's words in Matthew's order with his own
    words between them, where Aristotle brushing a verse twice chains two."""
    bits: float = 0.0
    """Total surprisal of every dictionary form the two share, against the frequencies of
    the language's own verses. Two shared common words score near nothing however correctly
    they were paired; `φρόνιμος ὄφις ἀκέραιος περιστερά` cannot co-occur by accident."""
    matched_lemmas: tuple[str, ...] = ()
    """Every dictionary form the passage and the quotation share. The evidence itself, so a
    caller who mistrusts the gates can weigh it again."""
    formula: str | None = None
    """The citation formula introducing this quotation, where one does -- *it is written*,
    *the scripture says*. Reported and never acted on: see :mod:`biblereference.formulae`
    for the measurement that says why it is evidence but not a threshold."""
    itacised: bool = False
    """Whether the itacised second tier read any spelling inside this match's span.

    True only under ``Searcher(itacised=True)``, and only where a spelling the lexicon
    does not know was re-read through the classes scribes wrote by ear -- ει/ι, η/ι,
    ω/ο and their kin. The flag is what makes the looseness survivable: a consumer can
    hold these matches to a stricter gate, or read them, without either policy touching
    a match the exact tier answered."""
    family: tuple[str, ...] = ()
    """Verses that carry these same words, verified verbally. See :mod:`.parallels`.

    Acts 8:32 *is* Isaiah 53:7 — Acts is quoting Isaiah — and a consumer scoring this
    match against a scholar who wrote "Isaiah 53" needs to know they agreed. Coordinates
    are the ones the library's Greek is held in (``org`` for the New Testament, ``lxx``
    for the Old), best-chained first. Empty until ``biblereference parallels`` builds the
    index, and always empty for a passage with no verbal parallel."""
    positional_candidate: str | None = None
    """Which end of a letter this passage sits at: ``"opening"``, ``"close"``, or ``None``.

    Epistles open with a salutation and close with a farewell blessing, and the fathers
    write both registers constantly without quoting anybody -- *grace to you and peace* is
    how a letter starts, whoever writes it. A match here is not wrong, but a consumer who
    knows *their* document's shape -- this paragraph is Polycarp's own address, that one
    his farewell -- can put this beside that knowledge and settle a class of findings no
    threshold can.

    Which end, rather than merely whether, because the two registers are different claims
    and the consumer knows which part of *their* document they are reading: an opening
    matched against a farewell is as much a mismatch as no match at all. Computed from the
    store's own verse numbering; reported, never acted on, like :attr:`formula`."""

    @property
    def ambiguous(self) -> bool:
        return bool(self.alternates)

    @property
    def similarity(self) -> float:
        return self.witnesses[0].similarity if self.witnesses else 0.0

    @property
    def coverage(self) -> float:
        """Share of the searched words this passage accounts for. See :func:`_coverage`."""
        return self.witnesses[0].coverage if self.witnesses else 0.0

    @property
    def identified(self) -> bool:
        """Whether the wording is close enough to name the translation.

        False where the passage is clear but the wording is not any indexed translation --
        the ordinary case for a quotation from the NIV, ESV, NASB or NKJV.
        """
        return self.similarity >= self.identified_at

    @property
    def anachronistic(self) -> bool:
        """Whether every named translation postdates the text being searched.

        True means the wording is real evidence about the *edition in hand* and none at all
        about what its author read: a scripture quotation in a Victorian translation of
        Chrysostom matches the King James word for word, and Chrysostom died in 407.

        False whenever any named translation could have been read, since then the
        attribution stands on its own. Also false when the caller did not say when the text
        was written, because a date nobody supplied is not grounds for doubting anything.
        """
        if self.composed is None:
            return False
        named = self.translations()
        return bool(named) and all(
            w.translated is not None and w.translated > self.composed for w in named
        )

    def translations(self, margin: float = DEFAULT_MARGIN) -> tuple[Witness, ...]:
        """The witnesses too close to the best to be told apart from it."""
        if not self.witnesses:
            return ()
        cut = self.similarity - margin
        return tuple(w for w in self.witnesses if w.similarity >= cut)

    @property
    def decisive(self) -> bool:
        """Whether exactly one translation stands out."""
        return self.identified and len(self.translations()) == 1

    def describe(self) -> str:
        """A one-line account fit for a terminal."""
        where = self.passage.pretty()
        if not self.identified:
            return (
                f"{where} ({self.similarity:.0%}) -- passage identified; the wording "
                f"matches no indexed translation closely, so the translation is unknown"
            )
        named = ", ".join(w.corpus for w in self.translations())
        rivals = f"; or {', '.join(p.pretty() for p in self.alternates)}" if self.alternates else ""
        if self.anachronistic:
            # Named, but as a fact about the edition rather than about its author. The
            # wording is the translator's; the text is older than every translation it
            # matches.
            return (
                f"{where} ({self.similarity:.0%}) -- this edition's wording follows "
                f"{named}, all of which postdate the text{rivals}"
            )
        if self.decisive:
            return f"{where} ({self.similarity:.0%}) -- {named}{rivals}"
        return f"{where} ({self.similarity:.0%}) -- {named} (indistinguishable here){rivals}"

    def to_dict(self, margin: float = DEFAULT_MARGIN) -> dict[str, object]:
        """The JSONL record: one quotation, ready for a pipeline to aggregate."""
        return {
            "passage": str(self.passage),
            "pretty": self.passage.pretty(),
            "book": self.passage.book,
            "vrs": self.passage.vrs,
            "similarity": round(self.similarity, 4),
            "coverage": round(self.coverage, 4),
            "identified": self.identified,
            "decisive": self.decisive,
            # True means the named translations describe the edition in hand and not what
            # its author read. A count of who quoted what should filter on this rather than
            # on `identified`, or it will report that Chrysostom read the King James.
            "anachronistic": self.anachronistic,
            "composed": self.composed,
            "span": list(self.span) if self.span else None,
            "quoted": self.quoted or None,
            "ambiguous": self.ambiguous,
            "alternates": [str(passage) for passage in self.alternates],
            # Added, never altered: every key above means exactly what it meant before
            # inflected matching existed, and `grade == "direct"` is the whole of what this
            # returned then.
            "grade": self.grade,
            "run": self.run,
            "lemma_run": self.lemma_run,
            "chain": self.chain,
            "bits": round(self.bits, 2),
            "matched_lemmas": list(self.matched_lemmas),
            "formula": self.formula,
            "itacised": self.itacised,
            "family": list(self.family),
            "positional_candidate": self.positional_candidate,
            "translations": [
                {
                    "corpus": w.corpus,
                    "label": w.label,
                    "similarity": round(w.similarity, 4),
                    "translated": w.translated,
                }
                for w in self.translations(margin)
            ],
        }


@dataclass(frozen=True, slots=True)
class FormulaDebt:
    """A citation formula with no quotation found after it.

    *It is written* is a promise that scripture follows. When the library finds nothing
    within reach of one, either the announced text is absent from the library or the gates
    refused it -- and either way this is the one kind of false negative visible without
    gold data, because the document itself says a quotation is there. A ledger of these is
    a self-updating account of recall debt: it shrinks when a missing corpus arrives or a
    gate learns something, and every entry is an address to go look at.

    Reported, never gated, like :attr:`Match.formula` -- this is that field's dual.
    """

    formula: str
    """The formula found, folded, exactly as :attr:`Match.formula` reports it."""
    language: str
    """Which language's formula list recognised it."""
    at: int
    """Character offset in the document where the formula begins, as written."""
    end: int
    """Character offset just past the formula, as written."""
    announced: str
    """The words that follow the formula, as written -- what was promised and not found.
    A dozen words, enough to read the ledger without the document open."""

    def to_dict(self) -> dict[str, object]:
        """The JSONL record: one broken promise, ready for a pipeline to aggregate."""
        return {
            "unmatched_formula": self.formula,
            "language": self.language,
            "at": self.at,
            "end": self.end,
            "announced": self.announced,
        }


# -- searching --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Corpus:
    label: str
    language: str
    versification: str


class Searcher:
    """Reads the search index. Open once and reuse; it holds a read-only connection."""

    def __init__(
        self,
        home: DataHome,
        *,
        corpora: Sequence[str] | None = None,
        families: Sequence[str] | None = None,
        languages: Sequence[str] | None = None,
        quotation: float = QUOTATION,
        coverage: float = COVERAGE,
        identified: float = IDENTIFIED,
        min_run: int | Callable[[int], int] = _MIN_RUN,
        min_query: int = _MIN_QUERY,
        composed: int | None = None,
        inflected: bool = False,
        concave: bool = False,
        itacised: bool = False,
        min_grade: str | None = None,
        gates: Sequence[Gate] | None = None,
        min_lemma_run: int | None = None,
        min_bits: float | None = None,
    ) -> None:
        # `min_lemma_run` and `min_bits` are measured rather than chosen. Over 500 quotations
        # the Patristic Text Archive's editors marked by hand, scored on landing on the
        # verse they named:
        #
        #     ==========================  ========  ==========
        #     gate                         verse     book
        #     ==========================  ========  ==========
        #     inflected=False (today)       52.4%      59.0%
        #     run>=2 bits>=10               69.6%      80.6%
        #     run>=2 bits>=15  (default)    69.2%      79.8%
        #     run>=2 bits>=20               65.2%      74.8%
        #     run>=3 bits>=15               65.4%      75.2%
        #     ==========================  ========  ==========
        #
        # 15 rather than 10 because the curve is flat between them -- four tenths of a point
        # -- and the consumer would refuse a change that raised its false-positive rate
        # whatever it did for recall, so the strictest setting on the flat part is the one
        # to ship. A run of 3 costs four points and takes `indirect` matches from 29 to 10,
        # which is most of the point of the feature.
        """
        :param corpora: Search only these, by id.
        :param families: Search only corpora in these versifications. Confining a search
            to one family is what lets the numbering be tested apart from the wording:
            every candidate then shares a coordinate system, so a verse that matches at the
            wrong number is a fault rather than a translation difference.
        :param languages: Search only corpora in these languages. Latin against Latin
            measures the numbering almost alone, with no translator standing between.

        The four scoring parameters default to this module's constants, which are calibrated
        on English prose. They are parameters because that calibration does not travel: six
        unbroken words is a longer commitment in Latin than in English, and longer again in
        heavily inflected Greek.

        :param quotation: Similarity a passage must reach to count as quoted at all. A
            passage clearing either this or ``coverage`` is a quotation; see
            :data:`COVERAGE` for why it takes both to keep the noise out.
        :param coverage: Share of the searched words a passage must account for to count
            as quoted whatever its overall resemblance. This is what finds a short exact
            quotation of a long verse.
        :param identified: Similarity at which the translation may be named.
        :param min_run: Words a match must share consecutively. Either a fixed count or a
            function of the query's length -- ``lambda n: max(3, min(6, n // 2))`` makes the
            gate proportional, so three words out of four is evidence and three out of forty
            is not. Measured on short Greek quotations, that took the four-to-six word band
            from 9% found to 72%.
        :param min_query: Words below which a search is refused outright. Two words match
            something everywhere; the floor is what stops the index being asked.

        The defaults are deliberately conservative, and for a language they were not
        calibrated on they leave most of the gain on the table. Measured against 4,470
        quotations a human editor tagged by hand in Greek patristic prose, scored on landing
        in the right book:

        =========================================  =========
        the gates as they were before coverage     25.0%
        these defaults                             30.3%
        ``coverage=0.5``, ``min_run`` scaled,      **61.3%**
        ``min_query=3``
        =========================================  =========

        The defaults move Greek by five points and the parameters move it by thirty-one,
        which is the whole argument for having them. A Greek quotation carries inflectional
        variation an English one does not, so it rarely accounts for 90% of the words it
        was written with, and the median tagged quotation is seven words long where
        ``min_run`` alone wants six of them unbroken::

            Searcher(home, languages=["grc"], coverage=0.5, min_query=3,
                     min_run=lambda n: max(3, min(5, n // 2)))

        :param composed: The year the text being searched was written. Where given, a match
            whose every named translation postdates it is reported as
            :attr:`Match.anachronistic`: the wording is evidence about the edition in hand
            and none at all about what its author read. A scripture quotation in a Victorian
            translation of Chrysostom matches the King James word for word, and Chrysostom
            died in 407. Nothing is suppressed -- the translations are still named, because
            which one an editor followed is a real fact about editorial practice -- but the
            inference a reader would otherwise draw is refused.
        """
        self._composed = composed
        #: Concave gap costs in the chain instead of the hard 8/2 walls. Opt-in until the
        #: control corpus prices it, exactly as every loosening before it: the axes it
        #: reports mean the same things, but a wall refused what a cost now weighs, and
        #: what that admits on pre-Christian Greek is a measurement nobody has made yet.
        self._concave = concave
        #: The itacised second tier: spellings the lexicon does not know, re-read through
        #: the classes scribes wrote by ear. Opt-in and flagged on every match that used
        #: it, for the same pricing discipline as `concave`.
        self._itacised = itacised
        # Off, and off is today. Nothing below runs, no lemma table is opened and no query
        # takes a different path unless a caller has asked for one in so many words.
        self._home = home
        self._inflected = inflected
        # Defaulted from `inflected` rather than to a constant. `min_grade=DIRECT` with
        # `inflected=True` is a coherent request -- give me the lemma index's opinion but
        # only where the spelling already agreed -- and it is nobody's intention by
        # accident, so asking for inflected matching admits inflected matches.
        self._min_grade = min_grade or (INDIRECT if inflected else DIRECT)
        # `min_lemma_run=`/`min_bits=` remain as the one-gate shorthand they were shipped as.
        # Naming either builds that gate and nothing else, so code written against the first
        # release keeps its exact meaning rather than silently acquiring a union.
        if min_lemma_run is not None or min_bits is not None:
            if gates is not None:
                raise ValueError("pass gates= or min_lemma_run=/min_bits=, not both")
            gates = (Gate(lemma_run=min_lemma_run or 0, bits=min_bits or 0.0),)
        self._gates = tuple(gates) if gates is not None else DEFAULT_GATES
        self._lexicon: Lexicon | None = None
        self._weights: LemmaWeights | None = None
        self._quotation = quotation
        self._coverage = coverage
        self._identified = identified
        self._min_run = min_run
        self._min_query = min_query
        self._connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        self._corpora = self._load_corpora(home, corpora, families, languages)
        #: Last verse of each book already asked about, per versification. Filled lazily:
        #: most scans never touch an epistle's ending, and the whole table is never needed.
        self._ends: dict[tuple[str, str], tuple[int, int]] = {}
        #: The parallel-family reader, opened on first use for the same reason.
        self._parallels: Parallels | None = None
        self._texts = int(
            self._connection.execute("SELECT COUNT(*) FROM search_text").fetchone()[0]
        )
        if not self._texts:
            raise LookupError(
                "the search index is empty; run `biblereference sync` or "
                "`biblereference index` to build it"
            )

    def _load_corpora(
        self,
        home: DataHome,
        only: Sequence[str] | None,
        families: Sequence[str] | None,
        languages: Sequence[str] | None,
    ) -> dict[str, _Corpus]:
        """The corpora this searcher will answer from, and a refusal where it cannot.

        **Validated against the index, not the library.** A corpus is in the library as soon
        as it is built and searchable only once it is folded, and the two had drifted thirteen
        corpora apart -- the whole Syriac Bible among them. Every filter here checked the
        first, so `languages=["syc"]` was accepted and answered nothing, which is
        indistinguishable from a genuine absence of matches. That cost another project a
        sweep of two million words.

        So: what you *name* must be searchable, or this raises. What you do not name is
        merely reported, because a plain ``Searcher(home)`` has to stay usable while a
        reindex is pending.
        """
        rows = self._connection.execute(
            "SELECT corpus, label, language, versification FROM source_meta"
        )
        loaded = {
            str(corpus): _Corpus(str(label), str(language), str(versification))
            for corpus, label, language, versification in rows
        }
        held = indexed_corpora(home)

        spoken: list[str] | None = None
        if languages is not None:
            spoken = [
                resolve_language(one, {m.language for m in loaded.values()}) for one in languages
            ]

        def check(kind: str, asked: Sequence[str] | None, of: dict[str, str]) -> None:
            """Refuse a value this machine does not hold, or holds and cannot search."""
            for value in dict.fromkeys(asked or ()):
                named = {corpus for corpus, at in of.items() if at == value}
                if not named:
                    raise LookupError(
                        f"unknown {kind} {value!r}. "
                        f"This machine has: {', '.join(sorted(set(of.values())))}"
                    )
                if not named & held:
                    # Counted only on the way to raising: it is a scan of the verse table,
                    # and every ordinary construction of a `Searcher` skips it.
                    stored = {row.corpus: row.stored for row in index_coverage(home)}
                    verses = sum(stored.get(corpus, 0) for corpus in named)
                    raise LookupError(
                        f"{value!r} is in the library but not in the search index "
                        f"({len(named)} corpus{'' if len(named) == 1 else 'es'}, "
                        f"{verses:,} verses): {', '.join(sorted(named))}. "
                        f"Run `biblereference index` to fold them in."
                    )

        check("corpus", only, {corpus: corpus for corpus in loaded})
        check("family", families, {c: m.versification for c, m in loaded.items()})
        check("language", spoken, {c: m.language for c, m in loaded.items()})

        if only is not None:
            wanted = set(only)
            loaded = {c: m for c, m in loaded.items() if c in wanted}
        if families is not None:
            chosen = set(families)
            loaded = {c: m for c, m in loaded.items() if m.versification in chosen}
        if spoken is not None:
            wanted_languages = set(spoken)
            loaded = {c: m for c, m in loaded.items() if m.language in wanted_languages}

        # What is left but unsearchable is dropped rather than refused: nobody asked for it
        # by name, and a library with one stale corpus has to stay usable. Said once,
        # because silence here is the whole fault being fixed.
        absent = sorted(set(loaded) - held)
        if absent:
            warnings.warn(
                f"{len(absent)} of {len(loaded)} corpora are in the library but not in the "
                f"search index, and will not be searched: {', '.join(absent[:6])}"
                + (f", and {len(absent) - 6} more" if len(absent) > 6 else "")
                + ". Run `biblereference index`.",
                IndexIncomplete,
                stacklevel=3,
            )
            loaded = {c: m for c, m in loaded.items() if c in held}
        return loaded

    @property
    def corpora(self) -> Mapping[str, _Corpus]:
        """The corpora this searcher reads, keyed by id."""
        return self._corpora

    def verse(self, corpus: str, ref: VerseRef) -> str | None:
        """One verse straight from the store, whatever built the corpus it belongs to."""
        row = self._connection.execute(
            "SELECT text FROM verse WHERE corpus = ? AND book = ? AND chapter = ? AND verse = ?",
            (corpus, ref.book, int(ref.chapter), ref.verse),
        ).fetchone()
        return str(row[0]) if row else None

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Searcher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- retrieval ----------------------------------------------------------------------

    def _document_frequency(self, tokens: Iterable[str]) -> dict[str, int]:
        unique = sorted(set(tokens))
        if not unique:
            return {}
        marks = ",".join("?" * len(unique))
        rows = self._connection.execute(
            f"SELECT token, docs FROM search_df WHERE token IN ({marks})", unique
        )
        return {str(token): int(docs) for token, docs in rows}

    def _query_terms(self, tokens: Sequence[str], limit: int = _QUERY_TERMS) -> list[str]:
        """The words worth searching on, rarest first.

        A quotation's distinctive words are the ones that find it. *And it came to pass*
        matches half the Bible; *Melchizedek* matches nine verses. Common words are not
        merely useless here, they are the whole cost: asking FTS5 for *god* means scoring
        every text that contains it.
        """
        frequency = self._document_frequency(tokens)
        scored: list[tuple[float, str]] = []
        ceiling = self._texts * _COMMON_SHARE
        for token in dict.fromkeys(tokens):
            if len(token) < 2 or token in _STOPWORDS:
                continue
            docs = frequency.get(token, 0)
            # A word in a tenth of the corpus does not narrow anything and is the most
            # expensive kind of term to ask for, because every text carrying it has to be
            # scored. Dropping those is most of what makes a document scan tractable.
            if docs > ceiling:
                continue
            # Unseen words are rare by definition, but they are also the likeliest to be
            # a mishearing, so they rank below a genuinely rare indexed word.
            idf = math.log(self._texts / docs) if docs else 1.0
            scored.append((idf, token))
        scored.sort(reverse=True)
        return [token for _, token in scored[:limit]]

    def _min_run_for(self, length: int) -> int:
        """The contiguity gate for a query of this length."""
        return self._min_run(length) if callable(self._min_run) else self._min_run

    def _is_quotation(self, query: Sequence[str], best: Witness) -> bool:
        """Whether the best-matching text is close enough, and contiguous enough, to keep.

        Two gates, because either alone lets the wrong things through. Coverage says how
        much of what was written this passage accounts for; the longest unbroken run says
        whether that correspondence is a quotation or a coincidence. Formulaic religious
        speech clears the first regularly and the second almost never -- which is why the
        first can afford to be the looser, asymmetric measure.
        """
        if best.similarity < self._quotation and best.coverage < self._coverage:
            return False
        meta = self._corpora[best.corpus]
        return longest_run(query, _tokens(best.text, meta.language)) >= self._min_run_for(
            len(query)
        )

    def _candidates(self, terms: Sequence[str], limit: int) -> list[tuple[int, float]]:
        """Indexed texts sharing words with the query, best first.

        Every term is quoted before it goes into the MATCH expression. FTS5 reads bare
        input as its own query language, where an unbalanced quote is a hard error and
        ``OR`` and ``NEAR`` are operators, so interpolating a sentence would break on
        ordinary text.
        """
        if not terms:
            return []
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        rows = self._connection.execute(
            "SELECT rowid, bm25(search_fts) FROM search_fts "
            "WHERE search_fts MATCH ? ORDER BY 2 LIMIT ?",
            (expression, limit),
        )
        return [(int(rowid), float(score)) for rowid, score in rows]

    def _positions(self, text_ids: Sequence[int]) -> dict[tuple[str, str, int], set[int]]:
        """Where the candidate texts sit: ``(versification, book, chapter)`` to verses.

        Grouped by versification because a coordinate means different things in different
        systems -- the Septuagint's Psalm 22 is the English tradition's 23 -- so merging
        them would assemble passages that exist in neither.
        """
        return {key: verses for key, (verses, _) in self._located(text_ids, {}).items()}

    def _located(
        self,
        text_ids: Sequence[int],
        scores: Mapping[int, float],
        table: str = "search_ref",
    ) -> dict[tuple[str, str, int], tuple[set[int], float]]:
        """As :meth:`_positions`, but keeping each chapter's best retrieval score.

        The score is what decides which chapters are worth the expensive scoring pass.
        Ranking by how many consecutive verses a chapter contributed instead -- an obvious
        proxy -- is actively wrong: a chapter that shares one distinctive word beats one
        that shares four common ones, and the run length says the opposite.
        """
        if not text_ids:
            return {}
        marks = ",".join("?" * len(text_ids))
        rows = self._connection.execute(
            f"SELECT corpus, book, chapter, verse, text_id FROM {table} WHERE text_id IN ({marks})",
            list(text_ids),
        )
        found: dict[tuple[str, str, int], tuple[set[int], float]] = {}
        for corpus, book, chapter, verse, text_id in rows:
            meta = self._corpora.get(str(corpus))
            if meta is None:
                continue
            key = (meta.versification, str(book), int(chapter))
            # bm25 is negative and more negative is better, so the minimum is the best.
            score = scores.get(int(text_id), 0.0)
            verses, best = found.get(key, (set(), 0.0))
            verses.add(int(verse))
            found[key] = (verses, min(best, score))
        return found

    @staticmethod
    def _runs(verses: Iterable[int]) -> list[tuple[int, int]]:
        """Consecutive verse numbers collapsed into ``(first, last)`` spans."""
        ordered = sorted(verses)
        if not ordered:
            return []
        spans: list[tuple[int, int]] = []
        start = previous = ordered[0]
        for verse in ordered[1:]:
            if verse == previous + 1:
                previous = verse
                continue
            spans.append((start, previous))
            start = previous = verse
        spans.append((start, previous))
        return spans

    # -- scoring ------------------------------------------------------------------------

    def _renderings(
        self, vrs: str, book: str, chapter: int, first: int, last: int
    ) -> dict[str, str]:
        """Each corpus's text for one span of verses, joined in order."""
        corpora = [c for c, meta in self._corpora.items() if meta.versification == vrs]
        if not corpora:
            return {}
        marks = ",".join("?" * len(corpora))
        rows = self._connection.execute(
            f"SELECT corpus, verse, subverse, text FROM verse "
            f"WHERE corpus IN ({marks}) AND book = ? AND chapter = ? AND verse BETWEEN ? AND ? "
            f"ORDER BY corpus, verse, subverse",
            [*corpora, book, chapter, first, last],
        )
        collected: dict[str, list[str]] = {}
        for corpus, _verse, _subverse, text in rows:
            collected.setdefault(str(corpus), []).append(str(text))
        return {corpus: " ".join(parts) for corpus, parts in collected.items()}

    def _witnesses(
        self, vrs: str, book: str, chapter: int, first: int, last: int, query: Sequence[str]
    ) -> list[Witness]:
        witnesses: list[Witness] = []
        for corpus, text in self._renderings(vrs, book, chapter, first, last).items():
            meta = self._corpora[corpus]
            tokens = _tokens(text, meta.language)
            witnesses.append(
                Witness(
                    corpus,
                    meta.label,
                    text,
                    _ratio(query, tokens),
                    _translated(corpus),
                    _coverage(query, tokens),
                )
            )
        # Best-covered first, because that is the question being asked here -- which passage
        # these words came from. Similarity breaks the tie, since among passages that
        # account for the query equally the closest wording is the one being read.
        witnesses.sort(key=lambda w: (-w.coverage, -w.similarity, w.corpus))
        return witnesses

    def _grow(
        self, vrs: str, book: str, chapter: int, first: int, last: int, query: Sequence[str]
    ) -> tuple[int, int, list[Witness]]:
        """Extend one span outward while doing so makes the match better.

        Growth is judged on coverage, not similarity. Adding a verse lengthens the
        *passage*, which a symmetric ratio can punish even when the added verse contains
        more of the quotation -- so a quotation running across a verse boundary was being
        cut short by its own denominator. Coverage cannot fall as the passage grows, so
        growth stops when it stops helping rather than when the arithmetic turns against it.

        That makes the strict-improvement test load-bearing rather than incidental: without
        it, a measure that never falls would walk every span out to :data:`_MAX_PASSAGE`.
        Strictness alone is not enough either, which is what :data:`_GROWTH_BLOCK` is for.
        """
        witnesses = self._witnesses(vrs, book, chapter, first, last, query)
        best = self._span_score(witnesses, query)

        improved = True
        while improved:
            improved = False
            for start, end in ((first - 1, last), (first, last + 1)):
                if start < 1 or end - start > _MAX_PASSAGE:
                    continue
                grown = self._witnesses(vrs, book, chapter, start, end, query)
                score = self._span_score(grown, query)
                if score > best + 1e-9:
                    first, last, witnesses, best = start, end, grown, score
                    improved = True
        return first, last, witnesses

    def _span_score(self, witnesses: Sequence[Witness], query: Sequence[str]) -> float:
        """How well a span accounts for the query, for deciding whether to keep growing.

        Coverage over runs of at least :data:`_GROWTH_BLOCK` words, so that a neighbouring
        verse has to carry some of the quotation to be admitted rather than merely share
        vocabulary with the sentence around it.
        """
        if not witnesses:
            return 0.0
        best = witnesses[0]
        tokens = _tokens(best.text, self._corpora[best.corpus].language)
        return _coverage(query, tokens, min_block=_GROWTH_BLOCK)

    def _best_span(
        self, vrs: str, book: str, chapter: int, first: int, last: int, query: Sequence[str]
    ) -> tuple[int, int, list[Witness]]:
        """The span of verses within a candidate run that best matches the query.

        Retrieval returns every verse of a chapter sharing rare words with the query, and
        that is usually wider than the quotation: quoting John 3:16 lights up 3:15 through
        3:18, because a paragraph about believing and perishing shares most of its
        vocabulary with itself. Growing outward from the whole run therefore never finds
        the single verse actually quoted -- it can only get wider and worse.

        So each verse of the run is tried as its own starting point and grown from there,
        and the best result wins. A one-verse quotation contracts to one verse; a
        quotation running across three keeps all three, because growing into them is what
        improves the score.
        """
        best: tuple[float, int, int, list[Witness]] | None = None
        for seed in range(first, min(last, first + _MAX_SEEDS - 1) + 1):
            start, end, witnesses = self._grow(vrs, book, chapter, seed, seed, query)
            # The same measure :meth:`_grow` decides on, so that choosing between seeds and
            # choosing whether to extend one are answering the same question.
            score = self._span_score(witnesses, query)
            if best is None or score > best[0]:
                best = (score, start, end, witnesses)
        if best is None:  # pragma: no cover - a run always has at least one verse
            return first, last, []
        return best[1], best[2], best[3]

    # -- the public search --------------------------------------------------------------

    def search(self, text: str, *, limit: int = 5) -> list[Match]:
        """Passages the text was probably quoting, best first.

        Returns nothing when nothing scores above :data:`QUOTATION`, which is the right
        answer for ordinary religious language: *we are saved by grace* is a sentence about
        scripture rather than a quotation of it, and a matcher that guesses at such
        sentences would put noise into every count made from its output.
        """
        query = _tokens(text)
        if len(query) < self._min_query:
            return []

        terms = self._query_terms(query)
        candidates = self._candidates(terms, _CANDIDATES)
        grouped = self._located([text_id for text_id, _ in candidates], dict(candidates))

        spans: list[tuple[float, str, str, int, int, int]] = []
        for (vrs, book, chapter), (verses, score) in grouped.items():
            spans.extend(
                (score, vrs, book, chapter, first, last) for first, last in self._runs(verses)
            )
        # Best retrieval score first, so the scoring budget goes to the chapters the query
        # actually pointed at.
        spans.sort()

        matches: list[Match] = []
        seen: set[tuple[str, str, int, int, int]] = set()
        for _, vrs, book, chapter, first, last in spans[:_PASSAGES]:
            start, end, witnesses = self._best_span(vrs, book, chapter, first, last, query)
            key = (vrs, book, chapter, start, end)
            if key in seen or not witnesses:
                continue
            seen.add(key)
            if not self._is_quotation(query, witnesses[0]):
                continue
            passage = VerseRange(
                VerseRef(book, chapter, start, vrs=vrs), VerseRef(book, chapter, end, vrs=vrs)
            )
            matches.append(
                Match(
                    passage,
                    tuple(witnesses[:20]),
                    composed=self._composed,
                    identified_at=self._identified,
                    # Recorded rather than left at zero: the consumer asked to see the rule
                    # that found it, and a `direct` match saying its run was nothing would
                    # be the one field here nobody could check.
                    run=longest_run(
                        query, _tokens(witnesses[0].text, self._language_of(witnesses[0]))
                    ),
                )
            )

        matches.sort(key=lambda m: -m.similarity)
        exact = _one_per_passage(matches)
        if not self._inflected:
            return self._decorate(exact[:limit])

        # Settled first and settled whole. Letting the two sets compete for `limit` places
        # cost eight passages in four hundred that the exact path had found on its own --
        # measured, not feared -- and a feature that improves recall by losing matches is
        # the one thing this must not be. Graded matches fill what is left over, if
        # anything is.
        graded = [
            match
            for match in _one_per_passage(self._by_lemma(text, {m.passage for m in exact}))
            if self._graded_enough(match)
        ]
        graded.sort(key=lambda m: (-GRADES.index(m.grade), -m.bits, -m.similarity))
        return self._decorate((exact + graded)[:limit])

    # -- matching on dictionary forms ---------------------------------------------------

    def _language_of(self, witness: Witness) -> str | None:
        meta = self._corpora.get(witness.corpus)
        return meta.language if meta else None

    def _graded_enough(self, match: Match) -> bool:
        return GRADES.index(match.grade) >= GRADES.index(self._min_grade)

    def _lemma_tools(self, language: str) -> tuple[Lexicon, LemmaWeights]:
        if self._lexicon is None:
            self._lexicon = Lexicon(self._home)
        if self._weights is None:
            self._weights = LemmaWeights(self._home)
        self._lexicon.require(language)
        return self._lexicon, self._weights

    def _readings(
        self, tokens: Sequence[str], language: str, lexicon: Lexicon
    ) -> tuple[list[Reading], frozenset[int]]:
        """The query's readings, itacised-tier included where it was asked for.

        Only the query side: the verses are edited texts and their spellings are the
        editor's, so itacism lives on the father's side of the comparison alone.
        """
        plain = lemma_readings(list(tokens), language, lexicon)
        if not self._itacised or language != "grc":
            return plain, frozenset()
        return itacised_readings(tokens, language, lexicon, plain)

    def _lemma_languages(self) -> list[str]:
        """Which of the loaded corpora's languages a lemma pass can be run in."""
        return sorted({m.language for m in self._corpora.values()} & set(LEMMA_LANGUAGES))

    def _by_lemma(self, text: str, already: set[VerseRange]) -> list[Match]:
        """Passages sharing a run of dictionary forms with the text.

        The same shape as :meth:`search` and deliberately so -- retrieve, locate, score,
        gate -- but retrieving from ``lemma_fts`` and gating on a run of shared lemmas
        rather than of shared spellings. The scoring in between is the same code: it works
        on sequences of strings and does not care what the strings are.
        """
        out: list[Match] = []
        for language in self._lemma_languages():
            lexicon, weights = self._lemma_tools(language)
            query = _tokens(text, language)
            if len(query) < self._min_query:
                continue
            readings, re_read = self._readings(query, language, lexicon)
            weigh = weights.of(language)

            # The rarest shared *lemmas* are what narrow this, exactly as the rarest words
            # narrow the other index. A common lemma is the more expensive to ask for, since
            # every verse carrying it has to be scored.
            terms = sorted(
                {lemma for reading in readings for lemma in reading},
                key=lambda lemma: -weigh(lemma),
            )[:_QUERY_TERMS]
            candidates = self._lemma_candidates(terms, _CANDIDATES)
            grouped = self._located(
                [text_id for text_id, _ in candidates], dict(candidates), "lemma_ref"
            )

            spans: list[tuple[float, str, str, int, int, int]] = []
            for (vrs, book, chapter), (verses, score) in grouped.items():
                spans.extend(
                    (score, vrs, book, chapter, first, last) for first, last in self._runs(verses)
                )
            spans.sort()

            for _, vrs, book, chapter, first, last in spans[:_PASSAGES]:
                start, end, witnesses = self._best_span(vrs, book, chapter, first, last, query)
                if not witnesses:
                    continue
                passage = VerseRange(
                    VerseRef(book, chapter, start, vrs=vrs), VerseRef(book, chapter, end, vrs=vrs)
                )
                if passage in already:
                    continue
                graded = self._grade(readings, query, witnesses[0], language, weigh, lexicon)
                if graded is None:
                    continue
                grade, run, found, chained, weight, evidence = graded
                out.append(
                    Match(
                        passage,
                        tuple(witnesses[:20]),
                        composed=self._composed,
                        identified_at=self._identified,
                        grade=grade,
                        run=run,
                        lemma_run=found.length,
                        chain=chained.length,
                        bits=weight,
                        matched_lemmas=evidence,
                        itacised=bool(re_read),
                    )
                )
        return out

    def _grade(
        self,
        readings: Sequence[Reading],
        query: Sequence[str],
        best: Witness,
        language: str,
        weigh: Callable[[str], float],
        lexicon: Lexicon,
    ) -> tuple[str, int, LemmaRun, LemmaChain, float, tuple[str, ...]] | None:
        """What footing this passage rests on, or ``None`` if it rests on too little.

        Two ways in, and the shorter one is not the looser one. A run of identical spellings
        below ``min_run`` is refused today for being *short*, not for being different, and
        where it is surprising enough it comes back as :data:`PARTIAL` -- three verbatim
        words of Philippians 2:3 are a quotation by any reading. A run of shared dictionary
        forms with no such spelling behind it is :data:`INDIRECT`.

        Both need the bits. Without them `ὡς ὁ` would qualify as readily as `φρόνιμος ὄφις`,
        and the words a false match is made of are precisely the common ones.
        """
        spelled = _tokens(best.text, language)
        theirs = lemma_readings(spelled, language, lexicon)
        run = longest_run(query, spelled)
        found = lemma_run(readings, theirs, weigh)
        chained = lemma_chain(readings, theirs, weigh, concave=self._concave)
        evidence = shared_lemmas(readings, theirs)
        # Weighed over what actually matched, not over the window it was seen through. The
        # chain's span *is* the quotation's extent, so there is no other span this could be
        # taken over -- which is the whole of why a score no longer depends on how a document
        # happened to be sliced.
        # Weighed over the chain's own *distinct* lemmas, not over every shared word in the
        # stretch it covers. Both halves of that matter, and the consumer found the case that
        # proves it: Ignatius' Magnesians 9.1 against Romans 5:21 scored 66 bits -- the
        # highest of eighty-eight findings they read by hand, and a false positive -- on five
        # content words scattered through forty. The bits were coming from the span rather
        # than from the evidence, and three occurrences of `καί` were counted as three pieces
        # of it rather than one. Counting distinct links takes that case to 33 and leaves
        # Ignatius at Matthew 10:16, which is real, at 49.
        weight = sum(weigh(lemma) for lemma in set(chained.lemmas))
        if not any(gate.admits(run, found.length, chained.length, weight) for gate in self._gates):
            return None
        if _MIN_PARTIAL_RUN <= run < self._min_run_for(len(query)):
            return (PARTIAL, run, found, chained, weight, evidence)
        return (INDIRECT, run, found, chained, weight, evidence)

    def _lemma_candidates(self, terms: Sequence[str], limit: int) -> list[tuple[int, float]]:
        """Indexed lemma readings sharing dictionary forms with the query, best first."""
        if not terms:
            return []
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        rows = self._connection.execute(
            "SELECT rowid, bm25(lemma_fts) FROM lemma_fts "
            "WHERE lemma_fts MATCH ? ORDER BY 2 LIMIT ?",
            (expression, limit),
        )
        return [(int(rowid), float(score)) for rowid, score in rows]

    # -- scanning a document ------------------------------------------------------------

    def scan(
        self,
        text: str,
        *,
        window: int = _WINDOW,
        stride: int = _STRIDE,
    ) -> list[Match]:
        """Every quotation in a document, with where in it each one sits.

        Built for sermon transcripts: long, unpunctuated, and full of language that sounds
        like scripture without being it. The shape of the problem is that quotation
        boundaries are unknown, so the text is swept in overlapping windows, windows that
        point at the same chapter are gathered, and only those clusters are scored in full.
        Retrieval is cheap and scoring is not, which is what makes a long document
        tractable.
        """
        words = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]
        tokens = [fold(word) for word, _, _ in words]
        if len(tokens) < _MIN_QUOTE_WORDS:
            return []

        matches: list[Match] = []
        for (vrs, book, chapter), windows in self._sweep(tokens, window, stride):
            for cluster in _clusters(sorted(windows)):
                matches.extend(
                    self._score_cluster(vrs, book, chapter, cluster, tokens, words, window, stride)
                )

        matches.sort(key=lambda m: (-m.similarity, m.span or (0, 0)))
        return self._decorate(_without_overlaps(matches))

    def formula_debts(
        self,
        text: str,
        *,
        window: int = _WINDOW,
        stride: int = _STRIDE,
    ) -> list[FormulaDebt]:
        """Announced quotations this library failed to find. See :class:`FormulaDebt`.

        Runs the same scan a caller would and then asks the opposite question: not *what
        matched* but *what was promised* -- every citation formula in the document, minus
        those with a match beginning within :data:`~biblereference.formulae.REACH` words.
        The remainder is the recall debt, one record per broken promise.

        The reach is counted exactly as :func:`~biblereference.formulae.preceding` counts
        it, so a debt here and a filled :attr:`Match.formula` there are the two halves of
        one measurement and cannot disagree at the boundary.
        """
        from .formulae import FORMULAE, REACH, announced

        words = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]
        if not words:
            return []
        starts = {offset: index for index, (_, offset, _) in enumerate(words)}
        opened = {
            starts[match.span[0]]
            for match in self.scan(text, window=window, stride=stride)
            if match.span and match.span[0] in starts
        }
        debts: list[FormulaDebt] = []
        spoken = sorted({meta.language for meta in self._corpora.values()} & set(FORMULAE))
        for language in spoken:
            tokens = [fold(word, language) for word, _, _ in words]
            for formula, first, after in announced(tokens, language):
                # Kept promises: a quotation starting anywhere from the formula's own
                # first word (a verse can contain the formula's words) to REACH words
                # past its end, which is as far as `preceding` would have looked back.
                if any(first <= start < after + REACH for start in opened):
                    continue
                tail = words[after : after + 12]
                debts.append(
                    FormulaDebt(
                        formula=formula,
                        language=language,
                        at=words[first][1],
                        end=words[after - 1][2],
                        announced=text[tail[0][1] : tail[-1][2]] if tail else "",
                    )
                )
        debts.sort(key=lambda debt: debt.at)
        return debts

    def _book_end(self, vrs: str, book: str) -> tuple[int, int]:
        """The last verse this numbering gives the book, from the verses actually held."""
        cached = self._ends.get((vrs, book))
        if cached is None:
            held = [c for c, meta in self._corpora.items() if meta.versification == vrs]
            row = self._connection.execute(
                "SELECT chapter, verse FROM verse WHERE book = ? AND corpus IN "
                f"({','.join('?' * len(held))}) ORDER BY chapter DESC, verse DESC LIMIT 1",
                [book, *held],
            ).fetchone()
            cached = self._ends[(vrs, book)] = (row[0], row[1]) if row else (0, 0)
        return cached

    def _positional(self, passage: VerseRange) -> str | None:
        """Which end of a letter this passage sits at: ``opening``, ``close``, or nothing.

        A window rather than the exact first and last verse, measured by the consumer on
        their own eight salutation targets: the strict rule missed 2 Thessalonians 1:2,
        Philemon 1:3, and Ephesians 6:23 -- the closing grace standing one verse before
        the true last. Three verses in and two back covers all of them.

        The closing test is anchored to the book's *final verse* and not to its final
        chapter, which is the trap the consumer caught: Philemon's first chapter is also
        its last, so "in the last chapter" makes the whole letter a farewell. Where a book
        is short enough for the two windows to touch, the opening wins -- a salutation is
        the more distinctive register, and a greeting misread as a farewell is the error
        that would mislead somebody about what a father was doing.
        """
        first, last = passage.start, passage.end
        if first.book in _EPISTLES and first.chapter == 1 and first.verse <= _OPENING:
            return "opening"
        if last.book not in _EPISTLES:
            return None
        chapter, verse = self._book_end(last.vrs, last.book)
        if chapter and last.chapter == chapter and last.verse > verse - _CLOSING:
            return "close"
        return None

    def _family(self, passage: VerseRange) -> tuple[str, ...]:
        """The passage's verbal parallels, from the index `biblereference parallels`
        builds. Silence where it was never built."""
        if self._parallels is None:
            from .parallels import Parallels

            self._parallels = Parallels(self._connection)
        chapter = passage.start.chapter
        if not isinstance(chapter, int):
            # Esther's lettered additions: the index is numbered, so a letter chapter
            # has no family by construction.
            return ()
        return self._parallels.of(
            passage.start.book, chapter, passage.start.verse, passage.end.verse
        )

    def _decorate(self, matches: list[Match]) -> list[Match]:
        """Both reported-never-gated decorations, in one pass over the answer."""
        return [
            replace(
                match,
                positional_candidate=self._positional(match.passage),
                family=self._family(match.passage),
            )
            for match in matches
        ]

    def _sweep(
        self, tokens: Sequence[str], window: int, stride: int
    ) -> list[tuple[tuple[str, str, int], set[int]]]:
        """Which chapters the document points at, best first and capped.

        A sweep of a few dozen windows nominates hundreds of chapters, nearly all of them
        on the strength of one weak coincidence. Scoring all of them costs far more than
        the sweep itself and finds nothing, so only the best handful go through.

        Ranking them is subtler than it looks. Each window is a *different* query, so the
        BM25 scores they return are on different scales and cannot be compared: a window
        holding one very rare word scores everything it touches far below a window of
        ordinary vocabulary, and sorting on the raw numbers hands the whole budget to
        whichever window happened to contain a proper noun. What is comparable is a
        candidate's *position* within its own window, so a chapter is scored by how near
        the top it came, summed over the windows that found it. A genuine quotation is
        near the top of two or three consecutive windows; a coincidence is halfway down
        one.
        """
        votes: dict[tuple[str, str, int], set[int]] = {}
        weight: dict[tuple[str, str, int], float] = {}
        for index in _offsets(len(tokens), window, stride):
            chunk = tokens[index : index + window]
            terms = self._query_terms(chunk, _SWEEP_TERMS)
            candidates = self._candidates(terms, _SWEEP_CANDIDATES)
            # Negated so that the shared "lower is better" convention holds, as it does
            # for the bm25 scores this argument otherwise carries.
            ranks = {
                text_id: -1.0 / (1 + position) for position, (text_id, _) in enumerate(candidates)
            }
            for key, (_, best) in self._located(list(ranks), ranks).items():
                votes.setdefault(key, set()).add(index)
                weight[key] = weight.get(key, 0.0) + best

            # A second nomination, by dictionary form. Without it the graded path is
            # unreachable from a scan however good its gates are: a re-inflected quotation
            # shares almost no *spellings* with its verse, so the exact sweep above never
            # puts that chapter on the list, and nothing that is not on the list is ever
            # scored. Ignatius at Matthew 10:16 shares one spelling and nine dictionary
            # forms, and it is the nine that have to do the nominating.
            for key, best in self._lemma_votes(chunk).items():
                votes.setdefault(key, set()).add(index)
                weight[key] = weight.get(key, 0.0) + best

        ranked = sorted(votes, key=lambda key: weight[key])
        return [(key, votes[key]) for key in ranked[:_SCAN_CHAPTERS]]

    def _span_rivals(
        self,
        vrs: str,
        book: str,
        chapter: int,
        first: int,
        last: int,
        query: Sequence[str],
    ) -> list[tuple[float, int, int]]:
        """Every seed in this run and what it scored, not merely the winner.

        `_best_span` keeps one span per run and throws the rest away, which is right for
        deciding *what* was quoted and wrong for saying what else it might have been. Job 1:1
        and Job 1:8 are one contiguous run, carry the same four epithets, and until this the
        loser vanished before anything could report it.

        Only walked when inflected matching was asked for: it is the same loop `_best_span`
        already runs, and paying for it twice on a scan that did not ask is not worth an
        answer nobody requested.
        """
        if not self._inflected:
            return []
        found: list[tuple[float, int, int]] = []
        for seed in range(first, min(last, first + _MAX_SEEDS - 1) + 1):
            start, end, witnesses = self._grow(vrs, book, chapter, seed, seed, query)
            if witnesses:
                found.append((witnesses[0].similarity, start, end))
        return found

    def _near_ties(
        self,
        rivals: Sequence[tuple[float, int, int]],
        won: float,
        vrs: str,
        book: str,
        chapter: int,
        start: int,
        end: int,
    ) -> tuple[VerseRange, ...]:
        """Other verses of this same chapter that answered nearly as well.

        A scan keeps one span per chapter, so until now a rival inside the chapter was
        discarded before `_without_overlaps` ever saw it and `alternates` could only ever
        name a *different* chapter. Clement's Job quotation shows what that cost: Job 1:1 and
        Job 1:8 carry the same four epithets, both are correct, and only the first was
        reported -- with an empty `alternates`, which reads as "nothing else fits".

        Populated only when inflected matching was asked for, because filling a field that
        has always been empty changes what every existing scan returns, and half a million
        findings downstream rest on that not happening by surprise.
        """
        if not self._inflected:
            return ()
        return tuple(
            VerseRange(
                VerseRef(book, chapter, other_start, vrs=vrs),
                VerseRef(book, chapter, other_end, vrs=vrs),
            )
            for score, other_start, other_end in sorted(rivals, reverse=True)
            if (other_start, other_end) != (start, end) and won - score <= _TIE
        )

    def _with_axes(self, found: Match, query: Sequence[str], best: Witness) -> Match:
        """The lemma axes for a match the *exact* path found, where they can be computed.

        The exact path used to leave all four at their defaults, which made `bits = 0.0`
        mean "not computed" in a field where 0.0 also means "no information", and a caller
        could not tell the two apart without reading the source. Worse than untidy: the
        largest true error class the consumer found -- one liturgical doxology matching
        whichever epistle happens to end that way -- arrives through the exact path, so it
        had no surprisal defence at all. Nine verbatim words of *to whom be glory for ever
        and ever* now carry the seventeen bits they are worth rather than a silent zero.

        Empty unless inflected matching was asked for, because computing it costs a lexicon
        lookup per word and a caller who did not ask for the feature should not pay for it.
        """
        language = self._language_of(best)
        if not self._inflected or language not in LEMMA_LANGUAGES:
            return found
        lexicon, weights = self._lemma_tools(language)
        weigh = weights.of(language)
        mine = lemma_readings(list(query), language, lexicon)
        theirs = lemma_readings(_tokens(best.text, language), language, lexicon)
        chained = lemma_chain(mine, theirs, weigh, concave=self._concave)
        return replace(
            found,
            lemma_run=lemma_run(mine, theirs, weigh).length,
            chain=chained.length,
            bits=sum(weigh(lemma) for lemma in set(chained.lemmas)),
            matched_lemmas=shared_lemmas(mine, theirs),
        )

    def _formula_before(
        self, words: Sequence[tuple[str, int, int]], low: int, language: str | None
    ) -> str | None:
        """Whether this quotation was announced, and with what.

        Read off the words as written rather than off the folded tokens, because the reach is
        counted in words of the document and the document is what the caller will look at.
        """
        if not language or low <= 0:
            return None
        from .formulae import REACH, preceding

        before = " ".join(word for word, _, _ in words[max(0, low - REACH) : low])
        return preceding(before + " ", len(before) + 1, language)

    def _lemma_votes(self, chunk: Sequence[str]) -> dict[tuple[str, str, int], float]:
        """Chapters this window points at by dictionary form, scored as the exact arm scores.

        Silent when the feature is off or the language has no lexicon, so a scan that asked
        for nothing pays nothing: no query is built and no table is opened.
        """
        if not self._inflected:
            return {}
        spoken = {m.language for m in self._corpora.values()} & set(LEMMA_LANGUAGES)
        found: dict[tuple[str, str, int], float] = {}
        for language in sorted(spoken):
            lexicon, weights = self._lemma_tools(language)
            weigh = weights.of(language)
            readings = lemma_readings(list(chunk), language, lexicon)
            terms = sorted(
                {lemma for reading in readings for lemma in reading},
                key=lambda lemma: -weigh(lemma),
            )[:_SWEEP_TERMS]
            candidates = self._lemma_candidates(terms, _SWEEP_CANDIDATES)
            ranks = {
                text_id: -1.0 / (1 + position) for position, (text_id, _) in enumerate(candidates)
            }
            for key, (_, best) in self._located(list(ranks), ranks, "lemma_ref").items():
                found[key] = min(found.get(key, 0.0), best)
        return found

    def _score_cluster(
        self,
        vrs: str,
        book: str,
        chapter: int,
        cluster: Sequence[int],
        tokens: Sequence[str],
        words: Sequence[tuple[str, int, int]],
        window: int,
        stride: int,
    ) -> list[Match]:
        """Score one run of windows that all pointed at the same chapter.

        The exact path answers first and its answer is final. Only where it declines -- and
        it declines in several places, from finding no candidate to failing the quotation
        gate -- is the same cluster read again by dictionary form. Trying the graded path at
        one chosen point inside the exact one missed most of them: a re-inflected quotation
        shares so few spellings that the exact retrieval gives up before any gate is reached.
        """
        found = self._exact_cluster(vrs, book, chapter, cluster, tokens, words, window, stride)
        if not self._inflected:
            return [found] if found is not None else []
        first_token = max(0, cluster[0] - stride)
        last_token = min(len(tokens), cluster[-1] + window + stride)
        query = tokens[first_token:last_token]
        if len(query) < _MIN_QUOTE_WORDS:
            return [found] if found is not None else []
        if found is None:
            return self._graded_cluster(vrs, book, chapter, query, first_token, tokens, words)
        # The exact answer stands -- and the rest of the cluster is still read. Polycarp
        # quotes Matthew 7:1 word for word and then 7:2's measure-for-measure clause
        # re-inflected, in one sentence; the verbatim clause used to be the cluster's
        # whole answer and the other was structurally unreachable, being neither its own
        # cluster nor an uncovered one. Masking the exact match's words and grading the
        # remainder is the same uncovered-remainder rule the chains follow below.
        return [
            found,
            *self._graded_cluster(
                vrs, book, chapter, query, first_token, tokens, words,
                masked=self._span_tokens(found.span, words, first_token),
            ),
        ]

    @staticmethod
    def _span_tokens(
        span: tuple[int, int] | None,
        words: Sequence[tuple[str, int, int]],
        first_token: int,
    ) -> tuple[int, int]:
        """A match's character span as query-relative token positions, for masking."""
        if span is None:
            return (0, 0)
        low = next((i for i, (_, start, _) in enumerate(words) if start >= span[0]), 0)
        high = next((i + 1 for i, (_, _, end) in enumerate(words) if end >= span[1]), len(words))
        return (low - first_token, high - first_token)

    def _exact_cluster(
        self,
        vrs: str,
        book: str,
        chapter: int,
        cluster: Sequence[int],
        tokens: Sequence[str],
        words: Sequence[tuple[str, int, int]],
        window: int,
        stride: int,
    ) -> Match | None:
        """Score one run of windows that all pointed at the same chapter, by spelling."""
        # A stride of slack either side, because a quotation that begins near the end of
        # one window and finishes in the next is only partly inside either of them.
        # _matched_span trims the slack back off once the alignment says where the
        # quotation really starts and stops.
        first_token = max(0, cluster[0] - stride)
        last_token = min(len(tokens), cluster[-1] + window + stride)
        query = tokens[first_token:last_token]
        if len(query) < _MIN_QUOTE_WORDS:
            return None

        terms = self._query_terms(query)
        candidates = self._candidates(terms, _CANDIDATES)
        verses = self._positions([text_id for text_id, _ in candidates]).get((vrs, book, chapter))
        if not verses:
            return None

        best: tuple[float, int, int, list[Witness]] | None = None
        rivals: list[tuple[float, int, int]] = []
        for first, last in self._runs(verses):
            start, end, witnesses = self._best_span(vrs, book, chapter, first, last, query)
            if not witnesses:
                continue
            rivals.extend(self._span_rivals(vrs, book, chapter, first, last, query))
            if best is None or witnesses[0].similarity > best[0]:
                best = (witnesses[0].similarity, start, end, witnesses)
        if best is None:
            return None

        _, start, end, witnesses = best
        meta = self._corpora[witnesses[0].corpus]
        trimmed = _matched_span(query, _tokens(witnesses[0].text, meta.language))
        if trimmed is None:
            return None
        low, high = first_token + trimmed[0], first_token + trimmed[1]
        if high - low < _MIN_QUOTE_WORDS:
            return None

        # Re-score against only the words that actually matched. The window this came from
        # is padded with whatever the speaker said either side of the quotation, and
        # leaving that in would drag a real quotation below the threshold.
        exact = self._witnesses(vrs, book, chapter, start, end, tokens[low:high])
        if not exact or not self._is_quotation(tokens[low:high], exact[0]):
            return None

        passage = VerseRange(
            VerseRef(book, chapter, start, vrs=vrs), VerseRef(book, chapter, end, vrs=vrs)
        )
        span = (words[low][1], words[high - 1][2])
        found = Match(
            passage,
            tuple(exact[:20]),
            span=span,
            quoted=_original(words, low, high),
            composed=self._composed,
            identified_at=self._identified,
            # The rule that found it, recorded. `_is_quotation` just measured this and
            # threw it away; a grade a caller cannot check is not evidence.
            run=longest_run(tokens[low:high], _tokens(exact[0].text, self._language_of(exact[0]))),
            formula=self._formula_before(words, low, self._language_of(exact[0])),
            alternates=self._near_ties(rivals, best[0], vrs, book, chapter, start, end),
        )
        return self._with_axes(found, tokens[low:high], exact[0])

    def _graded_cluster(
        self,
        vrs: str,
        book: str,
        chapter: int,
        query: Sequence[str],
        first_token: int,
        tokens: Sequence[str],
        words: Sequence[tuple[str, int, int]],
        masked: tuple[int, int] = (0, 0),
    ) -> list[Match]:
        """Look at one cluster again by dictionary form, and weigh what actually matched.

        The chain does three jobs at once here, which is why it is worth computing rather
        than merely counting. It says *whether* the words agree in the verse's order, it says
        *where* in the searched text they do, and the weight is then taken over exactly that
        stretch. So a quotation scores the same whether the sweep happened to cut it into one
        window or two -- a score that depended on the slicing was not a score of the quotation
        at all, and it is what made every figure measured through a window understate itself.
        """
        # The language of the corpora numbered this way, which is what decides whether there
        # is a lexicon to look in at all.
        language = next((m.language for m in self._corpora.values() if m.versification == vrs), "")
        if language not in LEMMA_LANGUAGES:
            return []
        lexicon, weights = self._lemma_tools(language)
        weigh = weights.of(language)
        mine, _ = self._readings(query, language, lexicon)
        for position in range(max(masked[0], 0), min(masked[1], len(mine))):
            # Words an exact match already answered for: not evidence twice.
            mine[position] = frozenset()

        terms = sorted(
            {lemma for reading in mine for lemma in reading}, key=lambda lemma: -weigh(lemma)
        )[:_QUERY_TERMS]
        candidates = self._lemma_candidates(terms, _CANDIDATES)
        verses = {
            key: found
            for key, (found, _) in self._located(
                [text_id for text_id, _ in candidates], {}, "lemma_ref"
            ).items()
        }.get((vrs, book, chapter))
        if not verses:
            return []

        # Every run's readings, once: the rounds of chaining below reuse them, and the
        # rivalry the alternates report is a property of the cluster, not of any one chain.
        runs: list[tuple[int, int, list[Reading]]] = []
        rivals: list[tuple[float, int, int]] = []
        for first, last in self._runs(verses):
            witnesses = self._witnesses(vrs, book, chapter, first, last, query)
            if not witnesses:
                continue
            theirs = lemma_readings(_tokens(witnesses[0].text, language), language, lexicon)
            if not lemma_chain(mine, theirs, weigh, concave=self._concave).length:
                continue
            runs.append((first, last, theirs))
            rivals.append((witnesses[0].similarity, first, last))
        if not runs:
            return []

        # One finding per disjoint chain. A sentence of 1 Clement 13:2 weaves five sayings,
        # and a single best chain reports one of them and structurally misses four whatever
        # its gates -- so the best chain is taken, its stretch of the text is masked, and
        # what remains is chained again until nothing chains. Each finding then stands on
        # its own axes and passes or fails the gates alone. A chain the gates refuse is
        # masked all the same, so the loop always moves.
        matches: list[Match] = []
        remaining = list(mine)
        for _ in range(_MAX_CHAINS):
            best: tuple[LemmaChain, int, int] | None = None
            for first, last, theirs in runs:
                chained = lemma_chain(remaining, theirs, weigh, concave=self._concave)
                if not chained.length:
                    continue
                if best is None or (chained.length, chained.bits) > (best[0].length, best[0].bits):
                    best = (chained, first, last)
            if best is None:
                break
            chained, start, end = best
            for position in range(*chained.span):
                remaining[position] = frozenset()
            found = self._chain_match(
                chained, vrs, book, chapter, start, end, first_token, tokens, words,
                language, weigh, lexicon, rivals,
            )
            if found is not None:
                matches.append(found)
        return matches

    def _chain_match(
        self,
        chained: LemmaChain,
        vrs: str,
        book: str,
        chapter: int,
        start: int,
        end: int,
        first_token: int,
        tokens: Sequence[str],
        words: Sequence[tuple[str, int, int]],
        language: str,
        weigh: Callable[[str], float],
        lexicon: Lexicon,
        rivals: Sequence[tuple[float, int, int]],
    ) -> Match | None:
        """One chain of a cluster weighed into a finding, or refused by the gates."""
        low, high = first_token + chained.span[0], first_token + chained.span[1]
        if high - low < _MIN_QUOTE_WORDS or high > len(words):
            return None

        # Re-read the verse against the trimmed span, so the witness that answers is the one
        # that answers *this* quotation rather than the padded window around it.
        held = self._witnesses(vrs, book, chapter, start, end, tokens[low:high])
        if not held:
            return None
        trimmed, re_read = self._readings(tokens[low:high], language, lexicon)
        graded = self._grade(
            trimmed,
            tokens[low:high],
            held[0],
            language,
            weigh,
            lexicon,
        )
        if graded is None:
            return None
        grade, run, found, chain_here, weight, evidence = graded
        return Match(
            VerseRange(
                VerseRef(book, chapter, start, vrs=vrs), VerseRef(book, chapter, end, vrs=vrs)
            ),
            tuple(held[:20]),
            span=(words[low][1], words[high - 1][2]),
            quoted=_original(words, low, high),
            composed=self._composed,
            identified_at=self._identified,
            grade=grade,
            run=run,
            lemma_run=found.length,
            chain=chain_here.length,
            bits=weight,
            matched_lemmas=evidence,
            formula=self._formula_before(words, low, language),
            itacised=bool(re_read),
            # The same rivalry the exact path reports. Leaving it off here meant a match
            # found by dictionary form -- which is most of what this feature exists to find
            # -- came back saying nothing else fitted, on cases where something else fitted
            # exactly as well.
            alternates=self._near_ties(
                rivals,
                max((score for score, _, _ in rivals), default=0.0),
                vrs,
                book,
                chapter,
                start,
                end,
            ),
        )


def _merge_passages(
    first: Sequence[VerseRange], second: Sequence[VerseRange]
) -> tuple[VerseRange, ...]:
    """Both lists of rivals, in order, without repeating a passage."""
    seen: dict[tuple[str, object, int, int], VerseRange] = {}
    for passage in (*first, *second):
        seen.setdefault(_coordinates(passage), passage)
    return tuple(seen.values())


def _coordinates(passage: VerseRange) -> tuple[str, object, int, int]:
    """Which verses a passage names, without saying which system numbered them.

    Two passages with these coordinates equal are one passage reached twice. A New Testament
    quotation is found in the English numbering and again in the Vulgate's, because the two
    agree there and both the Douay-Rheims and the Clementine are indexed. Where the systems
    genuinely disagree the coordinates differ, so nothing is conflated that should not be.
    """
    return (
        passage.book,
        passage.start.chapter,
        passage.start.verse,
        passage.end.verse,
    )


def _one_per_passage(matches: Sequence[Match]) -> list[Match]:
    """Collapse the same passage reached through different versifications.

    Reporting one passage twice would double-count every New Testament citation in a study.
    """
    kept: dict[tuple[str, object, int, int], Match] = {}
    for match in matches:
        key = _coordinates(match.passage)
        best = kept.get(key)
        if best is None or match.similarity > best.similarity:
            kept[key] = match
    return sorted(kept.values(), key=lambda m: -m.similarity)


def _offsets(count: int, window: int, stride: int) -> list[int]:
    """Where each sweep window starts, always including one that reaches the end.

    A plain stride leaves a tail shorter than the stride uncovered by any full window, so
    a quotation in the last few words of a document is seen only in part and rejected as
    too short. The closing window is what makes the end of a transcript as visible as the
    middle.
    """
    starts = list(range(0, max(1, count - window + 1), stride))
    final = max(0, count - window)
    if final not in starts:
        starts.append(final)
    return starts


def _clusters(windows: Sequence[int], gap: int = _CLUSTER_GAP) -> list[list[int]]:
    """Window offsets grouped into runs, so two quotations of one chapter stay apart."""
    if not windows:
        return []
    groups: list[list[int]] = [[windows[0]]]
    for offset in windows[1:]:
        if offset - groups[-1][-1] <= gap:
            groups[-1].append(offset)
        else:
            groups.append([offset])
    return groups


def _matched_span(query: Sequence[str], actual: Sequence[str]) -> tuple[int, int] | None:
    """Which slice of the query actually corresponds to the verse.

    A window is padded with the speaker's own words on both sides. The matching blocks
    say where the quotation sits inside it, which is what makes the reported character
    span the quotation rather than the window it was found in.

    Taking the first block to the last is the obvious reading and it is wrong: one stray
    late agreement -- a *not*, a *the* -- drags the span across everything in between. A
    transcript quoting Psalm 23 and then Ephesians 2 half a paragraph later had the psalm
    reported as spanning both, which swallowed the second quotation whole and lost it. So
    the span grows outward from the longest block and stops at the first real gap.

    A gap is measured on both sides. See :func:`_continues`.
    """
    blocks = [b for b in _matcher(query, actual).get_matching_blocks() if b.size]
    if not blocks:
        return None

    anchor = max(range(len(blocks)), key=lambda i: blocks[i].size)
    low, high = anchor, anchor
    while low > 0 and _continues(blocks[low - 1], blocks[low]):
        low -= 1
    while high + 1 < len(blocks) and _continues(blocks[high], blocks[high + 1]):
        high += 1
    return blocks[low].a, _end(blocks[high])


def _continues(earlier: Match_, later: Match_) -> bool:
    """Whether `later` carries the quotation on from `earlier`, or merely agrees with it.

    Both distances are bounded, because a quotation and its verse advance together. Only
    the searched-text side was bounded once, and a single common word standing where the
    verse had already moved on was enough to drag a span across the sentence after it.

    ``get_matching_blocks`` yields blocks increasing in both coordinates, so neither gap is
    ever negative.
    """
    return (
        later.a - _end(earlier) <= _SPAN_GAP
        and later.b - (int(earlier.b) + int(earlier.size)) <= _VERSE_GAP
    )


def _end(block: Match_) -> int:
    return int(block.a) + int(block.size)


def _original(words: Sequence[tuple[str, int, int]], low: int, high: int) -> str:
    return " ".join(word for word, _, _ in words[low:high])


def _without_overlaps(matches: Sequence[Match]) -> list[Match]:
    """Keep the best match wherever two claim the same words, recording near-ties.

    A sermon quoting one verse produces several overlapping candidates -- the same words
    read as slightly different spans, sometimes as neighbouring passages. Counting all of
    them would inflate every frequency this feeds.

    But a loser that scored nearly as well is not a duplicate; it is a genuine rival
    reading, and it is kept as an alternate rather than dropped. Which case it is depends
    only on how close the scores are.

    Two quotations that merely *touch* are neither. See :func:`_claims`.
    """
    kept: list[Match] = []
    rivals: dict[int, list[VerseRange]] = {}
    for match in matches:
        if match.span is None:
            kept.append(match)
            continue
        claimed = next(
            (index for index, other in enumerate(kept) if _claims(other, match)),
            None,
        )
        if claimed is None:
            kept.append(match)
            continue
        winner = kept[claimed]
        if winner.similarity - match.similarity > _TIE:
            continue
        # Compared on coordinates, not on the VerseRange: a passage found in two
        # versifications that agree there is one passage, and comparing the objects made
        # it its own alternate -- reporting `ambiguous` for a match nothing rivalled.
        here = _coordinates(match.passage)
        if here == _coordinates(winner.passage):
            continue
        seen = rivals.setdefault(claimed, [])
        if all(here != _coordinates(rival) for rival in seen):
            seen.append(match.passage)

    # `replace` rather than a fresh `Match`: the only thing being changed here is
    # `alternates`, and listing the other fields to carry them is how this silently dropped
    # `composed` and `identified_at` once already -- every scanned match then reported
    # anachronistic as False and ignored whatever threshold its Searcher had been given.
    # A field added to `Match` in future is carried by this without anybody remembering to.
    # Merged, not replaced. A match may already carry rivals from inside its own chapter --
    # Job 1:1 and Job 1:8 answer a quotation of the same four epithets equally well -- and
    # those are found one span at a time, where this looks across spans. Overwriting them
    # here is what made `alternates` come back empty on the cases it was most wanted for.
    resolved = [
        replace(m, alternates=_merge_passages(m.alternates, rivals.get(index, ())))
        for index, m in enumerate(kept)
    ]
    return sorted(resolved, key=lambda m: m.span or (0, 0))


def _claims(winner: Match, match: Match) -> bool:
    """Whether `winner` has already accounted for what `match` found.

    Three cases arrive here overlapping, and only two of them are one result:

    * **The same passage, read as two slightly different spans.** One result, always. A
      passage found through two versifications that agree there arrives this way too.
    * **Two passages over the same words** -- Psalm 14 and Psalm 53, Galatians 6:9 and
      2 Thessalonians 3:13. One result, and the loser becomes an alternate if it scored
      nearly as well.
    * **Two quotations written one after another.** Neighbours, not rivals. They share the
      space between them and sometimes a word, and a bare interval intersection -- which
      this used to be -- deleted the second of them for it.

    So a different passage has to claim *most* of the shorter span before it counts as
    reading the same words, while the same passage claims any overlap at all. Without that
    second clause the same verse came back twice from one sentence.
    """
    left, right = winner.span, match.span
    if left is None or right is None:
        return False
    shared = min(left[1], right[1]) - max(left[0], right[0])
    if shared <= 0:
        return False
    if _coordinates(winner.passage) == _coordinates(match.passage):
        return True
    return shared * 2 > min(left[1] - left[0], right[1] - right[0])


def scan_records(
    home: DataHome, text: str, *, corpora: Sequence[str] | None = None
) -> Iterator[str]:
    """JSONL, one line per quotation. The pipeline entry point."""
    with Searcher(home, corpora=corpora) as searcher:
        for match in searcher.scan(text):
            yield json.dumps(match.to_dict(), ensure_ascii=False)


# -- resolving the translation ----------------------------------------------------------

#: The translations to try, in the order worth trying them.
#:
#: Roughly by how much of English-speaking preaching each accounts for since 1901, because
#: the search stops at the first decisive match and the order is therefore the whole cost
#: model: getting it right means two or three requests per passage instead of thirteen.
#: ``KJV`` and ``ASV`` sit in the middle rather than the end because they are already held
#: locally and cost nothing to check.
RESOLUTION_ORDER: Final = (
    "KJV",
    "ASV",
    "NIV",
    "ESV",
    "NKJV",
    "NLT",
    "CSB",
    "NASB",
    "GNT",
    "RSV",
    "NIRV",
    "TLB",
    # Last, and rarely reached, because resolution can only name the translation for a
    # passage the search already found -- and a Message quotation is usually not found at
    # all. It is a paraphrase far enough from the underlying text that no public-domain
    # translation aligns with it, so there is nothing for resolution to act on. Kept here
    # because when a passage *is* identified some other way, one request can still settle
    # it, and left until last because most of the time it would be a request for nothing.
    "MSG",
)

#: Network fetches one resolution run may spend. A scan of a long sermon can easily find
#: forty unattributed passages, and thirteen versions each at a fifteen-second crawl delay
#: is over two hours of requests nobody asked for. The run stops and says so instead.
DEFAULT_BUDGET: Final = 25


@dataclass(frozen=True, slots=True)
class Resolution:
    """What resolving one passage cost and concluded."""

    match: Match
    checked: tuple[str, ...]
    """Versions actually scored, whether they matched or not."""
    fetched: int
    """Network requests spent. Zero when everything needed was already stored."""
    exhausted: bool = False
    """The budget ran out before every version could be checked."""

    @property
    def resolved(self) -> bool:
        return self.match.identified


class Resolver:
    """Names the translation for passages the local corpus could identify but not attribute.

    The corpus holds fifty-odd English translations and none of the thirteen best-selling
    ones, because every one of those is under live copyright and no publisher-sanctioned
    channel permits a complete local copy. So a quotation from the NIV locates its passage
    confidently and then matches nothing closely, which is a question this can answer by
    asking for that one passage.

    Three properties make that affordable rather than a euphemism for scraping:

    *It only asks about passages already identified.* Nothing is fetched speculatively, and
    a document with no unattributed quotations makes no requests at all.

    *It asks in likelihood order and stops at the first decisive answer.* Most quotations
    are from the first few versions tried.

    *It asks once, ever.* Chapters are stored permanently, so the second sermon quoting
    Romans 8 in the NIV is free and works offline -- and because a request costs the site
    the same whether it returns one verse or thirty, each one banks the whole chapter.
    """

    def __init__(
        self,
        home: DataHome,
        searcher: Searcher,
        *,
        versions: Sequence[str] = RESOLUTION_ORDER,
        budget: int = DEFAULT_BUDGET,
        offline: bool = False,
        report: Reporter = _silent,
    ) -> None:
        self._home = home
        self._searcher = searcher
        self._versions = tuple(versions)
        self._remaining = budget
        self._offline = offline
        self._report = report
        self._providers: dict[str, BibleGatewayCorpus] = {}
        self._touched: set[str] = set()
        self._spent = 0

    @property
    def spent(self) -> int:
        """Network requests made so far."""
        return self._spent

    @property
    def touched(self) -> tuple[str, ...]:
        """Corpora that gained chapters, and so need reindexing for search."""
        return tuple(sorted(self._touched))

    def needs_resolution(self, match: Match) -> bool:
        """Whether this match still leaves the question open.

        Not simply "is it unattributed". A quotation of the NIV scores 87% against the
        Berean Standard Bible and is reported as attributed -- to Berean, tied with eight
        World English variants. That is a true statement and not an answer to the question
        being asked, which is which of the thirteen best-selling English Bibles the speaker
        was reading from. So the test is whether one of *those* is the decisive winner.
        """
        if not match.decisive:
            return True
        return match.witnesses[0].corpus.upper() not in {v.upper() for v in self._versions}

    def resolve(self, match: Match, quoted: str) -> Resolution:
        """Try to name the translation behind one match."""
        if not self.needs_resolution(match):
            return Resolution(match, (), 0)

        query = _tokens(quoted)
        if len(query) < _MIN_QUOTE_WORDS:
            return Resolution(match, (), 0)

        refs = _passage_refs(match.passage)
        if refs is None:
            return Resolution(match, (), 0)

        found: list[Witness] = list(match.witnesses)
        checked: list[str] = []
        spent_here = 0
        exhausted = False

        for version in self._versions:
            corpus = version.lower()

            # Whatever is already on disk is free, however it got there -- built in bulk
            # from an archive, or accumulated a chapter at a time by an earlier run. Those
            # two arrive by different routes and the difference must not leak out here, or
            # a version we already hold gets fetched over the network anyway.
            witness: Witness | None
            held = self._stored(corpus, refs)
            if held is not None:
                witness = Witness(corpus, self._label(version), held, _ratio(query, _tokens(held)))
            else:
                if self._offline:
                    continue
                cost = self._cost(corpus, refs)
                if cost > self._remaining:
                    exhausted = True
                    break
                witness = self._score(version, refs, query)
                # Charged whether or not the version answered. The request was made either
                # way, and a budget that only counts successes is not a ceiling on anything.
                self._remaining -= cost
                self._spent += cost
                spent_here += cost

            if witness is None:
                continue
            checked.append(version)
            found.append(witness)
            if witness.similarity >= IDENTIFIED:
                self._report(f"resolve: {match.passage.pretty()} -> {version}")
                break

        found.sort(key=lambda w: (-w.similarity, w.corpus))
        return Resolution(
            Match(
                match.passage,
                tuple(found[:20]),
                span=match.span,
                quoted=match.quoted,
                alternates=match.alternates,
            ),
            tuple(checked),
            spent_here,
            exhausted,
        )

    # -- one version --------------------------------------------------------------------

    def _label(self, version: str) -> str:
        local = self._searcher.corpora.get(version.lower())
        return local.label if local else KNOWN_VERSIONS.get(version, version)

    def _stored(self, corpus: str, refs: Sequence[VerseRef]) -> str | None:
        """The passage as this corpus already has it, or ``None`` if any of it is missing.

        Read straight from the verse store rather than through ``read_chapter``, which
        gates on ``chapter_state`` and so only sees corpora assembled a chapter at a time.
        A translation built in bulk from an archive has no such rows, and asking the
        network for a verse already sitting on disk would be the worst kind of waste.
        """
        texts: list[str] = []
        for ref in refs:
            row = self._searcher.verse(corpus, ref)
            if row is None:
                return None
            texts.append(row)
        joined = " ".join(texts).strip()
        return joined or None

    def _cost(self, corpus: str, refs: Sequence[VerseRef]) -> int:
        """Requests this version would cost: zero if its chapters are already stored."""
        chapters = {(ref.book, int(ref.chapter)) for ref in refs}
        return sum(
            1
            for book, chapter in chapters
            if read_chapter(self._home, corpus, book, chapter) is None
        )

    def _score(
        self, version: str, refs: Sequence[VerseRef], query: Sequence[str]
    ) -> Witness | None:
        provider = self._provider(version)
        try:
            verses = provider.fetch(list(refs))
        except (CorpusError, VerseUnavailable, OSError):
            # A version that does not carry the passage, or a request that failed, is not
            # an answer about the translation and must not be recorded as one.
            return None
        self._touched.add(version.lower())
        text = " ".join(verse.text for verse in verses).strip()
        if not text:
            return None
        return Witness(version.lower(), provider.label, text, _ratio(query, _tokens(text)))

    def _provider(self, version: str) -> BibleGatewayCorpus:
        cached = self._providers.get(version)
        if cached is None:
            cached = BibleGatewayCorpus(version, self._home, offline=self._offline)
            self._providers[version] = cached
        return cached


def _passage_refs(passage: VerseRange) -> list[VerseRef] | None:
    """Every verse of a passage, in the numbering the online versions use.

    Returns ``None`` where the passage cannot be expressed in that numbering -- the
    Septuagint psalms, the Vulgate's Esther -- because asking BibleGateway for a
    coordinate that means something else there would answer confidently and wrongly.
    """
    if passage.start.is_letter_chapter or passage.end.is_letter_chapter:
        return None
    refs = [
        VerseRef(passage.book, passage.start.chapter, verse, vrs=passage.vrs)
        for verse in range(passage.start.verse, passage.end.verse + 1)
    ]
    if passage.vrs == "eng":
        return refs

    versification = Versification.load()
    converted: list[VerseRef] = []
    for ref in refs:
        try:
            converted.extend(versification.convert_all(ref, "eng"))
        except VersificationError:
            return None
    return converted or None
