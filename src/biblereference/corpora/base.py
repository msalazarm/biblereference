"""What a text source has to provide.

A corpus is one edition of scripture -- the ASV, the Douay-Rheims, Swete's Septuagint --
that can hand back the words of a verse. Each one declares the versification it counts
in, so the renderer converts a reference into the corpus's own numbering before asking.
That is the whole reason corpora do not parse references themselves: a corpus is asked
for verses it already understands.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..refs import VerseRef

__all__ = ["Corpus", "CorpusError", "VerseText", "VerseUnavailable"]


class CorpusError(RuntimeError):
    """A corpus could not be read at all -- missing data, unreadable file."""


class VerseUnavailable(LookupError):
    """A corpus does not carry this verse.

    Distinct from a bad reference: the Douay-Rheims has no Psalm 151 and the ASV has no
    Sirach, but both references are perfectly valid elsewhere.
    """

    def __init__(self, ref: VerseRef, corpus: str, detail: str = "") -> None:
        self.ref = ref
        self.corpus = corpus
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"{corpus} does not carry {ref.pretty()}{suffix}")


@dataclass(frozen=True, slots=True)
class VerseText:
    """One verse's words, as a corpus holds them."""

    ref: VerseRef
    """The verse, in the corpus's own versification."""

    text: str
    """The words, whitespace-normalised, with no verse number attached."""


@runtime_checkable
class Corpus(Protocol):
    """A source of verse text."""

    @property
    def id(self) -> str:
        """Short stable identifier, e.g. ``"asv"``. Used in config and the database."""

    @property
    def label(self) -> str:
        """Human-readable name, e.g. ``"American Standard Version"``."""

    @property
    def language(self) -> str:
        """``"en"``, ``"grc"``, ``"hbo"``, ``"la"``."""

    @property
    def versification(self) -> str:
        """The versification this corpus counts in."""

    @property
    def attribution(self) -> str | None:
        """Credit line the renderer must emit, where the licence requires one."""

    def has_book(self, book: str) -> bool:
        """Whether this corpus carries a book at all, by USFM code.

        Answering cheaply matters: it is what lets the renderer fall back from the ASV
        to the Douay-Rheims for Sirach without a failed lookup first.
        """
        ...

    def fetch(self, refs: Sequence[VerseRef]) -> list[VerseText]:
        """Return the text of each reference, in the order given.

        :raises VerseUnavailable: any reference this corpus does not carry.
        :raises CorpusError: the corpus itself could not be read.
        """
        ...
