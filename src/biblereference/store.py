"""Where the texts live on disk, and how they are read back.

The layout is deliberately plain, because the point of it is that you own your corpus
independently of whether any upstream repository still exists::

    $data_home/
        sources/                 raw downloads, byte for byte, never rewritten
            oshb/2026-08-03/…
            MANIFEST.jsonl       one line per file: url, checksum, licence, when
        db/corpus.sqlite         the built index, regenerable from sources/ offline
        export/                  optional JSON dumps, for reading or diffing

``fetch`` only ever writes to ``sources/``. ``build`` only ever reads it. So once fetched,
everything works with the network off, a rebuild after a code change re-downloads nothing,
and backing up one directory backs up everything.

Downloads land in a dated subdirectory rather than overwriting, so re-fetching adds to the
archive instead of replacing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from platformdirs import user_data_dir

from .corpora.base import VerseText, VerseUnavailable
from .licences import LICENCES, Licence
from .refs import VerseRef

__all__ = [
    "ENV_VAR",
    "DataHome",
    "LibraryDigest",
    "ManifestEntry",
    "SourceMeta",
    "SqliteCorpus",
    "add_chapter",
    "default_data_home",
    "library_digest",
    "open_store",
    "read_chapter",
    "stored_chapters",
]

#: Point this at a synced or backed-up directory to carry your corpus between machines.
ENV_VAR: Final = "BIBLEREFERENCE_HOME"

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS verse (
    corpus    TEXT    NOT NULL,
    book      TEXT    NOT NULL,
    chapter   INTEGER NOT NULL,
    verse     INTEGER NOT NULL,
    subverse  TEXT    NOT NULL DEFAULT '',
    text      TEXT    NOT NULL,
    PRIMARY KEY (corpus, book, chapter, verse, subverse)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS source_meta (
    corpus        TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    language      TEXT NOT NULL,
    versification TEXT NOT NULL,
    license       TEXT,
    attribution   TEXT,
    source_url    TEXT,
    fetched_at    TEXT,
    built_at      TEXT,
    verse_count   INTEGER NOT NULL DEFAULT 0,
    licence_id    TEXT,
    licence_ids   TEXT
);

-- Which chapters of an incrementally-built corpus have been read in full. A corpus
-- assembled a chapter at a time cannot tell a chapter it has never seen from one whose
-- verses are simply absent, so completeness is recorded rather than inferred.
CREATE TABLE IF NOT EXISTS chapter_state (
    corpus     TEXT    NOT NULL,
    book       TEXT    NOT NULL,
    chapter    INTEGER NOT NULL,
    fetched_at TEXT    NOT NULL,
    verses     INTEGER NOT NULL,
    PRIMARY KEY (corpus, book, chapter)
) WITHOUT ROWID;
"""

#: The search index, kept apart from :data:`_SCHEMA` because it is derived data: it can be
#: dropped and rebuilt from ``verse`` at any time without a download.
#:
#: Rows are *distinct texts*, not verses. Across fifty-odd English translations the same
#: sentence recurs constantly -- the World English Bible variants render most verses
#: identically, as do the ASV and its Byzantine revision -- so indexing per verse would
#: store the same words many times over. The same table then answers "which translations
#: render this verse identically", which is what stops the matcher naming a winner among
#: texts that are not actually distinguishable.
#:
#: ``porter`` matters: without stemming, a query saying *loving* does not reach a verse
#: saying *loved*, and people quoting from memory shift tense constantly.
SEARCH_SCHEMA: Final = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    text,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS search_text (
    id   INTEGER PRIMARY KEY,
    hash BLOB    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS search_ref (
    corpus   TEXT    NOT NULL,
    book     TEXT    NOT NULL,
    chapter  INTEGER NOT NULL,
    verse    INTEGER NOT NULL,
    subverse TEXT    NOT NULL DEFAULT '',
    text_id  INTEGER NOT NULL,
    PRIMARY KEY (corpus, book, chapter, verse, subverse)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS search_ref_by_text ON search_ref (text_id);

CREATE TABLE IF NOT EXISTS search_state (
    corpus     TEXT PRIMARY KEY,
    indexed_at TEXT    NOT NULL,
    verses     INTEGER NOT NULL
);

-- How many distinct texts each word appears in, so a query can be built out of the words
-- that actually narrow it down. FTS5 keeps its own vocabulary, but it holds *stemmed*
-- terms, and a query word cannot be stemmed from Python to look itself up. This is
-- counted over the same folded, unstemmed tokens the query is made of, so the two agree.
CREATE TABLE IF NOT EXISTS search_df (
    token TEXT    PRIMARY KEY,
    docs  INTEGER NOT NULL
) WITHOUT ROWID;
"""


def default_data_home() -> Path:
    """Where the corpus lives unless told otherwise.

    Honours ``$BIBLEREFERENCE_HOME``, falling back to the platform data directory.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("biblereference", appauthor=False))


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One archived download."""

    source: str
    url: str
    path: str
    """Relative to ``sources/``, so the archive stays portable."""
    sha256: str
    bytes: int
    fetched_at: str
    license: str | None = None
    note: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class SourceMeta:
    """What the database records about one corpus."""

    corpus: str
    label: str
    language: str
    versification: str
    license: str | None = None
    attribution: str | None = None
    source_url: str | None = None
    fetched_at: str | None = None
    built_at: str | None = None
    verse_count: int = 0
    licence_id: str | None = None
    """The :class:`~biblereference.licences.Licence` this corpus is held under, by id."""
    licence_ids: str | None = None
    """Every distinct licence among the files it was built from, comma-separated. One is
    the ordinary case; more than one is worth being able to see."""

    @property
    def terms(self) -> Licence | None:
        """The licence object, where the id is one this library knows."""
        return LICENCES.get(self.licence_id or "")


@dataclass(frozen=True)
class DataHome:
    """The directory holding sources, the database, and exports."""

    root: Path = field(default_factory=default_data_home)

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def database(self) -> Path:
        return self.root / "db" / "corpus.sqlite"

    @property
    def exports(self) -> Path:
        return self.root / "export"

    @property
    def manifest(self) -> Path:
        return self.sources / "MANIFEST.jsonl"

    def prepare(self) -> None:
        """Create the directories. Safe to call repeatedly."""
        for path in (self.sources, self.database.parent, self.exports):
            path.mkdir(parents=True, exist_ok=True)

    # -- archive -----------------------------------------------------------------------

    def archive_dir(self, source: str, when: date | None = None) -> Path:
        """Dated directory for one source's downloads."""
        stamp = (when or datetime.now(UTC).date()).isoformat()
        return self.sources / source / stamp

    def latest_archive(self, source: str) -> Path | None:
        """Most recent dated directory for a source, or ``None`` if never fetched."""
        base = self.sources / source
        if not base.is_dir():
            return None
        dated = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
        return dated[0] if dated else None

    def record(self, entry: ManifestEntry) -> None:
        """Append one line to the manifest."""
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("a", encoding="utf-8") as handle:
            handle.write(entry.to_json() + "\n")

    def entries(self, source: str | None = None) -> list[ManifestEntry]:
        """Read the manifest back, newest last."""
        if not self.manifest.exists():
            return []
        out: list[ManifestEntry] = []
        for line in self.manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if source is None or data.get("source") == source:
                out.append(ManifestEntry(**data))
        return out

    def store_file(
        self,
        source: str,
        name: str,
        payload: bytes,
        *,
        url: str,
        license: str | None = None,
        note: str | None = None,
    ) -> Path:
        """Write a downloaded file into the archive and record it."""
        target = self.archive_dir(source) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        self.record(
            ManifestEntry(
                source=source,
                url=url,
                path=str(target.relative_to(self.sources)),
                sha256=hashlib.sha256(payload).hexdigest(),
                bytes=len(payload),
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                license=license,
                note=note,
            )
        )
        return target


#: Columns added to ``source_meta`` after the first release, in the order they arrived.
#:
#: ``CREATE TABLE IF NOT EXISTS`` does nothing to a table that already exists, so a new
#: column in :data:`_SCHEMA` never reaches a database somebody has already built. That
#: matters more here than it looks: :func:`read_meta` does ``SELECT *`` and passes the row
#: straight to :class:`SourceMeta`, so the first ``doctor`` after an upgrade would raise
#: ``TypeError`` on a missing keyword rather than say anything useful. Rebuilding is not an
#: answer -- the database is the better part of a gigabyte and takes an hour.
_ADDED_COLUMNS: Final = (
    ("source_meta", "licence_id", "TEXT"),
    ("source_meta", "licence_ids", "TEXT"),
)


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring an older database up to the current schema. Safe to run every time."""
    for table, column, kind in _ADDED_COLUMNS:
        present = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


@contextmanager
def open_store(home: DataHome) -> Iterator[sqlite3.Connection]:
    """Open the verse database, creating it if needed."""
    home.prepare()
    connection = sqlite3.connect(home.database)
    try:
        connection.executescript(_SCHEMA)
        connection.executescript(SEARCH_SCHEMA)
        _migrate(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()


def write_corpus(home: DataHome, meta: SourceMeta, verses: Iterable[tuple[VerseRef, str]]) -> int:
    """Replace one corpus's verses wholesale.

    Replacing rather than merging keeps a rebuild honest: a parser that starts dropping a
    book shows up as a smaller corpus, not as stale rows left behind from last time.
    """
    with open_store(home) as connection:
        connection.execute("DELETE FROM verse WHERE corpus = ?", (meta.corpus,))
        rows = [
            (meta.corpus, ref.book, int(ref.chapter), ref.verse, ref.subverse, text)
            for ref, text in verses
        ]
        connection.executemany(
            "INSERT OR REPLACE INTO verse "
            "(corpus, book, chapter, verse, subverse, text) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            "INSERT OR REPLACE INTO source_meta (corpus, label, language, versification, "
            "license, attribution, source_url, fetched_at, built_at, verse_count, "
            "licence_id, licence_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                meta.corpus,
                meta.label,
                meta.language,
                meta.versification,
                meta.license,
                meta.attribution,
                meta.source_url,
                meta.fetched_at,
                datetime.now(UTC).isoformat(timespec="seconds"),
                len(rows),
                meta.licence_id,
                meta.licence_ids,
            ),
        )
    return len(rows)


def drop_corpora(home: DataHome, corpora: Sequence[str]) -> dict[str, int]:
    """Remove corpora from the store completely, index and all.

    Deleting the verses by hand is not enough and is worse than doing nothing: the search
    index would keep pointing at them, so a hit would resolve to a corpus the store can no
    longer render, and the document frequencies behind every relevance score would still be
    counting texts that are gone.

    Two subtleties, both of which a plain ``DELETE`` gets wrong:

    * ``search_text`` is deduplicated by hash across corpora, so a text may be shared. Only
      rows nothing points at any more may go -- and their FTS rows with them, keyed on the
      same id.
    * ``search_df`` counts distinct texts per word and has to be recounted afterwards, not
      decremented, because a word's count changes only for the texts that actually vanished.

    :returns: verses removed, by corpus. Ids absent from the store are ignored rather than
        raising: dropping something already gone is the state the caller asked for.
    """
    from .search import recount_df  # deferred: search builds on this module

    removed: dict[str, int] = {}
    if not corpora:
        return removed

    with open_store(home) as connection:
        marks = ", ".join("?" * len(corpora))
        for corpus in corpora:
            row = connection.execute(
                "SELECT COUNT(*) FROM verse WHERE corpus = ?", (corpus,)
            ).fetchone()
            removed[corpus] = int(row[0])

        for table in ("verse", "source_meta", "chapter_state", "search_ref", "search_state"):
            connection.execute(f"DELETE FROM {table} WHERE corpus IN ({marks})", tuple(corpora))

        orphans = [
            int(row[0])
            for row in connection.execute(
                "SELECT id FROM search_text WHERE id NOT IN (SELECT text_id FROM search_ref)"
            )
        ]
        connection.executemany("DELETE FROM search_text WHERE id = ?", [(i,) for i in orphans])
        connection.executemany("DELETE FROM search_fts WHERE rowid = ?", [(i,) for i in orphans])

        recount_df(connection)

    return removed


def add_chapter(
    home: DataHome,
    meta: SourceMeta,
    book: str,
    chapter: int,
    verses: Mapping[int, str],
) -> int:
    """Store one whole chapter of a corpus that is built up a chapter at a time.

    Unlike :func:`write_corpus`, this adds rather than replaces: an online translation
    accumulates as a treatise cites it, and the corpus is whatever has been read so far.
    The chapter is recorded as complete so that a later lookup can tell a verse that is
    genuinely absent -- the NRSV relegates a few verses of Sirach to footnotes -- from one
    that has simply never been fetched.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with open_store(home) as connection:
        connection.execute(
            "INSERT INTO source_meta (corpus, label, language, versification, license, "
            "attribution, source_url, fetched_at, built_at, verse_count, licence_id, "
            "licence_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?) "
            "ON CONFLICT(corpus) DO UPDATE SET label=excluded.label, "
            "attribution=COALESCE(excluded.attribution, source_meta.attribution), "
            "licence_id=COALESCE(excluded.licence_id, source_meta.licence_id), "
            "licence_ids=COALESCE(excluded.licence_ids, source_meta.licence_ids), "
            "built_at=excluded.built_at",
            (
                meta.corpus,
                meta.label,
                meta.language,
                meta.versification,
                meta.license,
                meta.attribution,
                meta.source_url,
                meta.fetched_at or now,
                now,
                meta.licence_id,
                meta.licence_ids,
            ),
        )
        connection.execute(
            "DELETE FROM verse WHERE corpus = ? AND book = ? AND chapter = ?",
            (meta.corpus, book, chapter),
        )
        connection.executemany(
            "INSERT OR REPLACE INTO verse "
            "(corpus, book, chapter, verse, subverse, text) VALUES (?, ?, ?, ?, '', ?)",
            [(meta.corpus, book, chapter, verse, text) for verse, text in verses.items()],
        )
        connection.execute(
            "INSERT OR REPLACE INTO chapter_state "
            "(corpus, book, chapter, fetched_at, verses) VALUES (?, ?, ?, ?, ?)",
            (meta.corpus, book, chapter, now, len(verses)),
        )
        connection.execute(
            "UPDATE source_meta SET verse_count = "
            "(SELECT COUNT(*) FROM verse WHERE corpus = ?) WHERE corpus = ?",
            (meta.corpus, meta.corpus),
        )
    return len(verses)


def read_chapter(home: DataHome, corpus: str, book: str, chapter: int) -> dict[int, str] | None:
    """One stored chapter, or ``None`` if it has never been read in full."""
    if not home.database.exists():
        return None
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            known = connection.execute(
                "SELECT 1 FROM chapter_state WHERE corpus = ? AND book = ? AND chapter = ?",
                (corpus, book, chapter),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if known is None:
            return None
        rows = connection.execute(
            "SELECT verse, text FROM verse WHERE corpus = ? AND book = ? AND chapter = ? "
            "ORDER BY verse",
            (corpus, book, chapter),
        ).fetchall()
    return {verse: text for verse, text in rows}


@dataclass(frozen=True, slots=True)
class LibraryDigest:
    """A fingerprint of everything a machine holds, for comparing two of them.

    Four parts, because when two machines disagree the useful question is immediately
    *which* part disagrees, and one combined hash cannot say.
    """

    sources: str
    """Over the newest fetch of each *registered* source. This is the "hash of the
    hashes": the manifest already records a sha256 per file, so nothing is re-read."""
    texts: str
    """Over every verse `build` put in the database -- corpus, reference and words. What
    the sources digest cannot see: a half-finished build, or a corrupted page."""
    versification: str
    """The vendored mapping data and its corrections, from `versification.fingerprint`."""
    code: str
    """The library version. Same bytes in, different code, different database out."""
    library: str
    """Over the other four. The one line to compare."""
    source_count: int
    verse_count: int
    online: str
    """Over the chapters `resolve` fetched one at a time from a publisher's site. Kept out
    of :attr:`library` on purpose -- see :func:`library_digest`."""
    online_verses: int
    unregistered: tuple[str, ...]
    """Archived sources the code no longer knows about, also kept out of the digest."""

    def describe(self) -> str:
        lines = [
            f"  sources        {self.sources[:16]}  {self.source_count} registered source(s)",
            f"  texts          {self.texts[:16]}  {self.verse_count:,} verses built from them",
            f"  versification  {self.versification[:16]}  vendored data and corrections",
            f"  code           {self.code}",
            f"= library        {self.library}",
        ]
        # Only shown when there is something to say, so the ordinary case stays four lines.
        if self.online_verses:
            lines.append(
                f"\n  aside: {self.online_verses:,} verse(s) resolved from the web "
                f"({self.online[:16]}), which no sync produces and which is not counted above"
            )
        if self.unregistered:
            lines.append(
                f"  aside: archived but no longer registered, so not counted above: "
                f"{', '.join(self.unregistered)}"
            )
        return "\n".join(lines)


def library_digest(home: DataHome) -> LibraryDigest:
    """Fingerprint what this machine holds, so another machine can be compared with it.

    The question this answers is "did a sync produce the same library on both machines",
    and getting there means excluding three things that differ between machines which are,
    for that question, identical.

    **When a source was fetched, and how often.** The manifest records a dated path and a
    timestamp per download, and both differ between two machines that synced on different
    days holding byte-identical archives. Only the source id and checksum are hashed, and
    only the newest per source: fetching something twice does not make a machine different
    from one that fetched it once.

    **Sources the code no longer registers.** An archive is never deleted, so a machine
    that once fetched a source since dropped from the list keeps the files and the
    manifest lines forever. Counting those would mean it could never again match a fresh
    install, which is a permanent false alarm rather than a finding. They are reported in
    :attr:`LibraryDigest.unregistered` instead, because "you have four archives nothing
    reads any more" is worth knowing and is not a difference in the library.

    **Chapters fetched from a publisher's site.** ``resolve`` stores them one at a time as
    it attributes quotations, so they are real content that appears in no manifest -- and
    they are per-machine by nature, accumulating wherever the resolving happens to be run.
    Hashed separately as :attr:`LibraryDigest.online`.

    The texts digest walks the whole verse table in reference order. That sounds expensive
    and is not: about three seconds for the 1.4 million verses of a full sync, which is
    cheap enough that there is no reason to offer a version that skips it and no reason to
    trust the sources alone.
    """
    from .fetch import iter_sources
    from .versification import fingerprint

    # A source's own files, by name. Matching against these rather than trusting the
    # source id is what stops a stray manifest line standing in for a real download: the
    # BibleGateway fetcher used to archive under the id "web", which is also the World
    # English Bible's, so the newest line for "web" was an NIV chapter and the digest took
    # its checksum for the World English Bible's zip. The fetcher has its own namespace
    # now, but the old lines are on disk for good, and an archive is never rewritten.
    declared = {source.id: {file.name for file in source.files} for source in iter_sources(None)}
    newest: dict[str, str] = {}
    archived: set[str] = set()
    for entry in home.entries():  # newest last, so later writes win
        archived.add(entry.source)
        # An archived path is ``<source>/<date>/<the declared name>``, and the declared name
        # is what has to match. Taking the last segment instead works only while no name
        # contains a slash -- one that does would match nothing, and the source would drop
        # out of the digest silently, which is the exact failure this matching exists to
        # prevent.
        if entry.path.split("/", 2)[-1] in declared.get(entry.source, ()):
            newest[entry.source] = entry.sha256
    sources = hashlib.sha256(
        "".join(f"{source}\x1f{digest}\x1e" for source, digest in sorted(newest.items())).encode()
    ).hexdigest()

    texts, online = hashlib.sha256(), hashlib.sha256()
    verses = online_verses = 0
    if home.database.exists():
        with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
            try:
                # Small -- one row per chapter ever resolved -- so reading it up front
                # beats an EXISTS subquery per verse by a wide margin.
                resolved = {
                    tuple(row)
                    for row in connection.execute("SELECT corpus, book, chapter FROM chapter_state")
                }
            except sqlite3.OperationalError:
                resolved = set()
            try:
                rows = connection.execute(
                    "SELECT corpus, book, chapter, verse, subverse, text FROM verse "
                    "ORDER BY corpus, book, chapter, verse, subverse"
                )
            except sqlite3.OperationalError:
                rows = iter(())  # type: ignore[assignment]
            for row in rows:
                line = "\x1f".join(str(field) for field in row).encode("utf-8") + b"\x1e"
                if row[:3] in resolved:
                    online.update(line)
                    online_verses += 1
                else:
                    texts.update(line)
                    verses += 1

    from . import __version__

    parts = (sources, texts.hexdigest(), fingerprint(), __version__)
    return LibraryDigest(
        sources=parts[0],
        texts=parts[1],
        versification=parts[2],
        code=parts[3],
        library=hashlib.sha256("\x1e".join(parts).encode()).hexdigest(),
        source_count=len(newest),
        verse_count=verses,
        online=online.hexdigest(),
        online_verses=online_verses,
        unregistered=tuple(sorted(archived - set(declared))),
    )


def stored_chapters(home: DataHome, corpus: str) -> list[tuple[str, int, int]]:
    """``(book, chapter, verse count)`` for every chapter held of a corpus."""
    if not home.database.exists():
        return []
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute(
                "SELECT book, chapter, verses FROM chapter_state WHERE corpus = ? "
                "ORDER BY book, chapter",
                (corpus,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [(book, chapter, count) for book, chapter, count in rows]


def read_meta(home: DataHome) -> list[SourceMeta]:
    """Everything the database knows it holds."""
    if not home.database.exists():
        return []
    with closing(sqlite3.connect(home.database)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM source_meta ORDER BY corpus").fetchall()
        except sqlite3.OperationalError:
            return []
    return [SourceMeta(**dict(row)) for row in rows]


class SqliteCorpus:
    """A corpus read from the built database.

    Every fetched text -- Hebrew, Greek, Latin, English -- is served through this one
    class; what differs between them lives in the parser that filled the table, not in
    the reading.
    """

    def __init__(self, home: DataHome, meta: SourceMeta) -> None:
        self._home = home
        self._meta = meta
        self._connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        self._books: frozenset[str] | None = None

    @classmethod
    def load_all(cls, home: DataHome) -> dict[str, SqliteCorpus]:
        """Open every corpus the database holds, keyed by id."""
        return {meta.corpus: cls(home, meta) for meta in read_meta(home)}

    @property
    def id(self) -> str:
        return self._meta.corpus

    @property
    def label(self) -> str:
        return self._meta.label

    @property
    def language(self) -> str:
        return self._meta.language

    @property
    def versification(self) -> str:
        return self._meta.versification

    @property
    def attribution(self) -> str | None:
        return self._meta.attribution

    @property
    def meta(self) -> SourceMeta:
        return self._meta

    def has_book(self, book: str) -> bool:
        if self._books is None:
            rows = self._connection.execute(
                "SELECT DISTINCT book FROM verse WHERE corpus = ?", (self.id,)
            ).fetchall()
            self._books = frozenset(row[0] for row in rows)
        return book in self._books

    def fetch(self, refs: Sequence[VerseRef]) -> list[VerseText]:
        out: list[VerseText] = []
        for ref in refs:
            if ref.is_letter_chapter:
                raise VerseUnavailable(ref, self.label, "letter chapters are not stored")
            row = self._connection.execute(
                "SELECT text FROM verse WHERE corpus = ? AND book = ? AND chapter = ? "
                "AND verse = ? AND subverse = ?",
                (self.id, ref.book, int(ref.chapter), ref.verse, ref.subverse),
            ).fetchone()
            if row is None:
                raise VerseUnavailable(ref, self.label)
            out.append(VerseText(ref=ref, text=row[0]))
        return out

    def close(self) -> None:
        self._connection.close()
