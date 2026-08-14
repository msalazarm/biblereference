"""Finding a quotation whose words have been re-inflected.

Every fixture here comes from the request that asked for the feature, and the negatives
matter as much as the positives. A lemmatiser will pair `ἀνδρὸς` with `ἄνδρας` and
`μεμαρτυρημένου` with `μαρτυρουμένους` -- both correct pairings, both the same lemma -- and
hand back a two-word "quotation" of Acts 6:3 that no scholar accepts. Getting Matthew 10:16
right and that one wrong is easy; getting both right is the whole feature.

The lexicon here is small and written out by hand, so the suite needs no 33 MB download.
That is a real limitation: a lexicon containing exactly the words the fixtures need cannot
show that the matching works on words nobody thought about in advance. So
``test_real_lexicon.py`` runs the same fixtures against the fetched one and skips when it is
absent, and the recall figures in the reply come from neither -- they come from 5,044
quotations that editors marked by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.search import (
    DIRECT,
    INDIRECT,
    PARTIAL,
    Searcher,
    build_index,
    build_lemma_index,
)
from biblereference.store import DataHome, SourceMeta, open_store, write_corpus
from test_regression import GREEK, _filler

#: Nestle 1904 chapter and verse for each fixture's source, as the request names it.
AT = {
    "1TH 5:17": "1 Thess 5:17",
    "MAT 10:16": "Matt 10:16",
    "MAT 19:12": "Matt 19:12",
    "MAT 3:15": "Matt 3:15",
    "PHP 2:3": "Phil 2:3",
    "ACT 6:3": "Acts 6:3",
    "ACT 20:21": "Acts 20:21",
}

#: What Ignatius wrote, and the verse an editor says he was quoting. `run` is the longest
#: identically spelled run between the two, measured against the corpus below.
POSITIVES = [
    (
        "Pol. 2.2",
        "MAT 10:16",
        "φρόνιμος γίνου ὡς ὁ ὄφις ἐν ἅπασιν καὶ ἀκέραιος εἰς ἀεὶ ὡς ἡ περιστερά",
    ),
    ("Smyrn. 6.1", "MAT 19:12", "ἐστίν ὁ χωρῶν χωρείτω"),
    ("Phil. 8.2", "PHP 2:3", "μηδὲν κατ᾽ ἐριθείαν"),
    ("Smyrn. 1.1b", "MAT 3:15", "ἵνα πληρωθῇ πᾶσα δικαιοσύνη"),
]

#: The paper's fourth grade, *potential*, on entries its own author did not believe were
#: quotations. They are far more useful here than they ever were as positives.
NEGATIVES = [
    ("Smyrn. 9.1", "ACT 20:21", "εἰς θεὸν μετανοεῖν"),
    ("Phil. 11.1a", "ACT 6:3", "ἀνδρὸς μεμαρτυρημένου"),
]

#: Enough of a lexicon for the fixtures, written out rather than fetched. Each entry is a
#: real Morpheus pairing, checked against the fetched lexicon.
LEXICON: dict[str, tuple[str, ...]] = {
    "φρονιμοσ": ("φρονιμοσ",),
    "φρονιμοι": ("φρονιμοσ",),
    "γινου": ("γιγνομαι",),
    "γινεσθε": ("γιγνομαι",),
    "οφισ": ("οφισ",),
    "οφεισ": ("οφισ",),
    "ακεραιοσ": ("ακεραιοσ",),
    "ακεραιοι": ("ακεραιοσ",),
    "περιστερα": ("περιστερα",),
    "περιστεραι": ("περιστερα",),
    "χωρων": ("χωραζω", "χωρεω", "χωροσ"),
    "χωρειν": ("χωρεω",),
    "χωρειτω": ("χωρεω",),
    "πληρωθη": ("πληροω",),
    "πληρωσαι": ("πληροω",),
    "δικαιοσυνη": ("δικαιοσυνη",),
    "δικαιοσυνην": ("δικαιοσυνη",),
    "πασα": ("πασ",),
    "πασαν": ("πασ",),
    "ανδροσ": ("ανδροσ", "ανηρ"),
    "ανδρασ": ("αναδιδρασκω", "ανηρ"),
    "μεμαρτυρημενου": ("μαρτυρεω",),
    "μαρτυρουμενουσ": ("μαρτυρεω",),
    "μετανοειν": ("μετανοεω",),
    "μετανοιαν": ("μετανοια",),
    "θεον": ("θεοσ",),
    "θεου": ("θεοσ",),
    "θεω": ("θεοσ",),
    "εισ": ("εισ",),
    "ωσ": ("ωσ",),
    "ο": ("ο",),
    "οι": ("ο",),
    "η": ("ο",),
    "αι": ("ο",),
    "και": ("και",),
    "εν": ("εν",),
    "την": ("ο",),
    "τον": ("ο",),
}


def _function_words() -> dict[str, str]:
    """Filler that is mostly `καί`, `ὁ`, `εἰς`, `θεός` and `ὡς`.

    Without it these tests measure surprisal against a corpus of five hundred verses in
    which `εἰς` occurs twice and therefore looks like a rare word. It is not: in the Greek
    the library actually holds, `εἰς` is in 35,986 verses of 113,062 and `θεός` in 2,248,
    which is why the Acts 20:21 negative scores 7.3 bits there and would score 13.9 here.
    A gate calibrated on real frequencies has to be tested against something resembling
    them, or the test measures the fixture rather than the rule.
    """
    common = "και ο εισ θεοσ ωσ εν την του αυτου γαρ δε ουκ".split()
    verses: dict[str, str] = {}
    for chapter in range(26, 46):
        for verse in range(1, 41):
            index = chapter * 41 + verse
            verses[f"GEN {chapter}:{verse}"] = " ".join(
                common[(index + step) % len(common)] for step in range(12)
            )
    return verses


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    """A small Greek library with a lemma index over it."""
    where = DataHome(tmp_path / "brhome")
    verses = {**GREEK, **_filler("grc"), **_function_words()}
    rows = []
    for reference, text in verses.items():
        book, position = reference.split(" ")
        chapter, verse = position.split(":")
        from biblereference.refs import VerseRef

        rows.append((VerseRef(book, int(chapter), int(verse), vrs="org"), text))
    write_corpus(
        where,
        SourceMeta(corpus="n1904", label="N1904", language="grc", versification="org"),
        rows,
    )
    build_index(where)
    with open_store(where) as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO lemma_form (language, form, lemma) VALUES ('grc', ?, ?)",
            [(form, lemma) for form, lemmas in LEXICON.items() for lemma in lemmas],
        )
    build_lemma_index(where)
    return where


def searcher(home: DataHome, **options: object) -> Searcher:
    """At the tuning the consumer actually runs Greek at."""
    settings: dict[str, object] = {
        "coverage": 0.50,
        "min_query": 3,
        "min_run": lambda n: max(4, min(6, n // 2)),
    }
    settings.update(options)
    return Searcher(home, languages=["grc"], **settings)  # type: ignore[arg-type]


def passages(matches: object) -> list[str]:
    return [str(match.passage) for match in matches]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------
# The feature off is today
# --------------------------------------------------------------------------------------


def test_with_the_feature_off_the_re_inflected_quotations_are_still_missed(
    home: DataHome,
) -> None:
    """Not an aspiration but the baseline. If these were already found there would be
    nothing to add, and a test that passed either way would prove nothing later."""
    with searcher(home) as plain:
        for where, verse, text in POSITIVES:
            assert verse not in passages(plain.search(text)), f"{where} was already found"


def test_nothing_found_today_is_lost_when_the_feature_is_on(home: DataHome) -> None:
    """The consumer's Requirement 0, on the matching itself rather than on the record.

    Checked over every verse in the corpus rather than over a chosen few, because the fear
    is not that a named passage moves but that some unnamed one quietly does.
    """
    with searcher(home) as plain, searcher(home, inflected=True) as rich:
        for text in GREEK.values():
            before = set(passages(plain.search(text)))
            after = set(passages(rich.search(text)))
            assert before <= after, f"lost {before - after} from {text[:40]!r}"


def test_an_exact_match_is_graded_direct_and_says_what_found_it(home: DataHome) -> None:
    with searcher(home) as plain:
        found = plain.search(GREEK["LUK 24:39"])
    assert found and found[0].grade == DIRECT
    assert found[0].run >= 4, "the identical run that found it is on the record"


# --------------------------------------------------------------------------------------
# The quotations that must now be found
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("where", "verse", "text"), POSITIVES)
def test_a_re_inflected_quotation_is_found(
    home: DataHome, where: str, verse: str, text: str
) -> None:
    """The request's §5.1. Matthew 10:16 is the one that matters most: fourteen shared
    words, longest identical run of one, and if a lemmatiser cannot pair `φρόνιμος` with
    `φρόνιμοι` nothing else in the feature works."""
    with searcher(home, inflected=True) as rich:
        found = rich.search(text)
    assert verse in passages(found), f"{where} ({AT[verse]}) was not found"


def test_the_match_carries_the_evidence_it_rests_on(home: DataHome) -> None:
    """Not a verdict. They asked to weigh it themselves, and a grade nobody can check is
    an assertion rather than evidence."""
    with searcher(home, inflected=True) as rich:
        found = [m for m in rich.search(POSITIVES[0][2]) if str(m.passage) == "MAT 10:16"]
    assert found
    match = found[0]
    assert match.grade in {INDIRECT, PARTIAL}
    assert match.lemma_run >= 2
    assert match.bits > 0
    assert "περιστερα" in match.matched_lemmas
    assert "φρονιμοσ" in match.matched_lemmas


def test_three_verbatim_words_come_back_as_partial_rather_than_as_nothing(
    home: DataHome,
) -> None:
    """Philippians 2:3. Today's `min_run` refuses it for being short, not for being
    different -- so a grade is the whole of what it needed."""
    with searcher(home, inflected=True) as rich:
        found = [m for m in rich.search(POSITIVES[2][2]) if str(m.passage) == "PHP 2:3"]
    assert found and found[0].grade == PARTIAL
    assert found[0].run == 3, "identically spelled, and that is why it is not indirect"


# --------------------------------------------------------------------------------------
# The ones that must not be found
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("where", "verse", "text"), NEGATIVES)
def test_a_pairing_that_is_correct_but_not_a_quotation_is_refused(
    home: DataHome, where: str, verse: str, text: str
) -> None:
    """The sharpest test in the request.

    `ἀνδρὸς`/`ἄνδρας` and `μεμαρτυρημένου`/`μαρτυρουμένους` are both right, and Acts 6:3
    separates them with `ἐξ ὑμῶν` -- so as a *run* they are one word, and one word of
    `μαρτυρέω`, which is everywhere in Christian Greek, is not evidence of anything. What
    refuses this is not the lemmatiser being careful; it is the rule being a run.
    """
    with searcher(home, inflected=True) as rich:
        assert verse not in passages(rich.search(text)), f"{where} should not be found"


def test_two_words_are_refused_twice_over_and_it_is_worth_knowing_which(
    home: DataHome,
) -> None:
    """`ἀνδρὸς μεμαρτυρημένου` is two words, and two things refuse it.

    `min_query` refuses it before any of this is reached -- so the honest statement is that
    the run rule is not what saves us here, and a caller who lowered `min_query` would be
    relying on the run rule alone. Pinned so that both facts stay true: lowered, the gates
    still refuse it, and loosened past them it comes back. A refusal nobody can locate is
    not one anybody can rely on.
    """
    with searcher(home, inflected=True, min_query=2) as reachable:
        assert "ACT 6:3" not in passages(reachable.search(NEGATIVES[1][2]))
    with searcher(home, inflected=True, min_query=2, min_lemma_run=1, min_bits=0.0) as loose:
        assert "ACT 6:3" in passages(loose.search(NEGATIVES[1][2]))


# --------------------------------------------------------------------------------------
# Asking for it, and being told when it cannot be given
# --------------------------------------------------------------------------------------


def test_min_grade_filters_to_the_footing_asked_for(home: DataHome) -> None:
    with searcher(home, inflected=True, min_grade=DIRECT) as strict:
        assert "MAT 10:16" not in passages(strict.search(POSITIVES[0][2]))
    with searcher(home, inflected=True, min_grade=INDIRECT) as loose:
        assert "MAT 10:16" in passages(loose.search(POSITIVES[0][2]))


def test_a_language_with_no_lexicon_says_so_rather_than_finding_nothing(
    tmp_path: Path,
) -> None:
    """The silence this library was bitten by twice already: a feature that cannot work
    answering as though it had worked and found nothing."""
    from biblereference.lemmata import LexiconUnavailable
    from biblereference.refs import VerseRef

    where = DataHome(tmp_path / "bare")
    write_corpus(
        where,
        SourceMeta(corpus="n1904", label="N", language="grc", versification="org"),
        [(VerseRef("JHN", 1, 1, vrs="org"), GREEK["JHN 3:8"])],
    )
    build_index(where)
    with (
        pytest.raises(LexiconUnavailable, match="biblereference lemmata"),
        Searcher(where, languages=["grc"], inflected=True) as rich,
    ):
        rich.search(GREEK["JHN 3:8"])
