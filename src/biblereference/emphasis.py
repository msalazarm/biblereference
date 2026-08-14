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

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
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

#: Syriac punctuation, which separates words rather than belonging to them. Alongside
#: these, Serto pointing is handled for free by the NFD pass below -- every vowel and
#: qushshaya mark is a combining character, so it drops with the Hebrew's.
#:
#: That is load-bearing rather than incidental. The Patristic Text Archive's Peshitta is
#: unpointed and the Digital Syriac Corpus's is fully pointed, and folding is the only
#: reason the two can be compared at all.
_SYRIAC_PUNCTUATION: Final = {
    "܀",  # end of section
    "܂",  # full stop
    "܃",  # supralinear colon
    "܄",  # sublinear colon
    "܅",
    "܆",
    "܇",
    "܈",
    "܉",
    "܊",
    "܋",
    "܌",
}

#: Ligatures NFD does not decompose. The Clementine writes *flammæ*, an anchor will not.
_LIGATURES: Final[dict[str, str]] = {"æ": "ae", "œ": "oe", "ﬁ": "fi", "ﬂ": "fl"}

#: Everything that separates one word from the next without being part of either.
_WORD_SEPARATORS: Final = _HEBREW_PUNCTUATION | _SYRIAC_PUNCTUATION

#: Latin only. The Clementine writes *Jesus*, *justitia*, *ejus*; the Nova Vulgata writes
#: *Iesus*, *iustitia*, *eius*. The letters are the same letters -- j and v are late
#: typographic distinctions of i and u -- so an anchor should find either spelling.
#: Applied only to Latin: folding v to u would turn English *have* into *haue*.
_LATIN_LETTERS: Final[dict[str, str]] = {"j": "i", "v": "u"}

#: The Clementine brackets quoted speech and canticles, often opening in one verse and
#: closing in another. An anchor will not include a stray bracket, so it folds away.
_LATIN_PUNCTUATION: Final = {"[", "]"}

#: Greek only. The *nomina sacra*: the words a scribe contracts rather than writes out,
#: marked in a manuscript with an overline that a transcription usually drops.
#:
#: Without expansion a quotation matched against a manuscript transcription fails on its
#: most frequent words, and they are exactly the words a quotation of scripture is most
#: likely to contain -- God, Lord, Jesus, Christ. Keyed on the already-folded form, so the
#: table needs no accents, no case and no final sigma of its own.
#:
#: Contractions only, not every abbreviation: these are the conventional sacred names, the
#: set a transcription of a biblical manuscript actually uses.
_NOMINA_SACRA: Final[dict[str, str]] = {
    "θσ": "θεοσ",
    "θυ": "θεου",
    "θω": "θεω",
    "θν": "θεον",
    "κσ": "κυριοσ",
    "κυ": "κυριου",
    "κω": "κυριω",
    "κν": "κυριον",
    "ισ": "ιησουσ",
    "ιυ": "ιησου",
    "ιν": "ιησουν",
    "χσ": "χριστοσ",
    "χυ": "χριστου",
    "χω": "χριστω",
    "χν": "χριστον",
    "πνα": "πνευμα",
    "πνσ": "πνευματοσ",
    "πηρ": "πατηρ",
    "πρσ": "πατροσ",
    "πρι": "πατρι",
    "πρα": "πατερα",
    "μηρ": "μητηρ",
    "μρσ": "μητροσ",
    "υσ": "υιοσ",
    "υυ": "υιου",
    "υν": "υιον",
    "ανοσ": "ανθρωποσ",
    "ανου": "ανθρωπου",
    "ανων": "ανθρωπων",
    "ουνοσ": "ουρανοσ",
    "ουνου": "ουρανου",
    "ουνων": "ουρανων",
    "δαδ": "δαυιδ",
    "ιηλ": "ισραηλ",
    "ιλημ": "ιερουσαλημ",
    "σηρ": "σωτηρ",
    "σρσ": "σωτηροσ",
    "στσ": "σταυροσ",
    "εσται": "εσταυρωται",
}

#: Greek letters and digraphs that came to be pronounced alike, so that scribes writing by
#: ear spell them interchangeably. Itacism is the single largest class of orthographic
#: variant in Greek manuscripts.
#:
#: **Opt-in**, because it collapses words that are genuinely distinct in classical Greek --
#: ὑμεῖς and ἡμεῖς, *you* and *we*, become one string. That is the right trade when matching
#: against a manuscript and the wrong one when reading an edited text. Longest first, since
#: the digraphs must be tried before their component letters.
_ITACISM: Final[tuple[tuple[str, str], ...]] = (
    ("ει", "ι"),
    ("οι", "ι"),
    ("υι", "ι"),
    ("η", "ι"),
    ("υ", "ι"),
    ("ω", "ο"),
    ("αι", "ε"),
)


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


def _fold(text: str, language: str | None = None, *, orthographic: bool = False) -> _Folded:
    latin = language == "la"
    greek = language == "grc"
    out: list[str] = []
    offsets: list[int] = []
    pending_space = False

    for index, character in enumerate(text):
        if character.isspace() or character in _WORD_SEPARATORS:
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

    if greek:
        return _rewrite_greek(out, offsets, orthographic=orthographic)
    return _Folded("".join(out), tuple(offsets))


def _rewrite_greek(out: list[str], offsets: list[int], *, orthographic: bool) -> _Folded:
    """Expand the nomina sacra, and optionally collapse itacism, a word at a time.

    The character-by-character fold above cannot do this: a contraction is a property of
    the whole word, and ``θσ`` is only Θεός because nothing else surrounds it.

    **A word that is not rewritten keeps its own offsets, character for character.** Only a
    rewritten one collapses onto the first character of the word it came from, because an
    expansion has no per-character correspondence to point at -- the four letters of θεου
    stand for the two the scribe wrote.

    Collapsing them all was the first attempt and it broke :func:`apply_spans` quietly: with
    every character of λόγος pointing at the lambda, a span ending on that word ended after
    its first letter. Emphasis is applied through this map, so an anchor that resolves to
    the wrong end marks up the wrong text and nothing raises.
    """
    text = "".join(out)
    rewritten: list[str] = []
    positions: list[int] = []

    start = 0
    for word in re.split(r"( )", text):
        if not word:
            continue
        expanded = word
        if word != " ":
            expanded = _NOMINA_SACRA.get(word, word)
            if orthographic:
                for written, spoken in _ITACISM:
                    expanded = expanded.replace(written, spoken)

        rewritten.append(expanded)
        if expanded == word:
            positions.extend(offsets[start : start + len(word)])
        else:
            # Anchored at both ends rather than collapsed onto the first character: the
            # expansion is longer than what was written, so each character beyond the
            # source's length points at its last. A span ending on an expanded contraction
            # then covers the whole of what the scribe actually wrote.
            source = offsets[start : start + len(word)] or [offsets[-1] if offsets else 0]
            positions.extend(source[min(i, len(source) - 1)] for i in range(len(expanded)))
        start += len(word)

    return _Folded("".join(rewritten), tuple(positions))


def fold(text: str, language: str | None = None, *, orthographic: bool = False) -> str:
    """The searchable form of ``text``: no accents, no points, collapsed whitespace.

    :param language: Where given, applies that language's own equivalences. ``"la"``
        treats *j* and *i* and *v* and *u* as the same letters, which they are -- the
        distinction is typographic, and the two Vulgates use opposite conventions.
        ``"grc"`` expands the *nomina sacra*, the sacred names a scribe contracts, so that
        a quotation matched against a manuscript transcription does not fail on the very
        words scripture is most likely to contain.
    :param orthographic: Greek only, and off by default. Collapses itacism -- the letters
        and digraphs that came to sound alike, which scribes writing by ear spell
        interchangeably. It is the largest class of variant in Greek manuscripts and the
        right trade when matching against one; it is the wrong trade against an edited
        text, because it makes ὑμεῖς and ἡμεῖς, *you* and *we*, one string.

    Exposed because it is also the right comparison for checking a supplied quotation and
    for telling two editions of one text apart.

    Memoised. One document scan called this 33,292 times with 8,008 distinct inputs -- the
    same verse folded 94 times, ``καὶ`` folded 203 -- because every stage that compares a
    quotation with a verse re-folds the verse from scratch. Safe because the answer depends
    on nothing but the three arguments: verse text does not change under a running process,
    and where it changes on disk the store is rebuilt and the process with it.
    """
    return _folded(text, language, orthographic)


#: Entries, not bytes. A verse is a few hundred characters and a folded copy about as much,
#: so this is tens of megabytes at worst -- per worker process, which is what to multiply by
#: when sizing a server. Large enough to hold every verse of the corpora a scan touches,
#: which is the working set that matters; the words of the searched text are a rounding error
#: beside it.
_FOLD_CACHE: Final = 200_000


@lru_cache(maxsize=_FOLD_CACHE)
def _folded(text: str, language: str | None, orthographic: bool) -> str:
    """The cached body of :func:`fold`.

    Positional, because ``lru_cache`` keys on the call signature and ``fold(x, "grc")`` and
    ``fold(x, language="grc")`` would otherwise be two entries for one question.
    """
    return _fold(text, language, orthographic=orthographic).text


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
