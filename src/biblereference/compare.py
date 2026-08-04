"""Measuring how far two editions of one text have drifted apart.

Built for the two Latin Bibles. The Clementine is Jerome's text as the Church received
it; the Nova Vulgata is the 1979 revision, made against the modern critical editions of
the Hebrew and Greek. Asking how much they differ, and where, is asking how much the
twentieth century changed its mind about what the fourth century had.

Alignment goes through the pivot, because the two are not numbered alike -- the
Clementine's Psalm 22 is the Nova Vulgata's Psalm 23. Comparing them where they sit would
report the entire Psalter as divergent and tell you nothing.

Comparison is on folded text, so that orthography is not mistaken for substance: the
Clementine writes *Jesus* and *ejus*, the Nova Vulgata *Iesus* and *eius*, and those are
the same words. *Dominus regit me* against *Dominus pascit me* is a real difference and
survives the fold.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final

from .canon import book_title, canonical_order
from .corpora.base import Corpus, VerseUnavailable
from .emphasis import fold
from .refs import VerseRef
from .versification import Versification, VersificationError

__all__ = ["BookComparison", "VerseDifference", "compare_corpora"]


@dataclass(frozen=True, slots=True)
class VerseDifference:
    """One verse where the two editions do not agree."""

    ref: VerseRef
    """The verse in the pivot's numbering, so it can be looked up in either."""
    left: str
    right: str
    similarity: float

    @property
    def only_in_one(self) -> bool:
        return not self.left or not self.right


@dataclass
class BookComparison:
    """How two editions compare across one book."""

    book: str
    compared: int = 0
    identical: int = 0
    differing: list[VerseDifference] = field(default_factory=list)
    missing_left: int = 0
    missing_right: int = 0
    _similarity_total: float = 0.0

    @property
    def title(self) -> str:
        return book_title(self.book)

    @property
    def share_differing(self) -> float:
        return len(self.differing) / self.compared if self.compared else 0.0

    @property
    def mean_similarity(self) -> float:
        return self._similarity_total / self.compared if self.compared else 0.0

    def record(self, ref: VerseRef, left: str, right: str) -> None:
        similarity = SequenceMatcher(None, _words(left), _words(right)).ratio()
        self.compared += 1
        self._similarity_total += similarity
        if similarity >= 1.0:
            self.identical += 1
        else:
            self.differing.append(VerseDifference(ref, left, right, similarity))


#: Words only. The two editions punctuate quite differently -- the Clementine writes
#: "ad Jonam, filium Amathi, dicens:" where the Nova Vulgata has "ad Ionam filium Amathi
#: dicens:" -- and counting commas as textual variants would report almost every verse in
#: the Bible as changed while saying nothing about the words.
_WORD_RE: Final = re.compile(r"[^\W_]+", re.UNICODE)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(fold(text, "la"))


def _text(
    corpus: Corpus, versification: Versification, ref: VerseRef, covering: bool = False
) -> str | None:
    """One verse of a corpus, in the corpus's own numbering, or ``None`` if absent."""
    try:
        segments = versification.convert_all(ref, corpus.versification, covering=covering)
    except VersificationError:
        return None
    parts: list[str] = []
    for segment in segments:
        try:
            parts.extend(verse.text for verse in corpus.fetch([segment]))
        except VerseUnavailable:
            return None
    return " ".join(parts).strip() or None


def compare_corpora(
    left: Corpus,
    right: Corpus,
    versification: Versification,
    *,
    books: list[str] | None = None,
    covering: bool = False,
) -> Iterator[BookComparison]:
    """Compare two corpora book by book, in reading order.

    Only books both carry are compared. Every verse is addressed in the pivot's numbering
    and converted into each corpus's own, which is what makes the comparison meaningful
    for editions that number differently.
    """
    shared = books or sorted(
        {b for b in _books_of(left, versification) if _has(right, b)},
        key=canonical_order,
    )

    for book in shared:
        comparison = BookComparison(book=book)
        chapters = versification.chapter_count("org", book)
        for chapter in range(1, chapters + 1):
            for verse in range(
                versification.first_verse("org", book, chapter),
                versification.max_verse("org", book, chapter) + 1,
            ):
                ref = VerseRef(book, chapter, verse, vrs="org")
                a = _text(left, versification, ref, covering)
                b = _text(right, versification, ref, covering)
                if a is None and b is None:
                    continue
                if a is None:
                    comparison.missing_left += 1
                    continue
                if b is None:
                    comparison.missing_right += 1
                    continue
                comparison.record(ref, a, b)
        if comparison.compared or comparison.missing_left or comparison.missing_right:
            yield comparison


def _books_of(corpus: Corpus, versification: Versification) -> list[str]:
    from .canon import CANONICAL_ORDER

    return [
        book
        for book in CANONICAL_ORDER
        if versification.chapter_count("org", book) and corpus.has_book(book)
    ]


def _has(corpus: Corpus, book: str) -> bool:
    return corpus.has_book(book)
