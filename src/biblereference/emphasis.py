"""Marking up a span of a quoted verse.

A span is given by two anchors -- ``"twelve years .. festival"`` -- and everything from
the first to the second, inclusive, is wrapped in bold or italic.

Anchors are matched against a *folded* copy of the verse: accents, breathings, iota
subscripts, niqqud and cantillation all removed, whitespace collapsed, case flattened,
final sigma normalised. So an anchor can be typed as ``δωδεκα`` and still find δώδεκα,
and unpointed Hebrew finds the pointed text. The fold keeps a map back to the original
offsets, so what gets emitted is the accented text, untouched apart from the markers.

A span that cannot be found raises. An emphasis that quietly failed to apply would be a
claim about the source that the output does not support.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from .tags import Emphasis

__all__ = ["SpanNotFoundError", "apply_spans", "fold"]

_MARKERS: Final[dict[str, str]] = {"bold": "**", "italic": "*"}

#: Hebrew punctuation that joins or ends words. An anchor is unlikely to include them,
#: so they fold to a space rather than being kept.
_HEBREW_PUNCTUATION: Final = {
    "־",  # maqqef, the hyphen joining short words
    "׀",  # paseq
    "׃",  # sof pasuq, the full stop
    "׆",  # nun hafukha
}

#: Ligatures NFD does not decompose. The Clementine writes *flammæ*, an anchor will not.
_LIGATURES: Final[dict[str, str]] = {"æ": "ae", "œ": "oe", "ﬁ": "fi", "ﬂ": "fl"}

#: Latin only. The Clementine writes *Jesus*, *justitia*, *ejus*; the Nova Vulgata writes
#: *Iesus*, *iustitia*, *eius*. The letters are the same letters -- j and v are late
#: typographic distinctions of i and u -- so an anchor should find either spelling.
#: Applied only to Latin: folding v to u would turn English *have* into *haue*.
_LATIN_LETTERS: Final[dict[str, str]] = {"j": "i", "v": "u"}

#: The Clementine brackets quoted speech and canticles, often opening in one verse and
#: closing in another. An anchor will not include a stray bracket, so it folds away.
_LATIN_PUNCTUATION: Final = {"[", "]"}


class SpanNotFoundError(ValueError):
    """An emphasis span's anchors do not appear in the text, or appear out of order."""

    def __init__(self, message: str, text: str) -> None:
        self.text = text
        super().__init__(f"{message}\n  in: {text}")


@dataclass(frozen=True, slots=True)
class _Folded:
    """A searchable copy of a string, with a map back to the original."""

    text: str
    offsets: tuple[int, ...]
    """``offsets[i]`` is the index in the original of the character that produced
    ``text[i]``."""


def _fold(text: str, language: str | None = None) -> _Folded:
    latin = language == "la"
    out: list[str] = []
    offsets: list[int] = []
    pending_space = False

    for index, character in enumerate(text):
        if character.isspace() or character in _HEBREW_PUNCTUATION:
            pending_space = bool(out)
            continue
        if latin and character in _LATIN_PUNCTUATION:
            continue

        decomposed = unicodedata.normalize("NFD", character)
        kept = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
        if not kept:
            continue

        kept = kept.lower().replace("ς", "σ")
        kept = "".join(_LIGATURES.get(c, c) for c in kept)
        if latin:
            kept = "".join(_LATIN_LETTERS.get(c, c) for c in kept)

        if pending_space:
            out.append(" ")
            offsets.append(index)
            pending_space = False
        for piece in kept:
            out.append(piece)
            offsets.append(index)

    return _Folded("".join(out), tuple(offsets))


def fold(text: str, language: str | None = None) -> str:
    """The searchable form of ``text``: no accents, no points, collapsed whitespace.

    :param language: Where given, applies that language's own equivalences. ``"la"``
        treats *j* and *i* and *v* and *u* as the same letters, which they are -- the
        distinction is typographic, and the two Vulgates use opposite conventions.

    Exposed because it is also the right comparison for checking a supplied quotation and
    for telling two editions of one text apart.
    """
    return _fold(text, language).text


def _after_cluster(text: str, index: int) -> int:
    """The offset just past the character at ``index`` and any marks attached to it.

    A Hebrew letter carries its vowel points and cantillation as following combining
    characters, and a closing marker placed between them would split the letter from its
    pointing.
    """
    end = index + 1
    while end < len(text) and unicodedata.category(text[end]) == "Mn":
        end += 1
    return end


def apply_spans(text: str, spans: Sequence[Emphasis], language: str | None = None) -> str:
    """Wrap each span of ``text`` in its marker.

    :param language: Passed to :func:`fold`, so a Latin anchor finds either spelling.
    :raises SpanNotFoundError: an anchor is missing, the end precedes the start, or two
        spans overlap.
    """
    if not spans:
        return text

    folded = _fold(text, language)
    located: list[tuple[int, int, str]] = []

    for span in spans:
        start_anchor = fold(span.start, language)
        end_anchor = fold(span.end, language)
        if not start_anchor or not end_anchor:
            raise SpanNotFoundError(f"emphasis anchor {span.start!r} is empty", text)

        begin = folded.text.find(start_anchor)
        if begin < 0:
            raise SpanNotFoundError(f"could not find {span.start!r}", text)

        finish = folded.text.find(end_anchor, begin)
        if finish < 0:
            raise SpanNotFoundError(f"found {span.start!r} but not {span.end!r} after it", text)
        finish += len(end_anchor)

        marker = _MARKERS.get(span.style)
        if marker is None:
            raise SpanNotFoundError(f"unknown emphasis style {span.style!r}", text)

        located.append(
            (
                folded.offsets[begin],
                _after_cluster(text, folded.offsets[finish - 1]),
                marker,
            )
        )

    located.sort()
    for (_, first_end, _), (second_start, _, _) in pairwise(located):
        if second_start < first_end:
            raise SpanNotFoundError("emphasis spans overlap", text)

    # Right to left, so each insertion leaves the earlier offsets valid.
    out = text
    for start, end, marker in reversed(located):
        out = f"{out[:start]}{marker}{out[start:end]}{marker}{out[end:]}"
    return out
