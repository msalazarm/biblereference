"""Naming the translation for a passage the local corpus could find but not attribute.

The corpus holds fifty-odd English Bibles and none of the thirteen best-selling ones,
because every one of those is under live copyright. So a quotation from the NIV locates its
passage confidently and then matches nothing closely, and answering *whose Bible* means
asking BibleGateway about that one passage.

Every test here is about what that is allowed to cost. Nothing may be fetched
speculatively, nothing twice, and nothing at all once the budget is spent -- and the tests
prove it by making the network raise if it is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.web import BibleGatewayCorpus
from biblereference.refs import VerseRange, VerseRef
from biblereference.search import (
    Match,
    Resolver,
    Searcher,
    Witness,
    build_index,
)
from biblereference.store import DataHome, SourceMeta, add_chapter, write_corpus
from test_search import FILLER, build

#: What the local corpus has, and what the speaker actually said. The two are close enough
#: to identify Romans 8:28 and far enough apart that no held translation can be named --
#: which is exactly the state resolution exists to act on.
ARCHAIC_ROMANS = (
    "And we know that all things work together for good to them that love God, to them "
    "who are the called according to his purpose."
)
SPOKEN = (
    "And we know that for those who love God all things work together for good for those "
    "who are called according to his purpose"
)


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    root = DataHome(tmp_path / "brhome")
    build(root, "archaic", {"ROM 8:28": ARCHAIC_ROMANS, **FILLER})
    build_index(root)
    return root


@pytest.fixture
def unattributed() -> Match:
    """A match of the shape resolution acts on: passage known, translation not."""
    passage = VerseRange(VerseRef("ROM", 8, 28), VerseRef("ROM", 8, 28))
    return Match(
        passage,
        (Witness("archaic", "ARCHAIC", ARCHAIC_ROMANS, 0.72),),
        span=(0, len(SPOKEN)),
        quoted=SPOKEN,
    )


class Recorder:
    """Stands in for the network, counting what would have been requested."""

    def __init__(self, texts: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.texts = texts or {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        def _download(self: BibleGatewayCorpus, book: str, first: int, last: int) -> None:
            recorder.calls.append((self.id, book, first))
            text = recorder.texts.get(self.id)
            if text is None:
                from biblereference.corpora.base import CorpusError

                raise CorpusError(f"{self.id} does not carry {book} {first}")
            self._absorb(book, {first: {28: text}}, "")

        monkeypatch.setattr(BibleGatewayCorpus, "_download", _download)


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _download(self: BibleGatewayCorpus, book: str, first: int, last: int) -> None:
        raise AssertionError(f"the network was touched: {self.id} {book} {first}")

    monkeypatch.setattr(BibleGatewayCorpus, "_download", _download)


# --------------------------------------------------------------------------------------
# What must never cost a request
# --------------------------------------------------------------------------------------


def test_a_match_already_attributed_to_a_wanted_version_is_left_alone(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolution answers one question -- which of the thirteen was being read -- and a
    match that already answers it is a request nobody needed."""
    forbid_network(monkeypatch)
    passage = VerseRange(VerseRef("ROM", 8, 28), VerseRef("ROM", 8, 28))
    match = Match(passage, (Witness("kjv", "KJV", ARCHAIC_ROMANS, 0.99),), quoted=SPOKEN)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher).resolve(match, SPOKEN)

    assert outcome.fetched == 0
    assert outcome.checked == ()


def test_a_confident_match_on_an_unwanted_version_still_asks(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case that would otherwise be missed silently. A quotation of the NIV scores 87%
    against the Berean Standard Bible and is reported as attributed -- to Berean, which is
    a true statement and not an answer. Berean is not one of the thirteen, so the question
    is still open and worth one request."""
    passage = VerseRange(VerseRef("ROM", 8, 28), VerseRef("ROM", 8, 28))
    match = Match(passage, (Witness("bsb", "BSB", ARCHAIC_ROMANS, 0.92),), quoted=SPOKEN)
    recorder = Recorder({"niv": SPOKEN})
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, versions=("NIV",)).resolve(match, SPOKEN)

    assert outcome.fetched == 1
    assert outcome.match.translations()[0].corpus == "niv"


def test_a_stored_chapter_is_used_without_asking_again(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """The point of keeping whole chapters. The second sermon quoting Romans 8 in the NIV
    must cost nothing and work with the network off."""
    add_chapter(
        home,
        SourceMeta(corpus="niv", label="NIV", language="en", versification="eng"),
        "ROM",
        8,
        {28: SPOKEN},
    )
    forbid_network(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, versions=("NIV",)).resolve(unattributed, SPOKEN)

    assert outcome.fetched == 0
    assert outcome.resolved
    assert outcome.match.translations()[0].corpus == "niv"


def test_offline_never_reaches_the_network(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """The guarantee the whole library rests on: naming a version is the opt-in, and
    `--offline` withdraws it."""
    forbid_network(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, offline=True).resolve(unattributed, SPOKEN)

    assert outcome.fetched == 0
    assert not outcome.resolved


def test_a_corpus_already_held_locally_is_not_fetched(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """KJV and ASV are in the resolution order because they are cheap to check, not because
    they should be downloaded. A version already in the index is scored from it."""
    write_corpus(
        home,
        SourceMeta(corpus="kjv", label="KJV", language="en", versification="eng"),
        [(VerseRef("ROM", 8, 28, vrs="eng"), ARCHAIC_ROMANS)],
    )
    build_index(home)
    recorder = Recorder()
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        Resolver(home, searcher, versions=("KJV",)).resolve(unattributed, SPOKEN)

    assert [call[0] for call in recorder.calls] == []


# --------------------------------------------------------------------------------------
# What it does cost
# --------------------------------------------------------------------------------------


def test_it_stops_at_the_first_decisive_match(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """Thirteen versions at a fifteen-second crawl delay is over three minutes a passage.
    Stopping at the first answer is what makes the order matter and the cost bearable."""
    recorder = Recorder({"niv": SPOKEN})
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, versions=("NIV", "ESV", "NKJV")).resolve(
            unattributed, SPOKEN
        )

    assert outcome.resolved
    assert outcome.fetched == 1, "ESV and NKJV must not be asked for once the NIV matched"
    assert [call[0] for call in recorder.calls] == ["niv"]
    assert outcome.match.translations()[0].corpus == "niv"


def test_the_budget_is_a_ceiling_not_a_suggestion(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """A long sermon can hold forty unattributed passages. Without a hard stop this would
    quietly spend hours of requests nobody asked for."""
    recorder = Recorder()  # nothing matches, so every version is tried
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        resolver = Resolver(home, searcher, versions=("NIV", "ESV", "NKJV", "NLT"), budget=2)
        outcome = resolver.resolve(unattributed, SPOKEN)

    assert resolver.spent == 2
    assert outcome.exhausted
    assert not outcome.resolved


def test_an_unmatched_passage_reports_what_was_ruled_out(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """An unknown after checking is a different fact from an unknown before checking, and
    a study that cannot tell them apart cannot say what its gaps are."""
    recorder = Recorder(
        {"niv": "something else entirely about a different subject", "esv": "also not it"}
    )
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, versions=("NIV", "ESV")).resolve(unattributed, SPOKEN)

    assert not outcome.resolved
    assert outcome.checked == ("NIV", "ESV")
    assert "translation is unknown" in outcome.match.describe()


def test_a_version_that_does_not_carry_the_passage_is_not_an_answer(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """A failed request says nothing about which translation was quoted, and recording it
    as a rejection would be recording evidence that was never gathered."""
    recorder = Recorder({"esv": SPOKEN})  # the NIV call raises
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        outcome = Resolver(home, searcher, versions=("NIV", "ESV")).resolve(unattributed, SPOKEN)

    assert outcome.checked == ("ESV",), "the failed NIV request is not a checked version"
    assert outcome.resolved


def test_resolution_records_which_corpora_need_reindexing(
    home: DataHome, monkeypatch: pytest.MonkeyPatch, unattributed: Match
) -> None:
    """Chapters arriving this way have to reach the search index, or the text accumulated
    at fifteen seconds a chapter never makes the next scan any cheaper."""
    recorder = Recorder({"niv": SPOKEN})
    recorder.install(monkeypatch)

    with Searcher(home) as searcher:
        resolver = Resolver(home, searcher, versions=("NIV",))
        resolver.resolve(unattributed, SPOKEN)

    assert resolver.touched == ("niv",)
