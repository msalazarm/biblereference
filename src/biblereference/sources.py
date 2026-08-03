"""What can be fetched, from where, and under what terms.

Each :class:`Source` is one upstream project. Fetching downloads its files verbatim into
the archive; building runs its parser over that archive and produces one or more corpora.
A source can yield several corpora, which is how Swete's Septuagint ends up as two: its
Greek Daniel is numbered like the Vulgate's, not like the rest of the Septuagint, and
saying so is cheaper than a wrong verse.

Nothing here downloads anything. See :mod:`biblereference.fetch`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .refs import VerseRef

__all__ = ["BuiltCorpus", "RemoteFile", "Source", "all_sources", "get_source"]


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One file to download."""

    url: str
    name: str
    """Filename inside the archive directory."""


@dataclass(frozen=True, slots=True)
class BuiltCorpus:
    """One corpus, parsed out of an archive and ready to store."""

    id: str
    label: str
    language: str
    versification: str
    verses: list[tuple[VerseRef, str]]
    notes: list[str] = field(default_factory=list)
    """Anything the parser wants the author to know -- books it skipped, and why."""


@dataclass(frozen=True, slots=True)
class Source:
    """An upstream project this library can fetch and parse."""

    id: str
    label: str
    homepage: str
    license: str
    files: tuple[RemoteFile, ...]
    build: Callable[[Path], Iterable[BuiltCorpus]]
    attribution: str | None = None
    """Credit line the renderer must print. Set wherever the licence requires it."""
    note: str = ""


def _sources() -> dict[str, Source]:
    # Imported here so that fetching one source does not import every parser.
    from .corpora import ebible, nestle1904, oshb, swete

    return {
        source.id: source
        for source in (
            oshb.SOURCE,
            swete.SOURCE,
            nestle1904.SOURCE,
            ebible.WEBC,
            ebible.DRA,
        )
    }


def all_sources() -> dict[str, Source]:
    """Every source, keyed by id."""
    return _sources()


def get_source(source_id: str) -> Source:
    """One source by id.

    :raises KeyError: no such source.
    """
    sources = _sources()
    try:
        return sources[source_id]
    except KeyError:
        raise KeyError(
            f"unknown source {source_id!r}; known: {', '.join(sorted(sources))}"
        ) from None


#: Order the CLI fetches in, smallest first, so a failure surfaces quickly.
FETCH_ORDER: Final = ("webc", "dra", "nestle1904", "oshb", "swete")
