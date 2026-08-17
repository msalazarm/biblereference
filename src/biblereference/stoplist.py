"""The stock-phrase stoplist: what may not seed a search.

Genomics' structural answer to the doxology, adopted whole: DUST and SEG mask
low-complexity spans *before* alignment, so they neither trigger a search nor pad a
score — exclusion, which is stronger than down-weighting. Here the excluded class is the
liturgical furniture of Christian prose: doxologies, graces, epistolary closings — the
phrases a father writes constantly without quoting anybody, and the largest single class
of hand-read false-positive verdicts after the inner-biblical parallels.

The list itself is the first published one — the research pass found none for patristic
Greek — and it is data, not code: ``data/stoplist.json`` stores each phrase as written,
with its label and its source, and this loader folds it word by word exactly as the
scanner folds a document, so the two conventions cannot drift.

The one guarantee that makes masking survivable: a stoplisted phrase may not *seed*, but
it can still be *covered* by a match seeded elsewhere — a real quotation that happens to
end in a doxology is unharmed, because the cluster around a neighbouring window's
nomination still scores the whole stretch. Seeding is the only thing withheld.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Final

from .emphasis import fold

__all__ = ["covered", "phrases"]

#: Share of a window's tokens that must be stoplist-covered before the window may not
#: seed. Below it, the window carries enough free text to deserve its nomination.
COVER_SHARE: Final = 0.8


@lru_cache(maxsize=1)
def phrases() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every stoplist phrase as ``(label, folded word tuple)``, longest first.

    Folded with no language, because that is how ``scan`` folds a document -- a document
    scanned against a library of many languages has no one language to be folded in --
    and matching must happen in the scanner's own tokens or not at all.
    """
    raw = json.loads(
        resources.files("biblereference.data").joinpath("stoplist.json").read_text("utf-8")
    )
    out = [
        (str(entry["label"]), tuple(fold(word) for word in str(entry["text"]).split()))
        for entry in raw["phrases"]
    ]
    out.sort(key=lambda pair: -len(pair[1]))
    return tuple(out)


def covered(tokens: tuple[str, ...] | list[str]) -> frozenset[int]:
    """Which positions of a folded token stream any stoplist phrase covers.

    The same longest-first, whole-word walk as ``formulae.announced``: at each position
    the longest matching phrase wins and the walk advances past it, so ``εἰς τοὺς
    αἰῶνας`` inside the full doxology is the doxology's, not its own.
    """
    out: set[int] = set()
    at = 0
    stream = tuple(tokens)
    while at < len(stream):
        for _, phrase in phrases():
            if stream[at : at + len(phrase)] == phrase:
                out.update(range(at, at + len(phrase)))
                at += len(phrase)
                break
        else:
            at += 1
    return frozenset(out)
