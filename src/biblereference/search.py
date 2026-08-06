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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import Match as Match_
from difflib import SequenceMatcher
from typing import Final

from .corpora.base import CorpusError, VerseUnavailable
from .corpora.web import KNOWN_VERSIONS, BibleGatewayCorpus
from .dating import translated as _translated
from .emphasis import fold
from .refs import VerseRange, VerseRef
from .store import DataHome, open_store, read_chapter
from .versification import Versification, VersificationError

__all__ = [
    "COVERAGE",
    "DEFAULT_BUDGET",
    "DEFAULT_MARGIN",
    "IDENTIFIED",
    "QUOTATION",
    "RESOLUTION_ORDER",
    "IndexResult",
    "Match",
    "Resolution",
    "Resolver",
    "ScaledRun",
    "Searcher",
    "Witness",
    "build_index",
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
        "INSERT OR REPLACE INTO search_state (corpus, indexed_at, verses) VALUES (?, ?, ?)",
        (corpus, datetime.now(UTC).isoformat(timespec="seconds"), count),
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


def recount_df(connection: sqlite3.Connection, report: Reporter = _silent) -> None:
    """Recount how many distinct texts each word appears in.

    Counted over whole texts rather than whole verses on purpose: a sentence carried
    identically by twenty translations is one piece of evidence about how common its words
    are, not twenty.
    """
    connection.execute("DELETE FROM search_df")
    counts: dict[str, int] = {}
    for (text,) in connection.execute("SELECT text FROM search_fts"):
        for token in set(_WORD_RE.findall(text)):
            counts[token] = counts.get(token, 0) + 1
    connection.executemany(
        "INSERT INTO search_df (token, docs) VALUES (?, ?)", sorted(counts.items())
    )
    report(f"search: {len(counts):,} distinct words")


def index_is_stale(home: DataHome) -> list[str]:
    """Corpora whose verse count no longer matches what was indexed for them."""
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute(
                "SELECT m.corpus, m.verse_count, COALESCE(s.verses, -1) "
                "FROM source_meta m LEFT JOIN search_state s ON s.corpus = m.corpus"
            ).fetchall()
        except sqlite3.OperationalError:  # pragma: no cover - database not built yet
            return []
    return [str(corpus) for corpus, stored, indexed in rows if stored != indexed]


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
    ) -> None:
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
        self._quotation = quotation
        self._coverage = coverage
        self._identified = identified
        self._min_run = min_run
        self._min_query = min_query
        self._connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        self._corpora = self._load_corpora(corpora, families, languages)
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
        only: Sequence[str] | None,
        families: Sequence[str] | None,
        languages: Sequence[str] | None,
    ) -> dict[str, _Corpus]:
        rows = self._connection.execute(
            "SELECT corpus, label, language, versification FROM source_meta"
        )
        loaded = {
            str(corpus): _Corpus(str(label), str(language), str(versification))
            for corpus, label, language, versification in rows
        }
        if only is not None:
            wanted = set(only)
            loaded = {c: m for c, m in loaded.items() if c in wanted}
        if families is not None:
            chosen = set(families)
            loaded = {c: m for c, m in loaded.items() if m.versification in chosen}
        if languages is not None:
            spoken = set(languages)
            loaded = {c: m for c, m in loaded.items() if m.language in spoken}
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
        self, text_ids: Sequence[int], scores: Mapping[int, float]
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
            f"SELECT corpus, book, chapter, verse, text_id "
            f"FROM search_ref WHERE text_id IN ({marks})",
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
                )
            )

        matches.sort(key=lambda m: -m.similarity)
        return _one_per_passage(matches)[:limit]

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
                found = self._score_cluster(
                    vrs, book, chapter, cluster, tokens, words, window, stride
                )
                if found is not None:
                    matches.append(found)

        matches.sort(key=lambda m: (-m.similarity, m.span or (0, 0)))
        return _without_overlaps(matches)

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

        ranked = sorted(votes, key=lambda key: weight[key])
        return [(key, votes[key]) for key in ranked[:_SCAN_CHAPTERS]]

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
    ) -> Match | None:
        """Score one run of windows that all pointed at the same chapter."""
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
        for first, last in self._runs(verses):
            start, end, witnesses = self._best_span(vrs, book, chapter, first, last, query)
            if witnesses and (best is None or witnesses[0].similarity > best[0]):
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
        return Match(
            passage,
            tuple(exact[:20]),
            span=span,
            quoted=_original(words, low, high),
            composed=self._composed,
            identified_at=self._identified,
        )


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

    resolved = [
        Match(
            m.passage,
            m.witnesses,
            span=m.span,
            quoted=m.quoted,
            alternates=tuple(rivals.get(index, ())),
            # Carried, not dropped. Rebuilding without them made every scanned match report
            # anachronistic as False and ignore a Searcher's configured identified
            # threshold, whatever it had been asked for.
            composed=m.composed,
            identified_at=m.identified_at,
        )
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
