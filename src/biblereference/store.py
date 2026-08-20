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
    "all_books",
    "chapter_index",
    "default_data_home",
    "library_digest",
    "open_store",
    "read_chapter",
    "read_meta",
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

-- What was indexed for each corpus, and what it was indexed *from*.
--
-- `verses` counts the verses that produced a non-empty fold; `source_verses` counts what
-- the store held at the time. They differ legitimately -- a verse of nothing but editorial
-- sigla folds away -- and comparing `verses` against `source_meta.verse_count` therefore
-- reported four corpora as permanently stale, which reindexing could never clear. Keeping
-- both means "never indexed" and "has drifted" can be told apart, which is the whole use
-- anyone has for this table.
CREATE TABLE IF NOT EXISTS search_state (
    corpus        TEXT PRIMARY KEY,
    indexed_at    TEXT    NOT NULL,
    verses        INTEGER NOT NULL,
    source_verses INTEGER,
    fold_version  INTEGER
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


#: The second index: the same verses keyed by *dictionary form* rather than by spelling.
#:
#: A father quoting scripture adapts its grammar to his own sentence. Ignatius shares
#: fourteen words with Matthew 10:16 and his longest identically-spelled run is one, because
#: Matthew addresses disciples in the plural and Ignatius addresses one bishop. Measured over
#: 5,770 editor-marked Greek quotations, 27.5% have no four consecutive words spelled as the
#: source spells them, and no threshold over :data:`SEARCH_SCHEMA` can reach them.
#:
#: Kept in its own tables and never merged into the ones above. Half a million findings
#: downstream rest on what the exact-form index returns, and a document frequency shifted by
#: a lemma would move scores for every query ever asked. Greek and Latin only: English does
#: not inflect enough to need it, and folding it in would change what English already finds.
LEMMA_SCHEMA: Final = """
-- The fetched lexicon: which dictionary forms a spelling can belong to. Keyed on the
-- *folded* form, so it meets the search where the search already stands. One form may carry
-- several lemmas -- Greek `ἄρῃ` carries three -- and all of them are kept: a match needs
-- only that two words share one reading, and choosing between them here would be a guess
-- made where there is no context to make it with.
CREATE TABLE IF NOT EXISTS lemma_form (
    language TEXT NOT NULL,
    form     TEXT NOT NULL,
    lemma    TEXT NOT NULL,
    PRIMARY KEY (language, form, lemma)
) WITHOUT ROWID;

-- Which fold built the table above. It had none, and could not: the forms are folded on the
-- way in, so a fold change silently leaves every key spelled the way the old rule spelled it
-- and `scan --inflected` quietly stops finding the words it stopped agreeing about. The
-- search index has carried `fold_version` since it was bitten by exactly this; the lexicon
-- is the same artifact with the same hazard and had no stamp to check.
CREATE TABLE IF NOT EXISTS lemma_form_state (
    language     TEXT PRIMARY KEY,
    built_at     TEXT    NOT NULL,
    fold_version INTEGER NOT NULL,
    forms        INTEGER NOT NULL,
    readings     INTEGER NOT NULL
) WITHOUT ROWID;

-- Unstemmed on purpose. `porter` is an English stemmer; on Greek it is noise, and the
-- lemmas are already the reduction it would be trying and failing to approximate.
CREATE VIRTUAL TABLE IF NOT EXISTS lemma_fts USING fts5(
    lemmas,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS lemma_text (
    id   INTEGER PRIMARY KEY,
    hash BLOB    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS lemma_ref (
    corpus   TEXT    NOT NULL,
    book     TEXT    NOT NULL,
    chapter  INTEGER NOT NULL,
    verse    INTEGER NOT NULL,
    subverse TEXT    NOT NULL DEFAULT '',
    text_id  INTEGER NOT NULL,
    PRIMARY KEY (corpus, book, chapter, verse, subverse)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS lemma_ref_by_text ON lemma_ref (text_id);

-- Counted per language, which is the whole point of it. How surprising `θεόσ` is has to be
-- measured against the Greek a father could have written, not diluted by 900,000 English
-- verses that could never have contained it. `verses` is the denominator: the number of
-- verses of that language the count was taken over.
CREATE TABLE IF NOT EXISTS lemma_df (
    language TEXT    NOT NULL,
    lemma    TEXT    NOT NULL,
    docs     INTEGER NOT NULL,
    PRIMARY KEY (language, lemma)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS lemma_total (
    language TEXT PRIMARY KEY,
    verses   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lemma_state (
    corpus        TEXT PRIMARY KEY,
    indexed_at    TEXT    NOT NULL,
    verses        INTEGER NOT NULL,
    source_verses INTEGER,
    fold_version  INTEGER
);
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
    # Nullable on purpose. An index built before this column existed cannot say what it was
    # built from, and NULL means exactly that -- not zero, and not "stale". Telling a user
    # to reindex on the strength of a column we only just added would be crying wolf.
    ("search_state", "source_verses", "INTEGER"),
    # Which fold folded it. The index keys on `sha1(fold(text))`, so a change to the fold
    # invalidates every entry while leaving every count identical -- the one kind of
    # staleness the verse comparison provably cannot see. Nullable for the same reason as
    # `source_verses`: an index built before this column can only say "unknown".
    ("search_state", "fold_version", "INTEGER"),
    ("lemma_state", "fold_version", "INTEGER"),
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
        connection.executescript(LEMMA_SCHEMA)
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
    from .search import recount_df, recount_lemma_df  # deferred: search builds on this module

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

        for table in (
            "verse",
            "source_meta",
            "chapter_state",
            "search_ref",
            "search_state",
            # The lemma index is keyed by corpus too, and leaving it behind would be the
            # same fault in the newer half: a hit resolving to a corpus that is gone.
            "lemma_ref",
            "lemma_state",
        ):
            connection.execute(f"DELETE FROM {table} WHERE corpus IN ({marks})", tuple(corpora))

        for text, ref, fts in (
            ("search_text", "search_ref", "search_fts"),
            ("lemma_text", "lemma_ref", "lemma_fts"),
        ):
            orphans = [
                int(row[0])
                for row in connection.execute(
                    f"SELECT id FROM {text} WHERE id NOT IN (SELECT text_id FROM {ref})"
                )
            ]
            connection.executemany(f"DELETE FROM {text} WHERE id = ?", [(i,) for i in orphans])
            connection.executemany(f"DELETE FROM {fts} WHERE rowid = ?", [(i,) for i in orphans])

        recount_df(connection)
        recount_lemma_df(connection)

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


def all_books(home: DataHome) -> dict[str, frozenset[str]]:
    """Which books each corpus holds, for the whole library, in one query.

    The same answer :attr:`SqliteCorpus.books` gives, asked once for everybody. Sixty-odd
    corpora asking separately is a quarter of a second and this is a fifth of that; the
    difference matters because the per-corpus answer is cached on the corpus object, and
    anything that opens a fresh set of corpora -- a thread, a worker -- pays it again.
    """
    if not home.database.exists():
        return {}
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute("SELECT DISTINCT corpus, book FROM verse").fetchall()
        except sqlite3.OperationalError:
            return {}
    out: dict[str, set[str]] = {}
    for corpus, book in rows:
        out.setdefault(corpus, set()).add(book)
    return {corpus: frozenset(books) for corpus, books in out.items()}


def chapter_index(home: DataHome) -> dict[str, dict[str, dict[int, int]]]:
    """``corpus -> book -> chapter -> verses held``, for the whole library, in one query.

    What a reader needs before it fetches anything: which versions carry the passage at all,
    how far each book runs in each of them, and which chapters are short. Answering it from
    the verse table per request would be a scan a second; answering it once is half a second
    and about three megabytes, and it only changes when the database is rebuilt.

    Counts, not verse numbers. A chapter that omits a verse the edition does not print has a
    lower count than its highest number, and that difference is real -- it is what
    :func:`~biblereference.audit.faithful_chapters` looks at -- so a caller wanting the
    highest number has to ask for it rather than infer it from here.
    """
    if not home.database.exists():
        return {}
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute(
                "SELECT corpus, book, chapter, COUNT(*) FROM verse GROUP BY corpus, book, chapter"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    out: dict[str, dict[str, dict[int, int]]] = {}
    for corpus, book, chapter, count in rows:
        out.setdefault(corpus, {}).setdefault(book, {})[int(chapter)] = int(count)
    return out


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

    def __init__(
        self, home: DataHome, meta: SourceMeta, books: frozenset[str] | None = None
    ) -> None:
        self._home = home
        self._meta = meta
        self._connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
        self._books = books

    @classmethod
    def load_all(
        cls, home: DataHome, books: Mapping[str, frozenset[str]] | None = None
    ) -> dict[str, SqliteCorpus]:
        """Open every corpus the database holds, keyed by id.

        Opening the connections is cheap -- a few milliseconds for the whole library. What
        is not is the ``SELECT DISTINCT book`` each corpus runs the first time it is asked
        whether it holds something: a quarter of a second across sixty-odd corpora, paid
        again by every thread that opens its own set. Pass ``books`` -- from
        :func:`all_books`, which answers for the whole library in one query -- to seed them.
        """
        return {
            meta.corpus: cls(home, meta, books.get(meta.corpus) if books else None)
            for meta in read_meta(home)
        }

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

    @property
    def books(self) -> frozenset[str]:
        """Every book this corpus holds. Read once and kept."""
        if self._books is None:
            rows = self._connection.execute(
                "SELECT DISTINCT book FROM verse WHERE corpus = ?", (self.id,)
            ).fetchall()
            self._books = frozenset(row[0] for row in rows)
        return self._books

    def has_book(self, book: str) -> bool:
        return book in self.books

    def available(self, refs: Sequence[VerseRef]) -> list[VerseText]:
        """The verses of ``refs`` this corpus actually holds, in order, skipping the rest.

        :meth:`fetch` raises on the first missing verse, and that is the right contract for
        the renderer: a citation that silently loses a verse is a citation that misquotes.
        Reading is the other case. Editions genuinely differ about what a chapter contains,
        and a chapter shown with two verses absent is worth reading where a chapter refused
        outright is not -- so this reports what is there and lets the caller see the
        difference by counting.
        """
        wanted = [ref for ref in refs if not ref.is_letter_chapter]
        if not wanted:
            return []
        found: dict[tuple[str, int, int, str], str] = {}
        # One query per chapter rather than one per verse: a chapter of a psalm is 176
        # round trips otherwise, and every corpus in the library pays them.
        for book, chapter in dict.fromkeys((ref.book, int(ref.chapter)) for ref in wanted):
            for verse, subverse, text in self._connection.execute(
                "SELECT verse, subverse, text FROM verse "
                "WHERE corpus = ? AND book = ? AND chapter = ?",
                (self.id, book, chapter),
            ):
                found[(book, chapter, int(verse), subverse or "")] = text
        out = []
        for ref in wanted:
            text = found.get((ref.book, int(ref.chapter), ref.verse, ref.subverse))
            if text is not None:
                out.append(VerseText(ref=ref, text=text))
        return out

    def chapter(self, book: str, chapter: int) -> list[VerseText]:
        """Every verse the corpus holds of one chapter, in its own numbering.

        Unlike :meth:`available` this does not need to be told which verses to expect, so it
        answers for an edition that prints verses its declared system does not have --
        which is how a corpus's own divisions become visible rather than being clipped to
        the system's.
        """
        rows = self._connection.execute(
            "SELECT verse, subverse, text FROM verse "
            "WHERE corpus = ? AND book = ? AND chapter = ? ORDER BY verse, subverse",
            (self.id, book, int(chapter)),
        ).fetchall()
        return [
            VerseText(
                ref=VerseRef(book, chapter, int(verse), subverse or "", vrs=self.versification),
                text=text,
            )
            for verse, subverse, text in rows
        ]

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
