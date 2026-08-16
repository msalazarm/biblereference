"""The words a writer uses to say that what follows is scripture.

*It is written*, *the scripture says*, *God says*. A quotation introduced this way is being
announced, and the announcement is evidence about it that the words themselves do not carry.
Stephen Boyce, reading Ignatius, 1 Clement and Polycarp citation by citation, treats the
choice of formula as diagnostic rather than decorative -- on 1 Clement 29:3 he argues that
``λέγει`` where the author elsewhere writes ``γέγραπται`` implies recollection rather than a
manuscript open on the desk.

**Reported, never acted on.** Measured over this library's own corpora, these run at 1.52 per
thousand words in the fathers against 0.245 in Greek by authors who died before there was a
New Testament -- a sixfold enrichment, real and nowhere near strong enough to let a match in
that the evidence would otherwise refuse. Two things stop it being a gate:

* ``φησίν`` is ordinary Greek for *he says*, and Aristotle writes it constantly;
* **Ignatius uses no formula at all.** Boyce says so outright, and the quotations that this
  whole feature exists to find -- Matthew 10:16 above all -- are Ignatius'.

So :attr:`Match.formula` records what preceded a quotation and changes no threshold. The
people who asked for this said they would rather weigh the evidence than be handed a verdict.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import Final

from .emphasis import fold

__all__ = ["FORMULAE", "announced", "preceding"]

#: How far back to look, in words. A formula introduces what comes next; a clause away it is
#: introducing something else.
REACH: Final = 6

#: What each language announces a quotation with, in folded form, longest first so that
#: ``λέγει ἡ γραφή`` is reported rather than the ``λέγει`` inside it.
#:
#: The Greek is every formula Boyce quotes across his six papers, with where he quotes it.
#: The Latin is the Vulgate's own wording for the same act, which is what a Latin father
#: writing after Jerome reaches for.
FORMULAE: Final[dict[str, tuple[str, ...]]] = {
    "grc": (
        "ουτωσ γαρ φησιν ο αγιοσ λογοσ",  # 1 Clem. 56:3
        "ουτωσ γαρ που λεγει η γραφη",  # 1 Clem. 42:5b
        "και εν ετερω τοπω λεγει",  # 1 Clem. 29:3
        "ειρηκεν ο κυριοσ",  # Didache 9:1
        "λεγει η γραφη",
        "θεοσ γαρ φησιν",  # 1 Clem. 30:2
        "και παλιν λεγει",  # 1 Clem. 17:6
        "καθωσ γεγραπται",
        "ωσ γεγραπται",
        "γεγραπται",  # 1 Clem. 17:3, and the plainest of them
        "λεγει γαρ",  # 1 Clem. 30:4, "a common marker of scriptural citation"
        "φησιν",  # 1 Clem. 56:5 -- and ordinary Greek besides, which is why this is no gate
    ),
    "la": (
        "sicut scriptum est",
        "scriptura dicit",
        "scriptum est",
        "dicit dominus",
        "ait enim",
    ),
}

#: Anchored on whole words. Without it ``ὡς γέγραπται`` is found inside ``οὕτως γέγραπται``
#: -- the folded text runs the two together as ``ουτωσ γεγραπται`` -- and the formula reported
#: is one the writer did not use.
_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    language: re.compile(
        r"(?:(?<=\s)|^)(?:" + "|".join(re.escape(form) for form in forms) + r")(?=\s|$)"
    )
    for language, forms in FORMULAE.items()
}


#: The formulae as word tuples, longest first, for matching against a tokenised document.
#: Longest first so that at one position ``λεγει η γραφη`` is the announcement found and
#: not the ``λεγει`` it begins with -- the same rule the regex encodes by ordering.
_SPLIT: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    language: tuple(sorted((tuple(form.split()) for form in forms), key=len, reverse=True))
    for language, forms in FORMULAE.items()
}


def announced(tokens: Sequence[str], language: str) -> Iterator[tuple[str, int, int]]:
    """Every citation formula in a tokenised document, and where each one sits.

    The other direction from :func:`preceding`: that starts from a quotation and asks what
    introduced it, this starts from the document and asks what was introduced -- which is
    the question a false-negative ledger needs, because a formula with no quotation after
    it is the announcement of something the library failed to find.

    :param tokens: The document's words, folded one by one -- punctuation already shed by
        the tokeniser, which is why this can match on word tuples where :func:`preceding`
        needs a regex.
    :returns: ``(formula, start, after)`` word indices, non-overlapping, in order.
    """
    forms = _SPLIT.get(language, ())
    at = 0
    while at < len(tokens):
        for form in forms:
            if tuple(tokens[at : at + len(form)]) == form:
                yield " ".join(form), at, at + len(form)
                at += len(form)
                break
        else:
            at += 1


def preceding(text: str, start: int, language: str, *, reach: int = REACH) -> str | None:
    """The citation formula in the ``reach`` words before ``start``, if there is one.

    :param text: The document, as written.
    :param start: Character offset the quotation begins at.
    :returns: The formula, folded, or ``None``. Folded because that is the form it was
        recognised in and reporting the surface spelling would invite a caller to match on
        something this never compared.
    """
    patterns = _PATTERNS.get(language)
    if patterns is None or start <= 0:
        return None
    before = text[:start].split()
    if not before:
        return None
    found = patterns.findall(fold(" ".join(before[-reach:]), language))
    # The last one, because a sentence may carry several and the nearest is the one doing
    # the introducing.
    return str(found[-1]) if found else None
