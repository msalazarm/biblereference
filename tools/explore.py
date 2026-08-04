"""A local web page for looking at one passage in every version at once.

Not part of the library -- a bench for trying things by hand. Type a reference, pick the
numbering you wrote it in, and it shows two things side by side: how that reference is
numbered in each versification system, and the text of every corpus that carries it.

The covering toggle is the interesting part. Most passages look identical either way,
which is the point; the ones that do not are where an edition merges what another divides.
Some to try:

    Matt 17:14  in vul      the Douay carries both halves of what the Greek numbers 14 and 15
    Bar 6:43    in eng      English merges two Latin verses, and org LJE 1:43 is reachable
                            only under covering
    1Sam 20:42  in eng      a cover that crosses a chapter boundary
    Mal 3:22    in org      the Greek moves "remember the law of Moses" to the end
    Matt 5:4    in vul      the Clementine puts the meek before those who mourn

Run it:

    venv/bin/python tools/explore.py          # http://localhost:8000
    venv/bin/python tools/explore.py --port 9000
"""

from __future__ import annotations

import argparse
import html
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from biblereference.corpora.base import VerseUnavailable
from biblereference.refs import VerseRange, parse_reference
from biblereference.store import DataHome, SqliteCorpus
from biblereference.versification import (
    DEFAULT_SYSTEMS,
    Versification,
    VersificationError,
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


def page(query: str, source: str, covering: bool) -> str:
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
  <input type="text" name="q" value="{esc(query)}" autofocus
         placeholder="John 3:16 · Rom 1:1-5 · Matt 17:14">
  <label>written in <select name="vrs">{options}</select></label>
  <label><input type="checkbox" name="covering" value="1"
         {"checked" if covering else ""}> covering</label>
  <button type="submit">show</button>
</form>
{body or HINT}
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        try:
            out = page(
                (params.get("q") or [""])[0].strip(),
                (params.get("vrs") or ["eng"])[0],
                bool(params.get("covering")),
            )
            status = 200
        except Exception:
            out = f"<pre>{esc(traceback.format_exc())}</pre>"
            status = 500
        payload = out.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        return  # the console is for tracebacks, not for a line per request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(
        f"{len(corpora())} corpora · http://{args.host}:{args.port}  (ctrl-c to stop)",
        flush=True,
    )
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
