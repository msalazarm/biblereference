"""The slow walks, in their own processes.

Each of these is a whole-corpus walk taking minutes, and each runs in a *spawned* process
so that several use several cores and none of them inherits a SQLite connection from this
one -- a forked child would, and two processes writing through one connection is how a
database gets corrupted. They take and return plain data for the same reason: it has to
cross a pickle.

Which is also why this is a package module rather than a script. A spawned worker unpickles
a task by module name, so ``biblereference.web.jobs.job_scan`` has to be importable in a
fresh interpreter with nothing poked into ``sys.path``.
"""

from __future__ import annotations

import itertools
import multiprocessing
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any, Final

from .library import library_stamp

__all__ = ["BATCH_TASKS", "TASKS", "Jobs"]


def job_coverage(covering: bool = False) -> Any:
    """Convert every verse of every system and account for what came back."""
    from biblereference.audit import runs_of, verify_every_verse
    from biblereference.cli import COVERAGE_WITNESSES
    from biblereference.store import DataHome
    from biblereference.versification import Versification

    home, vrs = DataHome(), Versification.load()
    coverage, ghosts, contradicted = verify_every_verse(
        home, vrs, COVERAGE_WITNESSES, covering=covering
    )
    runs = runs_of(contradicted, 4)
    return {
        "systems": [
            {
                "system": row.system,
                "total": row.total,
                "refused": row.refused,
                "ghost": row.ghost,
                "checked": row.checked,
                "confirmed": row.confirmed,
                "contradicted": row.contradicted,
                "weak": row.weak,
                "unwitnessed": row.unwitnessed,
                "describe": row.describe(),
            }
            for row in coverage
        ],
        "ghosts": ghosts,
        "contradicted": len(contradicted),
        "runs": [
            {"system": s, "book": b, "chapter": c, "first": f, "last": last, "length": last - f + 1}
            for s, b, c, f, last in runs
        ],
    }


def job_audit(book: str | None = None, covering: bool = False) -> Any:
    """Check every family pair's mappings against the text of their witnesses."""
    from biblereference.audit import audit_all
    from biblereference.canon import resolve_book
    from biblereference.store import DataHome

    books = [resolve_book(book)] if book else None
    results = audit_all(DataHome(), books=books, covering=covering)
    return {
        "pairs": [
            {
                "source": r.source,
                "target": r.target,
                "witnesses": [r.source_corpus, r.target_corpus],
                "language": r.language,
                "decisive": r.decisive,
                "agreed": r.agreed,
                "rate": round(r.rate, 6),
                "weak": r.weak,
                "unmapped": r.unmapped,
                "flagged": len(r.disagreements),
                "summary": r.summary(),
            }
            for r in results
        ]
    }


def job_compare(left: str, right: str, book: str | None = None, covering: bool = False) -> Any:
    """How far two editions of one text have drifted apart, book by book."""
    from biblereference.canon import resolve_book
    from biblereference.compare import compare_corpora
    from biblereference.store import DataHome, SqliteCorpus
    from biblereference.versification import Versification

    home = DataHome()
    built = SqliteCorpus.load_all(home)
    missing = [name for name in (left, right) if name not in built]
    if missing:
        raise LookupError(f"not built: {', '.join(missing)}")
    books = [resolve_book(book)] if book else None
    rows = compare_corpora(
        built[left], built[right], Versification.load(), books=books, covering=covering
    )
    return {
        "books": [
            {
                "book": row.book,
                "title": row.title,
                "compared": row.compared,
                "identical": row.identical,
                "differing": len(row.differing),
                "share_differing": round(row.share_differing, 6),
                "mean_similarity": round(row.mean_similarity, 6),
                "missing_left": row.missing_left,
                "missing_right": row.missing_right,
                # The verses themselves, not just the count -- a whole-Bible comparison
                # would be megabytes of them, so this is the worst handful per book and
                # the count above says how many were left out.
                "worst": [
                    {
                        "ref": d.ref.pretty(),
                        "left": d.left,
                        "right": d.right,
                        "similarity": round(d.similarity, 4),
                    }
                    for d in sorted(row.differing, key=lambda d: d.similarity)[:5]
                ],
            }
            for row in rows
        ]
    }


#: One `Searcher` per configuration per worker process. Constructing one opens a database
#: and counts the index, which is wasted on every call after the first; a worker handles
#: thousands.
_SEARCHERS: dict[Any, Any] = {}


def worker_searcher(options: dict[str, Any]) -> Any:
    import os

    from biblereference.search import Searcher
    from biblereference.store import DataHome

    key = tuple(sorted((name, repr(value)) for name, value in options.items()))
    if key not in _SEARCHERS:
        # The composite artifact arrives by environment, not by option: this worker was
        # spawned, and `serve --composite` set the variable before the pool existed.
        # Injected here rather than folded into `options` so the cache key stays what
        # the request asked for.
        built = dict(options)
        artifact = os.environ.get("BIBLEREFERENCE_COMPOSITE")
        if artifact:
            built["composite"] = artifact
        _SEARCHERS[key] = Searcher(DataHome(), **built)
    return _SEARCHERS[key]


def job_scan_one(text: str, options: dict[str, Any]) -> list[Any]:
    """One document, in a worker process.

    Scanning is pure-Python string comparison and holds the GIL throughout, so serving it
    on a request thread gives one core's worth of throughput however many requests arrive
    at once -- measured at 16% of a 32-thread machine, with four simultaneous requests
    taking the same wall time as one. The pool is the only thing here that is actually
    parallel, so single requests go through it too rather than only batches.
    """
    if not text.strip():
        return []
    return [match.to_dict() for match in worker_searcher(options).scan(text)]


def job_debts_one(text: str, options: dict[str, Any]) -> list[Any]:
    """One document's announced-but-unmatched citation formulae, in a worker process.

    The recall-debt ledger over the wire. It costs a full scan to compute -- the debts
    are what the scan did *not* answer -- so it runs where every other scan runs.
    """
    if not text.strip():
        return []
    return [debt.to_dict() for debt in worker_searcher(options).formula_debts(text)]


def job_search_one(text: str, limit: int, options: dict[str, Any]) -> list[Any]:
    """One quotation, in a worker process. Same reasoning as :func:`job_scan_one`."""
    return [match.to_dict() for match in worker_searcher(options).search(text, limit=limit)]


def job_scan(documents: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    """Scan a chunk of documents, keyed by the id the caller gave each one.

    One unreadable document must not lose the chunk. Forty-three thousand passages is too
    many to resubmit because one of them was null, so a document that fails is left out of
    the result and named in ``failed`` -- the caller can see exactly which, and everything
    else still arrives.
    """
    searcher = worker_searcher(options)
    found: dict[str, Any] = {}
    failed: dict[str, str] = {}
    for document in documents:
        name = str(document.get("id"))
        try:
            text = document["text"]
            if not isinstance(text, str):
                raise TypeError(f"text must be a string, not {type(text).__name__}")
            found[name] = [m.to_dict() for m in searcher.scan(text)] if text.strip() else []
        except Exception as exc:
            failed[name] = f"{type(exc).__name__}: {exc}"
    return {"found": found, "failed": failed}


TASKS: Final[dict[str, Callable[..., Any]]] = {
    "coverage": job_coverage,
    "audit": job_audit,
    "compare": job_compare,
}

#: Tasks that take a list of work and are spread over the pool rather than run as one call.
BATCH_TASKS: Final[dict[str, Callable[..., Any]]] = {"scan": job_scan}


#: Documents per chunk, at most. Not a tuning knob for throughput -- the share-based size
#: below already handles that -- but the ceiling on how long a reader waits when a request
#: lands while a sweep is running. See :meth:`Jobs.submit_batch`.
_CHUNK_CEILING: Final = 12


class Jobs:
    """A handful of long walks, running at once, that the client polls for.

    Holding a socket open for the three minutes an audit takes is a good way to discover
    every timeout between here and the other machine. So a submission returns an id and
    the work goes to a process pool; the client asks again later.
    """

    def __init__(self, workers: int) -> None:
        """
        :param workers: Processes, and the only number here. It was two for a while -- a
            pool for batch jobs and a small separate one for single requests -- and two
            pools that cannot lend to each other strand whichever is idle. An operator who
            said "use 28 cores" on a 32-thread machine got four, because he was driving
            `/api/scan` and had sized the other pool; and when the split was evened up he
            got half the machine instead, for the same reason in the other direction. Both
            arms of his measurement then plateaued at the same throughput, which looked
            like a shared bottleneck and was simply two halves of equal size.

            The isolation the split protected is real -- a batch occupies every worker for
            hours, and a reader must not wait behind it -- and is kept in `submit_batch`
            instead, by bounding how long any one chunk can hold a worker.
        """
        self._workers = workers
        # Spawn, not fork. A forked child inherits this process's SQLite connections, and
        # two processes using one connection is how a database file gets corrupted.
        spawn = multiprocessing.get_context("spawn")
        self._pool = ProcessPoolExecutor(max_workers=workers, mp_context=spawn)
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._jobs: dict[str, dict[str, Any]] = {}

    def run(self, function: Callable[..., Any], *args: Any) -> Any:
        """Run one request's work in a worker and wait for it.

        Scanning is pure-Python string comparison and holds the GIL throughout, so serving
        it on a request thread gives one core's worth of throughput however many requests
        arrive at once. Measured on a 32-thread machine: 16% utilisation, and four
        simultaneous requests taking the same wall time as one. Handing it to the pool is
        what makes concurrent requests actually concurrent.

        The waiting itself is cheap -- a blocked thread holds no GIL -- so the serving
        threads stay free to accept work while the pool is busy.

        The same pool as the batch jobs, which is what lets a machine be fully used by
        whichever kind of work has actually arrived. What stops a running sweep from burying
        this is the chunk bound in :meth:`submit_batch`: a request waits behind at most one
        chunk per worker, not behind the sweep.
        """
        return self._pool.submit(function, *args).result()

    def _open(self, task: str, params: dict[str, Any], total: int | None = None) -> dict[str, Any]:
        job_id = f"{task}-{next(self._ids)}"
        record: dict[str, Any] = {
            "id": job_id,
            "task": task,
            "params": params,
            "state": "running",
            "submitted": time.time(),
        }
        if total is not None:
            record.update(done=0, total=total)
        with self._lock:
            self._jobs[job_id] = record
        return record

    def submit(self, task: str, params: dict[str, Any]) -> dict[str, Any]:
        if task not in TASKS:
            known = sorted(set(TASKS) | set(BATCH_TASKS))
            raise LookupError(f"unknown task {task!r}; try {', '.join(known)}")
        record = self._open(task, params)
        future: Future[Any] = self._pool.submit(TASKS[task], **params)
        future.add_done_callback(lambda done: self._finish(record["id"], done))
        return record

    def submit_batch(self, task: str, work: list[Any], options: dict[str, Any]) -> dict[str, Any]:
        """Spread a list of work across the pool, reporting progress as chunks land.

        Chunked rather than one item per future because forty thousand futures is a lot of
        pickling for work that takes milliseconds each, and chunked *small* -- several per
        worker -- because one long document among short ones would otherwise leave most of
        the machine idle at the end.

        A job of this size is a black box otherwise. The `coverage` task takes seventy
        seconds; this one takes hours, and "still running" is not a useful answer to give
        for that long.
        """
        if task not in BATCH_TASKS:
            raise LookupError(f"{task!r} is not a batch task; try {', '.join(BATCH_TASKS)}")
        record = self._open(task, options, total=len(work))
        if not work:
            self._settle(record["id"], {"found": {}, "failed": {}})
            return record

        # Bounded above by `_CHUNK_CEILING` as well as by the worker count. The share-based
        # size alone is what a sweep of forty thousand documents wants -- fewer, fatter
        # futures -- but a fat chunk is also how long an interactive request waits when it
        # arrives mid-sweep, since a worker finishes its chunk before taking anything else.
        # A dozen documents is a few seconds; the whole sweep would be hours.
        size = max(1, min(_CHUNK_CEILING, len(work) // (self._workers * 4) or 1))
        chunks = [work[i : i + size] for i in range(0, len(work), size)]
        remaining = {"chunks": len(chunks)}
        merged: dict[str, Any] = {"found": {}, "failed": {}}

        def landed(future: Future[Any]) -> None:
            with self._lock:
                job = self._jobs[record["id"]]
                try:
                    piece = future.result()
                    merged["found"].update(piece["found"])
                    merged["failed"].update(piece["failed"])
                except Exception as exc:
                    merged["failed"][f"<chunk {remaining['chunks']}>"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                job["done"] = len(merged["found"]) + len(merged["failed"])
                remaining["chunks"] -= 1
                done = remaining["chunks"] == 0
            if done:
                self._settle(record["id"], merged)

        for chunk in chunks:
            self._pool.submit(BATCH_TASKS[task], chunk, options).add_done_callback(landed)
        return record

    def _settle(self, job_id: str, result: Any) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record["finished"] = time.time()
            record["seconds"] = round(record["finished"] - record["submitted"], 1)
            record["state"] = "done"
            record["result"] = result
            record["library"] = library_stamp()

    def _finish(self, job_id: str, future: Future[Any]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record["finished"] = time.time()
            record["seconds"] = round(record["finished"] - record["submitted"], 1)
            error = future.exception()
            if error is None:
                record["state"], record["result"] = "done", future.result()
                record["library"] = library_stamp()
            else:
                record["state"] = "failed"
                record["error"] = f"{type(error).__name__}: {error}"

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in job.items() if k != "result"} for job in self._jobs.values()]

    def running(self) -> int:
        with self._lock:
            return sum(job["state"] == "running" for job in self._jobs.values())
