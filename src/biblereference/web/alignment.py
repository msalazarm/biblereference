"""Where the systems disagree, and why the answer is what it is.

The numbering table has always been able to say *that* ``vul`` puts two Greek verses in one
and that ``lxx`` refuses a verse outright. What it could not say is **why**, and there are
two different kinds of why:

**A refusal explains itself.** Every :class:`~biblereference.versification.VersificationError`
here is written as a sentence for a person -- "Baruch 6 is the Letter of Jeremiah, which
``org`` numbers as its own book" -- so the answer is to carry it through rather than
flatten it to null.

**A mapping does not.** Two hundred of them were corrected by somebody who had just read
the verses, and every one of those corrections carries a recorded reason that the loader
consumed and threw away. :func:`~biblereference.versification.corrections` keeps them now,
and this is what asks: for both ends of the mapping, since a verse can be moved by a
correction to the system it came from or by one to the system it is going to.
"""

from __future__ import annotations

from typing import Any

from ..canon import book_title, resolve_book
from ..refs import VerseRange, parse_reference
from ..versification import Correction, VersificationError, corrections
from .library import VRS
from .plain import SYSTEM_LABEL
from .reader import naming_of, system_of

__all__ = ["api_alignment", "api_corrections"]


def _as_dict(correction: Correction) -> dict[str, Any]:
    return {
        "system": correction.system,
        "kind": correction.kind,
        "key": correction.key,
        "scope": correction.scope,
        "reason": correction.reason,
        "detail": dict(correction.detail),
    }


def _unheld(system: str, spans: list[VerseRange]) -> str | None:
    """A sentence, where the conversion landed in a book this system does not have.

    ``convert_range`` falls back to the identity where neither system maps a book, and the
    fallback does not check that the target *has* it -- so ``ENO 1:1`` in ``org`` converts
    to ``ENO 1:1`` in ``nvl``, which declares no 1 Enoch. Measured over the shipped tables:
    2,384 conversions across 90 (source, target, book) triples, all of them books one
    system carries and another does not. The pivot has every one of them, which is why the
    coverage walk -- whose ghost check is against the pivot -- reports none.

    Recorded in TODO.md as its own question. Here it is only reported: a screen must say
    "the Nova Vulgata has no 1 Enoch" rather than raise on it.
    """
    missing = sorted({s.book for s in spans if not VRS.has_book(system, s.book)})
    if not missing:
        return None
    titles = ", ".join(book_title(book) for book in missing)
    return (
        f"{titles} is not a book of {system!r}, so this reference has no place in it. "
        f"(The conversion answered with the same numbering, which is the identity fallback "
        f"rather than a mapping.)"
    )


def _touching(system: str, spans: list[VerseRange]) -> list[Correction]:
    """Every correction bearing on these coordinates of this system, least specific first.

    Deduplicated across the spans by identity: a ranged correction covers many verses and
    would otherwise come back once per verse of the range.
    """
    seen: dict[int, Correction] = {}
    for span in spans:
        for ref in VRS.expand(span):
            for correction in corrections().at(system, ref.book, int(ref.chapter), ref.verse):
                seen.setdefault(id(correction), correction)
    return list(seen.values())


def api_alignment(params: dict[str, list[str]]) -> Any:
    """One reference as every system numbers it, exact beside covering, with the reasons.

    ``exact`` is which verse it *is*; ``covering`` is every verse needed to carry all of its
    text. They are identical for almost every verse in the library, which is the point --
    where they differ is where one edition merges what another divides.
    """
    source = system_of(params, "from") if params.get("from") else system_of(params)
    naming = naming_of(params)
    span = parse_reference(
        (params.get("ref") or [""])[0], vrs=source, naming=naming, allow_chapter=True
    )
    targets = [name for raw in (params.get("to") or []) for name in raw.split(",") if name] or list(
        VRS.system_names
    )
    for target in targets:
        if target not in VRS.system_names:
            raise ValueError(
                f"unknown versification {target!r}; this server has loaded "
                f"{', '.join(VRS.system_names)}"
            )

    # The source end of every mapping, which is the same whichever target is asked for.
    here = [_as_dict(c) for c in _touching(source, [span])]

    rows = []
    for target in targets:
        row: dict[str, Any] = {
            "system": target,
            "label": SYSTEM_LABEL.get(target, target),
            "why": list(here),
        }
        for mode in ("exact", "covering"):
            try:
                segments = VRS.convert_range(span, target, covering=mode == "covering")
            except VersificationError as exc:
                # Written as a sentence for a person, so it is the answer rather than the
                # absence of one.
                row[mode] = {"refused": str(exc)}
                continue
            absent = _unheld(target, segments)
            if absent is not None:
                row[mode] = {"refused": absent}
                continue
            row[mode] = {
                "ref": ", ".join(s.pretty() for s in segments) or "—",
                "usfm": ", ".join(str(s) for s in segments),
                "verses": sum(len(VRS.expand(s)) for s in segments),
            }
            if target != source:
                row["why"] += [
                    _as_dict(c)
                    for c in _touching(target, segments)
                    if not any(w["key"] == c.key and w["kind"] == c.kind for w in row["why"])
                ]
        row["differs"] = row["exact"] != row["covering"]
        rows.append(row)

    return {
        "asked": {
            "ref": span.pretty(),
            "usfm": str(span),
            "vrs": source,
            "naming": naming.value,
            "book": span.book,
        },
        "systems": rows,
    }


# --------------------------------------------------------------------------------------
# The corrections themselves
# --------------------------------------------------------------------------------------


def api_corrections(params: dict[str, list[str]]) -> Any:
    """Browse the recorded reasons: by system, by book, by coordinate, or by kind.

    ``malformed`` is here rather than buried because it is the honest part. One upstream key
    cannot be parsed as a reference and is in the file verbatim on purpose; a *new* one
    would be a reason nobody could reach, so the set is reported and a test pins it.
    """
    held = corrections()
    systems = [name for raw in params.get("system", ()) for name in raw.split(",") if name]
    kinds = {name for raw in params.get("kind", ()) for name in raw.split(",") if name}
    book = (params.get("book") or [""])[0]
    chapter = (params.get("chapter") or [""])[0]
    verse = (params.get("verse") or [""])[0]

    if book:
        code = resolve_book(book, naming_of(params))
        wanted = systems or list(VRS.system_names)
        found: list[Correction] = []
        for system in wanted:
            if chapter:
                found += held.at(system, code, int(chapter), int(verse) if verse else None)
            else:
                found += held.for_book(system, code)
    elif systems:
        found = [c for system in systems for c in held.for_system(system)]
    else:
        found = list(held.all())

    if kinds:
        found = [c for c in found if c.kind in kinds]

    counts: dict[str, int] = {}
    for correction in found:
        counts[correction.kind] = counts.get(correction.kind, 0) + 1

    return {
        "asked": {
            "systems": systems,
            "book": book,
            "chapter": chapter,
            "verse": verse,
            "kinds": sorted(kinds),
        },
        "total": len(found),
        "kinds": dict(sorted(counts.items())),
        "malformed": [
            {"system": system, "kind": kind, "key": key} for system, kind, key in held.malformed
        ],
        "corrections": [_as_dict(c) for c in found],
    }
