"""Reading verses out of TEI, in the three shapes the sources actually use.

This is the shared half of five corpus modules. What differs between the upstreams is
*what a file means* -- which book it is, which corpus it joins, what licence it carries --
and that stays in each module. What they agree on is how text comes out of an element, and
getting that wrong is silent, so it lives here once and is tested once.

Three shapes, and one reader each:

* **CTS/EpiDoc** -- ``<div type="textpart" subtype="chapter" n="1">`` containing
  ``subtype="verse"``. The Patristic Text Archive, First1KGreek and Perseus all use it, so
  :func:`cts_verses` covers three of the five sources.
* **``<ab>``** -- the Digital Syriac Corpus, ``<div type="chapter" n="1">`` with
  ``<ab type="verse" n="1">`` inside. :func:`ab_verses`.
* **Milestones** -- Corpus Corporum, which is TEI P4 wearing the P5 namespace:
  ``<div1>``/``<div2>`` and an empty ``<milestone unit="verse" n="1"/>``, with the verse
  text loose between two markers rather than inside anything. :func:`milestone_verses`.

**The one that will bite.** PTA's Greek carries 7,028 ``<app>`` apparatus entries, 829 in
Matthew alone, each holding a ``<lem>`` and two or three ``<rdg>`` alternatives::

    <app type="variants">
      <lem source="#WH #NIV"><w>Βόες</w> <w>ἐκ</w> <w>τῆς</w> <w>Ῥαχάβ</w></lem>
      <rdg source="#Treg">Βοὸς … Βοὸς</rdg>
      <rdg source="#RP">Βοὸζ … Βοὸζ</rdg>
    </app>

``"".join(element.itertext())`` splices all three into one verse. The result is plausible
Greek, it is the right length, and it passes every structural check this project has --
verse counts, chapter ends, the coverage walk. Nothing would catch it. So :func:`flatten`
takes the ``<lem>`` and drops every ``<rdg>``, and that is the first thing
``tests/test_tei.py`` asserts.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lxml import etree

from ..licences import Licence, from_url

__all__ = [
    "GAP",
    "TEI_NS",
    "ab_verses",
    "cts_verses",
    "flatten",
    "local",
    "milestone_verses",
    "parse_n",
    "read_licence",
]

TEI_NS: Final = "http://www.tei-c.org/ns/1.0"
XML_NS: Final = "http://www.w3.org/XML/1998/namespace"

#: Stands where the manuscript is damaged. Kept in the text rather than closed over,
#: because a lacuna silently healed is a reading this library invented.
GAP: Final = "…"

#: Editorial matter, not text. ``rdg`` is the alternative reading in an apparatus and is
#: the important one: see the module docstring.
_DROP: Final = frozenset({"note", "rdg", "head", "del", "surplus", "witDetail", "orig"})

#: Empty elements that mark a position rather than carrying words.
_EMPTY: Final = frozenset({"lb", "pb", "cb", "milestone", "gb", "space", "anchor"})

#: Elements that start a new line of text, so their words do not run into the previous
#: element's. Only these: adding a space around *inline* markup would break a word split
#: across an emphasis, which Latin printed from manuscript does constantly.
_BLOCK: Final = frozenset(
    {"p", "l", "lg", "ab", "div", "div1", "div2", "div3", "div4", "head", "item", "list"}
)

#: Marks a join with no space, so that punctuation attaches to the word before it. The
#: alternative is to strip whitespace before ``<pc>`` after the fact, which fails as soon
#: as anything else sits between them.
_JOIN: Final = "\x00"


def local(element: etree._Element) -> str:
    """An element's tag without its namespace."""
    return str(etree.QName(element).localname)


def flatten(element: etree._Element) -> str:
    """The words of one element, and only the words.

    Rules, each of which is a real file rather than a precaution:

    * ``<app>`` keeps its ``<lem>`` and drops every ``<rdg>``.
    * ``<w>`` is separated by a space, ``<pc>`` is not -- the Greek New Testament writes
      one element per word with no whitespace between them, so joining naively yields
      ``ΒίβλοςγενέσεωςἸησοῦ``.
    * ``<note>`` is dropped: Ottley's Isaiah carries 707 of them, all editorial.
    * ``<gap/>`` leaves :data:`GAP` behind.
    * ``<lb break="no"/>`` does not introduce a space, because the word continues.
    """
    parts: list[str] = []
    _walk(element, parts)
    text = "".join(parts)
    text = re.sub(rf"\s*{_JOIN}\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _walk(element: etree._Element, parts: list[str]) -> None:
    if element.text:
        parts.append(element.text)
    for child in element:
        if not isinstance(child.tag, str):  # a comment or processing instruction
            if child.tail:
                parts.append(child.tail)
            continue
        tag = local(child)
        if tag in _DROP:
            pass
        elif tag == "app":
            # The reading the editor chose. Everything else in here is what he rejected.
            for candidate in child:
                if isinstance(candidate.tag, str) and local(candidate) == "lem":
                    _walk(candidate, parts)
                    break
        elif tag == "w":
            parts.append(" ")
            _walk(child, parts)
        elif tag == "pc":
            parts.append(_JOIN)
            _walk(child, parts)
        elif tag == "gap":
            parts.append(f" {GAP} ")
        elif tag in _EMPTY:
            parts.append(_JOIN if child.get("break") == "no" else " ")
        else:
            _walk(child, parts)
        if child.tail:
            parts.append(child.tail)


def parse_n(value: str | None) -> tuple[int, str] | None:
    """A verse or chapter number and its letter, or ``None`` where it is neither.

    The grammar, measured over all 177 Patristic Text Archive files rather than assumed:

    * ``"12"`` is a plain verse.
    * ``"12a"`` through ``"12x"`` are the Greek additions to Esther and Daniel. The letter
      is a subverse, which :class:`~biblereference.refs.VerseRef` already models and
      already prints, so it survives rather than being flattened onto ``12``.
    * ``"t"`` is a superscription. It becomes verse 0, which is what
      :meth:`Versification.first_verse` and the shipped data already mean by a title.
    * ``"p"`` is Sirach's prologue, and ``"24a"``/``"30a"``/``"31a"`` are the chapters
      Greek Proverbs has and the Hebrew does not. Both return ``None``: no versification
      declares them, so importing them would put verses where nothing can cite them.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw == "t":
        return (0, "")
    match = re.fullmatch(r"(\d+)([a-z]?)", raw)
    if match is None:
        return None
    return (int(match.group(1)), match.group(2))


def read_licence(path: Path | str) -> Licence | None:
    """What the file says it is held under, where that is a licence we know.

    Read per file and never per repository, because it genuinely varies inside one: the
    Patristic Text Archive's ``pta-syc1`` is CC BY-NC over the Peshitta Old Testament and
    CC BY over the New Testament beside it, and reading one header gets the wrong answer
    for two thirds of it.
    """
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError:
        return None
    for licence in tree.iter(f"{{{TEI_NS}}}licence"):
        found = from_url(licence.get("target"))
        if found is not None:
            return found
    return None


# --------------------------------------------------------------------------------------
# The three shapes
# --------------------------------------------------------------------------------------


def _numbered(element: etree._Element) -> tuple[int, str] | None:
    return parse_n(element.get("n"))


def _chapter_of(element: etree._Element) -> int | None:
    """A chapter number, which unlike a verse number cannot be zero.

    Verse 0 is a superscription and is meaningful -- the shipped versification means
    exactly that by it. A *chapter* ``t`` is the Psalter's own title page and a chapter
    ``p`` is Sirach's prologue, and neither is a chapter of anything: ``VerseRef`` refuses
    them, rightly, and they have to be dropped here rather than at the point of use.

    Nor can a chapter carry a letter. ``parse_n`` reads ``24a`` as verse 24 subverse a,
    which is right for Esther's Greek additions and wrong here: Greek Proverbs really has
    chapters ``24a``, ``30a`` and ``31a``, and taking the number alone would pour their
    verses into chapter 24 on top of the ones already there.
    """
    number = parse_n(element.get("n"))
    if number is None or number[0] <= 0 or number[1]:
        return None
    return number[0]


def cts_verses(
    root: etree._Element | etree._ElementTree,
) -> Iterator[tuple[int, int, str, str]]:
    """``(chapter, verse, subverse, text)`` from CTS/EpiDoc textparts.

    Accepts ``type="translation"`` beside ``type="edition"`` -- the German Enoch, Ottley's
    Isaiah and the Coptic Mark are translations -- and ``subtype="section"`` beside
    ``subtype="verse"``, because one of the two Greek recensions of 1 Enoch divides itself
    into sections where the other uses verses.

    **A book of one chapter prints no chapter division at all**, so its verses hang
    directly off the edition. Obadiah, Jude, the Letter of Jeremiah, Susanna and Bel are
    all like that, and a reader that insisted on a chapter would drop every one of them
    without a word. They are chapter 1, which is how the canon and every citation of them
    already works.

    **Every verse asks which chapter is above it**, rather than every chapter gathering the
    verses beneath it, and the difference is not stylistic. Ottley's Isaiah *nests* two of
    its chapter divisions -- 23 contains 24 onwards, and 53 contains 54 onwards -- so a
    reader that descended from each chapter attributed every nested chapter's verses to the
    outer one as well: 1,309 verses out of a file holding 1,283, with Isaiah 66 sitting at
    chapter 53. One archived file of 203 is built that way, which is exactly the sort of
    thing a reader should survive rather than trust.

    It also settles the two cases that would otherwise need their own passes. A verse with
    no chapter above it is chapter 1 -- Obadiah, Jude, the Letter of Jeremiah, Susanna and
    Bel all print no chapter division, and insisting on one dropped every one of them
    without a word. And a verse under a chapter no versification declares is dropped, not
    promoted: Greek Proverbs really has chapters ``24a``, ``30a`` and ``31a``, and the
    cheaper test would sweep their verses into chapter 1 of Proverbs.
    """
    for verse in root.iter(f"{{{TEI_NS}}}div"):
        if verse.get("subtype") not in {"verse", "section"}:
            continue
        place = _numbered(verse)
        if place is None:
            continue
        enclosing = next(
            (
                ancestor
                for ancestor in verse.iterancestors(f"{{{TEI_NS}}}div")
                if ancestor.get("subtype") == "chapter"
            ),
            None,
        )
        if enclosing is None:
            number = 1
        else:
            found = _chapter_of(enclosing)
            if found is None:
                continue
            number = found
        text = flatten(verse)
        if text:
            yield (number, place[0], place[1], text)


def ab_verses(root: etree._Element | etree._ElementTree) -> Iterator[tuple[int, int, str, str]]:
    """``(chapter, verse, subverse, text)`` from ``<div type="chapter">``/``<ab>``.

    Every verse element in the Digital Syriac Corpus carries an ``n`` -- all 7,958 of them,
    counted -- so the numbers are read rather than inferred from position. That matters:
    the alternative is to call the *n*th ``<ab>`` verse *n*, and the 472 elements that are
    titles and rubrics would then shift every verse after them by one, silently.
    """
    for chapter in root.iter(f"{{{TEI_NS}}}div"):
        if chapter.get("type") != "chapter":
            continue
        number = _chapter_of(chapter)
        if number is None:
            continue
        for verse in chapter.iter(f"{{{TEI_NS}}}ab"):
            if verse.get("type") != "verse":
                continue
            place = _numbered(verse)
            if place is None:
                continue
            text = flatten(verse)
            if text:
                yield (number, place[0], place[1], text)


def milestone_verses(
    root: etree._Element | etree._ElementTree, *, chapter_tag: str = "div2"
) -> Iterator[tuple[int, int, str, str]]:
    """``(chapter, verse, subverse, text)`` where verses are marked, not contained.

    Corpus Corporum is TEI P4 wearing the P5 namespace, and its verse text is loose text
    *between* two empty markers::

        <p><milestone unit="verse" n="1"/>In principio creavit Deus caelum et terram.
           <milestone unit="verse" n="2"/>Terra autem erat inanis et vacua…</p>

    A reader looking for an element that holds a verse finds the milestones, reports every
    verse number correctly, and extracts nothing at all. So this walks the chapter in
    document order and accumulates text against whichever marker was last seen -- the same
    idea ``corpora/swete.py`` uses for word offsets, arriving from the other direction.

    A book of one chapter has no chapter division either, exactly as in
    :func:`cts_verses`: Susanna and Bel put their milestones straight into a paragraph
    under the book. Where no numbered chapter is found, the element passed in *is* chapter
    1 -- and asking that of the element rather than of the whole document is what keeps a
    caller iterating books from pouring one book's verses into another's chapter 1.
    """
    numbered: list[tuple[int, etree._Element]] = [
        (found, chapter)
        for chapter in root.iter(f"{{{TEI_NS}}}{chapter_tag}")
        if (found := _chapter_of(chapter)) is not None
    ]
    if not numbered and isinstance(root, etree._Element):
        numbered = [(1, root)]

    for number, chapter in numbered:
        current: tuple[int, str] | None = None
        parts: list[str] = []
        for element in chapter.iter():
            if not isinstance(element.tag, str):
                continue
            if local(element) == "milestone" and element.get("unit") == "verse":
                if current is not None:
                    text = re.sub(r"\s+", " ", "".join(parts)).strip()
                    if text:
                        yield (number, current[0], current[1], text)
                current, parts = parse_n(element.get("n")), []
            elif local(element) in _DROP:
                continue
            elif current is not None and element.text:
                if local(element) in _BLOCK:
                    parts.append(" ")
                parts.append(element.text)
            if current is not None and element.tail:
                parts.append(element.tail)
        if current is not None:
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if text:
                yield (number, current[0], current[1], text)
