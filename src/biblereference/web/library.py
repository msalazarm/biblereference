"""What this machine holds: read once for the process, not once per request.

Two different lifetimes live here, and confusing them is what made the page slow.

**The derived facts** -- which corpus holds which book, how long each chapter is, what each
edition is called and licensed under -- come from three whole-table queries and cannot
change until the database is rebuilt. They belong to the *process*, and :class:`Library`
holds them behind a key of the database's path, size and mtime, so a rebuild or a chapter
resolved from the web replaces them and nothing else can.

**The connections** cannot be shared: a SQLite connection belongs to the thread that opened
it and :class:`~http.server.ThreadingHTTPServer` hands each request to a new thread. So the
corpora stay per-thread -- but seeded from the process-wide table, which is the whole point.
Opening sixty-odd connections is 5 ms; finding out what they hold is 194 ms, and a browser
opening six connections used to pay it six times.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, Final

from ..store import (
    DataHome,
    SourceMeta,
    SqliteCorpus,
    all_books,
    chapter_index,
    library_digest,
    read_meta,
)
from ..versification import Versification

#: The shipped numbering systems. Bound at import, unlike ``HOME``, because it is built
#: from vendored package data that no data home can vary -- and ``Versification.load`` is
#: cached anyway, so a second caller gets this same object.
VRS: Final = Versification.load()

_local = threading.local()


def home() -> DataHome:
    """This process's data home, read at call time.

    The rule of this package. ``server.HOME`` is rebound by ``--data-home`` and by
    ``tests/test_server.py``, which points a whole server at the real store before starting
    it; a module that had bound the name at import would keep answering out of the home it
    found first.
    """
    from .server import HOME

    return HOME


def _key(where: DataHome) -> tuple[str, int, int]:
    """What identifies a build of the database: where it is, how big, how old.

    A rebuild moves both the size and the mtime, and so does a chapter resolved from the
    web, so the cache cannot go stale without being noticed. The path is in the key too,
    because ``HOME`` is rebindable and two data homes in one process would otherwise be
    able to collide on the other two.
    """
    try:
        stat = where.database.stat()
        return (str(where.database), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return (str(where.database), 0, 0)


class Library:
    """The derived, read-only facts about one build of the database.

    Built under a lock and shared by every thread. Nothing here is mutated after
    construction except :attr:`chapters`, which is memoised on first ask because it is the
    expensive one and only the reader needs it.
    """

    __slots__ = ("_chapters", "_lock", "books", "filters", "home", "key", "meta")

    def __init__(self, where: DataHome, key: tuple[str, int, int]) -> None:
        self.home = where
        self.key = key
        #: ``corpus -> the books it holds``. One query; seeds every thread's corpora.
        self.books: Mapping[str, frozenset[str]] = all_books(where)
        #: ``corpus -> SourceMeta``, in the database's own order.
        self.meta: Mapping[str, SourceMeta] = {row.corpus: row for row in read_meta(where)}
        #: What a filter may name. Derived from the metadata rather than from open corpora,
        #: so asking costs nothing.
        self.filters: Mapping[str, set[str]] = {
            "corpora": {row.corpus for row in self.meta.values()},
            "languages": {row.language for row in self.meta.values()},
            "families": {row.versification for row in self.meta.values()},
        }
        self._chapters: dict[str, dict[str, dict[int, int]]] | None = None
        self._lock = threading.Lock()

    @property
    def chapters(self) -> Mapping[str, Mapping[str, Mapping[int, int]]]:
        """``corpus -> book -> chapter -> verses held``, for the whole library.

        A third of a second and about three megabytes, which is why it is not built with
        the rest: every request needs :attr:`books`, and only the reader needs this. The
        pre-warm thread asks for it at startup so that the first reader does not.
        """
        with self._lock:
            if self._chapters is None:
                self._chapters = chapter_index(self.home)
            return self._chapters


_LIBRARY: Library | None = None
_LIBRARY_LOCK = threading.Lock()


def library() -> Library:
    """The process-wide facts, rebuilt only when the database underneath them changes.

    The build happens *inside* the lock on purpose. It is 200 ms, and a browser opening six
    connections at once would otherwise do it six times over; one thread doing it while five
    wait is the same 200 ms rather than six times it.
    """
    global _LIBRARY
    where = home()
    key = _key(where)
    with _LIBRARY_LOCK:
        if _LIBRARY is None or _LIBRARY.key != key:
            _LIBRARY = Library(where, key)
        return _LIBRARY


def prewarm() -> threading.Thread:
    """Build the process-wide facts in the background, so the first request does not.

    A daemon thread: if the server is stopped while this is still running there is nothing
    to wait for, and everything it computes is recomputable.
    """
    thread = threading.Thread(target=lambda: library().chapters, name="prewarm", daemon=True)
    thread.start()
    return thread


def corpora() -> dict[str, SqliteCorpus]:
    """Every built corpus, opened once for this thread and seeded from the process cache."""
    held = library()
    if getattr(_local, "key", None) != held.key:
        for corpus in getattr(_local, "corpora", {}).values():
            corpus.close()
        _local.corpora = SqliteCorpus.load_all(held.home, books=held.books)
        _local.by_system = None
        _local.key = held.key
    built: dict[str, SqliteCorpus] = _local.corpora
    return built


def by_system() -> dict[str, list[SqliteCorpus]]:
    """Corpora grouped by the versification they number in."""
    held = corpora()  # first, so a rebuild clears the grouping below
    if getattr(_local, "by_system", None) is None:
        grouped: dict[str, list[SqliteCorpus]] = {}
        for corpus in sorted(held.values(), key=lambda c: (c.language, c.id)):
            grouped.setdefault(corpus.versification, []).append(corpus)
        _local.by_system = grouped
    groups: dict[str, list[SqliteCorpus]] = _local.by_system
    return groups


def known_filters() -> Mapping[str, set[str]]:
    """What this machine actually holds, so a filter naming anything else can be refused."""
    return library().filters


_STAMP: dict[str, Any] = {}
_STAMP_LOCK = threading.Lock()


def library_stamp() -> Any:
    """Which library produced a result, carried on the result itself.

    A mapping correction is an edit to a JSON file, not a version bump, so a caller that
    only recorded a version would not notice one. Asking ``/api/digest`` separately and
    hoping nothing changed in between is the same gap in slower motion.

    Cached against :func:`_key`, because the full digest walks 1.4 million verses at about
    three seconds and this rides on every search.
    """
    where = home()
    key = _key(where)
    with _STAMP_LOCK:
        if _STAMP.get("key") != key:
            digest = library_digest(where)
            _STAMP.update(
                key=key,
                value={
                    "versification": digest.versification,
                    "digest": digest.library,
                    "code": digest.code,
                },
            )
        return _STAMP["value"]
