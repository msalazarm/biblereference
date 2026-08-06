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

from .licences import Licence
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
    licence: Licence | None = None
    """What the *files this corpus was built from* actually said, where the parser could
    read it. Set here rather than only on the source because one upstream can hold texts
    under different terms: the Patristic Text Archive publishes the Peshitta Old Testament
    under CC BY-NC and the New Testament beside it under CC BY. Falls back to
    :attr:`Source.terms` when the files carry no licence of their own."""
    licences: tuple[Licence, ...] = ()
    """Every distinct licence seen among those files. One entry is the ordinary case and
    the invariant a parser should assert; more than one is visible in ``doctor`` rather
    than merely assumed away."""


@dataclass(frozen=True, slots=True)
class Source:
    """An upstream project this library can fetch and parse."""

    id: str
    label: str
    homepage: str
    license: str
    files: tuple[RemoteFile, ...]
    build: Callable[[Path], Iterable[BuiltCorpus]]
    terms: Licence | None = None
    """The licence as an object, where somebody has read it. ``license`` above stays the
    human sentence, so a source written before this existed needs no edit; this is what
    can be *asked* whether the text may be used commercially."""
    attribution: str | None = None
    """Credit line the renderer must print. Set wherever the licence requires it."""
    note: str = ""
    crawl_delay: float = 0.0
    """Seconds to wait between this source's files. Set where the host's robots.txt asks
    for it -- vatican.va publishes ``Crawl-delay: 2`` -- so that fetching a source of many
    files stays within what the host has said it wants."""


def _sources() -> dict[str, Source]:
    # Imported here so that fetching one source does not import every parser.
    from .corpora import ebible, nestle1904, novavulgata, oshb, pta, swete

    return {
        source.id: source
        for source in (
            oshb.SOURCE,
            swete.SOURCE,
            nestle1904.SOURCE,
            pta.SOURCE,
            ebible.WEBC,
            ebible.DRA,
            ebible.LATVUC,
            novavulgata.SOURCE,
            *ebible.ENGLISH,
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


#: Order the CLI fetches in, smallest first, so a failure surfaces quickly. The texts the
#: renderer reaches for by name come first; the bulk English corpus, which exists for the
#: search index, follows in whatever order the table gives. Sources not named here are
#: still fetched -- see :func:`biblereference.fetch.iter_sources` -- so that registering
#: one cannot silently omit it.
FETCH_ORDER: Final = (
    "webc",
    "dra",
    "latvuc",
    "nestle1904",
    "oshb",
    "swete",
    "novavulgata",
)
