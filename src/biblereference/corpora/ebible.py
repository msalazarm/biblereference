"""Bibles from eBible.org: the English corpus, and the Latin.

Three texts are named here because the renderer reaches for them by name:

**World English Bible, Catholic Edition** -- translated from the Greek and numbered the
way the Greek is numbered, so it answers a citation written as ``Sir 24:1`` or
``Tob 1:1``. Modern English. This is the default fallback.

**Douay-Rheims 1899** -- translated from the Vulgate and numbered the way the Vulgate is
numbered. Jerome's Tobit, Judith and Sirach come from source texts that differ from the
Greek by whole clauses, which is exactly why the versification data refuses to map them;
so the Douay-Rheims answers citations written in Vulgate numbering, and only those.

**Clementine Vulgate** -- Jerome's Latin as the Church received it, numbered exactly as
the Douay-Rheims is, because the Douay-Rheims translates it. Sixty-five of its
seventy-three books agree with the Douay-Rheims verse for verse.

Behind those sit **fifty more English translations**, listed in
``data/ebible_english.json`` and built from the same machinery. They exist for the search
index rather than for citation: telling which translation a preacher quoted means holding
enough translations to tell them apart. Every one of them carries eBible's
``Redistributable`` flag -- thirty-two are public domain outright, eighteen are under
copyright and redistributed with the holder's permission, and that distinction is carried
into ``SourceMeta`` so the notice machinery can act on it.

Versification is the danger in a set that large. It is declared in the table and then
*checked* at build time against the structure actually parsed, because filing a
translation under the wrong numbering yields confidently wrong verses. See
:func:`best_fit_versification`.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Final

from ..canon import is_known
from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from ..versification import Versification, VersificationError
from .usfm import parse_usfm

__all__ = [
    "DRA",
    "ENGLISH",
    "LATVUC",
    "WEBC",
    "best_fit_versification",
    "build_dra",
    "build_latvuc",
    "build_webc",
    "english_table",
]

#: Systems a bulk English translation could plausibly be numbered in. ``org`` belongs here
#: because a translation made from the Hebrew for a Jewish readership follows the Masoretic
#: divisions rather than the English tradition's -- leaving it out of this tuple is how the
#: Orthodox Jewish Bible and Targum Onkelos were nearly filed one verse out through
#: Deuteronomy. ``nvl`` is the Nova Vulgata's own and belongs to one book; nothing in
#: English is numbered that way.
_CANDIDATE_SYSTEMS: Final = ("org", "eng", "lxx", "vul")

#: How much better a rival system must fit before the declared one is called into
#: question. Small disagreements are normal -- translations drop a verse here and there --
#: so only a decisive margin is worth a note.
_FIT_MARGIN: Final = 0.05


def _observed(verses: list[tuple[VerseRef, str]]) -> dict[str, dict[int, int]]:
    """The structure actually parsed: book to chapter to highest verse number seen."""
    shape: dict[str, dict[int, int]] = {}
    for ref, _ in verses:
        chapters = shape.setdefault(ref.book, {})
        chapter = int(ref.chapter)
        if ref.verse > chapters.get(chapter, -1):
            chapters[chapter] = ref.verse
    return shape


def _fit(shape: Mapping[str, Mapping[int, int]], vrs: Versification, system: str) -> float:
    """What share of the observed chapters end exactly where ``system`` says they do."""
    matched = compared = 0
    for book, chapters in shape.items():
        for chapter, highest in chapters.items():
            try:
                expected = vrs.max_verse(system, book, chapter)
            except VersificationError:
                continue
            compared += 1
            if expected == highest:
                matched += 1
    return matched / compared if compared else 0.0


def best_fit_versification(
    verses: list[tuple[VerseRef, str]],
    vrs: Versification,
    systems: tuple[str, ...] = _CANDIDATE_SYSTEMS,
) -> list[tuple[str, float]]:
    """Rank versification systems by how well each explains the text as parsed.

    Chapter ends are the tell. The Septuagint's psalter runs to 151 and puts the shepherd
    psalm at 22; the English runs to 150 and puts it at 23; the Vulgate numbers Esther
    through chapter 16. A translation filed under the wrong one of those does not fail
    loudly -- it silently answers with the neighbouring verse -- so the declared system is
    checked against the evidence rather than trusted.
    """
    shape = _observed(verses)
    scored = [(system, _fit(shape, vrs, system)) for system in systems]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


def _build(
    archive: Path,
    name: str,
    corpus: BuiltCorpus,
    *,
    declared: Mapping[str, Any] | None = None,
) -> BuiltCorpus:
    """Read every USFM file in a downloaded eBible zip.

    :param declared: eBible's own book/chapter/verse counts for this translation, when
        the table carries them. A parse that falls short of what the publisher declares
        means a book was dropped, and that is worth saying out loud.
    """
    verses: list[tuple[VerseRef, str]] = []
    unknown: set[str] = set()

    with zipfile.ZipFile(archive / name) as bundle:
        for entry in sorted(bundle.namelist()):
            if not entry.lower().endswith(".usfm"):
                continue
            content = bundle.read(entry).decode("utf-8-sig")
            for book, chapter, verse, text in parse_usfm(content):
                if not is_known(book):
                    unknown.add(book)
                    continue
                verses.append(
                    (
                        VerseRef(
                            book=book,
                            chapter=chapter,
                            verse=verse,
                            vrs=corpus.versification,
                        ),
                        text,
                    )
                )

    notes = list(corpus.notes)
    if unknown:
        notes.append(
            f"book codes outside this library's canon, not indexed: {', '.join(sorted(unknown))}"
        )
    notes.extend(_reconcile(verses, corpus, declared))
    return BuiltCorpus(
        id=corpus.id,
        label=corpus.label,
        language=corpus.language,
        versification=corpus.versification,
        verses=verses,
        notes=notes,
    )


def _reconcile(
    verses: list[tuple[VerseRef, str]],
    corpus: BuiltCorpus,
    declared: Mapping[str, Any] | None,
) -> list[str]:
    """Check the parse against what was declared, and the numbering against the text."""
    notes: list[str] = []

    if declared:
        expected = sum(part["verses"] for part in declared.values())
        # Books outside this library's canon are skipped above, so a parse can legitimately
        # come in under the declared total; coming in far under means something broke.
        if expected and len(verses) < expected * 0.9:
            notes.append(
                f"parsed {len(verses):,} verses against {expected:,} declared by eBible -- "
                f"{expected - len(verses):,} short, so a book may have been dropped"
            )

    try:
        ranking = best_fit_versification(verses, Versification.load())
    except VersificationError:  # pragma: no cover - a system failed to load
        return notes

    if not ranking:
        return notes
    best, best_score = ranking[0]
    declared_score = next((s for system, s in ranking if system == corpus.versification), 0.0)
    if best != corpus.versification and best_score - declared_score > _FIT_MARGIN:
        notes.append(
            f"numbering looks like {best!r} ({best_score:.0%} of chapters end where that "
            f"system says) rather than the declared {corpus.versification!r} "
            f"({declared_score:.0%}); verses may be misfiled"
        )
    return notes


_DRA_FILE: Final = "engDRA_usfm.zip"
_WEBC_FILE: Final = "eng-web-c_usfm.zip"
_LATVUC_FILE: Final = "latVUC_usfm.zip"
_ARBVD_FILE: Final = "arb-vd_usfm.zip"


def build_dra(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _DRA_FILE,
        BuiltCorpus(
            id="dra",
            label="Douay-Rheims 1899",
            language="en",
            versification="vul",
            verses=[],
            notes=[
                "Vulgate numbering throughout, including Esther 10:4-16:24 and Daniel "
                "13-14 for Susanna and Bel.",
            ],
        ),
    )


def build_webc(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _WEBC_FILE,
        BuiltCorpus(
            id="webc",
            label="World English Bible, Catholic Edition",
            language="en",
            versification="eng",
            verses=[],
            notes=[
                "The deuterocanon is translated from the Greek and numbered accordingly, "
                "which is what lets it answer a citation written as Sirach 24:1.",
            ],
        ),
    )


def build_latvuc(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _LATVUC_FILE,
        BuiltCorpus(
            id="latvuc",
            label="Clementine Vulgate",
            language="la",
            versification="vul",
            verses=[],
            notes=[
                "Numbered exactly as the Douay-Rheims is, which translates it: sixteen "
                "chapters of Esther, fourteen of Daniel, Susanna at Daniel 13.",
            ],
        ),
    )


def build_arbvd(archive: Path) -> Iterator[BuiltCorpus]:
    yield _build(
        archive,
        _ARBVD_FILE,
        BuiltCorpus(
            id="arbvd",
            label="Van Dyck Arabic Bible (1865)",
            language="ar",
            versification="eng",
            verses=[],
            notes=[
                "the standard Arabic Protestant Bible; positions the Arabic extension "
                "of quotes.md §11 -- Graf's corpus of Christian Arabic literature "
                "quotes toward this wording's ancestors",
            ],
        ),
    )


DRA: Final = Source(
    id="dra",
    label="Douay-Rheims 1899 American Edition",
    homepage="https://ebible.org/find/details.php?id=engDRA",
    license="Public domain.",
    terms=get("public-domain"),
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_DRA_FILE}", name=_DRA_FILE),),
    build=build_dra,
    note="English of the Vulgate, in Vulgate numbering.",
)

WEBC: Final = Source(
    id="webc",
    label="World English Bible, Catholic Edition",
    homepage="https://ebible.org/find/details.php?id=eng-web-c",
    license="Public domain.",
    terms=get("public-domain"),
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_WEBC_FILE}", name=_WEBC_FILE),),
    build=build_webc,
    note="The English deuterocanon, in Greek numbering.",
)

ARBVD: Final = Source(
    id="arbvd",
    label="Van Dyck Arabic Bible",
    homepage="https://ebible.org/find/details.php?id=arb-vd",
    license="Public domain, stated on eBible.",
    terms=get("public-domain"),
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_ARBVD_FILE}", name=_ARBVD_FILE),),
    build=build_arbvd,
    note="The 1865 Smith–Van Dyck translation, the received Arabic Protestant text.",
)

LATVUC: Final = Source(
    id="latvuc",
    label="Clementine Vulgate",
    homepage="https://ebible.org/find/details.php?id=latVUC",
    license="Public domain.",
    terms=get("public-domain"),
    attribution=None,
    files=(RemoteFile(url=f"https://ebible.org/Scriptures/{_LATVUC_FILE}", name=_LATVUC_FILE),),
    build=build_latvuc,
    note="Jerome's Latin as the Church received it, in Vulgate numbering.",
)


# -- the bulk English corpus -----------------------------------------------------------


#: Scripture *portions* rather than Bibles: editions that print selected passages for a
#: community rather than continuous text. They are excluded from the corpus because a
#: partial chapter is worse than no chapter here -- a search hit resolves to a verse the
#: edition never claimed to translate, and the structural checks in ``tests/test_witnesses``
#: read their excerpting as a versification fault.
#:
#: Membership is *measured*, not inferred from the catalogue, because eBible's declared
#: counts cannot tell a portion from a short complete text: "Barkly Bible Portions" averages
#: 26.8 verses per chapter, squarely among the complete Bibles, since its chapters are whole
#: and merely few. The tell is the share of chapters held complete -- verses 1..n with no
#: gaps -- where these four score 12%, 19%, 29% and 39% against 86% or better for every
#: other English edition.
#:
#: Note what is *not* here. ``e2t`` (Jonah alone), ``glw`` (four books) and ``oke`` (the
#: Pentateuch) are complete in every chapter they carry; they are small, not abridged, and
#: remain valid witnesses for the chapters they hold.
PORTIONS: Final[frozenset[str]] = frozenset(
    {
        "nna",  # Nyangumarta English Bible -- 12% of chapters complete, 46% of verses
        "barkly",  # Barkly Bible Portions -- 19%
        "pev",  # Plain English Version -- 29%, 80% of verses
        "aoi",  # Anindilyakwa English Bible -- 39%
    }
)


def english_table() -> list[dict[str, Any]]:
    """The vendored list of redistributable English translations, less the portions.

    Generated from eBible's ``translations.csv`` by ``tools/gen_ebible_english.py`` and
    committed, so that the sources exist without a network round trip on import.
    """
    data = resources.files("biblereference").joinpath("data", "ebible_english.json")
    loaded: list[dict[str, Any]] = json.loads(data.read_text(encoding="utf-8"))
    return [row for row in loaded if row["id"] not in PORTIONS]


def _english_builder(entry: Mapping[str, Any]) -> Any:
    """A build function closed over one table row."""
    name = f"{entry['ebible_id']}_usfm.zip"

    def build(archive: Path) -> Iterator[BuiltCorpus]:
        yield _build(
            archive,
            name,
            BuiltCorpus(
                id=str(entry["id"]),
                label=str(entry["label"]),
                language="en",
                versification=str(entry["versification"]),
                verses=[],
                notes=[],
            ),
            declared=entry["declared"],
        )

    return build


def _english_source(entry: Mapping[str, Any]) -> Source:
    name = f"{entry['ebible_id']}_usfm.zip"
    public_domain = bool(entry["public_domain"])
    return Source(
        id=str(entry["id"]),
        label=str(entry["title"]),
        homepage=f"https://ebible.org/find/details.php?id={entry['ebible_id']}",
        license="Public domain." if public_domain else str(entry["copyright"]),
        # eBible redistributes these by the holder's permission; the credit line is the
        # holder's own copyright statement, which is what a notice has to reproduce.
        #
        # The flag is what the table records, and it is the only structured thing eBible
        # publishes about terms -- so "by permission" here means exactly that and no more.
        # It is not a grant of commercial use, and `by-permission` says so rather than
        # letting fourteen copyrighted translations read as freely as the thirty-two that
        # really are public domain.
        terms=get("public-domain") if public_domain else get("by-permission"),
        attribution=None if public_domain else str(entry["copyright"]),
        files=(RemoteFile(url=f"https://ebible.org/Scriptures/{name}", name=name),),
        build=_english_builder(entry),
        note=str(entry["title"]),
        # ebible.org's robots.txt restricts only Baiduspider and publishes no crawl-delay;
        # these are the project's own bulk download files. A second between them is
        # courtesy rather than obligation.
        crawl_delay=1.0,
    )


#: Every redistributable English translation eBible publishes, less the two already
#: fetched under their own ids (``webc``, ``dra``). Built for the search index.
ENGLISH: Final[tuple[Source, ...]] = tuple(_english_source(row) for row in english_table())
