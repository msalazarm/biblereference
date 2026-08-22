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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from typing import Final

from .tags import LANGUAGES, Emphasis

__all__ = ["FOLD_VERSION", "SpanNotFoundError", "apply_spans", "fold"]

#: Bumped whenever `fold` changes its output for any input. Consumers bake folded text
#: into artefacts (the patristic n-gram tables key on it) and record this constant in
#: their metadata; a model on a stale fold is silently wrong, and this is what lets
#: either side notice. Memoisation and other output-identical changes do not bump it.
#:
#: 2 -- Greek elision marks fold away in all five spacing spellings, not only the
#: combining one. See :data:`_GREEK_ELISION`. Greek folds change; every other language
#: answers exactly as it did at version 1.
#:
#: 3 -- Greek gains two scribal conventions (:data:`_GREEK_CONVENTIONS`) and sixteen more
#: *nomina sacra*, both priced against real manuscript variation rather than guessed. Greek
#: folds change; every other language answers exactly as it did at version 1.
FOLD_VERSION: Final = 8

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

#: Ethiopic punctuation. The wordspace is the load-bearing one: Ge'ez writes `ቃለ፡ በረከት፡`,
#: and without this the token is `ቃለ፡` and never meets `ቃለ` anywhere else in the corpus.
#:
#: **Deliberately the whole of what the Ge'ez fold does.** The script is a syllabary with no
#: case, and its characters are precomposed, so the lowercasing and the NFD mark-strip below
#: are both no-ops on it -- stripping punctuation is the entire rule. What is *not* done here
#: is the orthographic part: Ge'ez manuscripts confuse ሀ/ሐ/ኀ and አ/ዐ the way Greek ones
#: confuse ι/ει/η, and that is the Ethiopic analogue of the itacism tier. It wants measuring
#: against real manuscript variation before it is applied, exactly as `_ITACISM` did, and
#: until then this fold does the least it can rather than guessing.
_ETHIOPIC_PUNCTUATION: Final = {
    "፡",  # wordspace, U+1361 -- between every pair of words
    "።",  # full stop
    "፣",  # comma
    "፤",  # semicolon
    "፥",  # colon
    "፦",  # preface colon
    "፧",  # question mark
    "፨",  # paragraph separator
}

#: Ligatures NFD does not decompose. The Clementine writes *flammæ*, an anchor will not.
_LIGATURES: Final[dict[str, str]] = {"æ": "ae", "œ": "oe", "ﬁ": "fi", "ﬂ": "fl"}

#: Everything that separates one word from the next without being part of either.
#:
#: This set is not language-scoped, so adding to it changes the fold for every language at
#: once. Adding the Ethiopic marks did **not** require a `FOLD_VERSION` bump, and that is
#: measured rather than assumed: of the 1,642,720 verses held when they were added, **zero**
#: contained any of them. Nothing already indexed folds differently, so nothing needs
#: rebuilding. A future addition to this set wants the same check before it is made.
_WORD_SEPARATORS: Final = _HEBREW_PUNCTUATION | _SYRIAC_PUNCTUATION | _ETHIOPIC_PUNCTUATION

#: Latin only. The Clementine writes *Jesus*, *justitia*, *ejus*; the Nova Vulgata writes
#: *Iesus*, *iustitia*, *eius*. The letters are the same letters -- j and v are late
#: typographic distinctions of i and u -- so an anchor should find either spelling.
#: Applied only to Latin: folding v to u would turn English *have* into *haue*.
_LATIN_LETTERS: Final[dict[str, str]] = {"j": "i", "v": "u"}

#: The Clementine brackets quoted speech and canticles, often opening in one verse and
#: closing in another. An anchor will not include a stray bracket, so it folds away.
_LATIN_PUNCTUATION: Final = {"[", "]"}

#: The mark a Greek text puts where a vowel was elided -- ``μετ᾽ αὐτοῦ`` for
#: ``μετὰ αὐτοῦ`` -- in every spelling but the combining one.
#:
#: Five characters for one thing, and folding kept them. Only U+0313, which is a
#: combining mark, fell out with the accents in the NFD pass; the rest are spacing
#: characters and survived, so ``μετ᾽`` and ``μετ̓`` -- the same word, digitised by two
#: projects -- folded to different tokens and no run could cross either. U+02BC is the
#: worst of them, because Unicode calls it a *letter*, so it survived the word tokeniser
#: too and sat inside the token.
#:
#: Counted over this library's nine Greek corpora: 19,745 elision marks, of which the
#: combining one that already worked appears **once**. The broken spellings are not an
#: edge case, they are the case. Dropped rather than turned into a space, so that all six
#: spellings agree with the one that was always right -- and 99.8% of them are followed by
#: a space in the text anyway, which makes the two choices the same for all but 38.
#:
#: Greek only. An apostrophe in English is a contraction and a different thing, and
#: `fold` must keep answering for English exactly as it did.
_GREEK_ELISION: Final = {
    "᾽",  # GREEK KORONIS
    "’",  # RIGHT SINGLE QUOTATION MARK
    "᾿",  # GREEK PSILI
    "'",  # APOSTROPHE
}

#: U+02BC, which needs stripping in *every* language rather than only in Greek.
#:
#: Unicode classes it as a modifier **letter**, so unlike the marks above it survives the
#: word tokeniser as well as the fold, and sits inside the token where nothing can reach
#: it. That would not matter if both sides of a comparison folded alike -- but they do
#: not: the index folds each corpus in its own language and `scan` folds the document it
#: is given in none, because a document is scanned against a library of many languages at
#: once and has no one language to be folded in. A rule that fired only for Greek would
#: therefore strip this from the verse and leave it in the quotation, which is the same
#: mismatch pointing the other way.
#:
#: Stripping it everywhere is right on its own merits. This library holds it in exactly
#: two places -- Westcott-Hort's Greek elisions, and the Orthodox Jewish Bible's
#: transliterations -- and in both a reader means the letters on either side of it.
_MODIFIER_APOSTROPHE: Final = "ʼ"

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
#:
#: **Expanded only for a manuscript transcription, from fold 7.** A scribe contracts; an
#: editor of a printed text has already expanded, so in an edition the contraction forms never
#: appear as contractions and are free to collide with ordinary Greek. Eleven of them did here,
#: on 4,537 words, catching nothing real: ``εσται`` took ἔσται, "will be", 4,412 times and
#: returned ἐσταύρωται; ``θω`` took θῶ in *ἕως ἂν θῶ τοὺς ἐχθρούς σου*; ``υσ``/``υν`` took ὗς,
#: the pig of the dietary law; ``κω`` took Κῶ, the island of Cos; ``ιν`` took elided ἵν' and the
#: *hin* measure; ``ανουσ`` took ἄνους, "senseless"; ``ανων``/``ιηλ`` took the names Ἀνών, Ἰήλ.
#:
#: Fold 5 deleted those eleven, and fold 6 shipped with the deletion. **That was wrong, and
#: churchfathers found it by running the audit against their own corpora.** All 44 survivors
#: occur there 53,040 times, 89% inside a transcription -- and worse, the deletion split a
#: single formula: ``τοῦ κυ ἡμῶν ἰῦ χῦ`` folded to *του κυ ημων ιησου χριστου*, Christ spelled
#: out and the Lord left contracted, because ``ιυ`` and ``χυ`` survived while ``κυ`` did not.
#: A half-expanded nomen sacrum is worse than either whole answer.
#:
#: So the table is whole again and the *expansion* is conditional. This library holds printed
#: editions only, so nothing here asks for it; a corpus of transcriptions passes
#: ``transcription=True`` and gets all 55. ``tools/nomina_sacra_audit.py`` runs the test, and
#: takes an explicit key list so a *deleted* entry can still be audited -- their first count
#: came back zero because the audit could only look up keys the table still held.
#:
#: **Never audit this table against the lemma lexicon.** Its forms are folded by this very
#: rule, so it files ἔσται under ``εσταυρωται`` and reports no collision for ``εσται``. Count
#: bare corpus words.
_NOMINA_SACRA: Final[dict[str, str]] = {
    # Restored at fold 7. Ordinary Greek in a printed edition, real contractions in a
    # manuscript, where churchfathers count them 79-99.8% inside a transcription. `κυ` is the
    # one that forced this: without it `τοῦ κυ ἡμῶν ἰῦ χῦ` expanded Christ and left the Lord
    # contracted, inside one formula.
    "θυ": "θεου",
    "θω": "θεω",
    "κυ": "κυριου",
    # All four guarded by :data:`_MARK_GUARDS`, on a mark the source actually carries.
    "ιν": "ιησουν",
    "κω": "κυριω",
    "υσ": "υιοσ",
    "υν": "υιον",
    "ανων": "ανθρωπων",
    "ιηλ": "ισραηλ",
    "ανουσ": "ανθρωπουσ",
    "θσ": "θεοσ",
    "θν": "θεον",
    "κσ": "κυριοσ",
    "κν": "κυριον",
    "ισ": "ιησουσ",
    "ιυ": "ιησου",
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
    "υυ": "υιου",
    "ανοσ": "ανθρωποσ",
    "ανου": "ανθρωπου",
    "ουνοσ": "ουρανοσ",
    "ουνου": "ουρανου",
    "ουνων": "ουρανων",
    "δαδ": "δαυιδ",
    "ιλημ": "ιερουσαλημ",
    "σηρ": "σωτηρ",
    "σρσ": "σωτηροσ",
    "στσ": "σταυροσ",
    # Added 2026-08-20 from churchfathers' PTA witness sample -- every `<expan>`/`<abbr>`
    # pair attested in the source XML, 43,458 occurrences of which the table above resolved
    # 76.4%. The misses were systematic rather than random: whole cases of a word we already
    # held in other cases, which is what a table written from memory looks like beside one
    # measured against a corpus. These sixteen are ~10,000 further attested occurrences.
    "ανοι": "ανθρωποι",
    "ανοισ": "ανθρωποισ",
    "ανον": "ανθρωπον",
    "ανινα": "ανθρωπινα",
    "ανινον": "ανθρωπινον",
    "πνι": "πνευματι",
    "ουνον": "ουρανον",
    "ουνω": "ουρανω",
    "ουνοισ": "ουρανοισ",
    "κε": "κυριε",
    "στρου": "σταυρου",
    "στρον": "σταυρον",
    "σρα": "σωτηρα",
    "σριαν": "σωτηριαν",
    "πρων": "πατερων",
    # NOT `προσ -> πατροσ`, though it is attested 155 times. The contraction for *patros*
    # written with an omicron is homographic with the preposition *pros*, one of the
    # commonest words in Greek, and expanding it would corrupt every occurrence to bridge a
    # hundred and fifty. Both projects reached that independently and neither wants it.
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


def _fold(
    text: str,
    language: str | None = None,
    *,
    orthographic: bool = False,
    transcription: bool = False,
) -> _Folded:
    latin = language == "la"
    greek = language == "grc"
    out: list[str] = []
    offsets: list[int] = []
    marks: list[int] = []
    pending_space = False

    for index, character in enumerate(text):
        if character.isspace() or character in _WORD_SEPARATORS:
            pending_space = bool(out)
            continue
        if latin and character in _LATIN_PUNCTUATION:
            continue
        if character == _MODIFIER_APOSTROPHE or (greek and character in _GREEK_ELISION):
            continue

        decomposed = unicodedata.normalize("NFD", character)
        kept = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
        if not kept:
            continue
        # Read before the marks are dropped, because dropping them is the whole problem.
        # See :data:`_MARK_GUARDS`: the diacritical evidence the fold carries past its own
        # strip, and the only place it does.
        carried = 0
        for mark, bit in _CARRIED_MARKS:
            if mark in decomposed:
                carried |= bit

        kept = kept.lower().replace("ς", "σ")
        kept = "".join(_LIGATURES.get(c, c) for c in kept)
        if latin:
            kept = "".join(_LATIN_LETTERS.get(c, c) for c in kept)

        if pending_space:
            out.append(" ")
            offsets.append(index)
            marks.append(0)
            pending_space = False
        for piece in kept:
            out.append(piece)
            offsets.append(index)
            marks.append(carried)

    if greek:
        return _rewrite_greek(
            out, offsets, marks, orthographic=orthographic, transcription=transcription
        )
    return _Folded("".join(out), tuple(offsets))


#: Greek only. Two scribal conventions that are spelling rather than disagreement, so
#: folding them cannot lose a reading. Priced against churchfathers' PTA sample -- each codex
#: transcribed separately, so the differences between two witnesses are what scribes actually
#: wrote -- where they account for 3,024 and 130 of the 54,597 substitutions measured.
#:
#: **Iota adscript after omega and eta only.** A dative singular is written three ways --
#: ``τῷ``, ``τῶι``, ``τῶ`` -- and the first folds to ``τω`` already, because a subscript is a
#: combining mark and drops with the accents. The adscript is a real letter and survives, so
#: ``τωι`` and ``τω`` were two tokens for one word.
#:
#: **Long alpha is deliberately excluded.** ``ᾳ`` carries a subscript too, but folding
#: ``-αι`` to ``-α`` merges the nominative plural with the singular, which is grammar rather
#: than orthography. Restricting to omega and eta keeps the rule to datives.
#:
#: **Movable nu is deliberately excluded, and it was the largest of the three.** Classifying
#: a *pair* can see that ``ἀπέδειξε`` and ``ἀπέδειξεν`` are one word; folding a *single* word
#: cannot, and stripping a final nu after -ε or -σι merges 162 lexicon forms into other
#: lemmas -- 3,029 occurrences in the Greek scripture held here. The worst is ``μέν``, the
#: commonest particle in the language, at 1,538 occurrences, which would become ``με``, the
#: accusative of *I*. Then ``οὐδέν`` and ``μηδέν`` onto ``οὐδέ`` and ``μηδέ``, and the whole
#: -θεν adverb class (``ποθεν``, ``οπισθεν``, ``εσωθεν``) where the nu was never movable at
#: all. It would bridge 2,521 real variants and corrupt more than it bridged: the same trade
#: as ``προσ -> πατροσ``, refused above for the same reason.
#:
#: What the two kept rules cost, measured rather than assumed: 274 lexicon forms collide
#: under the iota rule and they occur **0 times** in the Greek scripture here and 21 times in
#: 24 million tokens of patristic Greek -- Homeric and dialectal forms that the corpora do
#: not contain. ``οὕτως``/``οὕτω`` collides with nothing.
_GREEK_CONVENTIONS: Final = {"ουτωσ": "ουτω"}

#: Contractions **not** expanded, even for a transcription.
#:
#: * ``εσται`` -- **settled: never expand.** churchfathers read all 705 in-manuscript
#:   occurrences and every one is the future of εἰμί (690 written ἔσται, the rest accented
#:   variants). One clause decides it without appealing to accents at all --
#:   *ἄλλος ἂν εἴη θς παρὰ τοῦτον ποῦ δὲ καὶ ἔσται ὁ κατ αὐτοὺς θς* -- where the scribe
#:   contracts θεός twice and writes ἔσται out in full in the same sentence. He is contracting
#:   nomina sacra right there and declining to contract this word.
#: * ``υσ``, ``υν``, ``κω`` -- still unread: ὗς the pig, Κῶ the island.
#: * ``ιν`` -- **the information exists and this fold destroys it.** Their transcriptions mark
#:   the difference by breathing: ἵν rough is elided ἵνα, 309 of them; ἰν smooth is Ἰησοῦν, 94,
#:   of which 78 stand in *τὸν κν ἡμῶν ἰν χν*. Breathing is a combining mark, so the NFD pass
#:   strips it before this table is consulted and both arrive as ``ιν``. Reinstating the entry
#:   as it stands would take 309 ἵνα along with the 94 -- three wrong for each right.
#:
#: Withholding ``ιν`` splits the accusative formula τὸν κν ἡμῶν ἰν χν exactly as the genitive
#: split before ``κυ`` came back. That cost is taken knowingly. The apostrophe is no escape
#: either: this library writes elision both ways, ``ἵν’`` twice and bare ``ἵν`` twice.
#:
#: **The real fix moves the rule, it does not edit the table.** The breathing that separates ἵν
#: from ἰν, and the overline that marks a nomen sacrum at all, are both combining marks -- so
#: both are gone by the time anything here looks a word up. Same shape as the diaeresis that
#: :data:`_GENUINE_IOTA` exists to work around, and as the lexicon audit that hid ``εσται``:
#: **the evidence is destroyed before the rule that needs it runs.** Consulting the table ahead
#: of the NFD pass would let the scribe's own marking decide, and would settle ``υσ``/``υν``/
#: ``κω`` by the same stroke rather than by counting.
#:
#: Not done yet, deliberately: it is a fold change, ``υσ``/``υν``/``κω`` are still unread, and
#: one bump settling all of them costs the consumer less than two settling some. Until then
#: withholding stands, as the safer default -- expanding an ordinary word corrupts text, while
#: failing to expand a contraction only costs a match.
_NOMINA_SACRA_UNDECIDED: Final[dict[str, str]] = {
    "εσται": "εσταυρωται",
}

#: The four combining marks this fold carries past its own NFD strip, as a bitmask. Everything
#: else about a diacritic is still dropped; these four are kept because a contraction and an
#: ordinary word are told apart by them and by nothing else.
_PSILI: Final = 1  #: U+0313, smooth breathing
_DASIA: Final = 2  #: U+0314, rough breathing
_PERISPOMENI: Final = 4  #: U+0342, circumflex
_YPOGEGRAMMENI: Final = 8  #: U+0345, iota subscript

_CARRIED_MARKS: Final = (
    ("\u0313", _PSILI),
    ("\u0314", _DASIA),
    ("\u0342", _PERISPOMENI),
    ("\u0345", _YPOGEGRAMMENI),
)


def _union(marks: Sequence[int]) -> int:
    """Every mark anywhere in the word, as one bitmask."""
    carried = 0
    for mark in marks:
        carried |= mark
    return carried


def _always(marks: int) -> bool:
    return True


def _smooth_breathing(marks: int) -> bool:
    """``ιν`` is two words, and the breathing is the whole of the difference.

    Elided ἵνα takes the rough breathing, ἰν for Ἰησοῦν the smooth: churchfathers count 311
    rough against 101 smooth, 78 of the latter standing in *τὸν κν ἡμῶν ἰν χν* identically
    across Ms44-Ms48. Their 40 unmarked occurrences stay unexpanded -- the scribe did not say,
    and guessing there would turn ἵνα into Ἰησοῦν.
    """
    return bool(marks & _PSILI)


def _dative_not_the_island(marks: int) -> bool:
    """``κω`` is κυρίῳ contracted, except where it is Κῶ, the island of Acts 21:1.

    The dative ending survives on the contraction as an iota subscript -- 83 written ``κῳ`` and
    8 ``κῷ`` of 349 -- exactly as the genitive's perispomeni survives on θῦ, ἰῦ, χῦ. The island
    carries a perispomeni and no subscript, which is the 4 written ``κῶ``.

    So a perispomeni alone refuses; a perispomeni with a subscript is the dative and expands.
    Without this, *τῷ ἰδίῳ λόγῳ τῷ κω ἡμῶν ἰῦ χῷ* splits in the dative exactly as the genitive
    formula split before ``κυ`` came back.

    A bare ``κω`` expands, and 9 of the 851 bare forms are line-break fragments -- see
    :func:`_not_broken_across_a_line` for the measured rate and why it is worth taking.
    """
    return not marks & _PERISPOMENI or bool(marks & _YPOGEGRAMMENI)


def _not_broken_across_a_line(marks: int) -> bool:
    """``υσ``/``υν`` are υἱός/υἱόν contracted, and the perispomeni marks what they are not.

    Two things wear those letters otherwise. ὗς, the pig of Leviticus 11:7 and 2 Peter, takes a
    rough breathing *and* a perispomeni -- zero of 645 in churchfathers' transcriptions, which is
    what one expects of Athanasius. And a word broken across a line leaves a tail behind: their
    ``ῦς`` (2) and ``ὖν`` (6) are νοῦς and οὖν split, visible in *ὁ νο ὖν ῦς διακρίνῃ*. Both are
    the same fault as the ``θυ γατέρας`` and ``κυ κλώσουσιν`` splits that cost us fold 5.

    A perispomeni refuses, which covers the pig and the fragments together.

    **A bare form still expands, and that is a measured cost rather than an assumption.**
    churchfathers read all 851 unmarked occurrences: 11 are fragments no mark can betray --
    9 of ``κω`` and 2 of ``υσ``, splitting κωφοί, κωλυόμενον, ἐπιόρκῳ, σάκκῳ and ἐλέγχους --
    against 840 genuine contractions. 1.3%, taken knowingly.

    Taken because the two errors are not alike. Expanding a *collision* replaces a word that
    was correctly there, which is how ἔσται became ἐσταύρωται 4,412 times. Expanding a
    *fragment* replaces half a word in a region already broken: `καὶ κω φοὶ` becomes
    `και κυριω φοι`, and its neighbours are garbage too, so no run of matching words can form
    around it. A spurious κυρίῳ inside a broken line is inert in a way a spurious ἐσταύρωται
    in good text is not.
    """
    return not marks & _PERISPOMENI


#: Contractions whose expansion depends on a mark the source carries. Everything not named here
#: expands whenever the text is a transcription.
_MARK_GUARDS: Final[dict[str, Callable[[int], bool]]] = {
    "ιν": _smooth_breathing,
    "κω": _dative_not_the_island,
    "υσ": _not_broken_across_a_line,
    "υν": _not_broken_across_a_line,
}

#: The vowels an adscript iota may follow. Alpha is absent on purpose -- see above.
_ADSCRIPT_AFTER: Final = frozenset("ωη")

#: Words ending ``-ωι``/``-ηι`` where the iota is a **full vowel, not an adscript**, and the
#: rule above must not fire. Discovered rather than guessed: Greek marks a separate iota with
#: a diaeresis, so every ``-ωι``/``-ηι`` type in the Greek corpora was counted against the
#: spellings that carry one on the final iota. πρωι (166 marked of 635) and ελωι (6 of 14)
#: came back marked; the other four were read in context and every one is a genuine iota:
#:
#: * ``νηι`` -- ἐν τῇ νηὶ τῶν παίδων αὐτοῦ (1KI 9:27), the dative of ναῦς.
#: * ``θεκωι``, ``αχωι``, ``ρηι`` -- transliterated Hebrew: *the Tekoite* beside Ἀναθωθι,
#:   *the Ahohite* beside Ἀσωθι, and *Rei* beside Σεμεϊ, which marks its own final iota.
#:
#: **Listed, not detected from the diaeresis at fold time.** Only 172 of the 660 tokens carry
#: the mark, so trusting it would fold πρωῐ one way and πρωι another -- a rule firing on some
#: occurrences of a word and not others, which the docstring above explains is worse than one
#: that never fires. The list fires consistently whatever the edition prints.
#:
#: Two of the six were not merely corrupted but **merged into a different word**: νηι folds
#: onto an existing νη (11 tokens) and θεκωι onto θεκω (5). That is the harm this set exists
#: to stop; the rest is a nonword key nothing else claims.
#:
#: Discovered over the scripture corpora. A Diorisis-only word with a genuine final iota would
#: still misfold, which reaches the PPMI soft backoff and nothing that gates a match; regenerate
#: with ``tools/genuine_iota.py`` when a corpus is added.
_GENUINE_IOTA: Final = frozenset({"πρωι", "ελωι", "νηι", "θεκωι", "αχωι", "ρηι"})


def _greek_word(word: str, *, transcription: bool, marks: int = 0) -> str:
    """One Greek word with its contractions expanded and its conventions folded away.

    **Applied to the word's letters, not to the whole token.** `_rewrite_greek` splits the
    folded text on spaces, so a word keeps whatever punctuation followed it -- `fold` leaves
    `αρτι·` and `δικαιοσυνην.` intact and only `_tokens` strips them, later. Matching the
    raw token would fold *οὕτως γὰρ* and miss *οὕτως,*, which is how this was first written:
    two of the three verses holding the word folded and the third did not, and the document
    frequency of `ουτω` came out 2 where the corpus has 3. A rule that fires on some
    occurrences of a word and not others is worse than one that never fires, because the
    index and the query can disagree about the same text.
    """
    core = word.rstrip("".join(_TRAILING))
    tail = word[len(core) :]
    if not core:
        return word
    # Segmented on the editorial marks, not merely trimmed at the ends: Rahlfs writes a
    # parenthesis with no spaces around it -- `πολλοί—οὕτως`, `ταῦτα—οὕτως` -- and `fold`
    # splits on spaces, so that is one word to every rule and matches none of them. The word
    # tokeniser then splits it anyway and files the unfolded half. `_SEGMENT` keeps the marks,
    # so they go back exactly where the editor put them and the offsets still point at what
    # was written.
    return (
        "".join(
            _greek_head(part, transcription=transcription, marks=marks)
            for part in _SEGMENT.split(core)
        )
        + tail
    )


def _greek_head(head: str, *, transcription: bool, marks: int = 0) -> str:
    """The rules, applied to one unbroken run of letters.

    Split out so :func:`_greek_word` can map it over the pieces of a bracketed or dashed
    token without recursing: a piece that is *only* marks re-splits into itself for ever.
    """
    # The *nomina sacra* are looked up here too, and were not before: the expansion ran on
    # the raw token, so `θς` became θεός and `θς,` stayed `θς`. Every contraction followed
    # by a comma or an interpunct -- which in a manuscript transcription is a great many of
    # them -- silently failed to expand. Found by a canary written for the new rules.
    # Only where the text is a transcription. In a printed edition the editor expanded these
    # centuries ago, so a "contraction" found here is an ordinary word wearing the same letters.
    if transcription and _MARK_GUARDS.get(head, _always)(marks):
        head = _NOMINA_SACRA.get(head, head)
    head = _GREEK_CONVENTIONS.get(head, head)
    if (
        len(head) >= 3
        and head.endswith("ι")
        and head[-2] in _ADSCRIPT_AFTER
        and head not in _GENUINE_IOTA
    ):
        head = head[:-1]
    return head


#: Punctuation `fold` leaves attached to a Greek word, which `_tokens` strips afterwards.
_TRAILING: Final = frozenset(".,;:·’'\u00b7\u0387[]()<>{}\u2014\u2013")

#: Editorial marks that may *precede* a word, stripped before the rules below look it up and
#: put back afterwards. An editor brackets a supplied reading -- Swete's ``[οὕτως].``, WH's
#: ``[Οὕτως`` -- and Rahlfs opens a speech with an em dash, ``—οὕτως``. Every rule in
#: :func:`_greek_word` is a dictionary lookup on the whole head, so a mark on either side
#: made the lookup miss; then `_WORD_RE` discarded the mark anyway and the unfolded spelling
#: went into the index with nothing to show it had happened. Exactly the fault the docstring
#: below already records for `θς,` -- found again on the other end of the word.
_EDITORIAL: Final = "[](){}<>\u2014\u2013\u00ab\u00bb"

#: The same marks as a splitter, keeping them, so each run of letters between them is looked
#: up on its own and the marks go back where they were.
_SEGMENT: Final = re.compile(f"([{re.escape(_EDITORIAL)}]+)")


def _rewrite_greek(
    out: list[str],
    offsets: list[int],
    marks: Sequence[int],
    *,
    orthographic: bool,
    transcription: bool,
) -> _Folded:
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
            expanded = _greek_word(
                word,
                transcription=transcription,
                # The union over the word, not the mark on its first letter. `ἰν` carries its
                # breathing on the iota and worked either way; `κῶ` carries its perispomeni on
                # the omega, and reading only the first character let the island expand.
                marks=_union(marks[start : start + len(word)]),
            )
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


def fold(
    text: str,
    language: str | None = None,
    *,
    orthographic: bool = False,
    transcription: bool = False,
) -> str:
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

    :raises ValueError: for a language this library does not know. It used to ignore one.
        ``fold("Jesus", "lat")`` returned *jesus* unfolded -- no *j* to *i*, no error, just
        the answer for a language nobody named -- because the branch below tests
        ``language == "la"`` against a raw string. Every other language here is a
        three-letter code and Latin is two, so ``lat`` is the first thing a reader types;
        it cost the consumer twenty minutes, and it looked exactly like a fix not working.
        :data:`~biblereference.tags.LANGUAGES` already knew ``lat``, ``latin``, ``greek``
        and the rest, and is now what decides. ``None`` still means no language-specific
        folding, which is a different thing from a language that was not understood.
    """
    return _folded(text, _language(language), orthographic, transcription)


def _language(language: str | None) -> str | None:
    """A language name resolved to the code the folding rules are written against."""
    if language is None:
        return None
    code = LANGUAGES.get(language.strip().lower())
    if code is None:
        raise ValueError(
            f"fold does not know the language {language!r}. Known: "
            f"{', '.join(sorted(set(LANGUAGES.values())))} "
            f"(aliases: {', '.join(sorted(LANGUAGES))}). Pass None for no language-specific "
            f"folding, which is not the same as a language this library cannot name."
        )
    return code


#: Entries, not bytes. A verse is a few hundred characters and a folded copy about as much,
#: so this is tens of megabytes at worst -- per worker process, which is what to multiply by
#: when sizing a server. Large enough to hold every verse of the corpora a scan touches,
#: which is the working set that matters; the words of the searched text are a rounding error
#: beside it.
_FOLD_CACHE: Final = 200_000


@lru_cache(maxsize=_FOLD_CACHE)
def _folded(text: str, language: str | None, orthographic: bool, transcription: bool) -> str:
    """The cached body of :func:`fold`.

    Positional, because ``lru_cache`` keys on the call signature and ``fold(x, "grc")`` and
    ``fold(x, language="grc")`` would otherwise be two entries for one question.
    """
    return _fold(text, language, orthographic=orthographic, transcription=transcription).text


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


def apply_spans(
    text: str,
    spans: Sequence[Emphasis],
    language: str | None = None,
    *,
    transcription: bool = False,
) -> str:
    """Wrap each span of ``text`` in its marker.

    :param language: Passed to :func:`fold`, so a Latin anchor finds either spelling.
    :param transcription: Passed to :func:`fold`. An anchor written against expanded *nomina
        sacra* only meets the text when the text is folded the same way, and the expansion is
        conditional from fold 7 -- so a caller marking up a manuscript must say so here too.
    :raises SpanNotFoundError: an anchor is missing, the end precedes the start, or two
        spans overlap.
    """
    if not spans:
        return text

    folded = _fold(text, language, transcription=transcription)
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
