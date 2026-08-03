"""English public-domain texts, by way of ``pythonbible``.

``pythonbible`` ships the ASV and can install a couple of dozen more public-domain
English versions as extras. It is used here purely as a text source: its own book enum
stops at 1-2 Maccabees and has no Judith, Baruch, Susanna, Bel, or the Song of the
Three, and its Sirach follows the Vulgate's verse counts rather than the Greek -- so
reference parsing, canon, and versification all stay with this library, and the
deuterocanon comes from the Douay-Rheims instead.

In practice that means this corpus covers the sixty-six protocanonical books, and the
renderer falls back for the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from typing import Final

import pythonbible as pb

from ..refs import VerseRef
from .base import CorpusError, VerseText, VerseUnavailable

__all__ = ["PythonBibleCorpus", "available_versions"]

#: USFM code to ``pythonbible`` book. Only the protocanon: see the module docstring for
#: why the deuterocanonical members of ``pb.Book`` are deliberately not listed.
_BOOKS: Final[dict[str, pb.Book]] = {
    "GEN": pb.Book.GENESIS,
    "EXO": pb.Book.EXODUS,
    "LEV": pb.Book.LEVITICUS,
    "NUM": pb.Book.NUMBERS,
    "DEU": pb.Book.DEUTERONOMY,
    "JOS": pb.Book.JOSHUA,
    "JDG": pb.Book.JUDGES,
    "RUT": pb.Book.RUTH,
    "1SA": pb.Book.SAMUEL_1,
    "2SA": pb.Book.SAMUEL_2,
    "1KI": pb.Book.KINGS_1,
    "2KI": pb.Book.KINGS_2,
    "1CH": pb.Book.CHRONICLES_1,
    "2CH": pb.Book.CHRONICLES_2,
    "EZR": pb.Book.EZRA,
    "NEH": pb.Book.NEHEMIAH,
    "EST": pb.Book.ESTHER,
    "JOB": pb.Book.JOB,
    "PSA": pb.Book.PSALMS,
    "PRO": pb.Book.PROVERBS,
    "ECC": pb.Book.ECCLESIASTES,
    "SNG": pb.Book.SONG_OF_SONGS,
    "ISA": pb.Book.ISAIAH,
    "JER": pb.Book.JEREMIAH,
    "LAM": pb.Book.LAMENTATIONS,
    "EZK": pb.Book.EZEKIEL,
    "DAN": pb.Book.DANIEL,
    "HOS": pb.Book.HOSEA,
    "JOL": pb.Book.JOEL,
    "AMO": pb.Book.AMOS,
    "OBA": pb.Book.OBADIAH,
    "JON": pb.Book.JONAH,
    "MIC": pb.Book.MICAH,
    "NAM": pb.Book.NAHUM,
    "HAB": pb.Book.HABAKKUK,
    "ZEP": pb.Book.ZEPHANIAH,
    "HAG": pb.Book.HAGGAI,
    "ZEC": pb.Book.ZECHARIAH,
    "MAL": pb.Book.MALACHI,
    "MAT": pb.Book.MATTHEW,
    "MRK": pb.Book.MARK,
    "LUK": pb.Book.LUKE,
    "JHN": pb.Book.JOHN,
    "ACT": pb.Book.ACTS,
    "ROM": pb.Book.ROMANS,
    "1CO": pb.Book.CORINTHIANS_1,
    "2CO": pb.Book.CORINTHIANS_2,
    "GAL": pb.Book.GALATIANS,
    "EPH": pb.Book.EPHESIANS,
    "PHP": pb.Book.PHILIPPIANS,
    "COL": pb.Book.COLOSSIANS,
    "1TH": pb.Book.THESSALONIANS_1,
    "2TH": pb.Book.THESSALONIANS_2,
    "1TI": pb.Book.TIMOTHY_1,
    "2TI": pb.Book.TIMOTHY_2,
    "TIT": pb.Book.TITUS,
    "PHM": pb.Book.PHILEMON,
    "HEB": pb.Book.HEBREWS,
    "JAS": pb.Book.JAMES,
    "1PE": pb.Book.PETER_1,
    "2PE": pb.Book.PETER_2,
    "1JN": pb.Book.JOHN_1,
    "2JN": pb.Book.JOHN_2,
    "3JN": pb.Book.JOHN_3,
    "JUD": pb.Book.JUDE,
    "REV": pb.Book.REVELATION,
}

#: Short names an author might write in ``en=``, mapped to ``pythonbible`` versions.
#: Only versions that are actually public domain are offered.
_VERSIONS: Final[dict[str, tuple[pb.Version, str]]] = {
    "ASV": (pb.Version.AMERICAN_STANDARD, "American Standard Version"),
    "KJV": (pb.Version.KING_JAMES, "King James Version"),
    "AKJV": (pb.Version.AMERICAN_KING_JAMES, "American King James Version"),
    "WEB": (pb.Version.WORLD_ENGLISH, "World English Bible"),
    "YLT": (pb.Version.YOUNGS, "Young's Literal Translation"),
    "DARBY": (pb.Version.DARBY, "Darby Translation"),
    "GENEVA": (pb.Version.GENEVA, "Geneva Bible"),
    "WEBSTER": (pb.Version.WEBSTER, "Webster's Revision"),
    "TYNDALE": (pb.Version.TYNDALE, "Tyndale Bible"),
    "NHEB": (pb.Version.NEW_HEART, "New Heart English Bible"),
    "BBE": (pb.Version.BIBLE_IN_BASIC_ENGLISH, "Bible in Basic English"),
}


def available_versions() -> tuple[str, ...]:
    """Version names this corpus will accept in ``en=``."""
    return tuple(sorted(_VERSIONS))


class PythonBibleCorpus:
    """A public-domain English version served by ``pythonbible``.

    :param version: One of :func:`available_versions`, e.g. ``"ASV"``.
    :raises CorpusError: the version is unknown, or its text package is not installed.
    """

    versification = "eng"
    language = "en"
    attribution = None  # public domain throughout

    def __init__(self, version: str = "ASV") -> None:
        key = version.strip().upper()
        try:
            self._version, self._label = _VERSIONS[key]
        except KeyError:
            raise CorpusError(
                f"unknown English version {version!r}; pythonbible offers "
                f"{', '.join(available_versions())}"
            ) from None
        self._id = key.lower()

    @property
    def id(self) -> str:
        return self._id

    @property
    def label(self) -> str:
        return self._label

    def has_book(self, book: str) -> bool:
        return book in _BOOKS

    def fetch(self, refs: Sequence[VerseRef]) -> list[VerseText]:
        return [VerseText(ref=ref, text=self._one(ref)) for ref in refs]

    def _one(self, ref: VerseRef) -> str:
        book = _BOOKS.get(ref.book)
        if book is None:
            raise VerseUnavailable(
                ref, self.label, "pythonbible carries only the protocanonical books"
            )
        if ref.is_letter_chapter:
            raise VerseUnavailable(ref, self.label, "letter chapters are not supported here")
        assert isinstance(ref.chapter, int)

        # Verse 0 is a psalm superscription, which these versions print unnumbered and
        # pythonbible does not hold separately.
        if ref.verse == 0:
            raise VerseUnavailable(ref, self.label, "psalm superscriptions are not numbered")

        try:
            verse_id = pb.get_verse_id(book, ref.chapter, ref.verse)
        except pb.InvalidVerseError as exc:
            raise VerseUnavailable(ref, self.label, str(exc)) from exc

        try:
            text = _text(verse_id, self._version)
        except (
            pb.VersionMissingVerseError,
            pb.VersionMissingChapterError,
            pb.VersionMissingBookError,
        ) as exc:
            raise VerseUnavailable(ref, self.label, str(exc)) from exc
        except pb.MissingBiblePackageError as exc:
            raise CorpusError(
                f"{self.label} needs an extra package: {exc}. Install it with "
                f"`pip install pythonbible-{self._id}`."
            ) from exc

        return " ".join(text.split())


@cache
def _text(verse_id: int, version: pb.Version) -> str:
    """Cached lookup: rendering a document tends to cite the same verses repeatedly."""
    return str(pb.get_verse_text(verse_id, version=version))
