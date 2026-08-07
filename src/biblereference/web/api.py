"""The quick questions, answered off the built index in milliseconds.

Everything here reads ``HOME`` through :func:`library.home` rather than binding it, and
reaches the job pool through a deferred ``from .server import JOBS`` -- both are rebindable
globals that live in :mod:`~biblereference.web.server`, and a module-level import would
capture whichever value happened to exist when this file was first read.
"""

from __future__ import annotations

import os
from typing import Any

from ..refs import parse_reference
from ..versification import AVAILABLE_SYSTEMS, DEFAULT_SYSTEMS, VersificationError, fingerprint
from .jobs import job_scan_one, job_search_one
from .library import VRS, corpora, home, library_stamp


def _jobs() -> Any:
    """The pool, read at call time -- it is built in ``serve()`` once the worker count is
    known, and rebound by the test fixture."""
    from .server import JOBS

    return JOBS


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

    out: list[dict[str, Any]] = []
    for corpus in corpora().values():
        if wanted and corpus.id not in wanted:
            continue
        try:
            segments = VRS.convert_range(span, corpus.versification, covering=covering)
        except VersificationError as exc:
            out.append({"corpus": corpus.id, "refused": str(exc)})
            continue
        verses: list[dict[str, str]] = []
        asked = 0
        for segment in segments:
            if not corpus.has_book(segment.book):
                continue
            # `available`, not a verse-at-a-time `fetch`: same tolerance for a verse this
            # edition does not print, one query per chapter instead of one per verse.
            expected = VRS.expand(segment)
            asked += len(expected)
            verses.extend(
                {"ref": verse.ref.pretty(), "text": verse.text}
                for verse in corpus.available(expected)
            )
        if verses:
            out.append(
                {
                    "corpus": corpus.id,
                    "label": corpus.label,
                    "language": corpus.language,
                    "versification": corpus.versification,
                    "ref": ", ".join(s.pretty() for s in segments),
                    # Said rather than left to be counted. "This edition does not print
                    # verse 37" and "the passage is shorter in this numbering" produce the
                    # same short array, and they are not the same fact.
                    "asked": asked,
                    "missing": asked - len(verses),
                    "partial": asked > len(verses),
                    "verses": verses,
                }
            )
        elif asked:
            # It has the book and prints none of these verses. Worth saying: silence here
            # reads as "not built" when it is really "this edition ends earlier".
            out.append({"corpus": corpus.id, "absent": True, "asked": asked})
    return {"asked": {"ref": span.pretty(), "covering": covering}, "found": out}


def api_search(params: dict[str, list[str]], body: str) -> Any:
    """Which passage a quotation came from, and which translation it was quoted in."""
    from .server import search_options

    text = body or (params.get("q") or [""])[0]
    limit = int((params.get("limit") or ["5"])[0])
    options = search_options(params)
    return {
        "matches": _jobs().run(job_search_one, text, limit, options),
        "library": library_stamp(),
    }


def api_scan(params: dict[str, list[str]], body: str) -> Any:
    """Every quotation in a document, and where in the document each one sits.

    The inverse of `search`, and the one this server was asked for: `search` must be handed
    a quotation, `scan` finds them. The spans are character offsets into the body exactly as
    posted, so a caller can point back at its own text -- which is what makes a finding
    checkable rather than merely plausible.
    """
    from .server import search_options

    options = search_options(params)
    return {
        "matches": _jobs().run(job_scan_one, body, options),
        "words": len(body.split()),
        "library": library_stamp(),
    }


def api_health() -> Any:
    return {
        "ok": True,
        "corpora": len(corpora()),
        "systems": list(AVAILABLE_SYSTEMS),
        "loaded": list(DEFAULT_SYSTEMS),
        "versification_fingerprint": fingerprint(),
        "data_home": str(home().root),
        "cores": os.cpu_count(),
        "jobs_running": _jobs().running(),
    }


def api_digest() -> Any:
    """A fingerprint of everything this machine holds, for comparing with another."""
    from dataclasses import asdict

    from ..store import library_digest

    return asdict(library_digest(home()))


def api_sources() -> Any:
    """The newest checksum of every archived source, so a mismatched digest can be run
    down to the file that caused it.

    A digest that says two machines differ and cannot say *where* sends you hunting, which
    is how the first version of it was found wanting.
    """
    from ..fetch import iter_sources

    registered = {source.id for source in iter_sources(None)}
    newest: dict[str, dict[str, Any]] = {}
    for entry in home().entries():  # newest last, so later writes win
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


def api_manifest() -> Any:
    """Every line of the archive manifest, so another machine can mirror this one."""
    from dataclasses import asdict

    return {"entries": [asdict(entry) for entry in home().entries()]}


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
