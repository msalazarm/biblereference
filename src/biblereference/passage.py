"""Read a verse, in a stated numbering, in a stated language, and say what was done.

The primitives this composes are all older than it: :meth:`Versification.convert_range`
moves a reference between numberings, :meth:`SqliteCorpus.available` reads what a corpus
holds, and :meth:`Renderer._fetch` has done the two together correctly for as long as there
has been a renderer. What did not exist was any way to ask for them *by language*, and a
consumer holding half a million findings therefore wrote the loop itself, from outside,
guessing at the data model. Three faults came of it in one week, and they were one fault:

    a reference resolved under a numbering or in a language it was not in, silently,
    producing a confident answer about the wrong verse.

Each of the three is refused here by construction rather than by care.

**Language cannot be crossed.** Candidates are drawn only from corpora whose declared
language is the one asked for. There is no fallback list to end in the ASV, so a Greek
question cannot be answered with English -- which is what happened, for `DAN 10:11`, to 356
findings of which 275 had been confirmed. Not holding a text is a *useful* answer, and
``reason`` says which kind of not-holding it was.

**The numbering is required and never assumed.** ``vrs`` is keyword-only and has no
default. `PSA 79:5` numbered `vul` is *Domine Deus virtutum*; numbered `nvl` it is a
different psalm altogether, and nothing but the caller can know which was meant.

**What came back says what it is.** The answering corpus, its language, its numbering, and
the reference as renumbered into it -- which is the number a reader needs to check the
answer by hand. The identity case is not an exception to that: same numbering in and out
still returns a labelled reference, because an unlabelled one is read downstream as
whatever that reader's default happens to be.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from .refs import VerseRange, VerseRef, parse_reference
from .store import DataHome, SqliteCorpus, all_books
from .tags import resolve_language
from .versification import (
    UnknownVersificationError,
    VerseOutOfRangeError,
    Versification,
    VersificationError,
)

__all__ = ["PREFERRED", "PassageReader", "ResolvedPassage"]


#: Which corpus of a language answers first, where the choice is editorial rather than
#: mechanical. Consulted *within* each numbering tier -- see :meth:`PassageReader.candidates`
#: -- so a corpus that needs no conversion still outranks a preferred one that does.
#:
#: Naming a corpus here does not require this machine to hold it: unbuilt ids are skipped,
#: so the table may name more than any one library has. Corpora absent from it are not
#: excluded either, only ranked after, by verse count.
PREFERRED: Final[Mapping[str, tuple[str, ...]]] = {
    # Greek Daniel is the case that makes this table worth having. `swete-daniel` is
    # Theodotion, numbered like the Vulgate; `rahlfs-cc` is the Old Greek under the book
    # code `DAG`. They are different texts, not different editions of one, and a caller
    # who cares must say so with `corpora=` -- which is why every answer names its corpus.
    "grc": ("n1904", "swete", "swete-daniel", "rahlfs-cc", "rahlfs", "rahlfs-alt", "sblgnt", "wh"),
    "hbo": ("wlc",),
    "syc": ("peshitta-nt", "peshitta-ot", "peshitta-alt"),
    "la": ("latvuc", "novavulgata", "oldlatin-a", "oldlatin-b", "castellio"),
    "cop": ("coptic-mark",),
    "en": ("asv", "webc", "dra", "kjv", "web", "brenton"),
}

#: Why nothing came back, or in what way something did. These are separate facts and a
#: caller collapsing them into "no text" loses the difference between a gap in the library
#: and a reference that is simply wrong.
OK: Final = "ok"
PARTIAL: Final = "partial"
NO_CORPUS: Final = "no-corpus"
BOOK_NOT_HELD: Final = "book-not-held"
VERSE_NOT_HELD: Final = "verse-not-held"
OUT_OF_RANGE: Final = "out-of-range"
UNCONVERTIBLE: Final = "unconvertible"


@dataclass(frozen=True, slots=True)
class ResolvedPassage:
    """One passage as some corpus of the asked-for language actually carries it."""

    asked: VerseRange
    """What was asked, in the numbering it was asked in. Always labelled, including where
    that numbering is the corpus's own -- an unlabelled span is read downstream as whatever
    the reader's default happens to be, which for one caller was `org` and for this library
    is `eng`."""
    language: str
    """The language asked for, resolved to this library's code. Where :attr:`found`, this
    is also the answering corpus's own language: they cannot differ, because nothing else
    was ever a candidate."""
    reason: str
    """:data:`OK`, :data:`PARTIAL`, :data:`NO_CORPUS`, :data:`BOOK_NOT_HELD`,
    :data:`VERSE_NOT_HELD`, :data:`OUT_OF_RANGE` or :data:`UNCONVERTIBLE`."""
    text: str = ""
    corpus: str = ""
    """Which corpus answered. Worth recording per verdict: "the model was shown Swete" and
    "the model was shown the Nova Vulgata" are different pieces of evidence."""
    versification: str = ""
    """The answering corpus's numbering, which is often not the one asked in."""
    reference: tuple[VerseRange, ...] = ()
    """The passage as renumbered into that corpus -- the number a reader needs to check
    this by hand.

    A tuple because conversion legitimately fragments: Vulgate `Daniel 3:1-100` is three
    separate spans in the Hebrew frame, and calling that one range would be the same kind
    of tidy lie this module exists to refuse.
    """
    verses: tuple[VerseRef, ...] = ()
    """Exactly the verses read, in the answering corpus's numbering. Counting these against
    :attr:`reference` is how :attr:`partial` is decided."""

    @property
    def found(self) -> bool:
        return bool(self.text)

    @property
    def partial(self) -> bool:
        """Some verses of the range were missing from the corpus that answered.

        A partial answer is still an answer and still has text, so this is the one place
        the module can still mislead a caller who does not look. Hence a flag rather than
        a silent shortfall.
        """
        return self.reason == PARTIAL

    def __bool__(self) -> bool:
        return self.found

    def __str__(self) -> str:
        if not self.found:
            return f"<{self.asked} ({self.asked.vrs}) in {self.language}: {self.reason}>"
        where = ", ".join(str(span) for span in self.reference)
        return f"{self.corpus} {where} ({self.versification}): {self.text}"


class PassageReader:
    """Reads passages by language. Open once and reuse; it holds a connection per corpus.

    Sixty-odd read-only connections and one query for what every corpus holds, paid at
    construction. A caller resolving half a million findings must not pay that per finding,
    which is the same reason :class:`~biblereference.search.Searcher` says so too.
    """

    def __init__(self, home: DataHome, *, versification: Versification | None = None) -> None:
        self.home = home
        self.versification = versification or Versification.load()
        # Seeded from one query rather than left to sixty `SELECT DISTINCT book`s, which is
        # a quarter of a second against a fifth of one. See `store.all_books`.
        self._corpora = SqliteCorpus.load_all(home, all_books(home))

    # -- lifetime ------------------------------------------------------------------------

    def close(self) -> None:
        for corpus in self._corpora.values():
            corpus.close()

    def __enter__(self) -> PassageReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- what is on offer ----------------------------------------------------------------

    @property
    def languages(self) -> frozenset[str]:
        """The languages this machine holds any corpus in."""
        return frozenset(corpus.language for corpus in self._corpora.values())

    def candidates(self, language: str, vrs: str, *, corpora: Sequence[str] = ()) -> list[str]:
        """Which corpora will be tried, in order, for a reference numbered ``vrs``.

        Public because the order is a judgement and a caller is entitled to see it before
        trusting an answer, or to override it with ``corpora=``.

        Corpora needing **no conversion at all** come first: a text numbered as the
        reference is numbered cannot be renumbered wrongly, and that is worth more than any
        preference between editions. :data:`PREFERRED` then orders each tier, and anything
        it does not name follows by verse count -- so a corpus built tomorrow is reachable
        without editing this file.
        """
        code = resolve_language(language, self.languages)
        held = self._named(corpora) if corpora else self._corpora
        spoken = [c for c in held.values() if c.language == code]
        preferred = PREFERRED.get(code, ())

        def rank(corpus: SqliteCorpus) -> tuple[int, int, int, str]:
            named = preferred.index(corpus.id) if corpus.id in preferred else len(preferred)
            return (
                0 if corpus.versification == vrs else 1,
                named,
                -corpus.meta.verse_count,
                corpus.id,
            )

        return [corpus.id for corpus in sorted(spoken, key=rank)]

    def _named(self, corpora: Sequence[str]) -> dict[str, SqliteCorpus]:
        """The corpora a caller named, refusing any this machine does not hold.

        Silently dropping an unknown id would answer out of whatever was left, which is a
        different corpus than the one asked for and no way to tell.
        """
        unknown = [name for name in corpora if name not in self._corpora]
        if unknown:
            raise LookupError(
                f"unknown corpus/corpora: {', '.join(unknown)}. "
                f"This machine has: {', '.join(sorted(self._corpora))}"
            )
        return {name: self._corpora[name] for name in dict.fromkeys(corpora)}

    # -- the call ------------------------------------------------------------------------

    def resolve(
        self,
        reference: str | VerseRef | VerseRange,
        *,
        vrs: str,
        language: str,
        corpora: Sequence[str] = (),
        covering: bool = False,
    ) -> ResolvedPassage:
        """The verse text of ``reference``, in ``language``, or a reason why not.

        :param reference: A reference string, a :class:`VerseRef` or a :class:`VerseRange`.
            A ref or range is *relabelled* into ``vrs``, not converted: this call is being
            told what numbering the reference is written in, not asked to move it.
        :param vrs: The numbering the reference is written in. Required and never inferred.
            `PSA 79:5` under `vul` and under `nvl` are different verses, and about 42,000
            findings in one downstream corpus sat on that difference.
        :param language: This library's code, or any alias
            :func:`~biblereference.tags.resolve_language` knows -- ``lat``, ``eng``, ``he``
            and the written-out names among them. The answer is never in another language.
        :param corpora: Try only these, in this order. Anything not in ``language`` is
            ignored rather than obeyed: the guarantee holds even here.
        :param covering: Read every verse needed to carry the whole of this reference's
            text rather than the single verse it answers to. See
            :meth:`Versification.convert_all`. Off by default, as in the renderer: a
            citation names a verse, not a span.

        :raises LookupError: The language is not one this machine holds, or ``corpora``
            names something it does not have.
        :raises UnknownVersificationError: ``vrs`` is not a loaded numbering.
        :raises ReferenceParseError: The reference could not be read.

        Everything else is reported rather than raised, because everything else is a fact
        about the library rather than a fault in the question.
        """
        if vrs not in self.versification.system_names:
            raise UnknownVersificationError(
                f"unknown versification {vrs!r}; loaded: "
                f"{', '.join(self.versification.system_names)}"
            )
        code = resolve_language(language, self.languages)
        asked = self._as_range(reference, vrs)

        def outcome(reason: str) -> ResolvedPassage:
            return ResolvedPassage(asked=asked, language=code, reason=reason)

        try:
            self.versification.validate(asked)
        except VerseOutOfRangeError:
            # Almost always the caller's numbering rather than the library's gap, so it is
            # worth telling apart from a verse the library merely does not carry.
            return outcome(OUT_OF_RANGE)
        except VersificationError:
            return outcome(UNCONVERTIBLE)

        order = self.candidates(code, vrs, corpora=corpora)
        if not order:
            return outcome(NO_CORPUS)

        reason = BOOK_NOT_HELD
        best: ResolvedPassage | None = None
        for name in order:
            corpus = self._corpora[name]
            try:
                segments = self.versification.convert_range(
                    asked, corpus.versification, covering=covering
                )
            except VersificationError:
                # This corpus's numbering cannot express the reference. Another's may.
                reason = UNCONVERTIBLE if reason == BOOK_NOT_HELD else reason
                continue
            # Checked after converting, not before: Susanna is Daniel 13 in a Vulgate text,
            # so the book that has to exist is the one the conversion landed on.
            if not all(corpus.has_book(segment.book) for segment in segments):
                continue

            wanted = [ref for segment in segments for ref in self.versification.expand(segment)]
            # `available` rather than `fetch`: a range the corpus half-holds is worth
            # returning as a partial, where `fetch` would raise on the first gap. The
            # renderer wants the raise -- a citation that loses a verse misquotes -- and
            # this does not, which is the one place the two loops differ on purpose.
            got = corpus.available(wanted)
            if not got:
                reason = VERSE_NOT_HELD
                continue

            answer = ResolvedPassage(
                asked=asked,
                language=code,
                reason=OK if len(got) == len(wanted) else PARTIAL,
                text=" ".join(one.text for one in got).strip(),
                corpus=corpus.id,
                versification=corpus.versification,
                reference=tuple(segments),
                verses=tuple(one.ref for one in got),
            )
            if answer.reason == OK:
                return answer
            # A complete answer from a later corpus beats a partial one from this, so the
            # partial is kept rather than returned. A half-quoted verse is how a citation
            # comes to misrepresent, and preferring one to a whole verse elsewhere would be
            # choosing the wrong risk.
            best = best or answer

        return best or outcome(reason)

    def _as_range(self, reference: str | VerseRef | VerseRange, vrs: str) -> VerseRange:
        """The reference as a range labelled ``vrs``, whatever form it arrived in.

        A ref or range is relabelled, never converted -- ``vrs`` is being *told* to this
        call, and quietly converting a span that arrived carrying `eng` (which is what a
        `VerseRef` carries when nobody said otherwise) would invent a passage nobody asked
        for.
        """
        if isinstance(reference, str):
            return parse_reference(reference, vrs=vrs)
        if isinstance(reference, VerseRef):
            return VerseRange.single(reference.in_vrs(vrs))
        return VerseRange(reference.start.in_vrs(vrs), reference.end.in_vrs(vrs))
