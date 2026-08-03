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

Nothing here writes to the versification data. It produces evidence for a person to read.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .refs import VerseRef

__all__ = [
    "GRAMMAR",
    "Judge",
    "Judgement",
    "Verdict",
    "open_judgements",
]

#: The whole grammar. Two tokens, so the answer needs no parsing and cannot wander.
GRAMMAR: Final = 'root ::= "YES" | "NO"'

DEFAULT_SERVER: Final = "http://127.0.0.1:8080"

_PROMPT: Final = """You are comparing two verses from different editions of the Bible. \
The editions may be in different languages, and may number their verses differently.

Answer YES if these are the same verse of scripture -- the same passage, even where the \
wording or the language differs. Answer NO if they are different verses.

Verse A ({left_label}): {left}

Verse B ({right_label}): {right}

Are these the same verse of scripture? Answer YES or NO.
Answer: """


class Verdict:
    """What one verse's pair of probes established."""

    CONFIRMED: Final = "confirmed"
    """YES to the mapping and NO to its neighbour: the model can tell them apart, and
    agrees with the mapping."""
    CONTRADICTED: Final = "contradicted"
    """NO to the mapping. Worth a person's attention whatever the neighbour probe said."""
    UNINFORMATIVE: Final = "uninformative"
    """YES to both, or NO to both. The model is not discriminating here, so its opinion on
    this verse is not evidence either way."""


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
        if not self.mapping_answer:
            return Verdict.CONTRADICTED
        return Verdict.UNINFORMATIVE if self.control_answer else Verdict.CONFIRMED


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
        server: str = DEFAULT_SERVER,
        *,
        timeout: float = 120.0,
        temperature: float = 0.0,
    ) -> None:
        self._server = server.rstrip("/")
        self._timeout = timeout
        self._temperature = temperature
        self.calls = 0

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self._server}/health", timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def ask(self, left: str, right: str, left_label: str, right_label: str) -> bool:
        """One question, one token of answer."""
        prompt = _PROMPT.format(
            left=left.strip(),
            right=right.strip(),
            left_label=left_label,
            right_label=right_label,
        )
        body = json.dumps(
            {
                "prompt": prompt,
                "grammar": GRAMMAR,
                "n_predict": 4,
                "temperature": self._temperature,
                "cache_prompt": True,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._server}/completion", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            answer = str(json.load(response)["content"]).strip().upper()
        self.calls += 1
        return answer.startswith("YES")

    def judge(
        self,
        source: VerseRef,
        mapped: VerseRef,
        source_text: str,
        mapped_text: str,
        control_text: str,
        *,
        left_label: str,
        right_label: str,
    ) -> Judgement:
        """Ask about the mapping, then about its neighbour, and keep both answers."""
        mapping = self.ask(source_text, mapped_text, left_label, right_label)
        control = self.ask(source_text, control_text, left_label, right_label)
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
