"""The process-wide cache: shared where it must be, per-thread where it cannot be.

The distinction is the whole content of this module. A SQLite connection belongs to the
thread that opened it, so the corpora are per-thread; what those corpora *hold* is three
whole-table queries that cannot change until the database is rebuilt, so that is per
process. Getting it the other way round is what made a page 226 ms, because a browser opens
six connections and each got its own thread and each re-ran the 194 ms query.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from biblereference.refs import VerseRef
from biblereference.search import build_index
from biblereference.store import DataHome, SourceMeta, write_corpus
from biblereference.web import library as lib
from biblereference.web import server


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataHome:
    """A small real database, and the module globals pointed at it.

    The cache is a module global and survives between tests, so it is reset here rather
    than left for the next test to trip over.
    """
    where = DataHome(tmp_path)
    write_corpus(
        where,
        SourceMeta(corpus="alpha", label="Alpha", language="en", versification="eng"),
        [(VerseRef("JHN", 3, verse), f"john three {verse}") for verse in range(1, 20)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="beta", label="Beta", language="la", versification="vul"),
        [(VerseRef("PSA", 118, verse), f"psalmus {verse}") for verse in range(1, 10)],
    )
    monkeypatch.setattr(server, "HOME", where)
    monkeypatch.setattr(lib, "_LIBRARY", None)
    monkeypatch.setattr(lib, "_local", threading.local())
    return where


def in_a_thread(work):  # type: ignore[no-untyped-def]
    """Run ``work`` on a thread that has never touched the library, and return its result."""
    out: dict[str, object] = {}
    thread = threading.Thread(target=lambda: out.update(value=work()))
    thread.start()
    thread.join()
    return out["value"]


# --------------------------------------------------------------------------------------
# Shared for the process
# --------------------------------------------------------------------------------------


def test_every_thread_shares_one_answer_about_what_the_library_holds(home: DataHome) -> None:
    """The point of the whole module. Not merely equal -- the same object, because the
    equal-but-rebuilt version is the 194 ms this exists to stop paying."""
    first = lib.library()
    assert in_a_thread(lib.library) is first
    assert in_a_thread(lib.library) is first


def test_a_rebuilt_database_replaces_it(home: DataHome) -> None:
    """A cache that could not notice a rebuild would answer out of the old library
    indefinitely, which is worse than not having one."""
    before = lib.library()
    assert set(before.books) == {"alpha", "beta"}

    time.sleep(0.01)  # so the mtime is certain to differ
    write_corpus(
        home,
        SourceMeta(corpus="gamma", label="Gamma", language="grc", versification="lxx"),
        [(VerseRef("GEN", 1, 1), "εν αρχη")],
    )

    after = lib.library()
    assert after is not before
    assert set(after.books) == {"alpha", "beta", "gamma"}
    # Not `filters`, which now answers what can be *searched* and so is empty until
    # something is indexed. The metadata is the derived fact this test is about.
    assert after.meta["gamma"].versification == "lxx"


def test_a_fresh_thread_asks_the_database_nothing_about_books(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measurement, made as a fact rather than as a stopwatch.

    Opening sixty-odd connections is 5 ms and unavoidable per thread. Asking each of them
    what it holds is 194 ms, and *that* is what must happen once. Counting the calls says so
    on any machine, where a timing assertion says it only on a quiet one.
    """
    lib.library()  # the one time it is allowed

    calls = []
    monkeypatch.setattr(lib, "all_books", lambda where: calls.append(where) or {})

    for _ in range(4):
        assert set(in_a_thread(lambda: set(lib.corpora()))) == {"alpha", "beta"}
    assert calls == [], "a request thread went back to the database for the book lists"


def test_the_corpora_are_still_per_thread(home: DataHome) -> None:
    """They must not be shared, whatever else is: a connection used from a thread that did
    not open it is undefined behaviour that shows up as corruption, not as an exception."""
    mine = lib.corpora()["alpha"]
    theirs = in_a_thread(lambda: lib.corpora()["alpha"])
    assert mine is not theirs
    assert mine.books == theirs.books


def test_a_rebuild_reopens_this_threads_corpora(home: DataHome) -> None:
    """Otherwise a thread that had already served a request would keep reading the old
    database through connections nobody replaced."""
    before = lib.corpora()
    assert set(before) == {"alpha", "beta"}

    time.sleep(0.01)
    write_corpus(
        home,
        SourceMeta(corpus="gamma", label="Gamma", language="grc", versification="lxx"),
        [(VerseRef("GEN", 1, 1), "εν αρχη")],
    )

    after = lib.corpora()
    assert set(after) == {"alpha", "beta", "gamma"}
    assert after["alpha"] is not before["alpha"]
    assert lib.by_system()["lxx"][0].id == "gamma", "the grouping was rebuilt too"


# --------------------------------------------------------------------------------------
# The filters, which moved
# --------------------------------------------------------------------------------------


def test_the_filters_say_exactly_what_can_be_searched(home: DataHome) -> None:
    """Derived from the search index rather than from the metadata, because built and
    searchable are two facts and this gate used to check the wrong one -- refusing
    `klingon` while waving through `syc`, which held not one indexed verse."""
    build_index(home, corpora=["alpha"])
    lib._LIBRARY = None

    assert lib.known_filters() == {
        "corpora": {"alpha"},
        "languages": {"en"},
        "families": {"eng"},
    }
    assert lib.searchable_corpora() == frozenset({"alpha"})
    # Everything built, which is the other question and still has an answer.
    assert lib.built_filters()["corpora"] == {"alpha", "beta"}


def test_a_filter_is_still_refused_rather_than_ignored(home: DataHome) -> None:
    """The behaviour `search_options` exists for, checked against the new source of the
    known values."""
    build_index(home)
    lib._LIBRARY = None

    assert server.search_options({"languages": ["en"]}) == {"languages": ["en"]}
    with pytest.raises(LookupError, match="klingon"):
        server.search_options({"languages": ["klingon"]})


def test_a_corpus_held_but_unindexed_is_refused_for_the_right_reason(home: DataHome) -> None:
    """Two refusals, because a typo and an unrun command want different things done about
    them, and only one of them is the caller's fault."""
    build_index(home, corpora=["alpha"])
    lib._LIBRARY = None

    with pytest.raises(LookupError) as raised:
        server.search_options({"languages": ["la"]})
    assert "not in the search index" in str(raised.value)
    assert "biblereference index --stale" in str(raised.value)
    # Not the message for something never heard of, which offers no cure.
    assert "unknown languages" not in str(raised.value)


# --------------------------------------------------------------------------------------
# The expensive one, kept out of the common path
# --------------------------------------------------------------------------------------


def test_the_chapter_index_is_built_once_and_only_when_wanted(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third of a second and three megabytes. Every request needs `books`; only the
    reader needs this, so building it with the rest would tax every other endpoint."""
    held = lib.library()
    assert held._chapters is None, "built before anyone asked"

    calls = []
    real = lib.chapter_index
    monkeypatch.setattr(lib, "chapter_index", lambda w: calls.append(w) or real(w))

    assert held.chapters["alpha"]["JHN"][3] == 19
    assert held.chapters["beta"]["PSA"][118] == 9
    assert in_a_thread(lambda: lib.library().chapters["alpha"]["JHN"][3]) == 19
    assert len(calls) == 1


def test_prewarm_leaves_nothing_for_the_first_request_to_do(home: DataHome) -> None:
    """Half a second of whole-table queries, spent while nobody is waiting."""
    lib.prewarm().join(timeout=30)
    held = lib.library()
    assert held._chapters is not None
    assert set(held.books) == {"alpha", "beta"}
