"""The library over HTTP: a browsing page, a JSON API, and a job queue.

A bench, and a way to keep the corpus and the heavy work on one machine and use it from
another. Three things share one process:

**A page**, at ``/``. Type a reference, say which numbering you wrote it in, and it shows
how every system numbers it -- exact beside covering, differences highlighted -- and then
the text of every corpus that carries it.

**A JSON API**, under ``/api``, for the quick questions -- convert, passage, search --
which answer in milliseconds off the built index.

**A job queue**, for the ones that do not. The exhaustive walk is 155,578 conversions and
the pair audit reads most of the corpus; both take minutes, and both are single-threaded.

Where things live:

    server.py     the socket: Server, Handler, routing, auth, parameters, `serve`
    api.py        the quick questions
    plain.py      the server-rendered browsing page
    library.py    what this machine holds, and the digest carried on every answer
    jobs.py       the slow walks, in spawned processes

**The one rule: read ``HOME`` at call time, never bind it at import.** It lives in
:mod:`~biblereference.web.server` and is rebound by ``--data-home`` and by
``tests/test_server.py``, which points a whole server at the real store before starting it.
A module that had written ``from .server import HOME`` at the top would hold the home it
found first and quietly answer out of the wrong database. :func:`library.home` is the
accessor, and every reader here goes through it. ``VRS`` is the exception and is bound at
import on purpose: it is built from vendored package data, which no data home can vary.
"""

from __future__ import annotations

__all__ = ["main", "serve"]


def __getattr__(name: str) -> object:
    """Expose ``serve`` and ``main`` without importing the socket to read the docstring.

    Importing this package pulls in the whole store and the versification tables, which is
    a needless second of work for ``biblereference --help``.
    """
    if name in __all__:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
