"""Finding the citation in text that does not say where it came from.

The cases here are the ones the downstream use actually turns on. A sermon quotes
constantly and cites almost nothing; the words arrive half-remembered, often out of a
translation nobody may redistribute, and the statistic being built is a count of which
passages each tradition reaches for. Every failure mode below corrupts that count in a
different way, so each gets its own test.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from biblereference.refs import VerseRef
from biblereference.search import (
    COVERAGE,
    IDENTIFIED,
    QUOTATION,
    ScaledRun,
    Searcher,
    _coverage,
    _ratio,
    _tokens,
    build_index,
    index_is_stale,
)
from biblereference.store import DataHome, SourceMeta, write_corpus

# Two renderings of the same passages, far enough apart to tell apart. The archaic one
# stands in for the King James family and the plain one for the modern translations.
ARCHAIC = {
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
