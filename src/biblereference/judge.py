"""A second opinion on the mappings, from a local language model.

:mod:`biblereference.audit` measures whether the mapped verse resembles its counterpart
more than the neighbours do. That works wherever two families both hold a text in one
language, which is seven of the ten pairs. It cannot reach the other three, all of which
involve the Nova Vulgata: this repository has it only in Latin, and no other family holds
Latin. Those are also, awkwardly, the mappings generated here rather than vendored, so
they are the least independently checked thing in the project.

A model reads across languages, which is exactly the gap. It is asked one question, in a
grammar that admits one of two answers, so nothing has to be parsed out of prose.

**The control probe is what makes an answer mean anything.** A model inclined to agree
will say YES to every pair put in front of it and hand back a clean bill of health for a
corpus full of errors -- which is worse than not asking, because it looks like evidence.
So every verse is asked twice: once about the mapping, and once about a verse deliberately
next door. Only when the model says YES to the first and NO to the second has it
demonstrated it can tell them apart, and only then does its verdict count. Everything else
is recorded as uninformative, and the share of uninformative answers is reported at the top
of the results rather than buried under them.

**How it is asked was calibrated, not chosen.** Measured against labelled pairs built from
mappings already verified by hand:

======================================================  ==========
positive prompt, best-of-three, temp 0.7, distinct seeds  96--99%
inverse prompt alone ("are these DIFFERENT verses?")      36--78%
the two framings *in agreement*                           98.4--100%
======================================================  ==========

Three things follow, and each of them was a mistake first:

* **The chat endpoint, not ``/completion``.** An instruction-tuned model handed a raw
  completion prompt answered NO to almost everything, including pairs that are
  unquestionably right. An entire earlier dismissal of this approach rested on that and was
  wrong.
* **Temperature 0.7 with distinct seeds.** At temperature 0 the three votes of a best-of-three
  are the same computation three times, and the vote is theatre.
* **The inverse framing is a certificate, never a classifier.** Alone it is barely better
  than chance; used only to confirm a rejection the positive prompt already made, the pair
  agrees at 98.4% or above. So it can veto a flag and can never raise one.

Nothing here writes to the versification data. It produces evidence for a person to read.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .refs import VerseRef

__all__ = [
    "BIG",
    "DEFAULT_SERVERS",
    "DEFAULT_TEMPERATURE",
    "GRAMMAR",
    "SMALL",
    "Judge",
    "Judgement",
    "Verdict",
    "open_judgements",
    "tier",
]

#: The whole grammar. Two tokens, so the answer needs no parsing and cannot wander. Passed
#: where the server accepts it; the answer is also read defensively, because the calibration
#: above was measured without it and must not depend on it.
GRAMMAR: Final = 'root ::= "YES" | "NO"'

#: The two **gemma4 26b** endpoints, one per box: this machine's RTX 3090 and the remote's.
#: Both serve the same build -- ``gemma-4-26B-A4B-it-qat-UD-Q4_K_XL`` -- which is what makes
#: pooling them legitimate: a calibration measured across the pair describes one instrument
#: sampled twice, not two averaged. The weights are shared across a server's slots, so
#: concurrency costs no VRAM.
#:
#: **Neither ``:8081`` is here, and both boxes now run one.** They serve gemma4 E4B, and
#: :func:`~biblereference.adjudicate.calibrate` measures the *pool* rather than each server
#: -- it round-robins through :meth:`Judge.judge` like any other question -- so mixing the
#: tiers would average two instruments under one calibration and a pass would describe
#: neither. Prefer :meth:`Judge.available` with an explicit ``needs=BIG`` over trusting this
#: tuple: a default is a guess about the fleet, and the fleet changed twice on 2026-08-19.
DEFAULT_SERVERS: Final = ("http://127.0.0.1:8080", "http://10.0.0.182:8080")

#: Sampling temperature. Not zero: see the module docstring -- at zero the votes of a
#: best-of-three are one computation repeated, and the disagreement that makes a vote worth
#: taking can never occur.
DEFAULT_TEMPERATURE: Final = 0.7

#: The two model tiers the fleet runs, named exactly as ``churchfathers.adjudicate`` names
#: them so the two projects can hand each other a *requirement* rather than an address. An
#: address list goes stale -- ``100.98.85.58`` did, in ten files across two repositories --
#: and a tier does not.
#:
#: **The requirement has to be declared because getting it wrong is silent.** A run that
#: needs the large model and is handed the small one does not fail: it answers, less
#: decisively, and the verdicts it writes are the same shape as good ones. Measured on
#: 2026-08-19 over the 96 calibration rows, ``e4b`` was right every time it committed but
#: informative on 82% of rows against ``26b``'s 89-91% -- and on Church Slavonic, on one row
#: of three against three of three. Nothing downstream can tell a thin verdict from a
#: confident one, so the caller says what it needs and :meth:`Judge.available` refuses
#: rather than quietly running under strength.
BIG: Final = "26b"
SMALL: Final = "e4b"


def tier(model: str) -> str:
    """Which tier a model name belongs to, by the part of the name that states its size.

    Read off the name the server reports rather than the port it answers on: ``:8081`` is
    the small model on both boxes today and that is a convention, not a guarantee.
    """
    name = str(model).lower()
    if "26b" in name:
        return BIG
    if "e4b" in name or "e2b" in name:
        return SMALL
    return ""


_POSITIVE_SYSTEM: Final = (
    "You compare Bible verses. Two verses may be in different languages or translations "
    "and still be the same verse of scripture. Judge whether they render the SAME verse."
)

#: The inverse framing. Note that it does not merely negate the question -- it *states the
#: premise* that editions divide the text differently, which is what stops the model
#: agreeing out of politeness. Used only to confirm a rejection.
_INVERSE_SYSTEM: Final = (
    "You compare Bible verses from different editions. Editions divide the text "
    "differently, so a verse in one often corresponds to a DIFFERENT verse in another. "
    "Judge whether these two are different verses of scripture."
)

_POSITIVE_QUESTION: Final = (
    "Verse A: {left}\n\nVerse B: {right}\n\n"
    "Are these the SAME verse of scripture? Answer only YES or NO."
)

_INVERSE_QUESTION: Final = (
    "Verse A: {left}\n\nVerse B: {right}\n\n"
    "Are these DIFFERENT verses of scripture? Answer only YES or NO."
)


class Verdict:
    """What one verse's pair of probes established."""

    CONFIRMED: Final = "confirmed"
    """YES to the mapping, NO to its neighbour: the model can tell them apart and agrees."""
    CONTRADICTED: Final = "contradicted"
    """NO to the mapping and YES to its neighbour. The model can tell them apart and
    prefers the other one, which is the only shape of answer that is evidence against a
    mapping."""
    UNINFORMATIVE: Final = "uninformative"
    """YES to both, or NO to both. Either way the model has not distinguished the mapping
    from a verse known to be wrong, so its opinion here is not evidence."""


@dataclass(frozen=True, slots=True)
class Judgement:
    """One verse, judged."""

    source: VerseRef
    mapped: VerseRef
    mapping_answer: bool
    control_answer: bool
    """The model's answer for a verse deliberately next door. Should be NO."""

    @property
    def verdict(self) -> str:
        """Only a discriminating answer counts, in either direction.

        Treating a flat NO to both as a contradiction was this module's own first mistake,
        and it inflated the contradiction count enormously. A model that rejects the
        mapping *and* rejects a verse it was meant to reject has told us nothing about the
        mapping -- it has told us it cannot read this pair of texts. That happens often:
        against the Orthodox Jewish Bible, whose heavy transliteration (*achim*,
        *meyalledot*, *nogesim*) reads as a foreign language, this model answered NO to
        two thirds of a sample of verses that were unambiguously correct.

        The control probe was designed to catch a model too eager to agree. It does not
        catch one too eager to disagree unless the verdict is read this way.
        """
        if self.mapping_answer == self.control_answer:
            return Verdict.UNINFORMATIVE
        return Verdict.CONFIRMED if self.mapping_answer else Verdict.CONTRADICTED


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS judgement (
    left_family  TEXT    NOT NULL,
    right_family TEXT    NOT NULL,
    book         TEXT    NOT NULL,
    chapter      INTEGER NOT NULL,
    verse        INTEGER NOT NULL,
    mapped_book    TEXT    NOT NULL,
    mapped_chapter INTEGER NOT NULL,
    mapped_verse   INTEGER NOT NULL,
    mapping_answer INTEGER NOT NULL,
    control_answer INTEGER NOT NULL,
    verdict      TEXT    NOT NULL,
    PRIMARY KEY (left_family, right_family, book, chapter, verse)
) WITHOUT ROWID;
"""


def open_judgements(path: Path) -> sqlite3.Connection:
    """The results store. Separate from the corpus database because it is a lab notebook,
    not part of the library's data, and because a run of hours has to survive being
    interrupted -- every answer is committed as it arrives."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(_SCHEMA)
    return connection


class Judge:
    """Asks a llama.cpp server whether two verses are the same passage."""

    def __init__(
        self,
        servers: Sequence[str] = DEFAULT_SERVERS,
        *,
        timeout: float = 120.0,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self._servers = [server.rstrip("/") for server in servers] or list(DEFAULT_SERVERS)
        self._timeout = timeout
        self._temperature = temperature
        self._lock = threading.Lock()
        self._next = 0
        self.calls = 0

    def model_of(self, server: str) -> str:
        """The model a server reports, or ``""`` if it will not say.

        Health alone cannot answer this, and health alone is what this method used to check
        -- so a server running the small model was indistinguishable from one running the
        large, and a run could be judged under strength without any symptom.
        """
        try:
            with urllib.request.urlopen(f"{server}/v1/models", timeout=5) as response:
                data = json.load(response).get("data", [])
        except (urllib.error.URLError, OSError, ValueError):
            return ""
        return str(data[0].get("id", "")) if data else ""

    def available(self, *, needs: str = "") -> list[str]:
        """Which of the configured servers answer, and are strong enough. Empty means no run.

        ``needs=BIG`` keeps only the large model. ``needs=SMALL`` *prefers* the small one and
        falls back to the large when no small server answered -- which matters with two of
        each in the fleet: a small job helping itself to the large servers starves the big
        job beside it, and holding both exists so the two can run at once. A small question
        is not answered worse by a large model; sending it there is merely wasteful.

        ``needs=""`` keeps whatever answers, which is right only for a caller that does not
        care -- and a caller judging scripture always cares.
        """
        alive = []
        for server in self._servers:
            try:
                with urllib.request.urlopen(f"{server}/health", timeout=5):
                    alive.append(server)
            except (urllib.error.URLError, OSError):
                continue
        if not needs:
            return alive
        tiers = {server: tier(self.model_of(server)) for server in alive}
        if needs == BIG:
            return [server for server in alive if tiers[server] == BIG]
        return [server for server in alive if tiers[server] == SMALL] or [
            server for server in alive if tiers[server] == BIG
        ]

    def _take_server(self) -> str:
        """Strict round-robin.

        Hashing the thread name looked equivalent and was not: a fresh pool per batch reuses
        thread names, so both workers landed on one server while the second sat idle. A
        counter under a lock cannot drift.
        """
        with self._lock:
            server = self._servers[self._next % len(self._servers)]
            self._next += 1
            return server

    def ask(self, left: str, right: str, *, system: str, question: str, seed: int) -> bool:
        """One question, one token of answer.

        The chat endpoint, not ``/completion``: handed a raw completion prompt, an
        instruction-tuned model rejects nearly everything put to it, which is a failure that
        looks exactly like a corpus full of faults.
        """
        body = json.dumps(
            {
                "model": "local",
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": question.format(left=left.strip(), right=right.strip()),
                    },
                ],
                "temperature": self._temperature,
                "max_tokens": 4,
                "seed": seed,
            }
        ).encode()

        server = self._take_server()
        try:
            answer = self._post(server, body)
        except (urllib.error.URLError, OSError, KeyError):
            # One server dying should cost seconds, not the night. Fall back to another and
            # keep going; a total outage is for the supervisor to wait out, not this.
            others = [s for s in self._servers if s != server] or self._servers
            time.sleep(2)
            answer = self._post(others[0], body, timeout=self._timeout * 1.5)

        with self._lock:
            self.calls += 1
        return answer.strip().upper().startswith("YES")

    def _post(self, server: str, body: bytes, timeout: float | None = None) -> str:
        request = urllib.request.Request(
            f"{server}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout or self._timeout) as response:
            payload = json.load(response)
        return str(payload["choices"][0]["message"]["content"])

    def best_of_three(
        self, left: str, right: str, *, system: str, question: str, invert: bool = False
    ) -> bool:
        """Two votes, and a third only to break a tie.

        The two are asked with the verses in *opposite order*, so a positional bias shows up
        as disagreement -- and therefore as a third question -- rather than as a confident
        wrong answer. Distinct seeds make them genuinely independent; at temperature 0 they
        would be one computation run twice.
        """
        first = self.ask(left, right, system=system, question=question, seed=1) ^ invert
        second = self.ask(right, left, system=system, question=question, seed=2) ^ invert
        if first == second:
            return first
        return self.ask(left, right, system=system, question=question, seed=3) ^ invert

    def same_verse(self, left: str, right: str) -> bool:
        """The positive question, voted. This is the only call that can *accept* a pair."""
        return self.best_of_three(left, right, system=_POSITIVE_SYSTEM, question=_POSITIVE_QUESTION)

    def confirms_rejection(self, left: str, right: str) -> bool:
        """The inverse framing, which may only ever confirm a NO the positive prompt gave.

        Alone this question is worth little -- 36% to 78% against labelled pairs, barely
        better than guessing. In agreement with the positive framing it is worth a great
        deal, 98.4% and up. So it is wired as a veto and cannot raise a flag by itself.

        No inversion here, and the sign is worth being careful about because getting it
        backwards silently inverts the whole escalation. The question asked is "are these
        DIFFERENT verses?", so a YES *is* the confirmation that the rejection stands. Only
        callers wanting the answer expressed as sameness need :meth:`best_of_three`'s
        ``invert``.
        """
        return self.best_of_three(left, right, system=_INVERSE_SYSTEM, question=_INVERSE_QUESTION)

    def judge(
        self,
        source: VerseRef,
        mapped: VerseRef,
        source_text: str,
        mapped_text: str,
        control_text: str,
    ) -> Judgement:
        """Ask about the mapping, then about its neighbour, and keep both answers.

        Escalation keeps an exhaustive pass affordable: a pair the positive prompt accepts
        is settled, and only a rejection is worth the inverse framing and the control.
        """
        mapping = self.same_verse(source_text, mapped_text)
        if mapping:
            # Accepted. The control still has to be asked -- an answer that accepts
            # everything is exactly what the control exists to catch.
            control = self.same_verse(source_text, control_text)
            return Judgement(source, mapped, mapping, control)

        if not self.confirms_rejection(source_text, mapped_text):
            # The two framings disagree, so the rejection is not trustworthy. Recorded as a
            # non-discriminating pair, which reads as uninformative.
            return Judgement(source, mapped, False, False)

        control = self.same_verse(source_text, control_text)
        return Judgement(source, mapped, mapping, control)


def record(connection: sqlite3.Connection, left: str, right: str, judged: Judgement) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO judgement (left_family, right_family, book, chapter, verse, "
        "mapped_book, mapped_chapter, mapped_verse, mapping_answer, control_answer, verdict) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            left,
            right,
            judged.source.book,
            int(judged.source.chapter),
            judged.source.verse,
            judged.mapped.book,
            int(judged.mapped.chapter),
            judged.mapped.verse,
            int(judged.mapping_answer),
            int(judged.control_answer),
            judged.verdict,
        ),
    )


def already_judged(
    connection: sqlite3.Connection, left: str, right: str
) -> set[tuple[str, int, int]]:
    """What a previous run finished, so an interrupted pass resumes rather than restarts."""
    rows = connection.execute(
        "SELECT book, chapter, verse FROM judgement WHERE left_family = ? AND right_family = ?",
        (left, right),
    )
    return {(str(b), int(c), int(v)) for b, c, v in rows}


def tally(connection: sqlite3.Connection) -> list[tuple[str, str, int, int, int]]:
    """Per family pair: confirmed, contradicted, uninformative."""
    rows = connection.execute(
        "SELECT left_family, right_family, "
        "SUM(verdict = 'confirmed'), SUM(verdict = 'contradicted'), "
        "SUM(verdict = 'uninformative') "
        "FROM judgement GROUP BY left_family, right_family ORDER BY 1, 2"
    )
    return [(str(a), str(b), int(c or 0), int(d or 0), int(e or 0)) for a, b, c, d, e in rows]


def contradictions(
    connection: sqlite3.Connection, limit: int = 200
) -> Iterator[tuple[str, str, str, int, int, str, int, int]]:
    yield from connection.execute(
        "SELECT left_family, right_family, book, chapter, verse, "
        "mapped_book, mapped_chapter, mapped_verse FROM judgement "
        "WHERE verdict = 'contradicted' ORDER BY left_family, right_family, book, chapter, verse "
        "LIMIT ?",
        (limit,),
    )


def informative_rate(counts: Sequence[int]) -> float:
    """Share of answers that told us anything. Low means the pair's result is not evidence."""
    confirmed, contradicted, uninformative = counts
    total = confirmed + contradicted + uninformative
    return (confirmed + contradicted) / total if total else 0.0
