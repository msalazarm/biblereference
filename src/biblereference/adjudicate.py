"""Putting the mappings to a language model, at the scale of the whole corpus.

:mod:`biblereference.audit` compares a mapped verse with its neighbours and asks which
best explains the text. It is the stronger instrument and it has a hard limit: both sides
must be held in *one language*, which is true of 80,725 of the 155,578 conversions and
false of the rest. The Nova Vulgata is the extreme case -- this repository holds it only in
Latin, no other family holds Latin, and so not one of its 33,619 conversions has ever been
checked against a word of text by anything.

:mod:`biblereference.judge` reads across languages and closes that gap, under the
discipline set out in its docstring: the chat endpoint, a non-zero temperature, and above
all that only a *discriminating* pair of answers counts as evidence. This module is what
drives it over a work-list of tens of thousands rather than a handful, which needs three
things the handful did not:

**Calibration per language pair, not overall.** A run that is ninety percent Latin against
something can show 85% aggregate accuracy while Latin-against-Hebrew sits at 40%. Each pair
is measured against mappings whose answer is known and excluded on its own merits.

**Resumption.** Hours of work, unattended, over a link between two machines. Every answer
is committed as it arrives and a killed run continues rather than restarts.

**Survival.** Four servers across two machines: assume one goes away. A server that stops
answering is dropped and the run continues on the others.

Nothing here writes to the versification data. It produces evidence for a person to read.
"""

from __future__ import annotations

import itertools
import random
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from .audit import _Texts, faithful_chapters
from .judge import Judge, Judgement, Verdict, already_judged, record
from .refs import VerseRef
from .store import DataHome
from .versification import PIVOT, Versification, VersificationError

__all__ = [
    "CALIBRATION",
    "Calibration",
    "Task",
    "calibrate",
    "run_tasks",
    "witness_for",
]

#: Progress callback.
Reporter = Callable[[str], None]


def _silent(_: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class Task:
    """One verse to put to the model, and what to weigh it against.

    The control is the whole point. Where the alignment already prefers a different verse,
    that rival *is* the control and the model must choose between two live candidates --
    strictly stronger evidence than a verse picked to be wrong, because a model that cannot
    tell the mapping from its neighbour has at least been asked a real question.
    """

    source: VerseRef
    mapped: VerseRef
    control: VerseRef
    source_corpus: str
    target_corpus: str
    languages: str
    """``la-en``, ``la-hbo`` and so on. Calibration is per pair, so this rides along."""
    rival: bool = False
    """Whether the control is a competing mapping rather than an arbitrary neighbour."""


# --------------------------------------------------------------------------------------
# Choosing a witness
# --------------------------------------------------------------------------------------

#: Which corpora may speak for a system, best first, with the language each is in. Wider
#: than ``cli.COVERAGE_WITNESSES``, because a *model* does not need both sides in one
#: language and so a witness that would be useless to the deterministic check is useful
#: here.
#:
#: **The order for ``org`` is the whole soundness of the run, and getting it wrong cost a
#: night.** An earlier version put ``web`` first, for the good reason that this model reads
#: plain English better than it reads ``ojb``'s transliteration. But ``web`` is an
#: *English-tradition* corpus: wherever ``eng`` and ``org`` number differently it speaks
#: for the wrong system, and :func:`~biblereference.audit.faithful_chapters` cannot catch
#: it, because that compares verse *counts* and a swap leaves counts identical. English
#: Matthew 23 has the two woes in the opposite order from the Greek, so latvuc 23:13 --
#: which agrees with ``n1904`` exactly -- was flagged as wrong. 82 of 87 surviving flags in
#: that run rested on ``web`` speaking for ``org``.
#:
#: So: corpora that follow org's own numbering first. ``wlc`` is the Masoretic text, which
#: *is* org for the Hebrew canon; ``n1904`` is the Greek New Testament frame; ``ojb``
#: follows Hebrew numbering throughout and carries a New Testament, and is preferred over
#: ``web`` despite the transliteration because being hard to read is a lesser fault than
#: being the wrong numbering. ``web`` remains last because org's deuterocanon has no
#: witness here that follows it, and a hard-to-verify answer beats no answer -- but which
#: witness was used is recorded, so a finding that rests only on the fallback can be told
#: apart from one that does not.
WITNESSES: Mapping[str, Sequence[tuple[str, str]]] = {
    # Order is what matters here: `witness_for` takes the first that holds the verse, so
    # the Peshitta sits ahead of the English ones. That is the whole of its value. `wlc`
    # has no deuterocanon and `n1904` no Old Testament, so before this every org-side
    # comparison in Tobit, Judith, Sirach, Wisdom and Maccabees fell through to an
    # English-tradition text speaking for org -- which is the exact fault that invalidated
    # the first overnight run and had to be discovered from the inside.
    "org": (
        ("wlc", "hbo"),
        ("n1904", "grc"),
        ("peshitta-ot", "syc"),
        ("peshitta-nt", "syc"),
        ("ojb", "en"),
        ("web", "en"),
    ),
    "eng": (("web", "en"), ("kjv", "en"), ("asv", "en")),
    # Rahlfs before Swete: it is the standard critical text, and it follows what `lxx`
    # declares on 85% of chapters against Swete's 81% -- including the Psalms of Solomon,
    # where it matches on all eighteen and Swete on three.
    "lxx": (("brenton", "en"), ("rahlfs", "grc"), ("swete", "grc")),
    "vul": (("dra", "en"), ("latvuc", "la")),
    "nvl": (("novavulgata", "la"),),
    # The Elizabeth Bible, and the second registry it has to be named in. `build_work`
    # asks COVERAGE_WITNESSES which verses a same-language witness can reach, but `_task`
    # asks *this* map for the text itself -- so adding rso to the first alone sent every
    # Slavonic verse to "unreachable" and the run reported a clean 46,757-verse gap phase
    # containing none of them. Uniformly absent, no error: the day's third instance.
    "rso": (("chuelz", "chu"),),
}

#: Corpora that follow the numbering of the system they speak for, as a matter of textual
#: tradition rather than of counting. A flag raised against anything else is provisional.
PRIMARY: frozenset[str] = frozenset(
    {
        "wlc",
        "n1904",
        "ojb",
        "brenton",
        "swete",
        "rahlfs",
        "latvuc",
        "dra",
        "novavulgata",
        "web",
        "kjv",
        "asv",
        # The Peshitta is a second-century translation that follows the Hebrew's divisions,
        # not an edition arranged to somebody's numbering after the fact.
        "peshitta-ot",
        "peshitta-nt",
    }
)

#: ...except where the witness is standing in for a *different* system. ``web`` speaks for
#: ``eng`` natively and for ``org`` only as a fallback.
FALLBACK_FOR_ORG: frozenset[str] = frozenset({"web", "webc", "kjv", "asv", "brenton"})


class Witnesses:
    """Which corpora may be trusted to speak for a system, chapter by chapter.

    A witness is only usable where it numbers its verses as its system says. Restricting
    to those chapters is what keeps a comparison about the mapping rather than about the
    edition -- ``ojb`` is off from ``org`` on ten chapters, and using it blind there killed
    thirteen findings of an earlier sweep.
    """

    def __init__(self, home: DataHome, vrs: Versification) -> None:
        self._faithful = {
            (corpus, system): faithful_chapters(home, corpus, system, vrs)
            for system, pairs in WITNESSES.items()
            for corpus, _ in pairs
        }

    def for_chapter(
        self, system: str, book: str, chapter: int, *, language: str | None = None
    ) -> Iterator[tuple[str, str]]:
        """Every usable witness for this chapter, best first.

        ``language`` narrows to witnesses written in it. Calibration needs that: without
        it, an ``org`` entry is always answered by the first faithful witness -- ``wlc``,
        in Hebrew -- so a row meant to measure the model's Syriac would quietly measure
        its Hebrew instead, and the Syriac pairs would go out untested.
        """
        for corpus, found in WITNESSES.get(system, ()):
            if language is not None and found != language:
                continue
            if (book, chapter) in self._faithful[(corpus, system)]:
                yield corpus, found


def witness_for(
    witnesses: Witnesses,
    texts: _Texts,
    system: str,
    ref: VerseRef,
    *,
    language: str | None = None,
) -> tuple[str, str] | None:
    """A corpus faithful to ``system`` here that actually holds this verse.

    Every candidate is tried rather than only the best one. The two are not the same: a
    witness can number a chapter exactly as its system does and still not hold one verse of
    it -- a psalm superscription the edition prints unnumbered, a verse omitted as a later
    addition -- and stopping at the first would then answer "unreachable" for a verse three
    other witnesses carry. It matters more since ``wlc`` came first, that being a Hebrew
    text with no New Testament and no deuterocanon.
    """
    for corpus, found in witnesses.for_chapter(
        system, ref.book, int(ref.chapter), language=language
    ):
        if texts.verse(corpus, ref):
            return corpus, found
    return None


# --------------------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------------------

#: Mappings whose answer is known, as ``(source system, source ref, right target, wrong
#: target)``. Most were read verse by verse during this audit and are recorded with their
#: evidence in ``corrections.json``; the rest are identities no one disputes.
#:
#: The point is coverage of *language pairs*, not of books: the run is overwhelmingly Latin
#: against something, and an aggregate that looked fine could hide the one pair that
#: matters being no better than a coin.
#: A fifth element, where present, forces the language pair as ``source-target``.
#:
#: Without it each side is answered by its first faithful witness, which for ``org`` is
#: ``wlc`` in Hebrew and for ``lxx`` is Brenton in English -- so a row meant to measure the
#: model's Syriac or its Greek would quietly measure something else, and the pair it was
#: written for would go out untested. The pair is written the way
#: :class:`Calibration` keys it, so a row and the thing it measures cannot drift apart.
CALIBRATION: Sequence[tuple[str, str, str, str] | tuple[str, str, str, str, str]] = (
    # vul -> org, read by hand this session
    ("vul", "MAT 17:14", "MAT 17:15", "MAT 17:13"),
    ("vul", "MIC 5:11", "MIC 5:10", "MIC 5:12"),
    ("vul", "LEV 15:20", "LEV 15:19", "LEV 15:21"),
    ("vul", "REV 20:8", "REV 20:9", "REV 20:7"),
    ("vul", "1MA 1:36", "1MA 1:34", "1MA 1:37"),
    ("vul", "NUM 27:4", "NUM 27:5", "NUM 27:3"),
    ("vul", "JON 2:1", "JON 2:1", "JON 2:2"),
    ("vul", "PSA 22:1", "PSA 23:1", "PSA 23:2"),
    ("vul", "GEN 1:1", "GEN 1:1", "GEN 1:2"),
    ("vul", "ISA 53:5", "ISA 53:5", "ISA 53:6"),
    # Every pair the run can now produce and nothing did before. The Peshitta answers for
    # `org` wherever the Hebrew cannot -- which is the whole deuterocanon and the New
    # Testament -- and Rahlfs answers for `lxx` in Greek, so the pivot is read in Hebrew
    # against it. None of these three had a single calibration row until the corpora that
    # produce them arrived.
    ("vul", "GEN 1:1", "GEN 1:1", "GEN 1:2", "en-syc"),
    ("vul", "ISA 53:5", "ISA 53:5", "ISA 53:6", "en-syc"),
    ("vul", "MAT 17:14", "MAT 17:15", "MAT 17:13", "en-syc"),
    ("vul", "JON 2:1", "JON 2:1", "JON 2:2", "en-syc"),
    ("vul", "REV 20:8", "REV 20:9", "REV 20:7", "en-syc"),
    ("nvl", "GEN 1:1", "GEN 1:1", "GEN 1:2", "la-syc"),
    ("nvl", "ISA 53:5", "ISA 53:5", "ISA 53:6", "la-syc"),
    ("nvl", "JHN 3:16", "JHN 3:16", "JHN 3:17", "la-syc"),
    ("nvl", "MAT 5:4", "MAT 5:4", "MAT 5:5", "la-syc"),
    ("nvl", "EXO 20:3", "EXO 20:3", "EXO 20:4", "la-syc"),
    ("lxx", "GEN 1:1", "GEN 1:1", "GEN 1:2", "grc-hbo"),
    ("lxx", "ISA 53:5", "ISA 53:5", "ISA 53:6", "grc-hbo"),
    ("lxx", "EXO 20:3", "EXO 20:3", "EXO 20:4", "grc-hbo"),
    ("lxx", "DEU 6:4", "DEU 6:4", "DEU 6:5", "grc-hbo"),
    ("lxx", "MAL 3:22", "MAL 4:4", "MAL 4:5", "grc-hbo"),
    # The four pairs the witness tables can produce and nothing had measured, found by
    # enumerating the tables rather than by waiting for a run to skip 3,797 verses -- which
    # is what the first one did, and correctly, now that an unmeasured pair is refused.
    #
    # `en-en` and `grc-en` are the English-tradition witness answering for org, which is a
    # fallback rather than a first choice but still has to be measured before it is used.
    # `grc-syc` is Greek against the Peshitta, and `grc-grc` is Greek against Greek, which
    # only the New Testament can produce because that is where org's Greek witness reaches.
    ("eng", "GEN 1:1", "GEN 1:1", "GEN 1:2", "en-en"),
    ("eng", "ISA 53:5", "ISA 53:5", "ISA 53:6", "en-en"),
    ("eng", "MAL 4:4", "MAL 3:22", "MAL 3:23", "en-en"),
    ("eng", "JHN 3:16", "JHN 3:16", "JHN 3:17", "en-en"),
    ("eng", "NEH 7:69", "NEH 7:68", "NEH 7:69", "en-en"),
    ("lxx", "GEN 1:1", "GEN 1:1", "GEN 1:2", "grc-en"),
    ("lxx", "ISA 53:5", "ISA 53:5", "ISA 53:6", "grc-en"),
    ("lxx", "EXO 20:3", "EXO 20:3", "EXO 20:4", "grc-en"),
    ("lxx", "DEU 6:4", "DEU 6:4", "DEU 6:5", "grc-en"),
    ("lxx", "PSA 22:1", "PSA 23:1", "PSA 23:2", "grc-en"),
    ("lxx", "GEN 1:1", "GEN 1:1", "GEN 1:2", "grc-syc"),
    ("lxx", "ISA 53:5", "ISA 53:5", "ISA 53:6", "grc-syc"),
    ("lxx", "EXO 20:3", "EXO 20:3", "EXO 20:4", "grc-syc"),
    ("lxx", "DEU 6:4", "DEU 6:4", "DEU 6:5", "grc-syc"),
    ("lxx", "JOB 1:21", "JOB 1:21", "JOB 1:22", "grc-syc"),
    ("lxx", "MAL 3:22", "MAL 4:4", "MAL 4:5", "grc-grc"),
    # nvl -> org: the pair the whole run rests on, and the only one held in Latin alone
    ("nvl", "GEN 1:1", "GEN 1:1", "GEN 1:2"),
    ("nvl", "PSA 23:1", "PSA 23:1", "PSA 23:2"),
    ("nvl", "ISA 53:5", "ISA 53:5", "ISA 53:6"),
    ("nvl", "JHN 3:16", "JHN 3:16", "JHN 3:17"),
    ("nvl", "MAT 5:4", "MAT 5:4", "MAT 5:5"),
    ("nvl", "EXO 20:3", "EXO 20:3", "EXO 20:4"),
    ("nvl", "SIR 14:17", "SIR 14:16", "SIR 14:18"),
    ("nvl", "NEH 7:69", "NEH 7:68", "NEH 7:70"),
    ("nvl", "ROM 8:28", "ROM 8:28", "ROM 8:29"),
    ("nvl", "LUK 2:7", "LUK 2:7", "LUK 2:8"),
    # eng -> org
    ("eng", "GEN 1:1", "GEN 1:1", "GEN 1:2"),
    ("eng", "PSA 23:1", "PSA 23:1", "PSA 23:2"),
    ("eng", "ISA 53:6", "ISA 53:6", "ISA 53:7"),
    ("eng", "JHN 1:1", "JHN 1:1", "JHN 1:2"),
    ("eng", "MAL 4:4", "MAL 3:22", "MAL 3:23"),
    ("eng", "BAR 6:44", "LJE 1:44", "LJE 1:43"),
    ("eng", "NEH 7:69", "NEH 7:68", "NEH 7:70"),
    ("eng", "1SA 20:42", "1SA 21:1", "1SA 21:2"),
    # More of the Hebrew and Greek pairs, which the reordering makes dominant. Thin
    # calibration on the pair a run actually uses is the same failure as no calibration.
    ("vul", "GEN 22:2", "GEN 22:2", "GEN 22:3"),
    ("vul", "EXO 3:14", "EXO 3:14", "EXO 3:15"),
    ("vul", "DEU 6:4", "DEU 6:4", "DEU 6:5"),
    ("vul", "1SA 17:4", "1SA 17:4", "1SA 17:5"),
    ("vul", "JOB 1:21", "JOB 1:21", "JOB 1:22"),
    ("vul", "PRO 3:5", "PRO 3:5", "PRO 3:6"),
    ("vul", "JHN 1:1", "JHN 1:1", "JHN 1:2"),
    ("vul", "ROM 8:28", "ROM 8:28", "ROM 8:29"),
    ("nvl", "GEN 22:2", "GEN 22:2", "GEN 22:3"),
    ("nvl", "DEU 6:4", "DEU 6:4", "DEU 6:5"),
    ("nvl", "JOB 1:21", "JOB 1:21", "JOB 1:22"),
    ("nvl", "PRO 3:5", "PRO 3:5", "PRO 3:6"),
    ("nvl", "ACT 2:38", "ACT 2:38", "ACT 2:39"),
    ("nvl", "HEB 11:1", "HEB 11:1", "HEB 11:2"),
    ("eng", "GEN 22:2", "GEN 22:2", "GEN 22:3"),
    ("eng", "DEU 6:4", "DEU 6:4", "DEU 6:5"),
    ("eng", "JOB 1:21", "JOB 1:21", "JOB 1:22"),
    ("eng", "ACT 2:38", "ACT 2:38", "ACT 2:39"),
    ("eng", "MAT 5:9", "MAT 5:9", "MAT 5:10"),
    ("lxx", "GEN 22:2", "GEN 22:2", "GEN 22:3"),
    ("lxx", "DEU 6:4", "DEU 6:4", "DEU 6:5"),
    ("lxx", "JOB 1:21", "JOB 1:21", "JOB 1:22"),
    ("lxx", "PRO 3:5", "PRO 3:5", "PRO 3:6"),
    ("lxx", "ACT 2:38", "ACT 2:38", "ACT 2:39"),
    # lxx -> org
    ("lxx", "PSA 22:1", "PSA 23:1", "PSA 23:2"),
    ("lxx", "GEN 1:1", "GEN 1:1", "GEN 1:2"),
    ("lxx", "EXO 20:3", "EXO 20:3", "EXO 20:4"),
    ("lxx", "MAL 3:24", "MAL 3:22", "MAL 3:23"),
    ("lxx", "NUM 10:36", "NUM 10:34", "NUM 10:35"),
    ("lxx", "ISA 53:5", "ISA 53:5", "ISA 53:6"),
    ("lxx", "JHN 3:16", "JHN 3:16", "JHN 3:17"),
    ("lxx", "DEU 5:17", "DEU 5:18", "DEU 5:19"),
)

#: Correct answers a language pair must reach, among the answers that told us anything, to
#: be admitted. Below this the pair is excluded and the report says so, because a result
#: from an instrument that cannot read the pair is not a weak result -- it is not a result.
THRESHOLD: float = 0.80


@dataclass(slots=True)
class Calibration:
    """How well the model reads each language pair, before it is trusted with anything."""

    correct: Counter[str] = field(default_factory=Counter)
    informative: Counter[str] = field(default_factory=Counter)
    asked: Counter[str] = field(default_factory=Counter)

    def rate(self, languages: str) -> float:
        seen = self.informative[languages]
        return self.correct[languages] / seen if seen else 0.0

    def admits(self, languages: str) -> bool:
        """Whether answers in this language pair may be believed.

        An unmeasured pair is refused, not admitted. The rule used to be the other way
        round -- an untested pair meant calibration had no case for it, which was a gap in
        the calibration set rather than evidence against the model -- and that held while
        every pair a run could produce was in the set.

        Syriac broke it. A Peshitta witness produces ``syc-hbo``, ``syc-en`` and
        ``syc-grc``, none of which any calibration row could reach, and every one of them
        would have been admitted untested. A whole sweep would then have reported
        confidently on an instrument nobody had measured, which is worse than not sweeping:
        by this module's own argument, an unmeasured instrument is not a weak result but no
        result at all.
        """
        return bool(self.informative[languages]) and self.rate(languages) >= THRESHOLD

    def describe(self) -> str:
        lines = []
        for languages in sorted(self.asked):
            informative = self.informative[languages]
            share = informative / self.asked[languages] if self.asked[languages] else 0.0
            verdict = (
                "admitted"
                if self.admits(languages)
                else ("EXCLUDED -- never measured" if not informative else "EXCLUDED")
            )
            lines.append(
                f"  {languages:10} {self.correct[languages]:>3}/{informative:<3} correct "
                f"({self.rate(languages):.0%}), {share:.0%} of {self.asked[languages]} "
                f"answers informative -- {verdict}"
            )
        return "\n".join(lines)


def calibrate(
    judge: Judge,
    home: DataHome,
    vrs: Versification,
    *,
    report: Reporter = _silent,
) -> Calibration:
    """Measure the model against mappings whose answer is already known.

    A model that cannot tell Jonah 2:1 from Jonah 2:2 is not evidence about Nova Vulgata
    Sirach, and the only way to know which it is happens to be asking it first.
    """
    texts = _Texts(home)
    witnesses = Witnesses(home, vrs)
    result = Calibration()
    try:
        for row in CALIBRATION:
            system, source, right, wrong = row[:4]
            pair = row[4] if len(row) > 4 else None
            task = _calibration_task(
                witnesses, texts, vrs, system, source, right, wrong, languages=pair
            )
            if task is None and pair is not None:
                report(f"  calibration: no witness pair for {pair} at {system} {source}")
            if task is None:
                continue
            judged = judge.judge(
                task.source,
                task.mapped,
                texts.verse(task.source_corpus, task.source) or "",
                texts.verse(task.target_corpus, task.mapped) or "",
                texts.verse(task.target_corpus, task.control) or "",
            )
            result.asked[task.languages] += 1
            if judged.verdict != Verdict.UNINFORMATIVE:
                result.informative[task.languages] += 1
                result.correct[task.languages] += judged.verdict == Verdict.CONFIRMED
            report(f"  {system:4} {source:12} -> {right:12} {judged.verdict}")
    finally:
        texts.close()
    return result


def _calibration_task(
    witnesses: Witnesses,
    texts: _Texts,
    vrs: Versification,
    system: str,
    source: str,
    right: str,
    wrong: str,
    *,
    languages: str | None = None,
) -> Task | None:
    src = _parse(source, system)
    mapped = _parse(right, PIVOT)
    control = _parse(wrong, PIVOT)
    if src is None or mapped is None or control is None:
        return None
    left, _, right_language = (languages or "").partition("-")
    found = witness_for(witnesses, texts, system, src, language=left or None)
    target = witness_for(witnesses, texts, PIVOT, mapped, language=right_language or None)
    if found is None or target is None or not texts.verse(target[0], control):
        return None
    return Task(src, mapped, control, found[0], target[0], f"{found[1]}-{target[1]}")


def _parse(text: str, system: str) -> VerseRef | None:
    book, _, rest = text.partition(" ")
    chapter, _, verse = rest.partition(":")
    try:
        return VerseRef(book, int(chapter), int(verse), vrs=system)
    except (ValueError, VersificationError):
        return None


# --------------------------------------------------------------------------------------
# Running a work-list
# --------------------------------------------------------------------------------------


def run_tasks(
    tasks: Sequence[Task],
    judge: Judge,
    connection: sqlite3.Connection,
    *,
    phase: str,
    home: DataHome,
    workers: int = 16,
    report: Reporter = _silent,
    calibration: Calibration | None = None,
) -> Counter[str]:
    """Judge a work-list, resumably, and record every answer as it arrives.

    Texts are read single-threaded into a cache before the pool starts. A ``sqlite3``
    connection belongs to the thread that opened it, and pre-fetching also leaves the pool
    doing nothing but HTTP, which is the part worth parallelising.
    """
    admitted = [task for task in tasks if calibration is None or calibration.admits(task.languages)]
    if len(admitted) != len(tasks):
        report(f"  {len(tasks) - len(admitted):,} skipped: language pair failed calibration")

    done = {
        (left, *rest)
        for left in {task.source.vrs for task in admitted}
        for rest in already_judged(connection, left, f"{PIVOT}:{phase}")
    }
    pending = [
        task
        for task in admitted
        if (task.source.vrs, task.source.book, int(task.source.chapter), task.source.verse)
        not in done
    ]
    report(f"  {len(pending):,} to judge; {len(admitted) - len(pending):,} already done")
    if not pending:
        return Counter()

    texts = _Texts(home)
    cache: dict[tuple[str, str], str] = {}
    try:
        for task in pending:
            for corpus, ref in (
                (task.source_corpus, task.source),
                (task.target_corpus, task.mapped),
                (task.target_corpus, task.control),
            ):
                key = (corpus, str(ref))
                if key not in cache:
                    cache[key] = texts.verse(corpus, ref) or ""
    finally:
        texts.close()

    counts: Counter[str] = Counter()
    started = time.time()
    lock = _Progress(len(pending), report)

    def judge_one(task: Task) -> tuple[Task, Judgement] | None:
        try:
            judged = judge.judge(
                task.source,
                task.mapped,
                cache[(task.source_corpus, str(task.source))],
                cache[(task.target_corpus, str(task.mapped))],
                cache[(task.target_corpus, str(task.control))],
            )
        except Exception:
            # A server that went away mid-answer. The verse stays unjudged and a later run
            # picks it up; losing hours of work to one dropped connection would not.
            return None
        return task, judged

    # as_completed, not pool.map. map yields in submission order, so one request that
    # hangs stops every commit behind it however many workers are still finishing -- a run
    # went eight minutes without writing a row while its threads worked, because a single
    # early answer never came back. Committing as answers arrive means a stuck request
    # costs that verse and nothing else.
    #
    # Submitted in bounded waves rather than all at once, so forty-five thousand futures
    # are not built up front.
    with ThreadPoolExecutor(workers) as pool:
        queue = iter(pending)
        pending_futures = {
            pool.submit(judge_one, task) for task in itertools.islice(queue, workers * 4)
        }
        while pending_futures:
            settled, pending_futures = wait(pending_futures, return_when=FIRST_COMPLETED)
            for future in settled:
                lock.tick()
                outcome = future.result()
                if outcome is None:
                    counts["failed"] += 1
                    continue
                task, judged = outcome
                counts[judged.verdict] += 1
                record(connection, task.source.vrs, f"{PIVOT}:{phase}", judged)
                _record_evidence(connection, phase, task)
                connection.commit()
            pending_futures |= {
                pool.submit(judge_one, task) for task in itertools.islice(queue, len(settled))
            }

    elapsed = time.time() - started
    report(
        f"  {sum(counts.values()):,} judged in {elapsed / 60:.1f} min "
        f"({sum(counts.values()) / max(elapsed, 1):.1f}/s): "
        + ", ".join(f"{name} {count:,}" for name, count in sorted(counts.items()))
    )
    return counts


_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    phase    TEXT NOT NULL,
    system   TEXT NOT NULL,
    book     TEXT NOT NULL,
    chapter  INTEGER NOT NULL,
    verse    INTEGER NOT NULL,
    source_corpus TEXT NOT NULL,
    target_corpus TEXT NOT NULL,
    languages     TEXT NOT NULL,
    rival    INTEGER NOT NULL,
    fallback INTEGER NOT NULL,
    PRIMARY KEY (phase, system, book, chapter, verse)
) WITHOUT ROWID;
"""


def _record_evidence(connection: sqlite3.Connection, phase: str, task: Task) -> None:
    """Which corpora backed this answer, so a finding can be weighed rather than counted.

    A flag raised where ``org`` was spoken for by an English-tradition corpus is worth less
    than one raised against the Masoretic text, and the only way to tell them apart later
    is to write it down at the time.
    """
    connection.execute(_EVIDENCE)
    connection.execute(
        "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            phase,
            task.source.vrs,
            task.source.book,
            int(task.source.chapter),
            task.source.verse,
            task.source_corpus,
            task.target_corpus,
            task.languages,
            int(task.rival),
            int(task.target_corpus in FALLBACK_FOR_ORG),
        ),
    )


class _Progress:
    """A line every few thousand, so an overnight log is readable rather than a flood."""

    def __init__(self, total: int, report: Reporter, every: int = 2000) -> None:
        self._total, self._report, self._every = total, report, every
        self._seen = 0
        self._started = time.time()

    def tick(self) -> None:
        self._seen += 1
        if self._seen % self._every and self._seen != self._total:
            return
        elapsed = time.time() - self._started
        rate = self._seen / max(elapsed, 1e-6)
        left = (self._total - self._seen) / rate if rate else 0
        self._report(
            f"    {self._seen:,}/{self._total:,} ({self._seen / self._total:.0%}) "
            f"{rate:.1f}/s, {left / 60:.0f} min left"
        )


def neighbour(vrs: Versification, ref: VerseRef) -> VerseRef | None:
    """The verse next door, for use as a control where no rival mapping competes.

    Prefers the one after. A verse whose neighbour does not exist -- the last of a chapter
    -- takes the one before instead, and a one-verse chapter has no control at all and is
    therefore not judgeable.
    """
    for step in (1, -1):
        candidate = VerseRef(ref.book, ref.chapter, ref.verse + step, vrs=ref.vrs)
        if candidate.verse < 1:
            continue
        try:
            if candidate.verse <= vrs.max_verse(ref.vrs, ref.book, int(ref.chapter)):
                return candidate
        except VersificationError:
            continue
    return None


def shuffled(tasks: list[Task], seed: int = 0) -> list[Task]:
    """Work in a scattered order, so an interrupted run leaves an unbiased sample rather
    than everything up to Leviticus."""
    random.Random(seed).shuffle(tasks)
    return tasks


def verdicts_for(
    connection: sqlite3.Connection, phase: str
) -> Iterator[tuple[str, str, int, int, str, int, int, str]]:
    """Every answer from one phase, for the report."""
    yield from connection.execute(
        "SELECT left_family, book, chapter, verse, mapped_book, mapped_chapter, "
        "mapped_verse, verdict FROM judgement WHERE right_family = ? "
        "ORDER BY left_family, book, chapter, verse",
        (f"{PIVOT}:{phase}",),
    )


# --------------------------------------------------------------------------------------
# Work-lists
# --------------------------------------------------------------------------------------


def _task(
    witnesses: Witnesses,
    texts: _Texts,
    source: VerseRef,
    mapped: VerseRef,
    control: VerseRef,
    *,
    rival: bool,
) -> Task | None:
    """A judgeable task, or ``None`` where no witness holds one of the three verses."""
    found = witness_for(witnesses, texts, source.vrs, source)
    target = witness_for(witnesses, texts, PIVOT, mapped)
    if found is None or target is None or not texts.verse(target[0], control):
        return None
    return Task(
        source, mapped, control, found[0], target[0], f"{found[1]}-{target[1]}", rival=rival
    )


def build_work(
    home: DataHome,
    vrs: Versification,
    *,
    systems: Sequence[str] = ("eng", "lxx", "vul", "nvl", "rso"),
    report: Reporter = _silent,
) -> dict[str, list[Task]]:
    """Every verse worth putting to the model, sorted into the three phases.

    One walk of all 155,578 conversions rather than three, because the walk is the
    expensive part and each verse belongs to exactly one phase: either a deterministic
    witness already contradicted it, or one confirmed it, or none could reach it.
    """
    from .audit import _each_conversion, _ratio, _tokens
    from .cli import COVERAGE_WITNESSES

    strict = {
        (corpus, system): faithful_chapters(home, corpus, system, vrs)
        for system, pairs in COVERAGE_WITNESSES.items()
        for corpus, _ in pairs
    }

    def same_language(system: str, ref: VerseRef, language: str | None) -> tuple[str, str] | None:
        for corpus, spoken in COVERAGE_WITNESSES.get(system, ()):
            if language and spoken != language:
                continue
            if (ref.book, int(ref.chapter)) in strict[(corpus, system)]:
                return corpus, spoken
        return None

    witnesses = Witnesses(home, vrs)
    texts = _Texts(home)
    work: dict[str, list[Task]] = {"suspicions": [], "gap": [], "confirmed": []}
    unreachable: Counter[str] = Counter()
    try:
        for system in systems:
            counts = dict.fromkeys(
                ("total", "refused", "ghost", "confirmed", "contradicted", "weak", "unwitnessed"), 0
            )
            for ref, target in _each_conversion(vrs, system, counts, []):
                near = neighbour(vrs, target)
                if near is None:
                    continue

                # Which phase: what did the deterministic instrument manage to say here?
                source_side = same_language(system, ref, None)
                other_side = same_language(PIVOT, target, source_side[1]) if source_side else None
                here = there = None
                if source_side and other_side:
                    here = texts.verse(source_side[0], ref)
                    there = texts.verse(other_side[0], target)

                if here and there and source_side and other_side:
                    corpus, language = other_side
                    tokens = _tokens(here, source_side[1])
                    score = _ratio(tokens, _tokens(there, language))
                    rival = _best_rival(texts, corpus, target, tokens, language, score)
                    phase, control, is_rival = (
                        ("suspicions", rival, True) if rival else ("confirmed", near, False)
                    )
                else:
                    phase, control, is_rival = "gap", near, False

                built = _task(witnesses, texts, ref, target, control, rival=is_rival)
                if built is None:
                    unreachable[f"{system} {ref.book}"] += 1
                    continue
                work[phase].append(built)
    finally:
        texts.close()

    for phase, tasks in work.items():
        report(f"  {phase:12} {len(tasks):>7,}")
    report(f"  {'unreachable':12} {sum(unreachable.values()):>7,} (no witness holds one side)")
    work["unreachable"] = []  # placeholder so callers can see the key exists
    _UNREACHABLE.update(unreachable)
    return work


#: Where the walk found no witness at all, kept so the report can name it by book rather
#: than round it into a percentage. A missing corpus, not a missing analysis.
_UNREACHABLE: Counter[str] = Counter()


def _best_rival(
    texts: _Texts,
    corpus: str,
    target: VerseRef,
    tokens: Sequence[str],
    language: str,
    score: float,
) -> VerseRef | None:
    """The neighbouring verse that explains the source better than the mapping does.

    ``None`` where the mapping wins, which is the ordinary case. Where one exists it is a
    live competitor rather than a verse picked to be wrong, and putting the two to the
    model is a sharper question than asking about either alone.
    """
    from .audit import MARGIN, _ratio, _tokens

    best: VerseRef | None = None
    best_score = score + MARGIN
    for offset in OFFSETS_NONZERO:
        if target.verse + offset < 1:
            # Verse 0 is a psalm superscription and negative is nothing at all. Building
            # the reference first would raise rather than skip.
            continue
        candidate = VerseRef(target.book, target.chapter, target.verse + offset, vrs=target.vrs)
        nearby = texts.verse(corpus, candidate)
        if not nearby:
            continue
        rival_score = _ratio(tokens, _tokens(nearby, language))
        if rival_score > best_score:
            best, best_score = candidate, rival_score
    return best


OFFSETS_NONZERO: Sequence[int] = (-2, -1, 1, 2)
