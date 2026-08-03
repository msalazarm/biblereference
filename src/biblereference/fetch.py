"""Downloading sources into the archive, and building the index from it.

The two halves never overlap. :func:`fetch_source` writes only to ``sources/``; it never
touches the database. :func:`build_source` reads only ``sources/``; it never touches the
network. So a rebuild after a code change re-downloads nothing, and once fetched, the
whole library works offline -- which is the point of keeping the raw files rather than
only the parsed result.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx

from .sources import Source, get_source
from .store import DataHome, SourceMeta, write_corpus

__all__ = ["BuildResult", "FetchResult", "build_source", "fetch_source"]

_USER_AGENT: Final = (
    "biblereference/0.1 (+https://github.com/openscriptures/morphhb; personal research)"
)

#: Progress callback: (message,) -> None.
Reporter = Callable[[str], None]


def _silent(_: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class FetchResult:
    source: str
    archive: Path
    files: int
    bytes: int
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class BuildResult:
    source: str
    corpora: tuple[tuple[str, int], ...]
    """``(corpus id, verse count)`` for each corpus built."""
    notes: tuple[str, ...] = ()

    @property
    def verses(self) -> int:
        return sum(count for _, count in self.corpora)


def fetch_source(
    source: Source | str,
    home: DataHome,
    *,
    report: Reporter = _silent,
    force: bool = False,
    timeout: float = 120.0,
) -> FetchResult:
    """Download one source's files into a dated archive directory.

    :param force: Fetch again even if an archive already exists. Without it, a source
        already present is left alone -- re-fetching is for refreshing, not for routine
        use, and the old copy is kept either way.
    """
    if isinstance(source, str):
        source = get_source(source)

    existing = home.latest_archive(source.id)
    if existing is not None and not force:
        present = {p.name for p in existing.iterdir()}
        if all(f.name in present for f in source.files):
            report(f"{source.id}: already fetched into {existing}")
            return FetchResult(source.id, existing, 0, 0, skipped=len(source.files))

    home.prepare()
    target = home.archive_dir(source.id)
    total = 0
    written = 0

    with httpx.Client(
        follow_redirects=True, timeout=timeout, headers={"User-Agent": _USER_AGENT}
    ) as client:
        for index, remote in enumerate(source.files, start=1):
            if index > 1 and source.crawl_delay:
                time.sleep(source.crawl_delay)
            report(f"{source.id}: [{index}/{len(source.files)}] {remote.name}")
            response = client.get(remote.url)
            response.raise_for_status()
            payload = response.content
            home.store_file(
                source.id,
                remote.name,
                payload,
                url=remote.url,
                license=source.license,
            )
            total += len(payload)
            written += 1

    report(f"{source.id}: {written} file(s), {total / 1e6:.1f} MB into {target}")
    return FetchResult(source.id, target, written, total)


def build_source(
    source: Source | str, home: DataHome, *, report: Reporter = _silent
) -> BuildResult:
    """Parse a fetched archive into the database.

    :raises FileNotFoundError: the source has never been fetched.
    """
    if isinstance(source, str):
        source = get_source(source)

    archive = home.latest_archive(source.id)
    if archive is None:
        raise FileNotFoundError(
            f"{source.id} has not been fetched; run `biblereference fetch "
            f"--source {source.id}` first"
        )

    fetched_at = next((entry.fetched_at for entry in reversed(home.entries(source.id))), None)

    built: list[tuple[str, int]] = []
    notes: list[str] = []
    for corpus in source.build(archive):
        count = write_corpus(
            home,
            SourceMeta(
                corpus=corpus.id,
                label=corpus.label,
                language=corpus.language,
                versification=corpus.versification,
                license=source.license,
                attribution=source.attribution,
                source_url=source.homepage,
                fetched_at=fetched_at,
            ),
            corpus.verses,
        )
        built.append((corpus.id, count))
        notes.extend(f"{corpus.id}: {note}" for note in corpus.notes)
        report(f"{source.id}: built {corpus.id} ({count:,} verses)")

    return BuildResult(source.id, tuple(built), tuple(notes))


def iter_sources(only: str | None = None) -> Iterator[Source]:
    """Sources to act on: one named, or all of them in fetch order.

    ``FETCH_ORDER`` names the texts the renderer reaches for, smallest first, so that a
    failure surfaces quickly. Everything else follows in id order. Registering a source
    without listing it there used to mean it was never fetched at all; now it is simply
    fetched last.
    """
    from .sources import FETCH_ORDER, all_sources

    if only:
        yield get_source(only)
        return
    sources = all_sources()
    for source_id in FETCH_ORDER:
        if source_id in sources:
            yield sources[source_id]
    for source_id in sorted(sources.keys() - set(FETCH_ORDER)):
        yield sources[source_id]
