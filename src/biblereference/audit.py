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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final

from .canon import CANONICAL_ORDER, book_title
from .emphasis import fold
from .refs import VerseRef
from .store import DataHome
from .versification import Versification, VersificationError

__all__ = [
    "OFFSETS",
    "WITNESSES",
    "Alignment",
    "Disagreement",
    "PairResult",
    "Witness",
    "audit_all",
    "audit_pair",
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
    ("eng", "en"): Witness("web", "eng", "en"),
    ("lxx", "en"): Witness("brenton", "lxx", "en"),
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
    for i, left in enumerate(families):
        for right in families[i + 1 :]:
            shared = [
                (WITNESSES[(left, lang)], WITNESSES[(right, lang)])
                for lang in ("la", "en")
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
) -> PairResult:
    """Check every mapping between two families against the text of their witnesses.

    Walks the whole of the source system rather than only its declared mappings, because
    a verse with no mapping is asserting that none is needed, and that assertion can be
    wrong in exactly the same way.
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
                targets = vrs.convert_all(source, right.family)
            except VersificationError:
                result.unmapped += 1
                continue
            if not targets:
                result.unmapped += 1
                continue

            mapped = targets[0]
            alignment = _score(store, right, source, mapped, source_text)
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
) -> list[PairResult]:
    """Audit every family pair that has a same-language witness on both sides."""
    vrs = Versification.load()
    texts = _Texts(home)
    try:
        return [
            audit_pair(home, vrs, left, right, books=books, texts=texts)
            for left, right in (pairs if pairs is not None else witness_pairs())
        ]
    finally:
        texts.close()


def book_of(disagreements: Sequence[Disagreement]) -> dict[str, int]:
    """How the flagged verses fall across books, which is how a systematic fault shows."""
    counts: dict[str, int] = {}
    for item in disagreements:
        title = book_title(item.alignment.source.book)
        counts[title] = counts.get(title, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def home_default() -> Path:
    return DataHome().root
