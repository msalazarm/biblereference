"""The library describing itself, and the licence column that has a wrong answer in it.

Two of these run against the *real* store, because the facts worth pinning are facts about
what has actually been built: twenty-five of the sixty-six restricted, one with no recorded
licence, one carrying two. A synthetic corpus cannot have those properties by accident, and
inventing them would only test that the test invented them.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from biblereference.refs import VerseRef
from biblereference.store import DataHome, SourceMeta, write_corpus
from biblereference.web import library as lib
from biblereference.web import server
from biblereference.web.catalogue import api_library


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> DataHome:
    """The developer's own library, skipped where there is not one."""
    real = DataHome(Path.home() / ".local/share/biblereference")
    if not real.database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    monkeypatch.setattr(server, "HOME", real)
    monkeypatch.setattr(lib, "_LIBRARY", None)
    monkeypatch.setattr(lib, "_local", threading.local())
    return real


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataHome:
    where = DataHome(tmp_path)
    write_corpus(
        where,
        SourceMeta(
            corpus="known",
            label="A public-domain Bible",
            language="en",
            versification="eng",
            licence_id="public-domain",
        ),
        [(VerseRef("JHN", 3, verse), f"john {verse}") for verse in range(1, 37)],
    )
    write_corpus(
        where,
        SourceMeta(
            corpus="sharing",
            label="A share-alike edition",
            language="grc",
            versification="lxx",
            licence_id="cc-by-sa-4.0",
        ),
        [(VerseRef("GEN", 1, verse), f"γενεσις {verse}") for verse in range(1, 32)],
    )
    write_corpus(
        where,
        SourceMeta(corpus="unknown", label="An unread licence", language="en", versification="eng"),
        [(VerseRef("MAT", 1, verse), f"matthew {verse}") for verse in range(1, 26)],
    )
    monkeypatch.setattr(server, "HOME", where)
    monkeypatch.setattr(lib, "_LIBRARY", None)
    monkeypatch.setattr(lib, "_local", threading.local())
    return where


def row(payload: dict, corpus: str) -> dict:  # type: ignore[type-arg]
    (found,) = [r for r in payload["corpora"] if r["corpus"] == corpus]
    return found  # type: ignore[no-any-return]


# --------------------------------------------------------------------------------------
# The licence column
# --------------------------------------------------------------------------------------


def test_an_unrecorded_licence_is_louder_than_a_restrictive_one(home: DataHome) -> None:
    """This library's own doctrine: *a licence nobody has read is not a licence to do
    anything*. A blank cell reads as "no restrictions" and means the opposite."""
    found = row(api_library({}), "unknown")["licence"]
    assert found["unrecorded"] is True
    assert found["restricted"] is True
    assert "nobody has established" in found["describe"]


def test_share_alike_is_a_restriction_too(home: DataHome) -> None:
    """So the badge cannot be a single non-commercial flag: CC BY-SA permits commercial use
    and still obliges you."""
    found = row(api_library({}), "sharing")["licence"]
    assert (found["commercial"], found["share_alike"], found["restricted"]) == (True, True, True)
    assert "share-alike" in found["describe"]


def test_an_unrestricted_licence_says_so(home: DataHome) -> None:
    found = row(api_library({}), "known")["licence"]
    assert (found["unrecorded"], found["restricted"]) == (False, False)


def test_the_two_states_are_counted_apart(home: DataHome) -> None:
    """Only one of them is knowledge. Folding "we do not know" into "restricted" produces
    one reassuring number that conceals the difference."""
    totals = api_library({})["totals"]
    assert (totals["restricted"], totals["unrecorded"]) == (1, 1)
    assert totals["corpora"] == 3


# --------------------------------------------------------------------------------------
# What has actually been built
# --------------------------------------------------------------------------------------


def test_the_real_library_is_reported_as_it_stands(built: DataHome) -> None:
    totals = api_library({})["totals"]
    assert totals["corpora"] >= 66
    assert totals["verses"] > 1_500_000
    assert set(totals["languages"]) >= {"en", "grc", "la", "syc", "hbo", "cop"}
    assert totals["restricted"] >= 25, "the count fell; a licence was loosened or lost"


def test_the_corpus_with_no_recorded_licence_is_the_one_we_know_about(built: DataHome) -> None:
    """If a second appears, something was built without its terms being read."""
    payload = api_library({})
    unrecorded = [r["corpus"] for r in payload["corpora"] if r["licence"]["unrecorded"]]
    assert unrecorded == ["niv"]


def test_a_corpus_may_carry_two_licences(built: DataHome) -> None:
    """The case the schema exists for. `sblgnt`'s files declare CC BY 4.0; the edition's own
    terms do not permit redistribution and are what governs, so answering with the header
    would tell a reader they may do something they may not. Both are kept, so the
    discrepancy stays visible instead of being smoothed away."""
    found = row(api_library({}), "sblgnt")
    assert found["licence_ids"] == ["cc-by-4.0", "sblgnt"]
    assert found["licence"]["governed_by"] == "sblgnt"
    assert found["licence"]["restricted"] is True


def test_an_ancient_text_is_undated_rather_than_unknown(built: DataHome) -> None:
    """`translated` is the year the *wording* appeared, which is what makes a quotation
    anachronistic. None means ancient; a reader must not see it as missing data."""
    payload = api_library({})
    assert row(payload, "wlc")["ancient"] is True
    assert row(payload, "wlc")["translated"] is None
    assert row(payload, "dra")["ancient"] is False
    assert row(payload, "dra")["translated"] == 1752


def test_each_corpus_says_what_part_of_the_canon_it_holds(built: DataHome) -> None:
    payload = api_library({})
    assert row(payload, "wlc")["canon"] == {"hebrew": 39}
    assert set(row(payload, "peshitta-nt")["canon"]) == {"nt"}
