"""Comparing two editions of one text.

The two Latin Bibles are the case this was built for, and they are awkward in exactly the
ways that matter: they are numbered differently, they spell differently, and they
punctuate differently. Only the third of those is noise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.compare import compare_corpora
from biblereference.refs import VerseRef
from biblereference.store import DataHome, SourceMeta, SqliteCorpus, write_corpus
from biblereference.versification import Versification


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def build(home: DataHome, corpus: str, versification: str, verses: dict[str, str]) -> None:
    """Write a small corpus, keyed by "BOOK chapter:verse"."""
    rows = []
    for reference, text in verses.items():
        book, position = reference.split(" ")
        chapter, verse = position.split(":")
        rows.append((VerseRef(book, int(chapter), int(verse), vrs=versification), text))
    write_corpus(
        home,
        SourceMeta(corpus=corpus, label=corpus.upper(), language="la", versification=versification),
        rows,
    )


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    return DataHome(tmp_path / "brhome")


def test_punctuation_is_not_a_textual_difference(home: DataHome, vrs: Versification) -> None:
    """The Clementine writes "ad Jonam, filium Amathi, dicens:" where the Nova Vulgata
    has "ad Ionam filium Amathi dicens:". Counting commas would report the whole Bible
    as changed."""
    build(
        home,
        "a",
        "org",
        {"JON 1:1": "Et factum est verbum Domini ad Jonam, filium Amathi, dicens:"},
    )
    build(
        home, "b", "org", {"JON 1:1": "Et factum est verbum Domini ad Ionam filium Amathi dicens:"}
    )
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert result.compared == 1
    assert result.identical == 1
    assert result.differing == []


def test_latin_orthography_is_not_a_textual_difference(home: DataHome, vrs: Versification) -> None:
    """j and i, v and u, are the same letters in different centuries' typography."""
    build(home, "a", "org", {"JON 1:1": "Justitia ejus universa"})
    build(home, "b", "org", {"JON 1:1": "Iustitia eius uniuersa"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert result.identical == 1


def test_a_changed_word_is_a_difference(home: DataHome, vrs: Versification) -> None:
    """The revision this was built to measure: regit becomes pascit."""
    build(home, "a", "org", {"JON 1:1": "Dominus regit me et nihil mihi deerit"})
    build(home, "b", "org", {"JON 1:1": "Dominus pascit me et nihil mihi deerit"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert len(result.differing) == 1
    assert 0.5 < result.differing[0].similarity < 1.0


def test_a_dropped_word_is_a_difference(home: DataHome, vrs: Versification) -> None:
    build(home, "a", "org", {"JON 1:1": "et descendit in Joppen"})
    build(home, "b", "org", {"JON 1:1": "et descendit Ioppen"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert len(result.differing) == 1


def test_editions_numbered_differently_are_aligned_through_the_pivot(
    home: DataHome, vrs: Versification
) -> None:
    """The Clementine's Psalm 22 is the Nova Vulgata's Psalm 23. Compared where they sit,
    every psalm would read as divergent."""
    build(home, "clem", "vul", {"PSA 22:1": "Dominus regit me"})
    build(home, "nova", "org", {"PSA 23:1": "Dominus pascit me"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["clem"], corpora["nova"], vrs, books=["PSA"])
    assert result.compared == 1, "the two psalms should have been lined up"
    assert len(result.differing) == 1
    assert result.differing[0].ref.chapter == 23


def test_a_verse_only_one_edition_has_is_counted_apart(home: DataHome, vrs: Versification) -> None:
    """Not as a difference: there is nothing to compare it with."""
    build(home, "a", "org", {"JON 1:1": "Et factum est", "JON 1:2": "Surge et vade"})
    build(home, "b", "org", {"JON 1:1": "Et factum est"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert result.compared == 1
    assert result.identical == 1
    assert result.missing_right == 1
    assert result.differing == []


def test_the_summary_figures(home: DataHome, vrs: Versification) -> None:
    build(home, "a", "org", {"JON 1:1": "alpha beta", "JON 1:2": "gamma delta"})
    build(home, "b", "org", {"JON 1:1": "alpha beta", "JON 1:2": "gamma epsilon"})
    corpora = SqliteCorpus.load_all(home)

    (result,) = compare_corpora(corpora["a"], corpora["b"], vrs, books=["JON"])
    assert result.compared == 2
    assert result.share_differing == 0.5
    assert 0.5 < result.mean_similarity < 1.0
    assert result.title == "Jonah"
