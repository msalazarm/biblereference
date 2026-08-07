"""The socket: routing, auth, parameter handling, and the globals everything else reads.

``HOME``, ``JOBS``, ``TOKEN`` and ``MAX_BODY`` live here because they are the four things a
run is configured with, and three of them cannot be known until :func:`serve` is called.
Every other module in this package reads them at call time -- see the package docstring for
why that is a rule rather than a style.

Run it:

    biblereference serve                        # http://localhost:8000, local only
    biblereference serve --host 0.0.0.0 --token "$(openssl rand -hex 24)"

See the README for setting it up on another machine.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

from ..store import DataHome
from .alignment import api_alignment, api_corrections
from .api import (
    api_convert,
    api_corpora,
    api_digest,
    api_health,
    api_manifest,
    api_passage,
    api_scan,
    api_search,
    api_sources,
)
from .assets import assets
from .catalogue import api_families, api_library
from .jobs import BATCH_TASKS, TASKS, Jobs
from .library import corpora, known_filters, prewarm
from .plain import page
from .reader import api_books, api_parse, api_reader

#: `Jobs`, `TASKS` and `BATCH_TASKS` are re-exported rather than merely imported: this
#: module is what `tools/serve.py` resolves to, so a name that was on the old script has to
#: still be reachable here.
__all__ = ["BATCH_TASKS", "TASKS", "Handler", "Jobs", "Server", "main", "serve"]

#: The store every reader here answers out of. Rebound by ``--data-home`` and by the test
#: fixture, which is why nothing imports it at module level.
HOME = DataHome()

#: Built in :func:`serve`, which knows the worker count.
JOBS: Jobs = None  # type: ignore[assignment]

TOKEN: str | None = None

#: Largest body accepted, in bytes. Patristic passages run to 100,000 words; this is a few
#: times that, and going over is refused with a 413 rather than silently truncated.
MAX_BODY: int = 64 * 1024 * 1024


# --------------------------------------------------------------------------------------
# Parameters: refused, not ignored
# --------------------------------------------------------------------------------------

#: Everything `Searcher` takes that can survive a query string, with how to read it.
#: Anything not here is refused rather than ignored -- see :func:`search_options`.
_SCORES: Final = {"quotation": None, "coverage": None, "identified": None}
_FILTERS: Final = {"languages", "corpora", "families"}
#: `composed` is here rather than in `_SCORES` because it is a year, not a fraction: the
#: date the document was written, which is what makes `Match.anachronistic` mean anything.
_OTHER: Final = {
    "q",
    "limit",
    "token",
    "min_run",
    "min_query",
    "window",
    "stride",
    "composed",
}

#: Query parameters the job endpoint owns. Named explicitly rather than folded into the
#: general allow-list, so that `/api/search?task=scan` is still the error it ought to be.
JOB_PARAMS: Final = frozenset({"task", "book", "left", "right", "covering"})


def _fraction(name: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number between 0 and 1, not {raw!r}") from None
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, not {value}")
    return value


def _min_run(raw: str) -> int | Callable[[int], int]:
    """A fixed word count, or ``scaled:<floor>`` for one proportional to the query.

    A callable cannot cross a query string, and the proportional form is the one that was
    measured -- it took short Greek quotations from 9% found to 72% -- so it needs a
    spelling. ``scaled:4`` is :class:`~biblereference.search.ScaledRun`, which is a class
    and not a closure precisely so that it survives the pickle into a worker process.
    """
    from ..search import ScaledRun

    if not raw.startswith("scaled:"):
        try:
            fixed = int(raw)
        except ValueError:
            raise ValueError(f"min_run must be an integer or scaled:<floor>, not {raw!r}") from None
        if fixed < 1:
            raise ValueError(f"min_run must be at least 1, not {fixed}")
        return fixed
    try:
        floor = int(raw.removeprefix("scaled:"))
    except ValueError:
        raise ValueError(f"scaled: needs a floor, as in scaled:4, not {raw!r}") from None
    try:
        return ScaledRun(floor)
    except ValueError as exc:
        raise ValueError(str(exc)) from None


def _listed(params: dict[str, list[str]], name: str) -> list[str] | None:
    """A repeatable, comma-separated parameter. ``None`` when absent, meaning no filter."""
    values = [
        piece.strip() for raw in params.get(name, ()) for piece in raw.split(",") if piece.strip()
    ]
    return values or None


def search_options(
    params: dict[str, list[str]], extra: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Turn a query string into `Searcher` keyword arguments, refusing what it cannot.

    Silently ignoring a parameter is how a caller comes to believe it configured something
    it did not: the answer looks like a genuine absence of matches and there is nothing to
    tell the two apart. So an unknown name, an unreadable value and an out-of-range one are
    all 400s, and only the parameters actually applied are accepted.
    """
    allowed = set(_SCORES) | _FILTERS | _OTHER | set(extra)
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(
            f"unknown parameter(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(allowed - {'token'}))}"
        )

    options: dict[str, Any] = {}
    for name in _SCORES:
        if params.get(name):
            options[name] = _fraction(name, params[name][0])
    if params.get("min_run"):
        options["min_run"] = _min_run(params["min_run"][0])
    if params.get("min_query"):
        raw = params["min_query"][0]
        try:
            options["min_query"] = int(raw)
        except ValueError:
            raise ValueError(f"min_query must be an integer, not {raw!r}") from None
    if params.get("composed"):
        raw = params["composed"][0]
        try:
            options["composed"] = int(raw)
        except ValueError:
            raise ValueError(
                f"composed must be the year the document was written, not {raw!r}"
            ) from None

    known = known_filters()
    for name in _FILTERS:
        chosen = _listed(params, name)
        if chosen is None:
            continue
        strange = [value for value in chosen if value not in known[name]]
        if strange:
            # Not an empty result: that would be indistinguishable from nothing matching,
            # which is the failure this whole function exists to prevent.
            raise LookupError(
                f"unknown {name}: {', '.join(strange)}. "
                f"This machine has: {', '.join(sorted(known[name]))}"
            )
        options[name] = chosen
    return options


def _batch_work(body: str) -> list[Any]:
    """The documents of a batch scan: a JSON array of ``{"id": ..., "text": ...}``.

    Ids are the caller's, so results come back matched to them rather than to a position
    in a list that a partial failure would shift.
    """
    if not body.strip():
        return []
    parsed = json.loads(body)
    if not isinstance(parsed, list):
        raise ValueError("a scan batch must be a JSON array of {id, text} objects")
    for item in parsed:
        if not isinstance(item, dict) or "id" not in item:
            raise ValueError(f"every document needs an id: {item!r}")
    return parsed


def _job_params(params: dict[str, list[str]], body: str) -> dict[str, Any]:
    """Job arguments from the query string, or from a JSON body if one was sent."""
    if body.strip():
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("a job body must be a JSON object of arguments")
        return parsed
    out: dict[str, Any] = {}
    for key in ("book", "left", "right"):
        if params.get(key):
            out[key] = params[key][0]
    if params.get("covering"):
        out["covering"] = True
    return out


# --------------------------------------------------------------------------------------
# The socket
# --------------------------------------------------------------------------------------


ROUTES = {
    "GET  /": "the browsing page",
    "GET  /static/<name>": "one shipped asset, revalidated with an ETag",
    "GET  /api/health": "corpora count, fingerprint, cores, jobs running",
    "GET  /api/corpora": "every built corpus",
    "GET  /api/digest": "fingerprint of this machine's library, for comparing with another",
    "GET  /api/sources": "per-source checksums, for running a mismatched digest to ground",
    "GET  /api/manifest": "every archive manifest line, for mirroring this machine",
    "GET  /api/archive": "?path=<manifest path> -- one archived file, raw",
    "GET  /api/convert": "?ref=&from=eng&to=vul&covering=1 (repeat to=, or omit for all)",
    "GET  /api/passage": "?ref=&vrs=eng&covering=1 -- the text in every corpus",
    "GET  /api/books": "?vrs=eng&naming=modern -- every book, grouped, with its shape",
    "GET  /api/reader": "?book=&chapter=&vrs=&corpus=&covering= -- a chapter across versions",
    "GET  /api/parse": "?q= -- is this a reference or is it prose? always 200",
    "GET  /api/alignment": "?ref=&vrs=&to= -- exact beside covering, and why each is what it is",
    "GET  /api/corrections": "?system=&book=&chapter=&verse=&kind= -- the recorded reasons",
    "GET  /api/library": "every corpus: what it holds, when it was written, its licence",
    "GET  /api/families": "versification families derived from where the chapter ends fall",
    "POST /api/search": "body is the quotation; ?limit=5 and any scoring or filter option",
    "POST /api/scan": "body is a document; finds the quotations in it and where they sit",
    "POST /api/jobs": "?task=coverage|audit|compare (&book=&left=&right=&covering=1)",
    "POST /api/jobs?task=scan": "body is [{id, text}, ...]; scans them all across the pool",
    "GET  /api/jobs": "every job, without results",
    "GET  /api/jobs/<id>": "one job, with its result once done",
}


class Server(ThreadingHTTPServer):
    """`ThreadingHTTPServer`, minus the traceback when a client hangs up.

    A caller that times out and disconnects mid-response is ordinary, and printing a
    BrokenPipeError stack for it is noise that hides real errors among it.
    """

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        import sys

        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


#: The cookie a browser carries the token in. A `<link>` or a `<script src>` cannot send an
#: `Authorization` header, so a token-in-JavaScript scheme would 401 the page's own assets.
COOKIE: Final = "br_token"


class Handler(BaseHTTPRequestHandler):
    server_version = "biblereference"

    #: Keep-alive. A page is a document plus its assets, which is several requests in a
    #: burst, and a fresh TCP connection for each is a handshake apiece for nothing. Safe
    #: because every response here sends an accurate Content-Length -- which is also why
    #: the 413 path below has to close: it never read the body it refused.
    protocol_version = "HTTP/1.1"

    #: How long an idle kept-alive connection may hold a thread. Without this a client that
    #: opens a connection and says nothing holds one until the process ends.
    timeout = 30

    # -- plumbing ----------------------------------------------------------------------

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra: Mapping[str, str] | None = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The caller gave up before the answer arrived -- a timeout on their side, or
            # a killed client. Their business, not a fault here, and reporting it as one
            # buries whatever the request was actually doing under a second traceback.
            self.close_connection = True

    def _json(self, status: int, payload: Any, extra: Mapping[str, str] | None = None) -> None:
        # default=str so that one unforeseen object in a result cannot turn a completed
        # job into a 500 when you go to collect it. Better a repr than a lost answer.
        body = json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    # -- who is asking -----------------------------------------------------------------

    def _cookies(self) -> dict[str, str]:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return {}  # a malformed jar is an unauthenticated one, not a 500
        return {name: morsel.value for name, morsel in jar.items()}

    def _offered(self, params: dict[str, list[str]]) -> str:
        """The token this request carries, from whichever of the three places has it.

        Header first, because that is what a script uses and it is the most deliberate.
        Then the query string, which is how a person arrives from a link. Then the cookie,
        which is how they stay once they have.
        """
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:]
        if params.get("token"):
            return params["token"][0]
        return self._cookies().get(COOKIE, "")

    def _authorised(self, params: dict[str, list[str]]) -> bool:
        if TOKEN is None:
            return True
        # compare_digest rather than ==, so a wrong token cannot be found one byte at a
        # time by watching how long the answer takes. Bytes rather than str, because the
        # str form rejects non-ASCII with a TypeError and a token is caller-supplied.
        return hmac.compare_digest(
            self._offered(params).encode("utf-8", "replace"), TOKEN.encode("utf-8")
        )

    def _keep_the_token(self, params: dict[str, list[str]]) -> Mapping[str, str]:
        """Set the cookie when a person arrives with a valid ``?token=`` on a page.

        ``SameSite=Strict`` is the whole CSRF answer: a cross-site page cannot make the
        browser send it at all, so there is no state-changing request to forge. ``HttpOnly``
        because nothing in the page needs to read it -- the browser attaches it to the
        asset and API requests by itself, which is the point.
        """
        if TOKEN is None or not params.get("token"):
            return {}
        return {"Set-Cookie": f"{COOKIE}={TOKEN}; Path=/; SameSite=Strict; HttpOnly"}

    def log_message(self, *args: object) -> None:
        return  # the console is for tracebacks, not a line per request

    # -- routing -----------------------------------------------------------------------

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            # Said rather than truncated. A document cut short here would read as a father
            # quoting less than he did, and nothing downstream could tell.
            # The body was refused, which means it was never read off the socket. Under
            # keep-alive the next read would start partway through a rejected document and
            # parse it as a request line -- the client and the server would disagree about
            # where every subsequent request began, and the failure would surface as a
            # nonsensical answer to some later, innocent request. So: say `close`, which
            # `send_header` also takes as the instruction to actually close.
            self._json(
                413,
                {
                    "error": f"body is {length:,} bytes; the limit is {MAX_BODY:,}. "
                    f"Split the document, or raise --max-body."
                },
                {"Connection": "close"},
            )
            return
        self._route(self.rfile.read(length).decode("utf-8", "replace") if length else "")

    def _route(self, body: str = "") -> None:
        url = urlparse(self.path)
        params = parse_qs(url.query)
        path = url.path.rstrip("/") or "/"

        if not self._authorised(params):
            self._json(401, {"error": "a token is required: Authorization: Bearer <token>"})
            return

        try:
            if path.startswith("/api"):
                self._api(path, params, body)
            elif path.startswith("/static/"):
                self._static(path.removeprefix("/static/"))
            elif path == "/":
                out = page(
                    (params.get("q") or [""])[0].strip(),
                    (params.get("vrs") or ["eng"])[0],
                    bool(params.get("covering")),
                    # Carried in a hidden field, so following the form does not drop it.
                    (params.get("token") or [""])[0],
                )
                self._send(
                    200,
                    out.encode("utf-8"),
                    "text/html; charset=utf-8",
                    self._keep_the_token(params),
                )
            else:
                self._json(404, {"error": f"no route {path!r}"})
        except (ValueError, LookupError) as exc:
            # What a person gets wrong: a mistyped reference, an unbuilt corpus, an
            # unknown task. Their fault to fix, so name it rather than dumping a stack.
            self._json(400, {"error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            self._json(500, {"error": traceback.format_exc()})

    def _static(self, name: str) -> None:
        """One file from the package's own ``static/``, by name.

        A name, not a path: see :mod:`~biblereference.web.assets` for why that is the whole
        traversal defence. Revalidated rather than cached outright -- the assets change
        whenever the package does, and a stale stylesheet served from a browser cache is a
        confusing thing to debug -- so an unchanged file costs one 304 and no body.
        """
        asset = assets().get(name)
        if asset is None:
            self._json(404, {"error": f"no such asset {name!r}", "assets": sorted(assets())})
            return
        if self.headers.get("If-None-Match") == asset.etag:
            self.send_response(304)
            self.send_header("ETag", asset.etag)
            self.end_headers()
            return
        self._send(200, asset.body, asset.type, {"ETag": asset.etag, "Cache-Control": "no-cache"})

    def _archive(self, wanted: str) -> None:
        """One archived file, by its manifest path.

        The path comes from a client, so it is resolved and checked to be *inside* the
        archive rather than merely starting with its name -- `..` segments and symlinks
        both resolve away, and neither should be able to read this machine's disk.
        """
        root = HOME.sources.resolve()
        target = (root / wanted).resolve()
        if not wanted or root not in target.parents or not target.is_file():
            self._json(404, {"error": f"not in the archive: {wanted!r}"})
            return
        self._send(200, target.read_bytes(), "application/octet-stream")

    def _api(self, path: str, params: dict[str, list[str]], body: str) -> None:
        if path == "/api/health":
            self._json(200, api_health())
        elif path == "/api/corpora":
            self._json(200, api_corpora())
        elif path == "/api/digest":
            self._json(200, api_digest())
        elif path == "/api/sources":
            self._json(200, api_sources())
        elif path == "/api/manifest":
            self._json(200, api_manifest())
        elif path == "/api/archive":
            self._archive((params.get("path") or [""])[0])
        elif path == "/api/convert":
            self._json(200, api_convert(params))
        elif path == "/api/passage":
            self._json(200, api_passage(params))
        elif path == "/api/books":
            self._json(200, api_books(params))
        elif path == "/api/reader":
            self._json(200, api_reader(params))
        elif path == "/api/parse":
            self._json(200, api_parse(params))
        elif path == "/api/alignment":
            self._json(200, api_alignment(params))
        elif path == "/api/corrections":
            self._json(200, api_corrections(params))
        elif path == "/api/library":
            self._json(200, api_library(params))
        elif path == "/api/families":
            self._json(200, api_families(params))
        elif path == "/api/search":
            self._json(200, api_search(params, body))
        elif path == "/api/scan":
            self._json(200, api_scan(params, body))
        elif path == "/api/jobs":
            if self.command == "POST":
                task = (params.get("task") or [""])[0]
                if task in BATCH_TASKS:
                    options = search_options(params, JOB_PARAMS)
                    self._json(202, JOBS.submit_batch(task, _batch_work(body), options))
                else:
                    self._json(202, JOBS.submit(task, _job_params(params, body)))
            else:
                self._json(200, {"jobs": JOBS.all()})
        elif path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            self._json(200 if job else 404, job or {"error": "no such job"})
        else:
            self._json(404, {"error": f"no route {path!r}", "routes": sorted(ROUTES)})


# --------------------------------------------------------------------------------------
# Starting it
# --------------------------------------------------------------------------------------


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    token: str | None = None,
    max_body: int | None = None,
    workers: int | None = None,
    interactive_workers: int = 4,
    data_home: Path | None = None,
    announce: bool = True,
) -> None:
    """Configure the globals, build the pools, and serve until interrupted."""
    global HOME, JOBS, TOKEN, MAX_BODY

    if data_home is not None:
        # Set the *environment*, not only `HOME`. The job pool is spawned, and a spawned
        # worker builds its own `DataHome()` -- it cannot be handed this one and does not
        # inherit the assignment. Setting only `HOME` would apply `--data-home` to reads
        # and silently not to jobs, which is the shape of bug that takes an afternoon.
        from ..store import ENV_VAR

        os.environ[ENV_VAR] = str(data_home)
        HOME = DataHome(data_home)

    TOKEN = token or None
    if max_body is not None:
        MAX_BODY = max_body
    if workers is None:
        workers = max(1, (os.cpu_count() or 2) - 1)
    # After the environment, so the spawned workers see it.
    JOBS = Jobs(workers, interactive_workers)
    # And before the socket opens, so the half-second of whole-table queries is spent while
    # nobody is waiting rather than by whoever asks first.
    prewarm()

    if announce:
        print(
            f"{len(corpora())} corpora · {workers} job workers + "
            f"{interactive_workers} interactive, of {os.cpu_count()} cores\n"
            f"http://{host}:{port}  (ctrl-c to stop)",
            flush=True,
        )
        if host != "127.0.0.1" and TOKEN is None:
            print(
                "  WARNING: listening on the network with no --token. Anyone who can reach "
                "this port can run jobs on this machine.",
                flush=True,
            )
    Server((host, port), Handler).serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m biblereference.web.server`` and ``python tools/serve.py``.

    Delegates to the CLI rather than parsing again, so the options have one definition and
    cannot drift between the two ways of starting the same server.
    """
    from ..cli import main as cli

    return cli(["serve", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
