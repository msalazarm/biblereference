"""Downloading sources into the archive, and building the index from it.

The two halves never overlap. :func:`fetch_source` writes only to ``sources/``; it never
touches the database. :func:`build_source` reads only ``sources/``; it never touches the
network. So a rebuild after a code change re-downloads nothing, and once fetched, the
whole library works offline -- which is the point of keeping the raw files rather than
only the parsed result.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx

from .sources import Source, get_source
from .store import DataHome, ManifestEntry, SourceMeta, write_corpus

__all__ = [
    "BuildResult",
    "FetchResult",
    "MirrorResult",
    "build_source",
    "fetch_source",
    "mirror_archive",
]

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


@dataclass(frozen=True, slots=True)
class MirrorResult:
    """What copying another machine's archive moved."""

    copied: int
    bytes: int
    already_held: int
    reused: int
    """Files the other machine had under a path this one does not, but whose bytes were
    already here under another. Copied from disk rather than fetched."""
    corrupt: int
    """Files whose bytes did not match the checksum the other machine recorded. Refused
    rather than written, because a mirror that can introduce a wrong verse is worse than
    no mirror."""


def mirror_archive(
    home: DataHome,
    base_url: str,
    *,
    token: str | None = None,
    report: Reporter = _silent,
    timeout: float = 120.0,
) -> MirrorResult:
    """Copy another machine's archive into this one, over its HTTP server.

    Point a new machine at an old one and it ends up holding the same bytes, rather than
    re-downloading 160 MB from a dozen upstreams and getting whatever they publish today.
    That difference is not hypothetical: two machines synced two days apart here already
    disagreed about two of eBible's files, because eBible had republished them in between.
    A mirror is the only way to be *sure* two machines match, since upstream is free to
    change under both of them.

    Only ``sources/`` is copied. The database is derived, and rebuilding it locally is
    both faster than transferring 600 MB and a stronger check -- if the same bytes build
    into a different database, that is worth knowing rather than papering over.

    Every file is verified against the checksum the other machine recorded *before* it is
    written, so a truncated transfer is refused rather than archived. The manifest line is
    then copied verbatim: it says where the bytes originally came from and when, which is
    the honest record, and it is what makes the two machines' digests agree.

    Downloads are keyed on content, not on where they sit. Archive paths carry the date
    they were fetched, so two machines that synced on different days hold every file under
    a different path while almost all of the bytes are identical -- mirroring by path alone
    moved 155 MB to change two files the first time this was run. Anything already held
    under any path is copied from disk instead.

    Disk is the one thing this does spend. The archive is append-only by design, so a
    mirror that lands on new dates adds a second copy of everything rather than replacing
    it; the old files stay, which is what makes any earlier build reproducible.
    """
    base = base_url.rstrip("/")
    headers = {"User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    home.prepare()
    held = {(entry.source, entry.path, entry.sha256) for entry in home.entries()}
    elsewhere: dict[str, list[str]] = {}
    for entry in home.entries():
        elsewhere.setdefault(entry.sha256, []).append(entry.path)
    copied = skipped = reused = corrupt = moved = 0

    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = client.get(f"{base}/api/manifest")
        response.raise_for_status()
        entries = [ManifestEntry(**row) for row in response.json()["entries"]]
        report(f"{len(entries)} archived file(s) on {base}")

        for index, entry in enumerate(entries, start=1):
            target = home.sources / entry.path
            if target.is_file() and _sha256(target) == entry.sha256:
                skipped += 1
                if (entry.source, entry.path, entry.sha256) not in held:
                    # The bytes are here but this machine never recorded them, which is
                    # what a hand-copied `sources/` directory looks like.
                    home.record(entry)
                    held.add((entry.source, entry.path, entry.sha256))
                continue

            # The same bytes under another path -- almost always the same file fetched on
            # another date. Hashed before being trusted, because a local file can rot too,
            # but a disk read still beats a transfer by orders of magnitude.
            local = next(
                (
                    candidate
                    for path in elsewhere.get(entry.sha256, ())
                    if (candidate := home.sources / path).is_file()
                    and _sha256(candidate) == entry.sha256
                ),
                None,
            )
            if local is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(local, target)
                if (entry.source, entry.path, entry.sha256) not in held:
                    home.record(entry)
                    held.add((entry.source, entry.path, entry.sha256))
                elsewhere.setdefault(entry.sha256, []).append(entry.path)
                reused += 1
                continue

            report(f"[{index}/{len(entries)}] {entry.path} ({entry.bytes / 1e6:.1f} MB)")
            payload = client.get(f"{base}/api/archive", params={"path": entry.path}).content
            if hashlib.sha256(payload).hexdigest() != entry.sha256:
                report(f"  REFUSED: {entry.path} does not match the checksum recorded for it")
                corrupt += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            elsewhere.setdefault(entry.sha256, []).append(entry.path)
            if (entry.source, entry.path, entry.sha256) not in held:
                home.record(entry)
                held.add((entry.source, entry.path, entry.sha256))
            copied += 1
            moved += len(payload)

    report(
        f"{copied} file(s) fetched, {moved / 1e6:.1f} MB; {reused} already here under "
        f"another path; {skipped} already held"
        + (f"; {corrupt} REFUSED as corrupt" if corrupt else "")
    )
    return MirrorResult(copied, moved, skipped, reused, corrupt)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
