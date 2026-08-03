"""Versification tests.

The interesting cases are the ones where traditions genuinely disagree. Each test below
names a divergence that a theological citation would get wrong if the mapping were
ignored, so the assertions double as documentation of what the data claims.
"""

from __future__ import annotations

import pytest

from biblereference.refs import VerseRef, parse_reference
from biblereference.versification import (
    AVAILABLE_SYSTEMS,
    PIVOT,
    VerseOutOfRangeError,
    Versification,
    VersificationGapError,
)


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


@pytest.mark.parametrize("system", AVAILABLE_SYSTEMS)
def test_every_advertised_system_actually_loads(system: str) -> None:
    """AVAILABLE_SYSTEMS is a promise, and for a long time two of its members could not be
    loaded at all: the Russian Synodal files carried contradictory psalm mappings that made
    Versification.load raise. Nothing caught it because neither is in DEFAULT_SYSTEMS, so
    nothing loaded them unless asked by name. Advertised and loadable are now the same
    list, and this is what keeps them that way."""
    loaded = Versification.load((PIVOT, system))

    assert system in loaded.system_names
    assert loaded.chapter_count(system, "PSA") > 0


def test_all_systems_load_together() -> None:
    """Loading them one at a time is not the same test: the loader builds each against the
    pivot, and a fault in one must not be masked by the others."""
    loaded = Versification.load(AVAILABLE_SYSTEMS)

    assert loaded.system_names == tuple(AVAILABLE_SYSTEMS)


def convert(vrs: Versification, text: str, source: str, target: str) -> str:
    spans = vrs.convert_range(parse_reference(text, vrs=source), target)
    return ", ".join(str(s) for s in spans)


# --------------------------------------------------------------------------------------
# Psalms
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "target", "expected"),
    [
        # The Septuagint and Vulgate run one behind from Psalm 10 to Psalm 147.
        ("Ps 23:1-6", "lxx", "PSA 22:1-6"),
        ("Ps 23:1", "vul", "PSA 22:1"),
        # ...because Greek Psalm 9 is Hebrew 9 and 10 together.
        ("Ps 10:1", "lxx", "PSA 9:22"),
        # ...and rejoins after Greek 146+147 become Hebrew 147.
        ("Ps 147:1", "lxx", "PSA 146:1"),
        ("Ps 148:1", "lxx", "PSA 148:1"),
    ],
)
def test_psalm_numbering(vrs: Versification, text: str, target: str, expected: str) -> None:
    assert convert(vrs, text, "eng", target) == expected


def test_hebrew_psalm_superscriptions_are_numbered_verses(vrs: Versification) -> None:
    """Psalm 51's two-verse heading ("when Nathan the prophet came to him") pushes the
    body down by two in the Hebrew."""
    assert convert(vrs, "Ps 51:1", "eng", "org") == "PSA 51:3"


def test_psalm_titles_are_verse_zero_where_numbered_separately(vrs: Versification) -> None:
    assert vrs.first_verse("eng", "PSA", 3) == 0
    assert vrs.first_verse("eng", "PSA", 1) == 1  # Psalm 1 has no superscription


# --------------------------------------------------------------------------------------
# Daniel and the Greek additions
# --------------------------------------------------------------------------------------


def test_song_of_the_three_is_a_separate_book_in_the_hebrew_frame(vrs: Versification) -> None:
    assert convert(vrs, "Dan 3:24-90", "vul", "org") == "S3Y 1:1-67"


def test_susanna_and_bel_are_daniel_13_and_14_in_the_vulgate(vrs: Versification) -> None:
    assert convert(vrs, "Dan 13:1-64", "vul", "org") == "SUS 1:1-64"
    assert convert(vrs, "Sus 1:1", "org", "vul") == "DAN 13:1"
    assert convert(vrs, "Bel 1:1", "org", "vul") == "DAN 14:1"


def test_a_range_that_straddles_an_addition_comes_back_in_pieces(vrs: Versification) -> None:
    """Vulgate Daniel 3 contains material the Hebrew frame files under another book, so
    the result cannot honestly stay a single span."""
    assert convert(vrs, "Dan 3:1-100", "vul", "org") == "DAN 3:1-33, S3Y 1:1-67"


def test_english_daniel_4_opens_three_verses_into_the_hebrew_chapter_3(
    vrs: Versification,
) -> None:
    assert convert(vrs, "Dan 4:1", "eng", "org") == "DAN 3:31"


def test_greek_daniel_carries_the_song_inline(vrs: Versification) -> None:
    """Greek Daniel 3 runs to 97 verses because the Song sits inside it, so Hebrew 3:24
    is Greek 3:91."""
    assert convert(vrs, "Dan 3:24", "org", "lxx") == "DAG 3:91"
    assert convert(vrs, "S3Y 1:1", "org", "lxx") == "DAG 3:24"


def test_vulgate_daniel_is_preferred_over_greek_daniel(vrs: Versification) -> None:
    """The Vulgate versification defines Daniel twice; a Douay-Rheims corpus prints DAN."""
    assert convert(vrs, "Dan 3:24", "org", "vul").startswith("DAN")
    assert convert(vrs, "S3Y 1:1", "org", "vul") == "DAN 3:24"


# --------------------------------------------------------------------------------------
# Books absorbed into other books
# --------------------------------------------------------------------------------------


def test_letter_of_jeremiah_is_baruch_6(vrs: Versification) -> None:
    assert convert(vrs, "Bar 6:1", "eng", "org") == "LJE 1:1"
    assert convert(vrs, "LJE 1:1", "org", "eng") == "BAR 6:1"


# --------------------------------------------------------------------------------------
# Split verses
# --------------------------------------------------------------------------------------


def test_a_verse_split_in_two_returns_both_halves(vrs: Versification) -> None:
    """Hebrew Isaiah 63:19 runs on into what English numbers 64:1 ("Oh that thou wouldest
    rend the heavens"). Quoting only the first half would misrepresent the verse."""
    assert convert(vrs, "Isa 63:19", "org", "eng") == "ISA 63:19, ISA 64:1"
    assert convert(vrs, "Isa 64:1", "eng", "org") == "ISA 63:19"


def test_convert_returns_where_the_text_begins(vrs: Versification) -> None:
    ref = VerseRef("ISA", 63, 19, vrs="org")
    assert vrs.convert(ref, "eng") == VerseRef("ISA", 63, 19, vrs="eng")
    assert len(vrs.convert_all(ref, "eng")) == 2


# --------------------------------------------------------------------------------------
# Other well-known divergences
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mal 4:1", "MAL 3:19"),  # Hebrew Malachi has three chapters, not four
        ("Joel 2:28", "JOL 3:1"),
        ("Isa 9:1", "ISA 8:23"),
        ("Neh 4:1", "NEH 3:33"),
        ("Exod 8:1", "EXO 7:26"),
        # Hebrew Numbers starts chapter 17 fifteen verses earlier than English does.
        ("Num 16:36", "NUM 17:1"),
        ("Num 17:1", "NUM 17:16"),
    ],
)
def test_english_to_hebrew_divergences(vrs: Versification, text: str, expected: str) -> None:
    assert convert(vrs, text, "eng", "org") == expected


def test_verses_that_agree_everywhere_pass_straight_through(vrs: Versification) -> None:
    for text in ["Luke 2:42", "John 3:16", "Gen 1:1", "Sir 24:1-9", "2 Macc 7:28"]:
        book_chapter_verse = str(parse_reference(text))
        assert convert(vrs, text, "eng", "org") == book_chapter_verse


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_citing_past_the_end_of_a_chapter_is_caught(vrs: Versification) -> None:
    with pytest.raises(VerseOutOfRangeError, match="has 30 verses"):
        vrs.validate(parse_reference("Sir 51:31"))
    vrs.validate(parse_reference("Sir 51:30"))


def test_citing_a_chapter_a_book_does_not_have_is_caught(vrs: Versification) -> None:
    with pytest.raises(VerseOutOfRangeError, match="12 chapters"):
        vrs.validate(parse_reference("Dan 14:1"))
    vrs.validate(parse_reference("Dan 14:1", vrs="vul"))


def test_psalm_151_exists_only_in_the_greek(vrs: Versification) -> None:
    with pytest.raises(VerseOutOfRangeError):
        vrs.validate(parse_reference("Ps 151:1"))
    vrs.validate(parse_reference("Ps 151:1", vrs="lxx"))


# --------------------------------------------------------------------------------------
# Refusing to convert what the data cannot line up
# --------------------------------------------------------------------------------------


def test_vulgate_sirach_tobit_and_judith_refuse_conversion(vrs: Versification) -> None:
    """Jerome translated these three from source texts differing from the Greek by whole
    clauses -- the Vulgate's Sirach runs 1605 verses to the Greek's 1401 -- and upstream
    carries no mapping at all. Converting would yield a plausible verse number pointing at
    different words."""
    for text in ("Sir 24:1", "Tob 5:1", "Jdt 8:1"):
        with pytest.raises(VersificationGapError, match="does not say how"):
            vrs.convert_range(parse_reference(text), "vul")


def test_transposed_sirach_chapters_refuse_but_the_rest_of_sirach_works(
    vrs: Versification,
) -> None:
    """Greek Sirach manuscripts transpose 30:25-33:16a with 33:16b-36:13a, so English and
    the original-language numbering diverge in a handful of chapters -- and only there."""
    assert convert(vrs, "Sir 24:1-9", "eng", "org") == "SIR 24:1-9"
    assert convert(vrs, "Sir 24:1-9", "eng", "lxx") == "SIR 24:1-9"
    assert convert(vrs, "Sir 51:1", "eng", "lxx") == "SIR 51:1"
    for text in ("Sir 33:1", "Sir 35:1", "Sir 36:1"):
        with pytest.raises(VersificationGapError):
            vrs.convert_range(parse_reference(text), "org")


def test_the_refusal_says_what_to_do_instead(vrs: Versification) -> None:
    with pytest.raises(VersificationGapError) as excinfo:
        vrs.convert_range(parse_reference("Tob 5:1"), "vul")
    message = str(excinfo.value)
    assert "Tobit chapter 5" in message
    assert "divided differently" in message
    assert "cite the passage" in message


def test_books_that_agree_are_not_swept_up_by_the_guard(vrs: Versification) -> None:
    """The guard must stay narrow: it flags chapters, not whole traditions."""
    assert convert(vrs, "2 Macc 7:28", "eng", "vul") == "2MA 7:28"
    assert convert(vrs, "Wis 2:12-20", "eng", "lxx") == "WIS 2:12-20"
    assert convert(vrs, "Bar 1:1", "eng", "org") == "BAR 1:1"
    assert ("PSA", 23) not in vrs.unmappable_chapters("lxx")
    assert ("LUK", 2) not in vrs.unmappable_chapters("vul")


def test_the_septuagints_own_esther_numbering_raises_rather_than_guessing(
    vrs: Versification,
) -> None:
    """ESG is the Septuagint's interleaved Esther, whose upstream data is
    self-contradictory. The A-F letter chapters are handled instead; see test_esther.py."""
    with pytest.raises(VersificationGapError, match=r"corrections\.json"):
        vrs.convert(VerseRef("ESG", 1, 1, vrs="eng"), "org")


# --------------------------------------------------------------------------------------
# Whole-data invariants
# --------------------------------------------------------------------------------------


def test_every_reverse_mapping_agrees_with_its_forward_mapping(vrs: Versification) -> None:
    for name in vrs.system_names:
        system = vrs._systems[name]
        for org_coord, sources in system.from_org.items():
            for source in sources:
                assert system.to_org.get(source, source) == org_coord, (
                    f"{name}: {source} does not map back to {org_coord}"
                )


def test_every_verse_survives_a_round_trip_through_the_pivot(vrs: Versification) -> None:
    """For each system, every verse converts to org and back to something covering it.

    Exceptions are principled and few: a book the system prints inside another (Susanna
    as Daniel 13) comes back under the host book, and one documented editorial choice
    picks Daniel 14:1 over 13:65 for the opening of Bel.
    """
    unexplained: list[str] = []
    for name in ("eng", "lxx", "vul"):
        system = vrs._systems[name]
        blocked = vrs.unmappable_chapters(name)
        for book in system.max_verses:
            if book in system.unreliable_books:
                continue
            for chapter in range(1, vrs.chapter_count(name, book) + 1):
                if (book, chapter) in blocked:
                    continue
                low = vrs.first_verse(name, book, chapter)
                high = vrs.max_verse(name, book, chapter)
                for verse in range(low, high + 1):
                    ref = VerseRef(book, chapter, verse, vrs=name)
                    back = vrs.convert_all(vrs.convert(ref, "org"), name)
                    if ref in back or (back and back[0].book != ref.book):
                        continue
                    unexplained.append(f"{name}: {ref} -> {back}")

    # The single expected residual is the documented Bel and the Dragon preference.
    assert unexplained == [
        "vul: DAN 13:65 -> [VerseRef(book='DAN', chapter=14, verse=1, subverse='', vrs='vul')]"
    ], unexplained


def test_loading_validates_the_corrections_still_apply(vrs: Versification) -> None:
    """Loading raises if a documented correction no longer matches upstream, which is how
    a refresh of the vendored data announces that a fix can be dropped."""
    assert vrs.system_names == ("org", "eng", "lxx", "vul", "nvl")


# --------------------------------------------------------------------------------------
# The Nova Vulgata's own numbering
# --------------------------------------------------------------------------------------


def test_the_nova_vulgata_has_a_versification_of_its_own(vrs: Versification) -> None:
    """It is the Church's official Latin text and numbers as it numbers. Filing it under
    another edition's divisions would mean dropping the chapters that do not fit."""
    assert vrs.has_book("nvl", "PSA")
    assert vrs.chapter_count("nvl", "PSA") == 150
    # Psalm 12 prints as one verse what the Masoretic frame splits into two.
    assert vrs.max_verse("nvl", "PSA", 12) == 8
    assert vrs.max_verse("org", "PSA", 12) == 9


def test_it_numbers_by_the_hebrew_not_the_vulgate(vrs: Versification) -> None:
    """Its Psalm 23 is the Hebrew's 23, headed "PSALMUS 23 (22)"."""
    assert convert(vrs, "Ps 23:1", "eng", "nvl") == "PSA 23:1"
    assert convert(vrs, "Ps 23:1", "eng", "vul") == "PSA 22:1"


def test_it_keeps_the_vulgates_arrangement_of_the_additions(vrs: Versification) -> None:
    """Susanna is its Daniel 13, and the Letter of Jeremiah its Baruch 6 -- each checked
    to align exactly on its own verse counts."""
    assert vrs.chapter_count("nvl", "DAN") == 14
    assert convert(vrs, "Sus 1:1", "org", "nvl") == "DAN 13:1"
    assert convert(vrs, "Bel 1:1", "org", "nvl") == "DAN 14:1"
    assert convert(vrs, "LJE 1:1", "org", "nvl") == "BAR 6:1"
    assert convert(vrs, "S3Y 1:1", "org", "nvl") == "DAN 3:24"


def test_where_it_differs_conversion_refuses_rather_than_shifting(
    vrs: Versification,
) -> None:
    with pytest.raises(VersificationGapError):
        vrs.convert_range(parse_reference("Ps 12:1"), "nvl")
    # Its Sirach follows the Vulgate's expanded numbering throughout.
    with pytest.raises(VersificationGapError):
        vrs.convert_range(parse_reference("Sir 1:1"), "nvl")
