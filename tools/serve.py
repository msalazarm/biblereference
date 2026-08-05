"""Serve the library over HTTP: a browsing page, a JSON API, and a job queue.

Not part of the library -- a bench, and a way to keep the corpus and the heavy work on one
machine and use it from another. Three things share one process:

**A page**, at ``/``. Type a reference, say which numbering you wrote it in, and it shows
how every system numbers it -- exact beside covering, differences highlighted -- and then
the text of every corpus that carries it. The covering toggle is the interesting part:
identical for almost every verse, which is the point, and where it differs is where one
edition merges what another divides. Some to try:

    Matt 17:14  in vul      the Douay carries both halves of what the Greek numbers 14 and 15
    Bar 6:43    in eng      English merges two Latin verses, and org LJE 1:43 is reachable
                            only under covering
    1Sam 20:42  in eng      a cover that crosses a chapter boundary
    Mal 3:22    in org      the Greek moves "remember the law of Moses" to the end
    Matt 5:4    in vul      the Clementine puts the meek before those who mourn

**A JSON API**, under ``/api``, for the quick questions -- convert, passage, search --
which answer in milliseconds off the built index.

**A job queue**, for the ones that do not. The exhaustive walk is 155,578 conversions and
the pair audit reads most of the corpus; both take minutes, and both are single-threaded.
Submitting them as jobs means several run at once on separate cores, and the client polls
rather than holding a socket open for three minutes. Jobs run in *spawned* processes, not
forked ones: a forked child inherits the parent's SQLite connections, and two processes
writing through one connection is how a database gets corrupted.

Run it:

    venv/bin/python tools/serve.py                     # http://localhost:8000, local only
    venv/bin/python tools/serve.py --host 0.0.0.0 --token "$(openssl rand -hex 24)"

See the README for setting it up on another machine.
"""

from __future__ import annotations

import argparse
import hmac
import html
import itertools
import json
import multiprocessing
import os
import threading
import time
import traceback
from concurrent.futures import Future, ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from biblereference.corpora.base import VerseUnavailable
from biblereference.refs import VerseRange, parse_reference
from biblereference.store import DataHome, SqliteCorpus, library_digest
from biblereference.versification import (
    AVAILABLE_SYSTEMS,
    DEFAULT_SYSTEMS,
    Versification,
    VersificationError,
    fingerprint,
)

VRS = Versification.load()
HOME = DataHome()

# SQLite connections belong to the thread that opened them and the server hands each
# request to a new one, so every thread gets its own set. Opening 55 corpora costs a few
# milliseconds and only happens once per thread.
_local = threading.local()


def corpora() -> dict[str, SqliteCorpus]:
    if not hasattr(_local, "corpora"):
        _local.corpora = SqliteCorpus.load_all(HOME)
    return _local.corpora


def by_system() -> dict[str, list[SqliteCorpus]]:
    """Corpora grouped by the versification they number in."""
    if not hasattr(_local, "by_system"):
        grouped: dict[str, list[SqliteCorpus]] = {}
        for corpus in sorted(corpora().values(), key=lambda c: (c.language, c.id)):
            grouped.setdefault(corpus.versification, []).append(corpus)
        _local.by_system = grouped
    return _local.by_system


SYSTEM_LABEL = {
    "org": "org — original-language (Masoretic / Greek NT)",
    "eng": "eng — English tradition",
    "lxx": "lxx — Septuagint",
    "vul": "vul — Clementine Vulgate",
    "nvl": "nvl — Nova Vulgata",
    "rsc": "rsc — Russian Synodal (Catholic)",
    "rso": "rso — Russian Synodal (Orthodox)",
}


def esc(value: object) -> str:
    return html.escape(str(value))


def convert(span: VerseRange, target: str, covering: bool) -> tuple[str, str]:
    """How ``span`` reads in ``target``, and a CSS class saying how it went."""
    try:
        segments = VRS.convert_range(span, target, covering=covering)
    except VersificationError as exc:
        return (str(exc), "gap")
    if not segments:
        return ("—", "gap")
    return (", ".join(segment.pretty() for segment in segments), "ok")


def numbering(span: VerseRange) -> str:
    """The reference as each system numbers it, exact beside covering."""
    rows = []
    for system in DEFAULT_SYSTEMS:
        exact, exact_class = convert(span, system, False)
        cover, cover_class = convert(span, system, True)
        differs = " differs" if exact != cover else ""
        rows.append(
            f"<tr class='{differs.strip()}'>"
            f"<th>{esc(SYSTEM_LABEL.get(system, system))}</th>"
            f"<td class='{exact_class}'>{esc(exact)}</td>"
            f"<td class='{cover_class}{differs}'>{esc(cover)}</td></tr>"
        )
    return (
        "<table class='numbering'><thead><tr><th></th>"
        "<th>exact <small>which verse it is</small></th>"
        "<th>covering <small>every verse it needs</small></th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def passage(corpus: SqliteCorpus, span: VerseRange, covering: bool) -> str | None:
    """One corpus's text for the span, in that corpus's own numbering."""
    try:
        segments = VRS.convert_range(span, corpus.versification, covering=covering)
    except VersificationError as exc:
        return f"<p class='gap'>{esc(exc)}</p>"
    if not segments:
        return None

    verses: list[str] = []
    where: list[str] = []
    for segment in segments:
        if not corpus.has_book(segment.book):
            return None
        where.append(segment.pretty())
        # One verse at a time: fetching a range in a single call means a corpus missing any
        # one verse of it shows nothing at all, and a partial passage is worth reading.
        for ref in VRS.expand(segment):
            try:
                found = corpus.fetch([ref])
            except VerseUnavailable:
                continue
            verses.extend(
                f"<span class='v'><sup>{esc(verse.ref.verse)}</sup>{esc(verse.text)}</span>"
                for verse in found
            )
    if not verses:
        return None
    return (
        f"<div class='corpus'><div class='head'><b>{esc(corpus.label)}</b>"
        f"<code>{esc(corpus.id)}</code><span class='meta'>{esc(corpus.language)} · "
        f"{esc(', '.join(where))}</span></div><p>{''.join(verses)}</p></div>"
    )


def texts(span: VerseRange, covering: bool) -> str:
    groups = by_system()
    out = []
    for system in sorted(
        groups, key=lambda s: DEFAULT_SYSTEMS.index(s) if s in DEFAULT_SYSTEMS else 99
    ):
        found = [r for r in (passage(c, span, covering) for c in groups[system]) if r]
        if not found:
            continue
        out.append(
            f"<section><h3>{esc(SYSTEM_LABEL.get(system, system))} "
            f"<small>{len(found)} of {len(groups[system])} carry it</small></h3>"
            + "".join(found)
            + "</section>"
        )
    return "".join(out) or "<p class='gap'>No corpus here carries that passage.</p>"


HINT = (
    "<p class='hint'>Try <code>Matt 17:14</code> in <code>vul</code>, or "
    "<code>Bar 6:43</code> in <code>eng</code>, with covering on and off. "
    "Highlighted rows are where the two answers differ.</p>"
)


def page(query: str, source: str, covering: bool, token: str = "") -> str:
    body = ""
    if query:
        try:
            span = parse_reference(query, vrs=source, allow_chapter=True)
        except ValueError as exc:
            # Covers the lot: ReferenceParseError, UnknownBookError and every
            # VersificationError are all ValueErrors, and a typed reference is the one
            # input here that a person gets wrong constantly.
            body = f"<p class='gap'>{esc(exc)}</p>"
        else:
            body = (
                f"<h2>{esc(span.pretty())} <small>in <code>{esc(source)}</code></small></h2>"
                + numbering(span)
                + texts(span, covering)
            )

    options = "".join(
        f"<option value='{s}'{' selected' if s == source else ''}>{s}</option>"
        for s in DEFAULT_SYSTEMS
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>biblereference — {esc(query) or "explore"}</title>
<style>
 :root {{ color-scheme: light dark; --line:#8884; --gap:#c0392b; --hi:#b8860b; }}
 body {{ font:16px/1.55 system-ui,sans-serif; max-width:60rem;
         margin:0 auto; padding:1.5rem; }}
 form {{ display:flex; gap:.5rem; flex-wrap:wrap; align-items:center;
         position:sticky; top:0; background:Canvas; padding:.75rem 0;
         border-bottom:1px solid var(--line); }}
 input[type=text] {{ flex:1; min-width:14rem; }}
 input[type=text], select, button {{ font:inherit; padding:.45rem .6rem;
         border:1px solid var(--line); border-radius:.35rem;
         background:Canvas; color:CanvasText; }}
 button {{ cursor:pointer; }}
 label {{ display:flex; align-items:center; gap:.35rem; white-space:nowrap; }}
 h2 {{ margin:1.2rem 0 .4rem; font-weight:600; }}
 h2 small, h3 small {{ opacity:.6; font-weight:400; }}
 h3 {{ margin:1.6rem 0 .5rem; font-size:.95rem; opacity:.85;
       border-bottom:1px solid var(--line); padding-bottom:.3rem; }}
 table.numbering {{ border-collapse:collapse; width:100%;
       margin:.5rem 0 1rem; font-size:.92rem; }}
 .numbering th, .numbering td {{ text-align:left; padding:.35rem .6rem;
       border-bottom:1px solid var(--line); vertical-align:top; }}
 .numbering thead th {{ font-weight:600; opacity:.75; }}
 .numbering thead small {{ display:block; font-weight:400; opacity:.6; }}
 .numbering tbody th {{ font-weight:500; white-space:nowrap; }}
 td.gap {{ color:var(--gap); font-size:.85rem; }}
 td.differs {{ color:var(--hi); font-weight:600; }}
 tr.differs th {{ font-weight:700; }}
 .corpus {{ margin:.55rem 0; padding:.5rem .7rem;
       border-left:2px solid var(--line); }}
 .corpus .head {{ display:flex; gap:.5rem; align-items:baseline;
       flex-wrap:wrap; font-size:.85rem; }}
 .corpus code {{ opacity:.65; }}
 .corpus .meta {{ opacity:.55; margin-left:auto; }}
 .corpus p {{ margin:.25rem 0 0; }}
 .v sup {{ opacity:.5; font-size:.7em; padding-right:.2em; }}
 .v + .v {{ margin-left:.35em; }}
 p.gap {{ color:var(--gap); }}
 .hint {{ opacity:.6; font-size:.85rem; margin:.6rem 0 0; }}
</style></head><body>
<form method="get">
  {f'<input type="hidden" name="token" value="{esc(token)}">' if token else ""}
  <input type="text" name="q" value="{esc(query)}" autofocus
         placeholder="John 3:16 · Rom 1:1-5 · Matt 17:14">
  <label>written in <select name="vrs">{options}</select></label>
  <label><input type="checkbox" name="covering" value="1"
         {"checked" if covering else ""}> covering</label>
  <button type="submit">show</button>
</form>
{body or HINT}
</body></html>"""


# --------------------------------------------------------------------------------------
# The quick questions, answered off the built index
# --------------------------------------------------------------------------------------


def api_convert(params: dict[str, list[str]]) -> Any:
    """One reference in one system, or in all of them if ``to`` is omitted."""
    ref = (params.get("ref") or [""])[0]
    source = (params.get("from") or ["eng"])[0]
    covering = bool(params.get("covering"))
    span = parse_reference(ref, vrs=source, allow_chapter=True)

    def answer(target: str) -> Any:
        try:
            segments = VRS.convert_range(span, target, covering=covering)
        except VersificationError as exc:
            return {"refused": str(exc)}
        return [
            {"ref": segment.pretty(), "usfm": str(segment), "verses": len(VRS.expand(segment))}
            for segment in segments
        ]

    targets = params.get("to") or list(DEFAULT_SYSTEMS)
    return {
        "asked": {"ref": span.pretty(), "usfm": str(span), "vrs": source, "covering": covering},
        "systems": {target: answer(target) for target in targets},
    }


def api_passage(params: dict[str, list[str]]) -> Any:
    """The text of a passage in every corpus that carries it."""
    span = parse_reference(
        (params.get("ref") or [""])[0],
        vrs=(params.get("vrs") or ["eng"])[0],
        allow_chapter=True,
    )
    covering = bool(params.get("covering"))
    wanted = set(params.get("corpus") or ())

    out = []
    for corpus in corpora().values():
        if wanted and corpus.id not in wanted:
            continue
        try:
            segments = VRS.convert_range(span, corpus.versification, covering=covering)
        except VersificationError as exc:
            out.append({"corpus": corpus.id, "refused": str(exc)})
            continue
        verses = []
        for segment in segments:
            if not corpus.has_book(segment.book):
                continue
            for one in VRS.expand(segment):
                try:
                    verses.extend(
                        {"ref": verse.ref.pretty(), "text": verse.text}
                        for verse in corpus.fetch([one])
                    )
                except VerseUnavailable:
                    continue
        if verses:
            out.append(
                {
                    "corpus": corpus.id,
                    "label": corpus.label,
                    "language": corpus.language,
                    "versification": corpus.versification,
                    "ref": ", ".join(s.pretty() for s in segments),
                    "verses": verses,
                }
            )
    return {"asked": {"ref": span.pretty(), "covering": covering}, "found": out}


def api_search(params: dict[str, list[str]], body: str) -> Any:
    """Which passage a quotation came from, and which translation it was quoted in."""
    from biblereference.search import Searcher

    text = body or (params.get("q") or [""])[0]
    limit = int((params.get("limit") or ["5"])[0])
    with Searcher(HOME) as searcher:
        return {"matches": [match.to_dict() for match in searcher.search(text, limit=limit)]}


def api_health() -> Any:
    return {
        "ok": True,
        "corpora": len(corpora()),
        "systems": list(AVAILABLE_SYSTEMS),
        "loaded": list(DEFAULT_SYSTEMS),
        "versification_fingerprint": fingerprint(),
        "data_home": str(HOME.root),
        "cores": os.cpu_count(),
        "jobs_running": JOBS.running(),
    }


def api_digest() -> Any:
    """A fingerprint of everything this machine holds, for comparing with another."""
    from dataclasses import asdict

    return asdict(library_digest(HOME))


def api_sources() -> Any:
    """The newest checksum of every archived source, so a mismatched digest can be run
    down to the file that caused it.

    A digest that says two machines differ and cannot say *where* sends you hunting, which
    is how the first version of it was found wanting.
    """
    from biblereference.fetch import iter_sources

    registered = {source.id for source in iter_sources(None)}
    newest: dict[str, dict[str, Any]] = {}
    for entry in HOME.entries():  # newest last, so later writes win
        newest[entry.source] = {
            "sha256": entry.sha256,
            "bytes": entry.bytes,
            "fetched_at": entry.fetched_at,
            "url": entry.url,
            "registered": entry.source in registered,
        }
    return {
        "registered": sorted(registered),
        "sources": dict(sorted(newest.items())),
    }


def api_corpora() -> Any:
    return {
        "corpora": [
            {
                "id": c.id,
                "label": c.label,
                "language": c.language,
                "versification": c.versification,
                "attribution": c.attribution,
            }
            for c in sorted(corpora().values(), key=lambda c: c.id)
        ]
    }


# --------------------------------------------------------------------------------------
# The slow ones, in their own processes
# --------------------------------------------------------------------------------------
#
# Each of these is a whole-corpus walk taking minutes, and each runs in a spawned process
# so that several use several cores and none of them inherits a SQLite connection from
# this one. They take and return plain data for the same reason: it has to cross a pickle.


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


TASKS = {"coverage": job_coverage, "audit": job_audit, "compare": job_compare}


class Jobs:
    """A handful of long walks, running at once, that the client polls for.

    Holding a socket open for the three minutes an audit takes is a good way to discover
    every timeout between here and the other machine. So a submission returns an id and
    the work goes to a process pool; the client asks again later.
    """

    def __init__(self, workers: int) -> None:
        # Spawn, not fork. A forked child inherits this process's SQLite connections, and
        # two processes using one connection is how a database file gets corrupted.
        self._pool = ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        )
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._jobs: dict[str, dict[str, Any]] = {}

    def submit(self, task: str, params: dict[str, Any]) -> dict[str, Any]:
        if task not in TASKS:
            raise LookupError(f"unknown task {task!r}; try {', '.join(sorted(TASKS))}")
        job_id = f"{task}-{next(self._ids)}"
        record = {
            "id": job_id,
            "task": task,
            "params": params,
            "state": "running",
            "submitted": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = record
        future: Future[Any] = self._pool.submit(TASKS[task], **params)
        future.add_done_callback(lambda done: self._finish(job_id, done))
        return record

    def _finish(self, job_id: str, future: Future[Any]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record["finished"] = time.time()
            record["seconds"] = round(record["finished"] - record["submitted"], 1)
            error = future.exception()
            if error is None:
                record["state"], record["result"] = "done", future.result()
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


JOBS: Jobs = None  # type: ignore[assignment]  # built in main(), which knows the worker count
TOKEN: str | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "biblereference"

    # -- plumbing ----------------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        # default=str so that one unforeseen object in a result cannot turn a completed
        # job into a 500 when you go to collect it. Better a repr than a lost answer.
        body = json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _authorised(self, params: dict[str, list[str]]) -> bool:
        if TOKEN is None:
            return True
        header = self.headers.get("Authorization", "")
        offered = header[7:] if header.startswith("Bearer ") else (params.get("token") or [""])[0]
        # compare_digest rather than ==, so a wrong token cannot be found one byte at a
        # time by watching how long the answer takes.
        return hmac.compare_digest(offered, TOKEN)

    def log_message(self, *args: object) -> None:
        return  # the console is for tracebacks, not a line per request

    # -- routing -----------------------------------------------------------------------

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
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
            elif path == "/":
                out = page(
                    (params.get("q") or [""])[0].strip(),
                    (params.get("vrs") or ["eng"])[0],
                    bool(params.get("covering")),
                    # Carried in a hidden field, so following the form does not drop it.
                    (params.get("token") or [""])[0],
                )
                self._send(200, out.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._json(404, {"error": f"no route {path!r}"})
        except (ValueError, LookupError) as exc:
            # What a person gets wrong: a mistyped reference, an unbuilt corpus, an
            # unknown task. Their fault to fix, so name it rather than dumping a stack.
            self._json(400, {"error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            self._json(500, {"error": traceback.format_exc()})

    def _api(self, path: str, params: dict[str, list[str]], body: str) -> None:
        if path == "/api/health":
            self._json(200, api_health())
        elif path == "/api/corpora":
            self._json(200, api_corpora())
        elif path == "/api/digest":
            self._json(200, api_digest())
        elif path == "/api/sources":
            self._json(200, api_sources())
        elif path == "/api/convert":
            self._json(200, api_convert(params))
        elif path == "/api/passage":
            self._json(200, api_passage(params))
        elif path == "/api/search":
            self._json(200, api_search(params, body))
        elif path == "/api/jobs":
            if self.command == "POST":
                task = (params.get("task") or [""])[0]
                self._json(202, JOBS.submit(task, _job_params(params, body)))
            else:
                self._json(200, {"jobs": JOBS.all()})
        elif path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            self._json(200 if job else 404, job or {"error": "no such job"})
        else:
            self._json(404, {"error": f"no route {path!r}", "routes": sorted(ROUTES)})


ROUTES = {
    "GET  /": "the browsing page",
    "GET  /api/health": "corpora count, fingerprint, cores, jobs running",
    "GET  /api/corpora": "every built corpus",
    "GET  /api/digest": "fingerprint of this machine's library, for comparing with another",
    "GET  /api/sources": "per-source checksums, for running a mismatched digest to ground",
    "GET  /api/convert": "?ref=&from=eng&to=vul&covering=1 (repeat to=, or omit for all)",
    "GET  /api/passage": "?ref=&vrs=eng&covering=1 -- the text in every corpus",
    "POST /api/search": "body is the quotation; ?limit=5",
    "POST /api/jobs": "?task=coverage|audit|compare (&book=&left=&right=&covering=1)",
    "GET  /api/jobs": "every job, without results",
    "GET  /api/jobs/<id>": "one job, with its result once done",
}


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


def main() -> None:
    global JOBS, TOKEN
    parser = argparse.ArgumentParser(description="Serve biblereference over HTTP.")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept from the network")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--token",
        default=os.environ.get("BIBLEREFERENCE_TOKEN"),
        help="require this bearer token; also read from $BIBLEREFERENCE_TOKEN",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="processes for the long jobs (default: cores - 1)",
    )
    args = parser.parse_args()

    TOKEN = args.token or None
    JOBS = Jobs(args.workers)

    print(
        f"{len(corpora())} corpora · {args.workers} job workers of {os.cpu_count()} cores\n"
        f"http://{args.host}:{args.port}  (ctrl-c to stop)",
        flush=True,
    )
    if args.host != "127.0.0.1" and TOKEN is None:
        print(
            "  WARNING: listening on the network with no --token. Anyone who can reach "
            "this port can run jobs on this machine.",
            flush=True,
        )
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
