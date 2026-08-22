"""Finding the citation in text that does not say where it came from.

The cases here are the ones the downstream use actually turns on. A sermon quotes
constantly and cites almost nothing; the words arrive half-remembered, often out of a
translation nobody may redistribute, and the statistic being built is a count of which
passages each tradition reaches for. Every failure mode below corrupts that count in a
different way, so each gets its own test.
"""

from __future__ import annotations

import pickle
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from biblereference.refs import VerseRef, parse_reference
from biblereference.search import (
    COVERAGE,
    IDENTIFIED,
    QUOTATION,
    Gate,
    IndexIncomplete,
    Match,
    ScaledRun,
    Searcher,
    Witness,
    _coverage,
    _matched_span,
    _ratio,
    _tokens,
    _without_overlaps,
    build_index,
    index_coverage,
    index_is_stale,
)
from biblereference.store import DataHome, SourceMeta, write_corpus

# Two renderings of the same passages, far enough apart to tell apart. The archaic one
# stands in for the King James family and the plain one for the modern translations.
ARCHAIC = {
    # John 1:1 is here for one reason: its second half repeats "God" and "the Word" often
    # enough that a stray word of a *later* quotation lands inside it. See
    # test_two_quotations_written_one_after_another_stay_apart.
    "JHN 1:1": "In the beginning was the Word, and the Word was with God, and the Word was God.",
    "JHN 3:16": "For God so loved the world, that he gave his only begotten Son, that "
    "whosoever believeth in him should not perish, but have everlasting life.",
    "JHN 3:17": "For God sent not his Son into the world to condemn the world; but that "
    "the world through him might be saved.",
    "JHN 11:35": "Jesus wept.",
    "ROM 8:28": "And we know that all things work together for good to them that love "
    "God, to them who are the called according to his purpose.",
    "PSA 23:1": "The LORD is my shepherd; I shall not want.",
    "PSA 23:2": "He maketh me to lie down in green pastures: he leadeth me beside the "
    "still waters.",
    "EPH 2:8": "For by grace are ye saved through faith; and that not of yourselves: it "
    "is the gift of God:",
    "EPH 2:9": "Not of works, lest any man should boast.",
}

MODERN = {
    "JHN 1:1": "In the beginning the Word already existed. The Word was with God, and "
    "the Word was God.",
    "JHN 3:16": "For God loved the world so much that he gave his one and only Son, so "
    "that everyone who believes in him will not perish but have eternal life.",
    "JHN 3:17": "God did not send his Son into the world to condemn the world, but to "
    "save the world through him.",
    "JHN 11:35": "Jesus wept.",
    "ROM 8:28": "And we know that God works all things together for the good of those "
    "who love him, who are called according to his purpose.",
    "PSA 23:1": "The LORD is my shepherd; I shall not be in want.",
    "PSA 23:2": "He makes me lie down in green pastures; he leads me beside quiet waters.",
    "EPH 2:8": "For it is by grace you have been saved through faith, and this not from "
    "yourselves; it is the gift of God,",
    "EPH 2:9": "not by works, so that no one can boast.",
}

#: A third rendering, deliberately left out of the index, standing in for the NIV, ESV,
#: NASB and NKJV -- the translations most quoted from American pulpits and the ones that
#: cannot be lawfully bulk-downloaded.
UNINDEXED = {
    "EPH 2:8": "For by grace you have been saved through faith. And this is not your own "
    "doing; it is the gift of God,",
}


def _filler() -> dict[str, str]:
    """Ordinary English, so that common words acquire a realistic document frequency.

    Without it every word in a tiny corpus looks rare and every phrase looks distinctive.
    The verses have to differ from one another as well as from the real ones: the index
    stores distinct texts, so five hundred copies of one sentence would count as one, and
    the commonness ceiling computed from that would throw away every query term.

    Deterministic, because a test that matches by luck is worse than no test.
    """
    subjects = "people elders priests scribes shepherds fishermen craftsmen judges".split()
    verbs = "gathered departed returned answered laboured rested journeyed waited".split()
    places = "valley hillside gateway courtyard vineyard threshing harbour storehouse".split()
    times = "morning evening harvest festival sabbath watch season assembly".split()
    verses: dict[str, str] = {}
    index = 0
    for chapter in range(1, 26):
        for verse in range(1, 21):
            index += 1
            verses[f"GEN {chapter}:{verse}"] = (
                f"And the {subjects[index % len(subjects)]} "
                f"{verbs[(index // 3) % len(verbs)]} by the "
                f"{places[(index // 7) % len(places)]} at the "
                f"{times[(index // 11) % len(times)]}, and it was so in that day."
            )
    return verses


FILLER = _filler()


def build(home: DataHome, corpus: str, verses: dict[str, str]) -> None:
    """Write a small English corpus, keyed by ``"BOOK chapter:verse"``."""
    rows = []
    for reference, text in verses.items():
        book, position = reference.split(" ")
        chapter, verse = position.split(":")
        rows.append((VerseRef(book, int(chapter), int(verse), vrs="eng"), text))
    write_corpus(
        home,
        SourceMeta(corpus=corpus, label=corpus.upper(), language="en", versification="eng"),
        rows,
    )


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    return DataHome(tmp_path / "brhome")


@pytest.fixture
def searcher(home: DataHome) -> Searcher:
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build(home, "modern", {**MODERN, **FILLER})
    build_index(home)
    return Searcher(home)


@pytest.fixture
def searcher_dated(home: DataHome) -> Searcher:
    """The same texts, but under corpus ids the date table knows.

    Searched as text written in 407 -- a Greek father reaching us through a translator who
    wrote in King James register. The ids matter: an undated corpus is never called
    anachronistic, so `archaic` and `modern` would prove nothing here.
    """
    build(home, "kjv", {**ARCHAIC, **FILLER})
    build(home, "web", {**MODERN, **FILLER})
    build_index(home)
    return Searcher(home, composed=407)


# --------------------------------------------------------------------------------------
# Building the index
# --------------------------------------------------------------------------------------


def test_identical_texts_are_indexed_once(home: DataHome) -> None:
    """Fifty English Bibles carry a great many verses word for word alike. Indexing each
    copy would store the same sentence fifty times and lose the fact that they agree."""
    build(home, "archaic", ARCHAIC)
    build(home, "modern", MODERN)
    result = build_index(home)

    assert result.verses == len(ARCHAIC) + len(MODERN)
    # "Jesus wept." is identical in both, so the pair costs one row rather than two.
    assert result.texts == result.verses - 1


def test_an_empty_index_says_how_to_build_it(home: DataHome) -> None:
    build(home, "archaic", ARCHAIC)
    with pytest.raises(LookupError, match="sync"):
        Searcher(home)


def test_a_corpus_built_after_indexing_is_reported_stale(home: DataHome) -> None:
    """The index is derived data, and derived data that quietly falls behind the thing it
    derives from is worse than none."""
    build(home, "archaic", ARCHAIC)
    build_index(home)
    assert index_is_stale(home) == []

    build(home, "modern", MODERN)
    assert index_is_stale(home) == ["modern"]


# --------------------------------------------------------------------------------------
# What can be searched, and what only looks as if it can
#
# A corpus can be built and unindexed at once, and for thirteen of them -- the whole
# Syriac Bible among them -- it was, for months. Every symptom pointed elsewhere: the
# corpus listed in `doctor`, the filter naming it was accepted, and the search came back
# empty in the ordinary way an unmatched query does. The tests here are of the seams that
# were silent, not of the search itself.
# --------------------------------------------------------------------------------------


def build_in(home: DataHome, corpus: str, language: str, verses: dict[str, str]) -> None:
    """The same as :func:`build`, for a corpus that is not in English."""
    rows = []
    for reference, text in verses.items():
        book, position = reference.split(" ")
        chapter, verse = position.split(":")
        rows.append((VerseRef(book, int(chapter), int(verse), vrs="org"), text))
    write_corpus(
        home,
        SourceMeta(corpus=corpus, label=corpus.upper(), language=language, versification="org"),
        rows,
    )


#: John 1:1 in the Peshitta, pointed as the corpus stores it and bare as a Syriac father
#: writing in the fourth century would have written it. The fold has always handled the
#: difference; what it could not do was find a corpus nobody had indexed.
PESHITTA = {
    "JHN 1:1": "ܒ݁ܪܺܫܺܝܬ݂ ܐܺܝܬ݂ܰܘܗ̱ܝ ܗ̱ܘܳܐ ܡܶܠܬ݂ܳܐ ܂ ܘܗܽܘ ܡܶܠܬ݂ܳܐ ܐܺܝܬ݂ܰܘܗ̱ܝ ܗ̱ܘܳܐ ܠܘܳܬ݂ ܐܰܠܳܗܳܐ",
    "JHN 1:2": "ܗܳܢܳܐ ܐܺܝܬ݂ܰܘܗ̱ܝ ܗ̱ܘܳܐ ܒ݁ܪܺܫܺܝܬ݂ ܠܘܳܬ݂ ܐܰܠܳܗܳܐ",
}
UNPOINTED = "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ ܐܠܗܐ"


def _syriac_filler() -> dict[str, str]:
    """:func:`_filler`'s job in another script: enough distinct Syriac verses that a word
    of John 1:1 is not automatically the rarest thing in the corpus."""
    nouns = "ܡܠܟܐ ܟܗܢܐ ܢܒܝܐ ܥܡܐ ܒܝܬܐ ܐܪܥܐ ܡܕܝܢܬܐ ܛܘܪܐ".split()
    verbs = "ܐܡܪ ܥܒܕ ܐܙܠ ܝܗܒ ܩܡ ܢܦܩ ܥܢܐ ܫܡܥ".split()
    places = "ܐܘܪܫܠܡ ܓܠܝܠܐ ܝܗܘܕ ܡܨܪܝܢ ܒܒܠ ܢܝܢܘܐ ܫܡܪܝܢ ܟܢܥܢ".split()
    verses: dict[str, str] = {}
    count = 0
    for chapter in range(1, 26):
        for verse in range(1, 21):
            count += 1
            verses[f"GEN {chapter}:{verse}"] = (
                f"ܘ{verbs[count % len(verbs)]} {nouns[(count // 3) % len(nouns)]} "
                f"ܒ{places[(count // 7) % len(places)]} ܘ{verbs[(count // 11) % len(verbs)]} "
                f"{nouns[(count // 13) % len(nouns)]} ܥܡ ܟܠܗ ܥܡܐ ܒܝܘܡܐ ܗܘ"
            )
    return verses


SYRIAC_FILLER = _syriac_filler()


def test_a_corpus_named_in_a_filter_but_never_indexed_is_refused(home: DataHome) -> None:
    """The failure this whole section exists for. Asking for a corpus that holds no
    indexed verse used to return an empty result, which is indistinguishable from the
    text simply not being quoted -- so a sweep of 2.2 M words reported nothing found and
    nobody could tell it apart from a sweep that had genuinely found nothing."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build(home, "modern", MODERN)
    build_index(home, corpora=["archaic"])

    with pytest.raises(LookupError) as raised:
        Searcher(home, corpora=["modern"])
    assert "not in the search index" in str(raised.value)
    assert "modern" in str(raised.value)
    # The message has to carry the cure, because the reader of it is by definition
    # someone who did not know the index and the store were different things.
    assert "biblereference index" in str(raised.value)


def test_an_unindexed_corpus_nobody_asked_for_is_dropped_with_one_warning(
    home: DataHome,
) -> None:
    """Refusing here instead would make a single stale corpus take the library down with
    it, and thirteen were stale at once. So the rest still answer -- but not quietly."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build(home, "modern", MODERN)
    build_index(home, corpora=["archaic"])

    with pytest.warns(IndexIncomplete, match="modern"):
        searcher = Searcher(home)
    found = list(searcher.search("He maketh me to lie down in green pastures"))
    assert [witness.corpus for match in found for witness in match.witnesses] == ["archaic"]


def test_syriac_answers_to_either_of_its_two_iso_codes(home: DataHome) -> None:
    """`syc` and `syr` both name Syriac. The library stores the first and `churchfathers`
    asked with the second, and got an empty corpus rather than an error.

    The query is unpointed and the corpus is pointed throughout, which is the shape the
    request blamed for the whole failure. It matches, and always would have.
    """
    build_in(home, "peshitta", "syc", {**PESHITTA, **SYRIAC_FILLER})
    build_index(home)

    under = {
        code: [str(match.passage) for match in Searcher(home, languages=[code]).search(UNPOINTED)]
        for code in ("syc", "syr")
    }
    assert under["syc"] == under["syr"] == ["JHN 1:1"]


def test_an_unrecognised_language_says_so_rather_than_finding_nothing(home: DataHome) -> None:
    build(home, "archaic", ARCHAIC)
    build_index(home)

    with pytest.raises(LookupError) as raised:
        Searcher(home, languages=["klingon"])
    assert "klingon" in str(raised.value)
    assert "en" in str(raised.value)


def test_a_language_held_but_unindexed_is_refused_for_that_reason(home: DataHome) -> None:
    """Two different refusals, because they want different things done about them: one is
    a typo and the other is a command the operator has not run yet."""
    build(home, "archaic", ARCHAIC)
    build_in(home, "peshitta", "syc", PESHITTA)
    build_index(home, corpora=["archaic"])

    with pytest.raises(LookupError) as raised:
        Searcher(home, languages=["syr"])
    assert "not in the search index" in str(raised.value)
    assert "peshitta" in str(raised.value)


def test_indexing_one_corpus_leaves_what_was_indexed_for_the_others_alone(
    home: DataHome,
) -> None:
    """`index --corpus` exists so the thirteen missing corpora could be folded in without
    re-folding the fifty-five already there.

    Proved by wrecking `archaic`'s rows first: if indexing `modern` touched it at all, the
    rows would come back. Comparing timestamps would not do -- they have one-second
    resolution and a corpus this small reindexes well inside one.
    """
    build(home, "archaic", ARCHAIC)
    build(home, "modern", MODERN)
    build_index(home)
    _forget_rows(home, "archaic")

    build_index(home, corpora=["modern"])

    assert _indexed_rows(home) == {"modern": len(MODERN)}
    assert set(_index_state(home)) == {"archaic", "modern"}


def test_a_freshly_indexed_corpus_is_not_reported_stale(home: DataHome) -> None:
    """The wolf that was cried. `source_meta.verse_count` records the verses a build
    *offered*; references that repeat collapse onto one row on the way in, so the store
    holds fewer than the metadata says. Comparing the index against the metadata reported
    four corpora as stale permanently, and six more the moment they were indexed."""
    twice = VerseRef("JHN", 11, 35, vrs="eng")
    write_corpus(
        home,
        SourceMeta(corpus="doubled", label="Doubled", language="en", versification="eng"),
        [(twice, "Jesus wept."), (twice, "Jesus wept.")],
    )
    (stored,) = _verse_counts(home).values()
    assert stored == 1, "the duplicate reference should have collapsed onto one row"

    build_index(home)
    assert index_is_stale(home) == []


def test_coverage_counts_the_rows_the_store_holds_not_the_ones_it_was_offered(
    home: DataHome,
) -> None:
    twice = VerseRef("JHN", 11, 35, vrs="eng")
    write_corpus(
        home,
        SourceMeta(corpus="doubled", label="Doubled", language="en", versification="eng"),
        [(twice, "Jesus wept."), (twice, "Jesus wept.")],
    )
    build_index(home)
    (row,) = index_coverage(home)
    assert (row.stored, row.indexed, row.source_verses) == (1, 1, 1)
    assert row.state == "current"


def _index_state(home: DataHome) -> dict[str, tuple[str, int]]:
    with closing(sqlite3.connect(home.database)) as connection:
        return {
            str(corpus): (str(at), int(verses))
            for corpus, at, verses in connection.execute(
                "SELECT corpus, indexed_at, verses FROM search_state"
            )
        }


def _indexed_rows(home: DataHome) -> dict[str, int]:
    with closing(sqlite3.connect(home.database)) as connection:
        return {
            str(corpus): int(n)
            for corpus, n in connection.execute(
                "SELECT corpus, COUNT(*) FROM search_ref GROUP BY corpus"
            )
        }


def _forget_rows(home: DataHome, corpus: str) -> None:
    with closing(sqlite3.connect(home.database)) as connection:
        connection.execute("DELETE FROM search_ref WHERE corpus = ?", (corpus,))
        connection.commit()


def _verse_counts(home: DataHome) -> dict[str, int]:
    with closing(sqlite3.connect(home.database)) as connection:
        return {
            str(corpus): int(n)
            for corpus, n in connection.execute(
                "SELECT corpus, COUNT(*) FROM verse GROUP BY corpus"
            )
        }


# --------------------------------------------------------------------------------------
# Finding the passage
# --------------------------------------------------------------------------------------


def test_a_verbatim_quotation_names_its_passage_and_its_translation(
    searcher: Searcher,
) -> None:
    (match, *_) = searcher.search(
        "For God so loved the world, that he gave his only begotten Son, that whosoever "
        "believeth in him should not perish"
    )
    assert str(match.passage) == "JHN 3:16"
    assert match.identified
    assert [w.corpus for w in match.translations()] == ["archaic"]


def test_a_paraphrase_from_memory_still_finds_the_passage(searcher: Searcher) -> None:
    """What a preacher actually says: the words drift, the clauses drop, and the passage
    is not in doubt."""
    (match, *_) = searcher.search(
        "we know that God works all things together for good for those who love him and "
        "are called according to his purpose"
    )
    assert str(match.passage) == "ROM 8:28"


def test_a_quotation_across_a_verse_boundary_is_one_passage(searcher: Searcher) -> None:
    """Verse numbers are an editorial layer the speaker cannot hear. Reporting Psalm 23:1
    and 23:2 separately would double-count the passage in every statistic built here."""
    (match, *_) = searcher.search(
        "The LORD is my shepherd; I shall not want. He maketh me to lie down in green "
        "pastures: he leadeth me beside the still waters."
    )
    assert str(match.passage) == "PSA 23:1-2"


def test_the_passage_is_named_even_when_the_translation_is_not_held(
    searcher: Searcher,
) -> None:
    """The case that decides whether a distribution is honest. NIV, ESV, NASB and NKJV are
    most of American preaching and none may be redistributed, so a quotation from one of
    them must locate its passage and then decline to name a translation -- rather than
    quietly crediting whichever public-domain text happens to sit nearest it."""
    (match, *_) = searcher.search(UNINDEXED["EPH 2:8"])

    assert str(match.passage) == "EPH 2:8"
    assert not match.identified, "no held translation should be claimed as the source"
    assert "translation is unknown" in match.describe()


def test_ordinary_religious_language_matches_nothing(searcher: Searcher) -> None:
    """The whole point. A matcher that fires on these would put a handful of cliches at
    the top of every denomination's list and say nothing true about any of them."""
    for phrase in (
        "we are saved by grace and not by anything that we have done ourselves",
        "i believe that god has a wonderful plan and a purpose for your life today",
        "let us pray together this morning as we come before the throne of grace",
        "there is power in the name of jesus to save and to heal and to deliver",
    ):
        assert searcher.search(phrase) == [], phrase


def test_a_short_fragment_is_not_attributed(searcher: Searcher) -> None:
    """Some genuine quotations are very short, and shortness is exactly what makes them
    unattributable: too few words agree for the agreement to mean anything."""
    assert searcher.search("Jesus wept") == []


# --------------------------------------------------------------------------------------
# Telling translations apart, and admitting when you cannot
# --------------------------------------------------------------------------------------


def test_translations_that_render_a_verse_identically_are_reported_as_a_tie(
    home: DataHome,
) -> None:
    """Where two texts print the same words, naming one of them is a coin flip dressed up
    as a finding. This is the ordinary case among the real corpora: the World English
    Bible variants agree with each other almost everywhere, as do the American Standard
    Version and its Byzantine revision."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build(home, "reprint", {**ARCHAIC, **FILLER})
    build(home, "modern", {**MODERN, **FILLER})
    build_index(home)

    (match, *_) = Searcher(home).search(
        "For by grace are ye saved through faith; and that not of yourselves: it is the "
        "gift of God: Not of works, lest any man should boast."
    )

    assert [w.corpus for w in match.translations()] == ["archaic", "reprint"]
    assert not match.decisive, "two texts printing the same words cannot be told apart"
    assert "indistinguishable" in match.describe()


def test_the_query_may_contain_fts5_operators(searcher: Searcher) -> None:
    """Users type "and", "or", "not" and "near", which are FTS5's own operators. Unquoted,
    an unbalanced quotation mark is a hard error rather than a poor match."""
    assert searcher.search('and or not near "') == []
    assert searcher.search("he said NEAR unto them AND* they") == []


# --------------------------------------------------------------------------------------
# Scanning a document
# --------------------------------------------------------------------------------------


def test_a_quotation_is_found_inside_an_unpunctuated_transcript(
    searcher: Searcher,
) -> None:
    """No quote marks, no capitals, no full stops -- and the reported span must be the
    quotation rather than the sentence around it."""
    transcript = (
        "now friends i want us to think this morning about what it cost him because "
        "for god so loved the world that he gave his only begotten son that whosoever "
        "believeth in him should not perish but have everlasting life and that is the "
        "whole gospel in a single sentence isnt it praise god for that"
    )
    matches = searcher.scan(transcript)

    assert [str(m.passage) for m in matches] == ["JHN 3:16"]
    (match,) = matches
    assert match.span is not None
    quoted = transcript[match.span[0] : match.span[1]]
    assert quoted.startswith("for god so loved")
    assert quoted.endswith("everlasting life")


def test_two_quotations_in_one_document_are_two_records(searcher: Searcher) -> None:
    transcript = (
        "hear the word of the lord the lord is my shepherd i shall not want he maketh "
        "me to lie down in green pastures he leadeth me beside the still waters and "
        "then hear what paul says not of works lest any man should boast amen"
    )
    matches = searcher.scan(transcript)

    assert {str(m.passage) for m in matches} == {"PSA 23:1-2", "EPH 2:9"}


def test_two_quotations_written_one_after_another_stay_apart(searcher: Searcher) -> None:
    """The case with no filler between them, which is the hard one.

    John 1:1 repeats *God* and *the Word*, so a quotation of John 3:16 beginning *God so
    loved* has its first word sitting inside John 1:1's second half. Measured on the
    searched-text side alone that word is adjacent to the John 1:1 match and gets absorbed;
    the span then swallows most of John 3:16, and the overlap check deletes the second
    quotation as a duplicate. One chimeric record where there should be two.
    """
    document = (
        "In the beginning was the Word. And God so loved the world that he gave his only Son."
    )
    matches = searcher.scan(document)

    assert [str(m.passage) for m in matches] == ["JHN 1:1", "JHN 3:16"]
    first, second = matches
    assert first.quoted.lower().startswith("in the beginning was the word")
    assert "loved" not in first.quoted.lower()
    assert second.quoted.lower().startswith("god so loved the world")
    # Neither is a rival reading of the other; they are neighbours.
    assert not first.ambiguous
    assert not second.ambiguous


def test_a_scanned_record_keeps_the_date_it_was_judged_on(
    searcher_dated: Searcher,
) -> None:
    """`scan` rebuilds every match to attach its alternates, and rebuilding it without the
    date silently turned `anachronistic` off for the whole document -- the one field a
    patristic count is supposed to filter on."""
    (record,) = [
        m.to_dict()
        for m in searcher_dated.scan(
            "and remember what he told us not of works lest any man should boast which "
            "means none of us can take the credit for any of it at all"
        )
    ]

    assert record["composed"] == 407
    assert record["anachronistic"] is True


def test_a_document_of_ordinary_preaching_yields_nothing(searcher: Searcher) -> None:
    """A false positive rate above zero puts noise into every cell of the distribution,
    and the rarely-quoted passages are where it would show up worst."""
    transcript = (
        "good morning church it is so good to see all of you here today and i want to "
        "welcome everyone who is visiting with us for the very first time this morning "
        "we believe that god has a plan for your life and that he loves you very much "
        "so please stay afterwards for coffee and let us get to know one another better"
    )
    assert searcher.scan(transcript) == []


def test_the_record_carries_everything_a_pipeline_needs(searcher: Searcher) -> None:
    """The downstream project aggregates thousands of these, so the record has to stand
    alone: what passage, how sure, from where in the file, and whether the translation
    was actually determined."""
    matches = searcher.scan(
        "and remember what he told us not of works lest any man should boast which "
        "means none of us can take the credit for any of it at all"
    )
    (record,) = [m.to_dict() for m in matches]

    assert record["passage"] == "EPH 2:9"
    assert record["pretty"] == "Ephesians 2:9"
    assert record["book"] == "EPH"
    assert record["vrs"] == "eng"
    assert isinstance(record["similarity"], float)
    assert record["identified"] is True
    assert record["span"] and len(record["span"]) == 2
    assert record["translations"][0]["corpus"] == "archaic"
    assert record["ambiguous"] is False


# --------------------------------------------------------------------------------------
# Where a span begins and ends, and when two spans are one
# --------------------------------------------------------------------------------------


def test_a_span_stops_where_the_verse_leaps_ahead_of_the_text() -> None:
    """The verse-side bound, on its own.

    *God* is the eighth word of the text and the eleventh of John 1:1. On the text side it
    is adjacent to the run before it and would be absorbed; on the verse side it is four
    words further on, which is a coincidence agreeing rather than a quotation continuing.
    """
    query = _tokens("In the beginning was the Word. And God so loved the world")
    assert _matched_span(query, _tokens(ARCHAIC["JHN 1:1"])) == (0, 7)


def test_a_span_follows_the_verse_over_a_word_the_quotation_omits() -> None:
    """The other direction, which must still work: *only Son* skips the verse's
    *begotten*, a verse-side gap of one, and the span has to reach the closing word."""
    query = _tokens("God so loved the world that he gave his only Son")
    assert _matched_span(query, _tokens(ARCHAIC["JHN 3:16"])) == (0, 11)


def _match(
    passage: str,
    span: tuple[int, int],
    similarity: float,
    *,
    coverage: float | None = None,
    run: int = 0,
    bits: float = 0.0,
) -> Match:
    return Match(
        parse_reference(passage),
        (
            Witness(
                "archaic",
                "Archaic",
                "",
                similarity,
                1611,
                similarity if coverage is None else coverage,
            ),
        ),
        span=span,
        quoted="",
        run=run,
        bits=bits,
    )


def test_two_quotations_that_merely_touch_are_both_kept() -> None:
    """A single shared character used to be enough to delete one of them."""
    kept = _without_overlaps([_match("JHN 1:1", (0, 30), 0.9), _match("JHN 3:16", (29, 80), 0.85)])
    assert [str(m.passage) for m in kept] == ["JHN 1:1", "JHN 3:16"]
    assert not any(m.ambiguous for m in kept)


def test_two_readings_of_the_same_words_are_one_record_with_an_alternate() -> None:
    """Which is what the overlap check is actually for."""
    kept = _without_overlaps([_match("PSA 14:1", (0, 40), 0.9), _match("PSA 53:1", (2, 38), 0.88)])
    (only,) = kept
    assert str(only.passage) == "PSA 14:1"
    assert [str(p) for p in only.alternates] == ["PSA 53:1"]


def test_a_rival_covering_more_is_kept_though_it_scores_lower_on_similarity() -> None:
    """Didache 1.4, and the reason `_TIE` alone was the wrong gate for keeping a rival.

    The father strings four sayings together. `MAT 5:39-42` answers the whole span at a
    ten-word run; `LUK 6:29` answers two thirds of it in four words. Similarity is
    symmetric, so the four-verse passage is marked down for the three verses he did not
    quote and lands 0.093 below -- outside the tie window, and so deleted without even
    becoming an alternate. The citation Boyce marked went with it.

    Coverage asks what is actually being asked. The winner does not change: `LUK 6:29`
    still sorted first and is still what this reports.
    """
    winner = _match("LUK 6:29", (72, 123), 0.387, coverage=0.667)
    covers_more = _match("MAT 5:39-42", (68, 123), 0.294, coverage=1.0)
    (only,) = _without_overlaps([winner, covers_more], covering_rivals=True)
    assert str(only.passage) == "LUK 6:29"
    assert [str(p) for p in only.alternates] == ["MAT 5:39-42"]


def test_a_match_that_clears_the_gate_wins_the_span_from_one_that_does_not() -> None:
    """The defect three other fixes circled, and the one that answers it.

    Suppression runs before anything is gated and picks its winner on similarity, which
    says how alike two texts are and nothing about whether the match will survive. At
    Didache 1.4 that deleted `MAT 5:39-42` -- ten words, 35.3 bits, over the gate -- for
    `LUK 6:29`, four words and 15.8 bits, under it. The span then reported nothing, having
    had the answer the whole time.

    Measured over Boyce's nine works: 75 citations found becomes 81, and 83 once the
    consumer reads `alternates` too.
    """
    gates = [Gate(3, 0, 0, 35.0)]
    under = _match("LUK 6:29", (72, 123), 0.387, coverage=0.667, run=4, bits=15.8)
    over = _match("MAT 5:39-42", (68, 123), 0.294, coverage=1.0, run=10, bits=35.3)
    (only,) = _without_overlaps([under, over], gates=gates)
    assert str(only.passage) == "MAT 5:39-42"
    assert [str(p) for p in only.alternates] == ["LUK 6:29"]


def test_without_gates_the_similarity_order_still_decides() -> None:
    """Opt-in, because it changes which passage is reported and half a million findings
    rest on that not happening by surprise."""
    under = _match("LUK 6:29", (72, 123), 0.387, coverage=0.667, run=4, bits=15.8)
    over = _match("MAT 5:39-42", (68, 123), 0.294, coverage=1.0, run=10, bits=35.3)
    (only,) = _without_overlaps([under, over])
    assert str(only.passage) == "LUK 6:29"


def test_two_matches_that_both_clear_the_gate_keep_their_old_order() -> None:
    """The tier reorders across the gate boundary and nowhere else, so a span where both
    rivals pass is arbitrated exactly as it is today."""
    gates = [Gate(3, 0, 0, 35.0)]
    strong = _match("PSA 14:1", (0, 40), 0.9, coverage=0.9, run=9, bits=60.0)
    weaker = _match("PSA 53:1", (2, 38), 0.88, coverage=0.88, run=8, bits=55.0)
    (only,) = _without_overlaps([strong, weaker], gates=gates)
    assert str(only.passage) == "PSA 14:1"
    assert [str(p) for p in only.alternates] == ["PSA 53:1"]


def test_the_covering_rival_is_not_kept_unless_it_is_asked_for() -> None:
    """Opt-in, because it fills a field a default scan leaves empty."""
    winner = _match("LUK 6:29", (72, 123), 0.387, coverage=0.667)
    covers_more = _match("MAT 5:39-42", (68, 123), 0.294, coverage=1.0)
    (only,) = _without_overlaps([winner, covers_more])
    assert str(only.passage) == "LUK 6:29"
    assert only.alternates == ()


def test_a_rival_covering_less_and_scoring_lower_is_still_dropped() -> None:
    """The other side of it, so the rule is a rule and not an amnesty.

    A rival that neither scores within the tie window nor explains as much of the span is
    what the suppression exists to remove, and it is still removed.
    """
    winner = _match("LUK 6:29", (72, 123), 0.9, coverage=0.9)
    weaker = _match("MAT 5:39-42", (68, 123), 0.4, coverage=0.5)
    (only,) = _without_overlaps([winner, weaker], covering_rivals=True)
    assert str(only.passage) == "LUK 6:29"
    assert only.alternates == ()


def test_one_passage_read_as_two_barely_overlapping_spans_is_one_record() -> None:
    """The clause the looser overlap test needs, and the regression that proved it.

    Requiring a *substantial* overlap is what lets two neighbouring quotations both
    survive. Applied to the same passage it lets it survive twice: scanning Mark 1:1
    followed by Acts 1:8 returned Acts 1:8 as two records, found at two nearly disjoint
    spans. A different passage has to claim most of the shorter span; the same passage
    claims any overlap at all.
    """
    kept = _without_overlaps([_match("ACT 1:8", (0, 40), 0.9), _match("ACT 1:8", (36, 90), 0.88)])
    assert [str(m.passage) for m in kept] == ["ACT 1:8"]


def test_one_passage_found_in_two_numberings_is_not_its_own_rival() -> None:
    """The Douay and the Clementine agree across the New Testament, so a quotation is
    found once in `eng` and again in `vul`. Comparing the ranges rather than the verses
    they name made the match an alternate of itself and reported it as ambiguous."""
    english = _match("JHN 3:16", (0, 40), 0.9)
    latin = Match(
        parse_reference("JHN 3:16", vrs="vul"),
        english.witnesses,
        span=(1, 39),
        quoted="",
    )
    (only,) = _without_overlaps([english, latin])
    assert only.alternates == ()
    assert not only.ambiguous


# --------------------------------------------------------------------------------------
# Coverage: finding a quotation shorter than the verse it came from
# --------------------------------------------------------------------------------------


def test_a_short_exact_quotation_of_a_long_verse_is_found(searcher: Searcher) -> None:
    """The whole point of the second measure.

    Six words quoted perfectly out of a twenty-six-word verse score 2*6/32 = 0.375 on a
    symmetric ratio, below any threshold that keeps ordinary religious language out, so this
    was refused however exact it was. Preachers quote whole verses and the ratio suits them;
    the fathers quote a clause and argue from it.
    """
    matches = searcher.search("he gave his only begotten Son")

    assert matches
    assert str(matches[0].passage) == "JHN 3:16"
    assert matches[0].coverage == 1.0
    assert matches[0].similarity < QUOTATION, "must have been admitted on coverage alone"


def test_coverage_is_insensitive_to_how_long_the_passage_is() -> None:
    quote = ["he", "gave", "his", "only", "begotten", "son"]
    short = _coverage(quote, quote)
    long = _coverage(quote, [*quote, "that", "whosoever", "believeth"] * 5)
    assert short == long == 1.0


def test_coverage_asks_a_different_question_from_similarity() -> None:
    """A clause of a verse is a complete quotation and a poor resemblance. Both numbers are
    right; they answer different questions, which is why both are kept."""
    query = ["he", "gave", "his", "only", "begotten", "son"]
    verse = _tokens(ARCHAIC["JHN 3:16"])
    assert _coverage(query, verse) == 1.0
    assert _ratio(query, verse) < 0.5


def test_ordinary_religious_language_still_matches_nothing(searcher: Searcher) -> None:
    """The most important regression test here.

    Coverage is a looser gate than a symmetric ratio, so this is where a false-positive
    regression would show. *We are saved by grace through faith alone* is the one that bites:
    Darby reads "ye are saved by grace, through faith", so the phrase really does carry six
    consecutive words of Ephesians 2:8 and the contiguity gate cannot tell the difference.
    Only requiring both measures to be unconvinced keeps it out.
    """
    for phrase in [
        "we are saved by grace through faith alone",
        "the Lord is good and his mercy endures",
        "let us pray for one another as brothers and sisters",
        "God has a wonderful plan for your life",
    ]:
        assert searcher.search(phrase) == [], phrase


def test_similarity_still_answers_which_translation(home: DataHome) -> None:
    """Regression guard: attribution must not move.

    ARCHAIC and REPRINT render this verse identically, so they tie. The tie is decided on
    similarity, not coverage, and must stay a tie -- IDENTIFIED and translations(margin) are
    calibrated on the symmetric measure and request 1 was written to leave them alone.
    """
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build(home, "reprint", {**ARCHAIC, **FILLER})
    build(home, "modern", {**MODERN, **FILLER})
    build_index(home)
    searcher = Searcher(home)

    (match, *_) = searcher.search(ARCHAIC["ROM 8:28"])
    assert [w.corpus for w in match.translations()] == ["archaic", "reprint"]
    assert not match.decisive


def test_a_quotation_spanning_verses_still_grows_to_the_span(searcher: Searcher) -> None:
    """Guards the band where the existing implementation was already the better one."""
    match = searcher.search(f"{ARCHAIC['PSA 23:1']} {ARCHAIC['PSA 23:2']}")[0]
    assert str(match.passage) == "PSA 23:1-2"


def test_growing_stops_when_it_stops_helping(searcher: Searcher) -> None:
    """Coverage cannot fall as a passage grows, so growth needs more than a
    strict-improvement test or every match runs to _MAX_PASSAGE.

    Strictness alone is not enough either: against a scan window, which carries the
    speaker's own prose as well as the quotation, adding the neighbouring verse picks up
    scattered words from the surrounding sentence and coverage genuinely rises. Requiring
    two consecutive words is what separates a quotation continuing into the next verse from
    a neighbour that merely shares vocabulary.
    """
    match = searcher.search(ARCHAIC["JHN 3:16"])[0]
    assert str(match.passage) == "JHN 3:16"
    assert match.passage.start.verse == match.passage.end.verse


# --------------------------------------------------------------------------------------
# The scoring constants as parameters
# --------------------------------------------------------------------------------------


def test_the_thresholds_default_to_todays_constants(home: DataHome) -> None:
    """Nothing changes for an existing caller."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    text = ARCHAIC["ROM 8:28"]

    plain = Searcher(home).search(text)
    explicit = Searcher(
        home, quotation=QUOTATION, coverage=COVERAGE, identified=IDENTIFIED, min_run=6
    ).search(text)

    assert [str(m.passage) for m in plain] == [str(m.passage) for m in explicit]


def test_a_lower_contiguity_gate_admits_a_shorter_quotation(home: DataHome) -> None:
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    phrase = "he leadeth me beside"

    assert Searcher(home, min_run=6).search(phrase) == []
    assert Searcher(home, min_run=3).search(phrase)


def test_min_run_may_scale_with_the_query(home: DataHome) -> None:
    """A callable is what lets the gate be proportional without the caller reimplementing
    it: three words out of four is evidence and three out of forty is not."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    scaled = Searcher(home, min_run=lambda n: max(3, min(6, n // 2)))

    assert scaled.search("he leadeth me beside")
    assert scaled._min_run_for(4) == 3
    assert scaled._min_run_for(40) == 6


def test_raising_the_gates_refuses_more(home: DataHome) -> None:
    """Self-calibrating rather than hard-coded: find what the match actually scores, then
    set both gates above it. A fixed 0.99 proves nothing against an exact quotation, which
    scores 1.0 on coverage and cannot be refused by any threshold at all."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    text = "and we know that all things work together for good to them that love the Lord"

    (found, *_) = Searcher(home).search(text)
    assert found.coverage < 1.0, "need an imperfect recollection for this to mean anything"

    strict = Searcher(home, quotation=found.similarity + 0.01, coverage=found.coverage + 0.01)
    assert strict.search(text) == []


def test_the_query_floor_is_configurable(home: DataHome) -> None:
    """Four tokens is a safe English default and the entire reason a three-word Greek
    quotation could never be found: search() returned [] before scoring happened."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)

    assert Searcher(home).search("Jesus wept") == []
    assert Searcher(home, min_query=2, min_run=2).search("Jesus wept")


# --------------------------------------------------------------------------------------
# Naming a translation the author could not have read
# --------------------------------------------------------------------------------------


def test_a_translation_postdating_the_text_is_reported_as_anachronistic(
    searcher_dated: Searcher,
) -> None:
    """``identified`` conflates two claims: that these words match a translation, and that
    the author was reading it. For a sermon both hold. For a father who died in 407 and
    reaches us through a Victorian translator only the first does -- and the library named
    the King James anyway.

    The translations stay named, because which one an editor followed is a real fact about
    editorial practice. What is refused is the inference a reader would otherwise draw.
    """
    (match, *_) = searcher_dated.search(ARCHAIC["JHN 3:16"])

    assert match.identified, "the words do match; that part was never in doubt"
    assert match.anachronistic
    assert all(w.translated and w.translated > 407 for w in match.translations())
    assert "postdate" in match.describe()


def test_a_translation_the_author_could_have_read_is_not_anachronistic(
    home: DataHome,
) -> None:
    """False whenever *any* named translation was available, since then the attribution
    stands on its own. A seventeenth-century Puritan could have read the King James."""
    build(home, "kjv", {**ARCHAIC, **FILLER})
    build_index(home)

    (match, *_) = Searcher(home, composed=1650).search(ARCHAIC["JHN 3:16"])
    assert not match.anachronistic


def test_saying_nothing_about_when_a_text_was_written_doubts_nothing(
    searcher: Searcher,
) -> None:
    """A date nobody supplied is not grounds for suspicion, and the default behaviour must
    not change for the sermon corpus this was built for."""
    (match, *_) = searcher.search(ARCHAIC["JHN 3:16"])
    assert match.composed is None
    assert not match.anachronistic


def test_the_record_carries_the_dates_it_judged_on(searcher_dated: Searcher) -> None:
    """A count of who quoted what should filter on `anachronistic` rather than on
    `identified`, so both it and the evidence behind it have to reach the pipeline."""
    record = searcher_dated.search(ARCHAIC["JHN 3:16"])[0].to_dict()

    assert record["anachronistic"] is True
    assert record["composed"] == 407
    assert all(t["translated"] for t in record["translations"])


def test_an_ancient_text_is_anachronistic_to_nobody() -> None:
    """The distinction the dates are *of the wording* rather than of the edition. Swete's
    Septuagint is an 1890s edition of an ancient text, so a Greek father could read those
    words -- and dating it 1894 would fire the flag on every father against the very corpus
    they actually quoted."""
    from biblereference.dating import anachronistic

    assert not anachronistic("swete", 407)
    assert not anachronistic("n1904", 407)
    assert not anachronistic("wlc", 407)
    assert anachronistic("kjv", 407)
    # The King James modernised in 2006 is still the wording of 1611.
    assert not anachronistic("kjv2006", 1650)
    # The Nova Vulgata is Latin and still anachronistic: a new translation, not an edition
    # of Jerome's.
    assert anachronistic("novavulgata", 407)
    assert not anachronistic("latvuc", 407)


def test_an_undated_corpus_is_never_accused() -> None:
    """Silence is not evidence, and a false accusation would suppress a real attribution."""
    from biblereference.dating import anachronistic

    assert not anachronistic("no-such-corpus", 407)


def test_every_built_corpus_has_a_date() -> None:
    """An undated corpus is invisible to the check, so a new one must not be forgotten."""
    import sqlite3
    from pathlib import Path

    from biblereference.dating import TRANSLATED

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        built = {row[0] for row in connection.execute("SELECT corpus FROM source_meta")}
    assert built - set(TRANSLATED) == set()


def test_a_scaled_run_is_the_documented_lambda_and_survives_a_pickle() -> None:
    """`min_run` may be proportional to the query, and the proportional form is a class
    rather than the closure the docstrings show, for one reason: it has to cross a process
    boundary. The server's batch scan runs in worker processes, and a closure defined
    inside a function cannot be pickled -- so the calibrated configuration was the one
    setting the batch could not accept, while every setting not worth running at scale
    worked. A class pickles by reference and cannot fail that way.
    """
    scaled = ScaledRun(4)

    assert [scaled(n) for n in range(60)] == [max(4, min(6, n // 2)) for n in range(60)]
    assert pickle.loads(pickle.dumps(scaled)) == scaled
    assert ScaledRun(3, ceiling=9)(40) == 9

    with pytest.raises(ValueError, match="at least 1"):
        ScaledRun(0)


def test_an_index_folded_by_an_older_rule_is_reported_stale(home: DataHome) -> None:
    """The staleness check compared verse counts, and a fold change leaves every count
    identical -- so when Greek elision marks started folding away, every entry in the
    index was keyed on `sha1` of the old normalisation and `doctor` said all corpora
    current. The query would say `μετ` and the index would say `μετʼ` and the two would
    never meet, silently, for as long as nobody reindexed.

    So the index records which fold built it. A recorded version that is not this one is
    drift, said before the counts are consulted -- they agree and mean nothing.
    """
    import sqlite3

    from biblereference.emphasis import FOLD_VERSION
    from biblereference.search import index_coverage

    write_corpus(
        home,
        SourceMeta(corpus="folded", label="Folded", language="grc", versification="org"),
        [(VerseRef("JHN", 11, 35, vrs="org"), "ἐδάκρυσεν ὁ Ἰησοῦς")],
    )
    build_index(home)
    assert index_is_stale(home) == [], "just built, by this very fold"
    assert [row.fold_version for row in index_coverage(home)] == [FOLD_VERSION]

    with closing(sqlite3.connect(home.database)) as connection:
        connection.execute("UPDATE search_state SET fold_version = ?", (FOLD_VERSION - 1,))
        connection.commit()
    assert index_is_stale(home) == ["folded"], "folded by a rule this code no longer applies"


def test_an_index_that_never_recorded_its_fold_is_not_cried_wolf_over(home: DataHome) -> None:
    """`NULL` means an index built before the column existed, which cannot say what folded
    it. Guessing "stale" there would send every existing install off to rebuild a
    perfectly good index -- the same judgement `source_verses` already makes."""
    import sqlite3

    write_corpus(
        home,
        SourceMeta(corpus="quiet", label="Quiet", language="en", versification="eng"),
        [(VerseRef("JHN", 11, 35, vrs="eng"), "Jesus wept.")],
    )
    build_index(home)
    with closing(sqlite3.connect(home.database)) as connection:
        connection.execute("UPDATE search_state SET fold_version = NULL")
        connection.commit()
    assert index_is_stale(home) == []


# --------------------------------------------------------------------------------------
# The lemma axes on an exact match, which `search` used to leave at zero
# --------------------------------------------------------------------------------------


def test_search_puts_the_lemma_axes_on_its_exact_matches(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_exact_cluster` has carried the axes since the doxology case; `search` did not.

    The same nine verbatim words scored 16.67 bits through `scan` and a silent 0.0 through
    `search`, so a consumer whose gate puts a surprisal floor on every arm -- as the shipped
    Latin gate does -- refused every exact match this method returned, true ones included.
    Nine hundred false positives were the reason that floor exists, so the floor is right and
    the missing axes were the bug.

    Asserted as wiring rather than as a number: the axes need a real lexicon, and the point
    of failure was that the call was absent, not that it computed the wrong thing.
    """
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    seen: list[int] = []

    original = Searcher._with_axes

    def counted(self: Searcher, found: object, query: object, best: object) -> object:
        seen.append(1)
        return original(self, found, query, best)  # type: ignore[arg-type]

    monkeypatch.setattr(Searcher, "_with_axes", counted)
    with Searcher(home, inflected=True) as searcher:
        found = searcher.search(ARCHAIC["JHN 1:1"])
    assert found, "the fixture verse should still be found"
    assert seen, "search returned an exact match without asking for its lemma axes"


def test_search_does_not_pay_for_the_axes_when_inflected_is_off(
    home: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The axes cost a lexicon lookup per word. A caller who did not ask does not pay."""
    build(home, "archaic", {**ARCHAIC, **FILLER})
    build_index(home)
    seen: list[int] = []
    original = Searcher._with_axes

    def counted(self: Searcher, found: object, query: object, best: object) -> object:
        seen.append(1)
        return original(self, found, query, best)  # type: ignore[arg-type]

    monkeypatch.setattr(Searcher, "_with_axes", counted)
    with Searcher(home) as searcher:
        searcher.search(ARCHAIC["JHN 1:1"])
    assert not seen
