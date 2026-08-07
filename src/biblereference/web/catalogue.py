"""The library describing itself: sixty-six editions, and which numbering each really uses.

Two endpoints with opposite temperaments. ``/api/library`` reports what each corpus *says*
it is -- its label, language, declared versification, licence and date -- off metadata
already in memory. ``/api/families`` reports what the chapter divisions *show*, which takes
two-thirds of a second of grouping and is therefore built once and lazily.

The licence column is the part with a wrong answer waiting in it. Twenty-five of the
sixty-six are restricted, and they include CC BY-SA -- share-alike is a real obligation, so
a single "non-commercial" flag would mislabel them. One corpus, ``niv``, has no recorded
licence at all, and by this library's own doctrine -- *a licence nobody has read is not a
licence to do anything* -- that has to be louder than a restrictive one rather than blank.
And ``sblgnt`` carries two, which is the case the schema exists for: its files declare
CC BY 4.0 and the edition's own terms govern.
"""

from __future__ import annotations

import threading
from typing import Any

from ..canon import book_canon, is_known
from ..dating import translated
from ..licences import Licence
from .library import corpora, home, library

__all__ = ["api_families", "api_library"]


def _licence(terms: Licence | None) -> dict[str, Any]:
    """What a reader may do with this text, and how confident we are that we know.

    ``unrecorded`` is the loudest state on purpose. A blank cell reads as "no restrictions"
    and an absent licence means the opposite: nobody has established what the terms are.
    """
    if terms is None:
        return {
            "unrecorded": True,
            "restricted": True,
            "describe": "no licence recorded -- nobody has established the terms",
        }
    governing = terms.effective
    return {
        "unrecorded": False,
        "id": terms.id,
        "name": terms.name,
        "url": terms.url,
        "summary": terms.summary,
        "notice": terms.notice,
        "describe": terms.describe(),
        # The *governing* terms, which are the stricter of what the file declares and what
        # the edition underneath it allows. Answering with the header would tell a reader
        # they may do something they may not.
        "governed_by": governing.id,
        "commercial": governing.commercial,
        "share_alike": governing.share_alike,
        "attribution": governing.attribution,
        "restricted": governing.restricted,
    }


def api_library(params: dict[str, list[str]]) -> Any:
    """Every built corpus, with what it holds and what may be done with it."""
    held = library()
    inventory = held.chapters
    rows: list[dict[str, Any]] = []
    languages: dict[str, int] = {}
    families: dict[str, int] = {}
    verses = restricted = unrecorded = 0
    for corpus in sorted(corpora().values(), key=lambda c: c.id):
        meta = corpus.meta
        books = sorted(corpus.books)
        chapters = inventory.get(corpus.id, {})
        canon: dict[str, int] = {}
        for book in books:
            if is_known(book):
                key = book_canon(book).value
                canon[key] = canon.get(key, 0) + 1
        year = translated(corpus.id)
        terms = _licence(meta.terms)
        verses += meta.verse_count
        languages[corpus.language] = languages.get(corpus.language, 0) + 1
        families[corpus.versification] = families.get(corpus.versification, 0) + 1
        if terms["unrecorded"]:
            unrecorded += 1
        elif terms["restricted"]:
            restricted += 1
        rows.append(
            {
                "corpus": corpus.id,
                "label": corpus.label,
                "language": corpus.language,
                "versification": corpus.versification,
                "attribution": corpus.attribution,
                "verses": meta.verse_count,
                "books": len(books),
                "chapters": sum(len(ch) for ch in chapters.values()),
                "canon": canon,
                # The year the *wording* appeared, which is what makes a quotation
                # anachronistic. None means the text is ancient rather than unknown.
                "translated": year,
                "ancient": year is None,
                "source_url": meta.source_url,
                "fetched_at": meta.fetched_at,
                "built_at": meta.built_at,
                "licence": terms,
                "licence_ids": (meta.licence_ids or meta.licence_id or "").split(",")
                if (meta.licence_ids or meta.licence_id)
                else [],
            }
        )

    return {
        "data_home": str(home().root),
        "totals": {
            "corpora": len(rows),
            "verses": verses,
            "languages": dict(sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))),
            "families": dict(sorted(families.items(), key=lambda kv: (-kv[1], kv[0]))),
            # Counted apart, because they are different states and only one of them is
            # knowledge. `restricted` is what a recorded licence actually restricts;
            # `unrecorded` is where nobody has established the terms, which is stricter
            # still and must not be added into a single reassuring number.
            "restricted": restricted,
            "unrecorded": unrecorded,
        },
        "corpora": rows,
    }


# --------------------------------------------------------------------------------------
# What the chapter divisions actually show
# --------------------------------------------------------------------------------------

_FAMILIES: dict[str, Any] = {}
_FAMILIES_LOCK = threading.Lock()


def api_families(params: dict[str, list[str]]) -> Any:
    """Versification families derived from where the corpora put their chapter ends.

    Two-thirds of a second to read the signatures and group them, and it changes only when
    the database is rebuilt -- so it is memoised against the same key as the rest of the
    process-wide cache, and only ever asked for by the screen that shows it.

    Worth having beside :func:`api_library` because the two can disagree, and where they do
    is the interesting part: a corpus *declares* a versification in its metadata, and this
    says which one its chapter divisions actually resemble.
    """
    from ..families import declared_systems, derive, read_signatures, to_json

    key = library().key
    with _FAMILIES_LOCK:
        if _FAMILIES.get("key") != key:
            where = home()
            signatures = read_signatures(where)
            _FAMILIES.update(
                key=key,
                value=to_json(derive(signatures), signatures, declared_systems(where)),
            )
        return _FAMILIES["value"]
