"""The two appendices: what a work quoted, and on whose terms.

**Appendix Y**, the passage register, lists every passage the work cites, once and whole.
An argument quotes the same passage in pieces as it needs them -- 1 Timothy 2:7, then 2:4,
then 2:1-6 -- and a reader checking the work should not have to reassemble that. The
pieces merge into 1 Timothy 2:1-7, printed plainly with no emphasis carried over from the
body, and with a line saying where to find the passage in whatever Bible the reader owns.

**Appendix Z**, the notices, is the obligation. Publishers require a copyright line
wherever their text is quoted, and each one requires its own wording. Assembling that by
hand at the end of a treatise is exactly the sort of task that gets forgotten, so it is
assembled from what was actually quoted. Where a publisher also sets a limit on how much
may be quoted without asking, the limit is checked and the shortfall named.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Final

from .canon import NamingScheme, book_title
from .refs import VerseRange, VerseRef
from .versification import Versification, VersificationError

__all__ = [
    "Quota",
    "RegisterEntry",
    "Usage",
    "check_quota",
    "cross_scheme_references",
    "quota_for",
]


@dataclass(frozen=True, slots=True)
class RegisterEntry:
    """One passage of the register: a merged range, its texts, and where else to find it."""

    span: VerseRange
    renditions: tuple[object, ...]
    """:class:`~biblereference.render.Rendition` objects, kept loosely typed to avoid a
    circular import."""
    equivalents: tuple[str, ...]
    """How the passage is referred to in other numbering and naming traditions."""

    @property
    def heading(self) -> str:
        return self.span.pretty()


@dataclass
class Usage:
    """How much of one text a work quotes."""

    corpus_id: str
    label: str
    verses: set[tuple[str, int, int, str]] = field(default_factory=set)
    words: int = 0
    attribution: str | None = None

    @property
    def verse_count(self) -> int:
        """Distinct verses. Quoting a verse twice does not make it two verses."""
        return len(self.verses)

    @property
    def books(self) -> set[str]:
        return {book for book, _, _, _ in self.verses}

    def record(self, refs: Iterable[VerseRef], text: str) -> None:
        for ref in refs:
            if isinstance(ref.chapter, int):
                self.verses.add((ref.book, ref.chapter, ref.verse, ref.subverse))
        # Words are counted as printed: a verse quoted twice puts its words on the page
        # twice, and a word limit is about the page.
        self.words += len(re.findall(r"[^\W_]+", text))


@dataclass(frozen=True, slots=True)
class Quota:
    """What a publisher permits without being asked."""

    corpus_id: str
    holder: str
    summary: str
    verses: int | None = None
    words: int | None = None
    work_fraction: float | None = None
    contact: str | None = None
    source: str | None = None

    @property
    def has_number(self) -> bool:
        """Whether there is a limit to measure against, rather than only a contact."""
        return self.verses is not None or self.words is not None


@dataclass(frozen=True, slots=True)
class QuotaFinding:
    """The result of measuring one text's use against its publisher's terms."""

    usage: Usage
    quota: Quota
    exceeded: bool
    reasons: tuple[str, ...]

    def message(self, alternative: Mapping[str, str]) -> str:
        head = (
            f"This work quotes {self.usage.verse_count} distinct verses "
            f"({self.usage.words:,} words) of the {self.usage.label}."
        )
        if not self.quota.has_number:
            return (
                f"{head} The {self.quota.holder} publishes no quota for it: "
                f"{self.quota.summary}. Confirm with {self.quota.contact} before "
                f"publishing."
            )
        body = f"The {self.quota.holder} permits {self.quota.summary}. " + (
            "That is exceeded: " + "; ".join(self.reasons) + "."
            if self.exceeded
            else "This work is within that."
        )
        if not self.exceeded:
            return f"{head} {body}"
        return (
            f"{head} {body}\n\n"
            f"Either write to {self.quota.contact}, or quote from a public-domain "
            f"translation. The {alternative['name']} ({alternative['abbreviation']}) is "
            f"{alternative['note']}; the World English Bible Catholic Edition, the "
            f"Douay-Rheims and the Clementine Vulgate are already available here and "
            f"carry none either."
        )


@cache
def _data() -> dict[str, object]:
    path = resources.files("biblereference").joinpath("data", "quotas.json")
    with path.open(encoding="utf-8") as handle:
        loaded: dict[str, object] = json.load(handle)
    return loaded


def public_domain_note(corpus_id: str) -> str | None:
    """The plain statement for a text that carries no restriction."""
    table = _data()["public_domain"]
    assert isinstance(table, dict)
    value = table.get(corpus_id)
    return str(value) if value else None


def quota_for(corpus_id: str) -> Quota | None:
    """The publisher's terms for a text, or ``None`` where none apply."""
    table = _data()["quotas"]
    assert isinstance(table, dict)
    entry = table.get(corpus_id)
    if entry is None:
        return None
    assert isinstance(entry, dict)
    while "same_as" in entry:
        entry = table[str(entry["same_as"])]
        assert isinstance(entry, dict)

    return Quota(
        corpus_id=corpus_id,
        holder=str(entry["holder"]),
        summary=str(entry["summary"]),
        verses=entry.get("verses"),  # type: ignore[arg-type]
        words=entry.get("words"),  # type: ignore[arg-type]
        work_fraction=entry.get("work_fraction"),  # type: ignore[arg-type]
        contact=str(entry.get("contact", "the publisher")),
        source=entry.get("source"),  # type: ignore[arg-type]
    )


def recommended_alternative() -> Mapping[str, str]:
    value = _data()["recommended_alternative"]
    assert isinstance(value, dict)
    return {k: str(v) for k, v in value.items()}


def check_quota(usage: Usage, document_words: int) -> QuotaFinding | None:
    """Measure one text's use against its publisher's terms.

    :param document_words: Words in the finished document, appendices included, for the
        publishers who cap the proportion of the work rather than the amount of scripture.
    """
    quota = quota_for(usage.corpus_id)
    if quota is None:
        return None

    reasons: list[str] = []
    if quota.verses is not None and usage.verse_count > quota.verses:
        reasons.append(f"{usage.verse_count} verses against a limit of {quota.verses}")
    if quota.words is not None and usage.words > quota.words:
        reasons.append(f"{usage.words:,} words against a limit of {quota.words:,}")
    if quota.work_fraction is not None and document_words:
        share = usage.words / document_words
        if share > quota.work_fraction:
            reasons.append(
                f"{share:.0%} of this work's words against a limit of {quota.work_fraction:.0%}"
            )

    return QuotaFinding(usage=usage, quota=quota, exceeded=bool(reasons), reasons=tuple(reasons))


# --------------------------------------------------------------------------------------
# Cross-scheme references
# --------------------------------------------------------------------------------------

#: How each versification is described to a reader, in reading order of usefulness.
_SYSTEM_NAMES: Final[Mapping[str, str]] = {
    "org": "Hebrew and Greek numbering",
    "eng": "English numbering",
    "lxx": "Septuagint",
    "vul": "Vulgate",
    "nvl": "Nova Vulgata",
}


def cross_scheme_references(versification: Versification, span: VerseRange) -> tuple[str, ...]:
    """Say where else this passage can be found, by number and by name.

    A reader fact-checking against a Douay-Rheims will not find Psalm 23 or 1 Chronicles
    in it. Only genuine differences are listed -- a passage numbered and named the same
    everywhere produces nothing, because a line of identical references is noise.
    """
    out: list[str] = []
    own = span.pretty()

    for system, description in _SYSTEM_NAMES.items():
        if system == span.vrs:
            continue
        try:
            segments = versification.convert_range(span, system)
        except VersificationError:
            continue
        rendered = ", ".join(segment.pretty() for segment in segments)
        if rendered and rendered != own:
            out.append(f"{description} {rendered}")

    for scheme, description in (
        (NamingScheme.DR, "Douay-Rheims"),
        (NamingScheme.LXX, "Septuagint"),
    ):
        name = book_title(span.book, scheme)
        if name != book_title(span.book):
            out.append(f"named {name} in a {description} Bible")

    return tuple(out)


def merge_citations(versification: Versification, spans: Sequence[VerseRange]) -> list[VerseRange]:
    """The register's passages: every citation, merged and in reading order."""
    return versification.merge(spans)
