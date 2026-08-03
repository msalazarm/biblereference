"""Pulling verse text out of USFM.

Parsing USFM properly is a large job. Extracting the words of a verse is not, and that is
all this does: take everything after a ``\\v`` marker until the next verse or chapter,
drop the formatting markers, and drop footnotes and cross-references entirely -- they are
an edition's apparatus, not its text.

The one subtlety is word-level markup. USFM 3 writes ``\\w And|strong="H6032"\\w*``, so
stripping markers alone would leave the lemma data sitting in the middle of the sentence.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Final

__all__ = ["parse_usfm"]

_ID_RE: Final = re.compile(r"^\\id\s+(?P<book>\w+)", re.MULTILINE)
_CHAPTER_RE: Final = re.compile(r"^\\c\s+(?P<chapter>\d+)", re.MULTILINE)
_VERSE_RE: Final = re.compile(r"^\\v\s+(?P<verse>\d+)(?:[-–]\d+)?\s*", re.MULTILINE)

#: Markers whose whole contents are apparatus rather than text.
_ENCLOSED_RE: Final = re.compile(r"\\(f|fe|x|fig)\b.*?\\\1\*", re.DOTALL)
#: Word-level markup carries lemma data after a pipe. Keep the word, drop the attributes.
_WORD_RE: Final = re.compile(r"\\\+?w\s+([^\\|]*?)(?:\|[^\\]*?)?\\\+?w\*")
#: Everything from a heading or reference marker to the end of its line.
_HEADING_RE: Final = re.compile(
    r"^\\(?:h|toc\d?|mt\d?|ms\d?|s\d?|r|d|sp|is\d?|cl|cp|rem|ide|usfm)\b.*$", re.MULTILINE
)
#: Any remaining marker, whose wrapped text is worth keeping: ``\add supplied\add*``.
_MARKER_RE: Final = re.compile(r"\\\+?(\w+)\*?")


def clean(fragment: str) -> str:
    """Reduce a USFM fragment to its words."""
    fragment = _ENCLOSED_RE.sub(" ", fragment)
    fragment = _HEADING_RE.sub(" ", fragment)
    fragment = _WORD_RE.sub(r"\1", fragment)
    fragment = _MARKER_RE.sub(" ", fragment)
    # Removing markers leaves gaps where punctuation used to sit against its word.
    fragment = re.sub(r"\s+([,;:.!?’”)\]])", r"\1", fragment)
    fragment = re.sub(r"([(“‘\[])\s+", r"\1", fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def parse_usfm(content: str) -> Iterator[tuple[str, int, int, str]]:
    """Yield ``(book, chapter, verse, text)`` from one USFM file."""
    id_match = _ID_RE.search(content)
    if not id_match:
        return
    book = id_match["book"].upper()

    chapters = list(_CHAPTER_RE.finditer(content))
    for index, chapter_match in enumerate(chapters):
        chapter = int(chapter_match["chapter"])
        end = chapters[index + 1].start() if index + 1 < len(chapters) else len(content)
        body = content[chapter_match.end() : end]

        verses = list(_VERSE_RE.finditer(body))
        for position, verse_match in enumerate(verses):
            stop = verses[position + 1].start() if position + 1 < len(verses) else len(body)
            text = clean(body[verse_match.end() : stop])
            if text:
                yield book, chapter, int(verse_match["verse"]), text
