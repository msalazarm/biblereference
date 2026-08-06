"""Checking that the versification mappings are actually right.

A wrong mapping does not fail. It answers, confidently, with the verse next door, and
everything built on it is quietly wrong ever after. So the mappings need an instrument
pointed at them, and the instrument needs to be one whose failures are visible.

**The test is differential, not absolute.** Two translations of one verse can share almost
no words -- the Douay-Rheims and the Orthodox Jewish Bible render Psalm 23:1 at 0.15
similarity, and they are unquestionably the same verse -- so a threshold on similarity
would reject the truth and accept nothing useful. What survives translation is *relative*
position: the right verse still resembles its counterpart more than its neighbours do. So
every check asks which of several candidate positions scores best, and passes when the
answer is the one the mapping claims. Measured on real pairs, that verdict was correct
even where the absolute score was 0.15.

**Comparison is same-language wherever possible.** Asking whether a Hebrew verse and a
Greek one are "the same" conflates two questions; comparing the Brenton Septuagint against
the Douay-Rheims -- both English, translated from the two traditions being aligned --
asks only the one that matters. Seven of the ten family pairs have such a witness. The
three that do not all involve the Nova Vulgata, which this repository holds only in Latin;
those go to :mod:`biblereference.judge` instead.

**Every verse is checked, not only the mapped ones.** A mapping file records exceptions,
so a verse it does not mention is *asserted* to be identical across systems. That
assertion is exactly as capable of being wrong as an explicit mapping, and only a sweep
over everything can catch a mapping that should exist and does not.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final

from .canon import CANONICAL_ORDER, book_title
from .emphasis import fold
from .refs import VerseRef
from .store import DataHome
from .versification import PIVOT, Versification, VersificationError

__all__ = [
    "OFFSETS",
    "WITNESSES",
    "Alignment",
    "Coverage",
    "Disagreement",
    "PairResult",
    "Witness",
    "audit_all",
    "audit_pair",
    "runs_of",
    "verify_every_verse",
    "witness_pairs",
]


@dataclass(frozen=True, slots=True)
class Witness:
    """A corpus standing in for its versification family in some language."""

    corpus: str
    family: str
    language: str


#: Which corpus speaks for each family, and in what language. Chosen so that the two sides
#: of every comparison are in the same language: the point is to test the numbering, and a
#: translation gap in the middle of the measurement would test that instead.
#:
#: ``web`` rather than ``asv`` for the English family because it carries the deuterocanon,
#: without which two thirds of the interesting disagreements are unreachable.
WITNESSES: Final[dict[tuple[str, str], Witness]] = {
    ("org", "en"): Witness("ojb", "org", "en"),
    ("org", "syc"): Witness("peshitta-ot", "org", "syc"),
    ("eng", "en"): Witness("web", "eng", "en"),
    ("lxx", "en"): Witness("brenton", "lxx", "en"),
    ("lxx", "grc"): Witness("rahlfs", "lxx", "grc"),
    ("vul", "en"): Witness("dra", "vul", "en"),
    ("vul", "la"): Witness("latvuc", "vul", "la"),
    ("nvl", "la"): Witness("novavulgata", "nvl", "la"),
}

#: Candidate positions tried around the one the mapping claims. Two either way is enough:
#: versification faults are off-by-one and off-by-two errors, and a wider window starts
#: catching genuinely similar neighbouring verses in repetitive passages.
OFFSETS: Final = (-2, -1, 0, 1, 2)

#: How much better a rival position must score before the mapping is called into question.
#: Below this the two are not distinguishable and reporting a fault would be noise.
MARGIN: Final = 0.05

#: Below this the verses have too little in common for their relative scores to mean
#: anything -- often because one side genuinely translates a different source text, as the
#: Vulgate's Sirach does. Reported separately as weak rather than wrong.
FLOOR: Final = 0.10

_WORD_RE: Final = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str, language: str) -> list[str]:
    return _WORD_RE.findall(fold(text, language))


def _ratio(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


@dataclass(frozen=True, slots=True)
class Alignment:
    """One verse's worth of evidence about one mapping."""

    source: VerseRef
    mapped: VerseRef
    scores: tuple[float, ...]
    """Similarity at each of :data:`OFFSETS`, in that order."""

    @property
    def at_mapping(self) -> float:
        return self.scores[OFFSETS.index(0)]

    @property
    def best_offset(self) -> int:
        return OFFSETS[max(range(len(OFFSETS)), key=lambda i: self.scores[i])]

    @property
    def best_score(self) -> float:
        return max(self.scores)

    @property
    def agrees(self) -> bool:
        """Whether the mapping's own position is the best explanation of the text."""
        return self.best_offset == 0 or self.best_score - self.at_mapping < MARGIN

    @property
    def weak(self) -> bool:
        """Too little shared vocabulary for the comparison to carry weight either way."""
        return self.best_score < FLOOR


@dataclass(frozen=True, slots=True)
class Disagreement:
    """A verse whose text is better explained by a position the mapping does not claim."""

    alignment: Alignment
    source_text: str
    mapped_text: str
    better_text: str

    def describe(self) -> str:
        a = self.alignment
        return (
            f"{a.source.pretty()} ({a.source.vrs}) -> {a.mapped.pretty()} ({a.mapped.vrs}) "
            f"scores {a.at_mapping:.2f}, but offset {a.best_offset:+d} scores "
            f"{a.best_score:.2f}"
        )


@dataclass
class PairResult:
    """What one family pair's audit found."""

    source: str
    target: str
    language: str
    source_corpus: str
    target_corpus: str
    compared: int = 0
    agreed: int = 0
    weak: int = 0
    unmapped: int = 0
    """Verses the versification refused to convert -- a stated refusal, not a fault."""
    missing: int = 0
    """Verses one witness or the other simply does not carry."""
    disagreements: list[Disagreement] = field(default_factory=list)

    @property
    def decisive(self) -> int:
        """Comparisons strong enough to mean something."""
        return self.compared - self.weak

    @property
    def rate(self) -> float:
        return self.agreed / self.decisive if self.decisive else 0.0

    def summary(self) -> str:
        return (
            f"{self.source}->{self.target} via {self.source_corpus}/{self.target_corpus} "
            f"({self.language}): {self.agreed:,}/{self.decisive:,} decisive comparisons "
            f"agree ({self.rate:.2%}), {len(self.disagreements)} flagged, "
            f"{self.weak:,} too weak to judge, {self.unmapped:,} unmapped"
        )


def witness_pairs() -> list[tuple[Witness, Witness]]:
    """Every family pair that can be checked with both sides in one language."""
    pairs: list[tuple[Witness, Witness]] = []
    families = ["org", "eng", "lxx", "vul", "nvl"]
    # Derived from the table rather than written out, so that adding a witness in a new
    # language cannot be silently ignored -- which is what a hardcoded ("la", "en") did to
    # the Syriac when it arrived. Latin first for the reason below; the rest by name, so
    # the order is at least stable.
    languages = ["la", *sorted({key[1] for key in WITNESSES} - {"la"})]
    for i, left in enumerate(families):
        for right in families[i + 1 :]:
            shared = [
                (WITNESSES[(left, lang)], WITNESSES[(right, lang)])
                for lang in languages
                if (left, lang) in WITNESSES and (right, lang) in WITNESSES
            ]
            # Latin first where both exist: comparing two Latin editions measures the
            # numbering almost alone, with no translator standing between the texts.
            if shared:
                pairs.append(shared[0])
    return pairs


class _Texts:
    """Verse lookup straight from the store, cached per chapter."""

    def __init__(self, home: DataHome) -> None:
        self._connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        self._cache: dict[tuple[str, str, int], dict[int, str]] = {}

    def chapter(self, corpus: str, book: str, chapter: int) -> dict[int, str]:
        key = (corpus, book, chapter)
        if key not in self._cache:
            rows = self._connection.execute(
                "SELECT verse, text FROM verse WHERE corpus = ? AND book = ? AND chapter = ?",
                (corpus, book, chapter),
            )
            self._cache[key] = {int(v): str(t) for v, t in rows}
        return self._cache[key]

    def verse(self, corpus: str, ref: VerseRef) -> str | None:
        return self.chapter(corpus, ref.book, int(ref.chapter)).get(ref.verse)

    def close(self) -> None:
        self._connection.close()


def _verses_of(vrs: Versification, system: str, books: Sequence[str] | None) -> Iterator[VerseRef]:
    """Every verse the system defines, in reading order."""
    for book in books or CANONICAL_ORDER:
        chapters = vrs.chapter_count(system, book)
        for chapter in range(1, chapters + 1):
            try:
                first = vrs.first_verse(system, book, chapter)
                last = vrs.max_verse(system, book, chapter)
            except VersificationError:  # pragma: no cover - chapter_count already gated
                continue
            for verse in range(first, last + 1):
                yield VerseRef(book, chapter, verse, vrs=system)


def audit_pair(
    home: DataHome,
    vrs: Versification,
    left: Witness,
    right: Witness,
    *,
    books: Sequence[str] | None = None,
    texts: _Texts | None = None,
    covering: bool = False,
) -> PairResult:
    """Check every mapping between two families against the text of their witnesses.

    Walks the whole of the source system rather than only its declared mappings, because
    a verse with no mapping is asserting that none is needed, and that assertion can be
    wrong in exactly the same way.

    :param covering: Judge the mapping against every verse it covers rather than only the
        one it names. Where an edition merges two verses the aligner lands on whichever
        half carries more text, which need not be the half the exact mapping names -- so
        a correct mapping reads as a disagreement, and correcting one can *raise* the
        count. Matthew 5 and Malachi 3 both did that. This measures the claim the data is
        actually making.
    """
    own = texts is None
    store = texts or _Texts(home)
    result = PairResult(left.family, right.family, left.language, left.corpus, right.corpus)

    try:
        for source in _verses_of(vrs, left.family, books):
            source_text = store.verse(left.corpus, source)
            if not source_text:
                result.missing += 1
                continue
            try:
                targets = vrs.convert_all(source, right.family, covering=covering)
            except VersificationError:
                result.unmapped += 1
                continue
            if not targets:
                result.unmapped += 1
                continue

            # Where the mapping covers more than one verse, any of them agreeing settles
            # it: the text is spread across all of them, and asking the aligner to have
            # picked a particular half is asking it to do something it cannot.
            mapped = targets[0]
            alignment = _score(store, right, source, mapped, source_text)
            for other in targets[1:]:
                if alignment is not None and alignment.agrees:
                    break
                alternative = _score(store, right, source, other, source_text)
                if alternative is not None and alternative.agrees:
                    mapped, alignment = other, alternative
            if alignment is None:
                result.missing += 1
                continue

            result.compared += 1
            if alignment.weak:
                result.weak += 1
                continue
            if alignment.agrees:
                result.agreed += 1
                continue
            better = mapped.__class__(
                mapped.book, mapped.chapter, mapped.verse + alignment.best_offset, vrs=mapped.vrs
            )
            result.disagreements.append(
                Disagreement(
                    alignment,
                    source_text,
                    store.verse(right.corpus, mapped) or "",
                    store.verse(right.corpus, better) or "",
                )
            )
    finally:
        if own:
            store.close()
    return result


def _score(
    store: _Texts, right: Witness, source: VerseRef, mapped: VerseRef, source_text: str
) -> Alignment | None:
    """Similarity of the source verse against the mapped position and its neighbours."""
    tokens = _tokens(source_text, right.language)
    chapter = store.chapter(right.corpus, mapped.book, int(mapped.chapter))
    if mapped.verse not in chapter:
        return None

    scores: list[float] = []
    for offset in OFFSETS:
        other = chapter.get(mapped.verse + offset)
        scores.append(_ratio(tokens, _tokens(other, right.language)) if other else 0.0)
    return Alignment(source, mapped, tuple(scores))


def audit_all(
    home: DataHome,
    *,
    books: Sequence[str] | None = None,
    pairs: Sequence[tuple[Witness, Witness]] | None = None,
    report: object = None,
    covering: bool = False,
) -> list[PairResult]:
    """Audit every family pair that has a same-language witness on both sides."""
    vrs = Versification.load()
    texts = _Texts(home)
    try:
        return [
            audit_pair(home, vrs, left, right, books=books, texts=texts, covering=covering)
            for left, right in (pairs if pairs is not None else witness_pairs())
        ]
    finally:
        texts.close()


@dataclass(frozen=True, slots=True)
class Membership:
    """Whether one corpus really is numbered the way its family says."""

    corpus: str
    family: str
    compared: int
    aligned: int
    """Verses where the corpus and the reference agree at the same coordinate."""
    shifted: dict[int, int]
    """How many verses aligned better at each non-zero offset."""

    @property
    def rate(self) -> float:
        return self.aligned / self.compared if self.compared else 0.0

    @property
    def belongs(self) -> bool:
        return self.rate >= 0.95

    def describe(self) -> str:
        worst = max(self.shifted.items(), key=lambda kv: kv[1], default=(0, 0))
        tail = f", worst drift {worst[1]} verses at {worst[0]:+d}" if worst[1] else ""
        return (
            f"{self.corpus:12} {self.rate:6.2%} of {self.compared:,} verses align"
            f"{tail}{'' if self.belongs else '   <-- does not belong here'}"
        )


def family_membership(
    home: DataHome,
    reference: str,
    corpora: Sequence[str],
    *,
    family: str = "eng",
    books: Sequence[str] | None = None,
    texts: _Texts | None = None,
) -> list[Membership]:
    """Check that corpora filed under one family really are numbered alike.

    Compares each against one reference rather than against each other. Alignment is
    transitive enough for this: if every corpus agrees with the ASV verse for verse, they
    agree with one another, and the pairwise graph would cost twenty times as much to
    establish the same thing. What it buys over the build-time check in
    :func:`biblereference.corpora.ebible.best_fit_versification` is depth -- that compares
    where chapters *end*, so a translation shifted in the middle of a chapter and shifted
    back by its close would pass. This compares every verse.
    """
    own = texts is None
    store = texts or _Texts(home)
    out: list[Membership] = []
    try:
        for corpus in corpora:
            if corpus == reference:
                continue
            compared = aligned = 0
            shifted: dict[int, int] = {}
            for book in books or CANONICAL_ORDER:
                for chapter in range(1, 200):
                    left = store.chapter(reference, book, chapter)
                    if not left:
                        break
                    right = store.chapter(corpus, book, chapter)
                    if not right:
                        continue
                    for verse, text in left.items():
                        if verse not in right:
                            continue
                        tokens = _tokens(text, "en")
                        scores = {
                            offset: _ratio(tokens, _tokens(right[verse + offset], "en"))
                            for offset in OFFSETS
                            if verse + offset in right
                        }
                        if not scores or max(scores.values()) < FLOOR:
                            continue
                        compared += 1
                        best = max(scores, key=lambda k: scores[k])
                        if best == 0 or scores[best] - scores.get(0, 0.0) < MARGIN:
                            aligned += 1
                        else:
                            shifted[best] = shifted.get(best, 0) + 1
            out.append(Membership(corpus, family, compared, aligned, shifted))
    finally:
        if own:
            store.close()
    return sorted(out, key=lambda m: m.rate)


def book_of(disagreements: Sequence[Disagreement]) -> dict[str, int]:
    """How the flagged verses fall across books, which is how a systematic fault shows."""
    counts: dict[str, int] = {}
    for item in disagreements:
        title = book_title(item.alignment.source.book)
        counts[title] = counts.get(title, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def home_default() -> Path:
    return DataHome().root


# --------------------------------------------------------------------------------------
# Deriving a mapping, rather than checking one
# --------------------------------------------------------------------------------------
#
# Everything above *verifies*: it takes the mapping's answer and asks whether the text
# prefers it to its immediate neighbours. That is the right instrument for the job and the
# wrong one for a different job, because a window of two verses cannot find a mapping it was
# not already told about. The Psalms run a whole chapter out between families; Greek Daniel
# further. So deriving needs a wider search and a stronger constraint to keep it honest.
#
# The constraint is **monotonicity**. Editions renumber verses, split them and merge them,
# but they do not reorder scripture: if verse A precedes verse B in one edition, whatever
# they correspond to keeps that order in the other. A per-verse argmax over a wide window
# has no such discipline and will happily match Psalm 14 to Psalm 53, which really are near
# duplicates. A monotonic alignment cannot.
#
# The exception is real and is reported rather than hidden: Septuagint Jeremiah moves the
# oracles against the nations bodily to the middle of the book. No monotonic alignment can
# describe that, so the quality score for such a book collapses and it is excluded from the
# derivation instead of producing a confident wrong answer.


#: Verses either side of the diagonal the alignment will consider.
#:
#: Set by the worst real case rather than by taste, and 60 is not enough. Superscriptions
#: are the reason: the Septuagint numbers a psalm's title as its first verse and the English
#: tradition does not store it at all, so Brenton carries about a hundred verses the World
#: English Bible has no row for. The displacement is cumulative down the whole Psalter, and
#: at a band of 60 the alignment ran out of room around Psalm 89 and shifted every remaining
#: psalm by one -- 1,030 disagreements that were the instrument's, not the data's.
#:
#: The cost is linear in this number. Psalms is 2,461 verses, so a band of 200 is a million
#: cells and about a second.
BAND: Final = 200


def faithful_chapters(
    home: DataHome, corpus: str, system: str, vrs: Versification
) -> set[tuple[str, int]]:
    """Chapters where this corpus numbers its verses exactly as the system says.

    The idea this replaces was to pick, per family, the one corpus that *is* the system and
    compare those. It does not survive contact with the corpus: measured against the shipped
    systems, `org` has an exact witness only in Hebrew and Greek, `eng` only in English,
    `nvl` only in Latin -- so no two faithful witnesses share a language and the
    same-language test could not run at all. Worse, `lxx` and `vul` have no faithful witness
    in any language, which is why every audit of them was quietly measuring the gap between
    the system and the nearest edition rather than the mapping.

    Restricting rather than discarding rescues it. A witness wrong on ten chapters is right
    on the other 1,179, and a comparison confined to chapters where *both* sides are faithful
    is sound even though neither corpus is faithful throughout. That is the difference
    between an audit that covers 99% of the text and one that cannot start.

    Verse 0 is a superscription rather than a verse and is excluded from both sides.

    **Which leaves one blind spot, in the Psalms.** The exclusion clamps the system's first
    verse to 1, so a corpus that numbers a psalm's title as verse 1 -- where its system
    numbers it 0 -- looks faithful and is off by one all the way down the psalm. Brenton
    does exactly that, and 137 of the 138 titled psalms count as faithful for it.

    Left as it is on purpose. The Copenhagen data models a superscription as verse 0 in the
    mappings while ``org``'s own verse counts number it 1 -- the Leningrad Codex's Psalm
    13:1 is the title and org gives the psalm six verses -- so the two conventions disagree
    upstream and no rule here can reconcile them. Measured over the whole derivation it
    costs seven flagged rows, all in the Psalms, which is a smaller error than any repair
    attempted from this side would be.
    """
    connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT book, chapter, MIN(verse), MAX(verse), COUNT(DISTINCT verse) FROM verse "
            "WHERE corpus = ? AND verse > 0 GROUP BY book, chapter",
            (corpus,),
        ).fetchall()
    finally:
        connection.close()

    out: set[tuple[str, int]] = set()
    for book, chapter, low, high, count in rows:
        if count != high - low + 1:  # a gap: the edition did not print the whole chapter
            continue
        try:
            first = max(vrs.first_verse(system, str(book), int(chapter)), 1)
            last = vrs.max_verse(system, str(book), int(chapter))
        except VersificationError:
            continue
        if (low, high) == (first, last):
            out.add((str(book), int(chapter)))
    return out


#: What an unmatched verse costs. Deliberately small relative to a good match: editions
#: genuinely add and drop verses, and a gap has to be cheaper than a bad pairing or the
#: alignment will invent correspondences to avoid it.
GAP: Final = -0.15

#: Below this mean score over the aligned pairs, the alignment is not describing the book.
#: Either the two editions translate different source texts, or the correspondence is not
#: monotonic and no alignment of this kind can hold it.
MIN_QUALITY: Final = 0.25


def _shingles(text: str, language: str) -> frozenset[str]:
    """Token set for the fast similarity used inside the alignment.

    Jaccard over token sets rather than :func:`_ratio`, which is thirty times slower: the
    alignment scores hundreds of thousands of candidate pairings per book, and the ordering
    information a sequence matcher adds is exactly what the monotonicity constraint is
    already supplying. The chosen path is rescored properly afterwards.
    """
    return frozenset(_tokens(text, language))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True, slots=True)
class BookAlignment:
    """One book aligned between two witnesses, with no mapping consulted."""

    book: str
    pairs: tuple[tuple[VerseRef | None, VerseRef | None], ...]
    """Corresponding verses in reading order. A ``None`` on either side is a verse the
    other edition has nothing for."""
    quality: float
    """Mean similarity over the pairs where both sides are present."""

    @property
    def reliable(self) -> bool:
        return self.quality >= MIN_QUALITY

    @property
    def matched(self) -> tuple[tuple[VerseRef, VerseRef], ...]:
        return tuple((a, b) for a, b in self.pairs if a is not None and b is not None)


def align_book(
    left: Sequence[tuple[VerseRef, str]],
    right: Sequence[tuple[VerseRef, str]],
    *,
    language: str,
    right_language: str | None = None,
    band: int = BAND,
    gap: float = GAP,
) -> tuple[tuple[VerseRef | None, VerseRef | None], ...]:
    """Best monotonic correspondence between two verse sequences.

    Needleman-Wunsch restricted to a diagonal band. The band is what makes it affordable --
    Psalms is 2,461 verses, so the full matrix is six million cells and the band is three
    hundred thousand -- and it is safe because a displacement wider than the band would be a
    reordering, which monotonic alignment cannot describe anyway.
    """
    n, m = len(left), len(right)
    if not n or not m:
        return tuple((a, None) for a, _ in left) + tuple((None, b) for b, _ in right)

    # Folded in each side's own language: the transformations are language-specific, and
    # Latin's i/j and u/v normalisation applied to English is simply wrong.
    left_sets = [_shingles(text, language) for _, text in left]
    right_sets = [_shingles(text, right_language or language) for _, text in right]

    width = 2 * band + 1
    low = float("-inf")
    # score[i][d] is the best score for left[:i] against right[:j], where j = i - band + d.
    score = [[low] * width for _ in range(n + 1)]
    back = [[0] * width for _ in range(n + 1)]

    def cell(i: int, j: int) -> int | None:
        d = j - i + band
        return d if 0 <= d < width else None

    start = cell(0, 0)
    if start is not None:
        score[0][start] = 0.0
    for j in range(1, min(m, band) + 1):
        d = cell(0, j)
        if d is not None:
            score[0][d] = gap * j
            back[0][d] = 2

    for i in range(1, n + 1):
        for d in range(width):
            j = i - band + d
            if j < 0 or j > m:
                continue
            best, choice = low, 0
            if j >= 1 and score[i - 1][d] > low:  # diagonal: consume both
                value = score[i - 1][d] + _jaccard(left_sets[i - 1], right_sets[j - 1])
                if value > best:
                    best, choice = value, 1
            if d + 1 < width and score[i - 1][d + 1] > low:  # consume left only
                value = score[i - 1][d + 1] + gap
                if value > best:
                    best, choice = value, 3
            if d >= 1 and j >= 1 and score[i][d - 1] > low:  # consume right only
                value = score[i][d - 1] + gap
                if value > best:
                    best, choice = value, 2
            score[i][d], back[i][d] = best, choice

    # Walk back from (n, m), or from the best reachable end if the band excludes it.
    d = cell(n, m)
    if d is None or score[n][d] == low:
        candidates = [(score[n][x], x) for x in range(width) if score[n][x] > low]
        if not candidates:
            return tuple((a, None) for a, _ in left) + tuple((None, b) for b, _ in right)
        d = max(candidates)[1]

    i, j = n, n - band + d
    out: list[tuple[VerseRef | None, VerseRef | None]] = []
    while i > 0 or j > 0:
        move = back[i][j - i + band] if 0 <= j - i + band < width else 0
        if move == 1:
            out.append((left[i - 1][0], right[j - 1][0]))
            i, j = i - 1, j - 1
        elif move == 2:
            out.append((None, right[j - 1][0]))
            j -= 1
        elif move == 3 or j == 0:
            out.append((left[i - 1][0], None))
            i -= 1
        else:  # pragma: no cover - only reachable if the band truncated the path
            break
    out.reverse()
    return tuple(out)


# --------------------------------------------------------------------------------------
# Every verse, accounted for
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """What became of every verse of one system.

    Each verse lands in exactly one bucket, and the buckets are chosen so that nothing can
    be quietly counted as fine. ``unwitnessed`` is the important one: "not contradicted" is
    not the same as "verified", and a number for what no corpus can check is worth more than
    silence about it.
    """

    system: str
    total: int = 0
    refused: int = 0
    """The data says these cannot be lined up. A stated refusal is an answer."""
    ghost: int = 0
    """Returned a verse the pivot does not have. Must be zero; anything else is a fault
    that no amount of textual agreement excuses."""
    confirmed: int = 0
    """A faithful witness on each side, in one language, and the mapped position explains
    the text better than its neighbours do."""
    contradicted: int = 0
    """A neighbour explains it better. Only meaningful in runs -- see :func:`runs_of`."""
    weak: int = 0
    """Too little shared vocabulary to be evidence either way."""
    unwitnessed: int = 0
    """Structurally sound and textually unchecked, because no faithful witness reaches it."""

    @property
    def checked(self) -> int:
        return self.confirmed + self.contradicted

    def describe(self) -> str:
        share = f"{self.checked / self.total:.1%}" if self.total else "-"
        rate = f"{self.confirmed / self.checked:.3%}" if self.checked else "-"
        return (
            f"{self.system:5} {self.total:>7,} verses  {self.ghost:>3} ghosts  "
            f"{self.refused:>6,} refused  {self.checked:>7,} checked ({share})  "
            f"{rate} confirmed  {self.unwitnessed:>7,} unwitnessed"
        )


def verify_every_verse(
    home: DataHome,
    vrs: Versification,
    witnesses: Mapping[str, Sequence[tuple[str, str]]],
    *,
    systems: Sequence[str] | None = None,
    covering: bool = False,
) -> tuple[list[Coverage], list[str], list[tuple[str, VerseRef, VerseRef]]]:
    """Convert every verse of every system and account for the result.

    Not a sample. The claim under test is that the mappings are right, and a sample cannot
    support it -- so this walks all of them and reports what it could not check as loudly as
    what it could.

    :param witnesses: system -> [(corpus, language)], best first. A comparison is only made
        where a faithful witness exists on both sides *in the same language*; anything else
        is unwitnessed rather than assumed.
    :param covering: Convert against every verse the mapping covers rather than only the
        one it names. See :func:`audit_pair` for why that changes the count.
    :returns: per-system coverage, ghost descriptions, and contradicted verses.
    """
    faithful = {
        (corpus, system): faithful_chapters(home, corpus, system, vrs)
        for system, pairs in witnesses.items()
        for corpus, _ in pairs
    }

    def witness_for(
        system: str, book: str, chapter: int, language: str | None = None
    ) -> tuple[str, str] | None:
        for corpus, lang in witnesses.get(system, ()):
            if language and lang != language:
                continue
            if (book, chapter) in faithful[(corpus, system)]:
                return corpus, lang
        return None

    texts = _Texts(home)
    out: list[Coverage] = []
    ghosts: list[str] = []
    contradicted: list[tuple[str, VerseRef, VerseRef]] = []

    try:
        for system in systems or vrs.system_names:
            if system == PIVOT:
                continue
            counts: dict[str, int] = dict.fromkeys(
                ("total", "refused", "ghost", "confirmed", "contradicted", "weak", "unwitnessed"),
                0,
            )
            for ref, target in _each_conversion(vrs, system, counts, ghosts, covering):
                source = witness_for(system, ref.book, int(ref.chapter))
                if source is None:
                    counts["unwitnessed"] += 1
                    continue
                corpus, language = source
                other = witness_for(PIVOT, target.book, int(target.chapter), language)
                if other is None:
                    counts["unwitnessed"] += 1
                    continue
                here = texts.verse(corpus, ref)
                there = texts.verse(other[0], target)
                if not here or not there:
                    counts["unwitnessed"] += 1
                    continue
                tokens = _tokens(here, language)
                score = _ratio(tokens, _tokens(there, language))
                if score < FLOOR:
                    counts["weak"] += 1
                    continue
                rival = 0.0
                for offset in OFFSETS:
                    if offset == 0 or target.verse + offset < 0:
                        continue
                    nearby = texts.verse(
                        other[0],
                        VerseRef(target.book, target.chapter, target.verse + offset, vrs=PIVOT),
                    )
                    if nearby:
                        rival = max(rival, _ratio(tokens, _tokens(nearby, language)))
                if score + MARGIN >= rival:
                    counts["confirmed"] += 1
                else:
                    counts["contradicted"] += 1
                    contradicted.append((system, ref, target))
            out.append(Coverage(system, **counts))
    finally:
        texts.close()
    return out, ghosts, contradicted


def _each_conversion(
    vrs: Versification,
    system: str,
    counts: dict[str, int],
    ghosts: list[str],
    covering: bool = False,
) -> Iterator[tuple[VerseRef, VerseRef]]:
    """Every verse of ``system`` that converts into the pivot without inventing a verse.

    Counts the refusals and ghosts as it goes and yields only what survives, so the caller
    is left with the textual question alone.
    """
    for ref in _verses_of(vrs, system, None):
        counts["total"] += 1
        try:
            targets = vrs.convert_all(ref, PIVOT, covering=covering)
        except VersificationError:
            counts["refused"] += 1
            continue
        if not targets:
            counts["refused"] += 1
            continue
        target = targets[0]
        if not vrs.has_book(PIVOT, target.book):
            counts["ghost"] += 1
            ghosts.append(f"{system}: {ref} -> {target} ({PIVOT} has no {target.book})")
            continue
        try:
            top = vrs.max_verse(PIVOT, target.book, int(target.chapter))
        except VersificationError:
            counts["ghost"] += 1
            ghosts.append(f"{system}: {ref} -> {target} (no such chapter in {PIVOT})")
            continue
        if target.verse > top:
            counts["ghost"] += 1
            ghosts.append(f"{system}: {ref} -> {target} ({PIVOT} max {top})")
            continue
        yield ref, target


def runs_of(
    contradicted: Sequence[tuple[str, VerseRef, VerseRef]], minimum: int = 4
) -> list[tuple[str, str, int, int, int]]:
    """Group contradicted verses into consecutive runs, which is what a fault looks like.

    Isolated flags are noise and in this corpus they are noise of a specific, understandable
    kind: the tribal-chief list of Numbers 1 reads "Of Symeon, Salamiel the son of Surisadai"
    in Brenton and "Of Shim'on, Shelumiel ben Tzurishaddai" in the Orthodox Jewish Bible, and
    every neighbouring verse has the identical shape. A structurally identical neighbour can
    outscore the true match by accident, and does, all through the genealogies and censuses.

    A run of verses all displaced the same way cannot happen by accident.
    """
    grouped: dict[tuple[str, str, int], list[int]] = {}
    for system, ref, _target in contradicted:
        grouped.setdefault((system, ref.book, int(ref.chapter)), []).append(ref.verse)

    out: list[tuple[str, str, int, int, int]] = []
    for (system, book, chapter), verses in grouped.items():
        # Sorted because the caller may hand these over in any order, and de-duplicated
        # because a verse flagged twice must not be read as a gap and break the run.
        ordered = sorted(set(verses))
        current = [ordered[0]]
        for verse in ordered[1:]:
            if verse == current[-1] + 1:
                current.append(verse)
                continue
            if len(current) >= minimum:
                out.append((system, book, chapter, current[0], current[-1]))
            current = [verse]
        if len(current) >= minimum:
            out.append((system, book, chapter, current[0], current[-1]))
    return sorted(out, key=lambda r: -(r[4] - r[3]))
