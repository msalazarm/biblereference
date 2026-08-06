"""What each text may be used for, as an object rather than a sentence.

Every corpus already carries a ``license`` string, and for a library of public-domain
English Bibles that is enough: the answer to "may I use this" is yes, and the only real
obligation is a credit line the renderer already prints.

It stops being enough the moment a text says no. The Peshitta Old Testament is CC BY-NC,
Corpus Corporum grants its files for non-commercial use, and the two say so in different
words -- ``CC BY-NC 4.0``, ``Creative Commons Attribution NonCommercial 4.0 International``,
``https://creativecommons.org/licenses/by-nc/4.0/``. A string cannot be asked which of
sixty-odd corpora forbid commercial use; an id can.

Three things this module knows that a pair of booleans could not:

* **The wording is part of the licence.** CC BY-NC-SA obliges two different things at once,
  public domain obliges nothing and should not be credited as though it did, and the SBLGNT
  requires a specific notice naming its publishers. What has to be printed belongs on the
  object that knows why.
* **Strictness is an editorial judgement.** Whether non-commercial is stricter than
  share-alike is a decision, not a derivation, so :attr:`Licence.rank` writes it down once
  where it can be argued with rather than recomputing it in three places.
* **A file can be wrong about itself.** The Patristic Text Archive publishes the SBL Greek
  New Testament under a CC BY 4.0 header. The text is the SBLGNT, whose own terms are not
  CC BY, and printing the header's claim would state something untrue. :attr:`underlying`
  is for exactly that: what the file says, and what the edition actually is.

An unrecognised licence returns ``None`` and the caller records a note. It never falls back
to something permissive -- a licence nobody has read is not a licence to do anything.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

__all__ = [
    "LICENCES",
    "Licence",
    "from_url",
    "get",
    "strictest",
]


@dataclass(frozen=True, slots=True)
class Licence:
    """The terms one text is held under."""

    id: str
    name: str
    url: str | None
    commercial: bool
    """Whether the text may be used commercially."""
    share_alike: bool
    """Whether a derivative must carry these same terms."""
    attribution: bool
    """Whether credit is required. False only for public domain."""
    rank: int
    """Strictness, low to high. See :func:`strictest`."""
    summary: str
    """One sentence, the form the ``license`` string has always taken."""
    notice: str
    """What the rendered appendix has to print."""
    underlying: Licence | None = None
    """Where the file's declared licence is not the edition's own terms."""

    @property
    def restricted(self) -> bool:
        """Whether anything here needs a reader's attention beyond a credit line."""
        return not self.commercial or self.share_alike or self.underlying is not None

    def describe(self) -> str:
        """One line for ``doctor``."""
        obliges = []
        if not self.commercial:
            obliges.append("non-commercial")
        if self.share_alike:
            obliges.append("share-alike")
        if self.attribution:
            obliges.append("attribution required")
        tail = f" -- {', '.join(obliges)}" if obliges else ""
        return f"{self.name}{tail}"


def _cc(
    slug: str, name: str, *, commercial: bool, share_alike: bool, rank: int, notice: str
) -> Licence:
    url = f"https://creativecommons.org/licenses/{slug}/4.0/"
    return Licence(
        id=f"cc-{slug}-4.0",
        name=name,
        url=url,
        commercial=commercial,
        share_alike=share_alike,
        attribution=True,
        rank=rank,
        summary=f"{name}. See {url}",
        notice=notice,
    )


#: Every licence this library knows how to hold a text under.
#:
#: Ranked, low to high: public domain obliges nothing; attribution alone is the mildest
#: real obligation; share-alike constrains what you may build; non-commercial constrains
#: who you may be; and terms that are neither Creative Commons nor readable from the file
#: rank hardest because they have to be read by a person.
LICENCES: Final[dict[str, Licence]] = {
    licence.id: licence
    for licence in (
        Licence(
            id="public-domain",
            name="Public domain",
            url=None,
            commercial=True,
            share_alike=False,
            attribution=False,
            rank=0,
            summary="Public domain.",
            notice="In the public domain. No permission is required to quote it.",
        ),
        _cc(
            "by",
            "CC BY 4.0",
            commercial=True,
            share_alike=False,
            rank=1,
            notice="Free to use, including commercially, with credit to the editors.",
        ),
        _cc(
            "by-sa",
            "CC BY-SA 4.0",
            commercial=True,
            share_alike=True,
            rank=2,
            notice=(
                "Free to use, including commercially, with credit -- but anything derived "
                "from it must carry these same terms. Keep such work separable from the rest."
            ),
        ),
        _cc(
            "by-nc",
            "CC BY-NC 4.0",
            commercial=False,
            share_alike=False,
            rank=3,
            notice="May not be used commercially. Credit to the editors is required.",
        ),
        _cc(
            "by-nc-sa",
            "CC BY-NC-SA 4.0",
            commercial=False,
            share_alike=True,
            rank=4,
            notice=(
                "May not be used commercially, and anything derived from it must carry "
                "these same terms."
            ),
        ),
        Licence(
            id="site-terms-nc",
            name="Non-commercial, by the distributor's terms",
            url=None,
            commercial=False,
            share_alike=False,
            attribution=True,
            rank=5,
            summary=(
                "Granted by the distributor for non-commercial use. The underlying edition "
                "is old enough to be out of copyright in its own right, so the constraint "
                "is on these files rather than on the text."
            ),
            notice=(
                "Held under the distributor's own non-commercial terms rather than a named "
                "licence, with provenance stated as a best effort. The printed editions "
                "behind it are out of copyright, so a copy obtained elsewhere may be freer."
            ),
        ),
        Licence(
            id="sblgnt",
            name="SBL Greek New Testament licence",
            url="https://sblgnt.com/license/",
            commercial=False,
            share_alike=False,
            attribution=True,
            rank=5,
            summary=(
                "The SBL Greek New Testament, under its own licence rather than a Creative "
                "Commons one. Quoting is free; redistributing the text is not."
            ),
            notice=(
                "The SBL Greek New Testament, copyright the Society of Biblical Literature "
                "and Logos Bible Software, used under the SBLGNT licence. Quotation is "
                "permitted; wholesale redistribution of the text is not."
            ),
        ),
    )
}

#: Which of the Creative Commons paths we recognise, by their ``by``/``nc``/``sa`` parts.
_CC_PATH: Final = re.compile(
    r"creativecommons\.org/(?:licenses|publicdomain)/(?P<slug>[a-z0-9-]+)/(?P<version>[\d.]+)?"
)


def get(licence_id: str) -> Licence:
    """One licence by id, or ``KeyError`` naming what is known."""
    try:
        return LICENCES[licence_id]
    except KeyError:
        raise KeyError(
            f"unknown licence {licence_id!r}; known: {', '.join(sorted(LICENCES))}"
        ) from None


def from_url(target: str | None) -> Licence | None:
    """The licence a ``<licence target="...">`` names, or ``None`` if we do not know it.

    Normalising matters more than it looks. The Digital Syriac Corpus writes ``http://``
    and the Patristic Text Archive ``https://``, one of them ends the path with a slash and
    the other does not, and treating those as different licences would file two thirds of
    the Syriac as unknown.

    Returning ``None`` is a real answer and the caller must record it. Guessing a
    permissive default here would be the one mistake in this module that nobody notices.
    """
    if not target:
        return None
    match = _CC_PATH.search(target.strip().lower())
    if match is None:
        return None
    slug = match.group("slug")
    if slug in {"zero", "mark", "publicdomain"}:
        return LICENCES["public-domain"]
    version = match.group("version") or "4.0"
    if version.split(".")[0] != "4":
        # 3.0 and 2.0 differ in ways this library has not read. Say so rather than assume.
        return None
    return LICENCES.get(f"cc-{slug}-4.0")


def strictest(licences: Iterable[Licence]) -> Licence:
    """The one that governs a set of texts held together.

    Used where a corpus is built from files that do not agree. The right answer for a
    library is always the hardest of them: a collection is only as usable as its most
    restricted member, and rounding the other way would state a freedom the holder does
    not have.
    """
    ordered = sorted(licences, key=lambda licence: (licence.rank, licence.id))
    if not ordered:
        raise ValueError("no licences given")
    return ordered[-1]
