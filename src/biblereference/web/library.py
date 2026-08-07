"""What this machine holds, and which library produced an answer.

Everything here is derived from the built database rather than asked of it per request, so
that a page rendering sixty-odd corpora is not sixty-odd table scans. The corpora
themselves are per *thread*, because a SQLite connection belongs to the thread that opened
it and :class:`~http.server.ThreadingHTTPServer` hands each request to a new one.
"""

from __future__ import annotations

import threading
from typing import Any, Final

from ..store import DataHome, SqliteCorpus, all_books, library_digest
from ..versification import Versification

#: The shipped numbering systems. Bound at import, unlike ``HOME``, because it is built
#: from vendored package data that no data home can vary -- and ``Versification.load`` is
#: cached anyway, so a second caller gets this same object.
VRS: Final = Versification.load()

# SQLite connections belong to the thread that opened them and the server hands each
# request to a new one, so every thread gets its own set. Opening sixty-odd corpora costs
# a few milliseconds; finding out what each one holds costs a quarter of a second, which is
# why `all_books` seeds them rather than each corpus asking for itself.
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


def corpora() -> dict[str, SqliteCorpus]:
    """Every built corpus, opened once for this thread."""
    if not hasattr(_local, "corpora"):
        where = home()
        _local.corpora = SqliteCorpus.load_all(where, books=all_books(where))
    built: dict[str, SqliteCorpus] = _local.corpora
    return built


def by_system() -> dict[str, list[SqliteCorpus]]:
    """Corpora grouped by the versification they number in."""
    if not hasattr(_local, "by_system"):
        grouped: dict[str, list[SqliteCorpus]] = {}
        for corpus in sorted(corpora().values(), key=lambda c: (c.language, c.id)):
            grouped.setdefault(corpus.versification, []).append(corpus)
        _local.by_system = grouped
    groups: dict[str, list[SqliteCorpus]] = _local.by_system
    return groups


def known_filters() -> dict[str, set[str]]:
    """What this machine actually holds, so a filter naming anything else can be refused."""
    if not hasattr(_local, "filters"):
        held = corpora().values()
        _local.filters = {
            "corpora": {c.id for c in held},
            "languages": {c.language for c in held},
            "families": {c.versification for c in held},
        }
    filters: dict[str, set[str]] = _local.filters
    return filters


_STAMP: dict[str, Any] = {}
_STAMP_LOCK = threading.Lock()


def library_stamp() -> Any:
    """Which library produced a result, carried on the result itself.

    A mapping correction is an edit to a JSON file, not a version bump, so a caller that
    only recorded a version would not notice one. Asking ``/api/digest`` separately and
    hoping nothing changed in between is the same gap in slower motion.

    Cached against the database's size and mtime, because the full digest walks 1.4 million
    verses at about three seconds and this rides on every search. A rebuild or a chapter
    resolved from the web moves both, so the cache cannot go stale without being noticed.
    """
    where = home()
    try:
        stat = where.database.stat()
        # The path is in the key as well as the size and mtime, because `HOME` is rebindable
        # and two data homes in one process could otherwise collide on both.
        key = (str(where.database), stat.st_size, stat.st_mtime_ns)
    except OSError:
        key = (str(where.database), 0, 0)
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
