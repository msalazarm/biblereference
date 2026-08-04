"""Versification tests.

The interesting cases are the ones where traditions genuinely disagree. Each test below
names a divergence that a theological citation would get wrong if the mapping were
ignored, so the assertions double as documentation of what the data claims.
"""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

import pytest

from biblereference.refs import VerseRef, parse_reference
from biblereference.versification import (
    AVAILABLE_SYSTEMS,
    DEFAULT_SYSTEMS,
    PIVOT,
    VerseOutOfRangeError,
    Versification,
    VersificationGapError,
    fingerprint,
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
    """Bel opens at 13:65, not 14:1, and that is not a quirk of this data.

    The Clementine prints 'Et rex Astyages appositus est ad patres suos' -- the Greek's
    Bel 1:1 -- as a sixty-fifth verse of Susanna, and begins its chapter 14 at the Greek's
    second verse. An earlier reading of this repository took the two upstream entries for
    alternative printings of one verse and preferred 14:1, which displaced the whole book
    by one; the Douay-Rheims settles it, matching Bel 1:n+1 on 41 of 42 verses.
    """
    assert convert(vrs, "Dan 13:1-64", "vul", "org") == "SUS 1:1-64"
    assert convert(vrs, "Sus 1:1", "org", "vul") == "DAN 13:1"
    assert convert(vrs, "Bel 1:1", "org", "vul") == "DAN 13:65"
    assert convert(vrs, "Bel 1:2", "org", "vul") == "DAN 14:1"


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
    """The English counts the letter's heading as a verse and the Latin does not, so the
    English runs one ahead: its 6:2 is the letter's first verse, and its 6:73 the last.

    The heading and the first verse therefore both answer to org's LJE 1:1, which is why
    converting back gives a two-verse span rather than one. That is the honest answer --
    org does not number the heading separately, so there is nowhere else to put it.
    """
    assert convert(vrs, "Bar 6:1", "eng", "org") == "LJE 1:1"
    assert convert(vrs, "Bar 6:2", "eng", "org") == "LJE 1:1"
    assert convert(vrs, "Bar 6:73", "eng", "org") == "LJE 1:72"

    # Coming back gives Baruch 6, which is how English Bibles print it -- including at the
    # heading, where org's single first verse is the English heading and its first verse
    # together. That used to come back in the standalone naming, as LJE 1:1-2, because the
    # tie-break preferred the identity over the deprioritised book; writing the English
    # letter as three segments rather than one range settled it on the Baruch naming, which
    # is what the rest of the book already answered.
    assert convert(vrs, "LJE 1:1", "org", "eng") == "BAR 6:1-2"
    assert convert(vrs, "LJE 1:5", "org", "eng") == "BAR 6:6"
    assert convert(vrs, "LJE 1:72", "org", "eng") == "BAR 6:73"

    # The Latin, which does not number the heading, lines up one for one throughout.
    assert convert(vrs, "Bar 6:1", "vul", "org") == "LJE 1:1"
    assert convert(vrs, "Bar 6:72", "vul", "org") == "LJE 1:72"


def test_the_english_letter_of_jeremiah_is_not_one_straight_offset(vrs: Versification) -> None:
    """The heading is not the only place the two traditions divide differently, and writing
    it as a single range got the middle of the chapter wrong for a long time.

    English merges two verses at 6:43 -- "burning bran for incense; but if any of them,
    drawn by some that pass by, lie with him" is the Latin's 6:42 and 6:43 together -- and
    that cancels the heading's offset, so 6:44 to 6:50 agree exactly. English then splits
    the Latin's 6:50 across its own 6:50 and 6:51 (the Authorised Version prints 6:51 with
    a lower-case opening, "and it shall manifestly appear"), and the offset resumes.

    Before this was written down, "Whatsoever is done among them is false" resolved to
    "when any one of them lieth with him": a different sentence, seven verses running.
    """
    assert convert(vrs, "Bar 6:43", "eng", "org") == "LJE 1:42"
    assert convert(vrs, "Bar 6:44", "eng", "org") == "LJE 1:44"
    assert convert(vrs, "Bar 6:50", "eng", "org") == "LJE 1:50"
    assert convert(vrs, "Bar 6:51", "eng", "org") == "LJE 1:50"
    assert convert(vrs, "Bar 6:52", "eng", "org") == "LJE 1:51"

    # The standalone naming must say the same thing as the Baruch 6 naming.
    assert convert(vrs, "LJE 1:44", "eng", "org") == "LJE 1:44"
    assert convert(vrs, "LJE 1:51", "eng", "org") == "LJE 1:50"


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

    # And every chapter of Judith and Tobit, not merely the ones whose verse counts happen
    # to differ. Judith 6 and 12 and Tobit 12 used to convert by identity because their
    # counts coincide, which is the worst of both: most of the book refuses and a few
    # chapters quietly return a plausible verse containing different words.
    for text in ("Jdt 6:13", "Jdt 12:1", "Tob 12:1"):
        with pytest.raises(VersificationGapError):
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
    assert "Tobit" in message
    assert "do not divide this book the same way" in message
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

    There are now no exceptions at all. There used to be one -- the Bel and the Dragon
    preference, where 13:65 converted out to Bel 1:1 and came back as 14:1 -- and it was
    documented here as principled. It was not: it was the symptom of a mapping that had
    the whole book one verse out. Correcting that closed the last hole, so this asserts an
    empty list rather than a curated exception.
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
                    try:
                        back = vrs.convert_all(vrs.convert(ref, "org"), name)
                    except VersificationGapError:
                        # A refusal is an answer. Systems carry text the pivot does not --
                        # the pluses in Greek Joshua and Proverbs, the Song's sixty-eighth
                        # verse -- and saying so is the point.
                        continue
                    if ref in back or (back and back[0].book != ref.book):
                        continue
                    unexplained.append(f"{name}: {ref} -> {back}")

    assert unexplained == [], unexplained


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


# --------------------------------------------------------------------------------------
# A fingerprint of the data, for anything that stores what this library resolved
# --------------------------------------------------------------------------------------


def test_the_fingerprint_is_stable_across_calls() -> None:
    assert fingerprint() == fingerprint()


def test_the_fingerprint_covers_the_corrections_as_well_as_the_vendored_maps() -> None:
    """The whole point. A mapping fix is a change to corrections.json rather than a
    release, so a digest that only covered the vendored files would miss exactly the
    changes most likely to move a downstream index.

    Recomputed independently here rather than compared to a stored constant, which would
    only assert that the function is unchanged.
    """
    data = resources.files("biblereference.versification").joinpath("data")
    names = sorted(e.name for e in data.iterdir() if e.name.endswith(".json"))
    assert "corrections.json" in names

    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update(data.joinpath(name).read_bytes())
    digest.update(b"\x00systems\x00")
    digest.update(",".join(sorted(DEFAULT_SYSTEMS)).encode())

    assert fingerprint() == digest.hexdigest()


def test_the_fingerprint_moves_when_a_correction_does(tmp_path: Path) -> None:
    """A byte changed anywhere in the data must show, since that is the failure this
    exists to catch: an index built yesterday silently disagreeing with today's mappings."""
    data = resources.files("biblereference.versification").joinpath("data")
    names = sorted(e.name for e in data.iterdir() if e.name.endswith(".json"))

    def digest_over(altered: str) -> str:
        out = hashlib.sha256()
        for name in names:
            out.update(name.encode())
            raw = data.joinpath(name).read_bytes()
            out.update(raw + b" " if name == altered else raw)
        out.update(b"\x00systems\x00")
        out.update(",".join(sorted(DEFAULT_SYSTEMS)).encode())
        return out.hexdigest()

    assert digest_over("corrections.json") != fingerprint()
    assert digest_over("org.json") != fingerprint()


def test_the_fingerprint_distinguishes_which_systems_were_loaded() -> None:
    """rsc and rso carry mappings the default five do not, so loading them is a different
    answer and has to look like one."""
    assert fingerprint(DEFAULT_SYSTEMS) != fingerprint(AVAILABLE_SYSTEMS)


def test_the_fingerprint_is_not_merely_the_version() -> None:
    from biblereference import __version__

    assert fingerprint() != __version__


def test_jeromes_judith_is_a_different_text_rather_than_a_renumbering(
    vrs: Versification,
) -> None:
    """Measured before it was declared unmappable, aligning the Douay-Rheims against the
    World English Bible across the whole book: quality 0.289 where an ordinary book runs 0.6
    to 0.8, 72 verses of some 345 with no counterpart at all, and the offsets scattering
    *within* chapters -- seven distinct ones across the 21 matched verses of chapter 7.

    Judith 6 is the case that proves a coinciding verse count means nothing. Both number the
    chapter at 21, and the Douay's 6:9 "they tied Achior to a tree" is the Greek's 6:13
    "bound Achior, cast him down, left him at the foot of the hill".
    """
    for chapter in range(1, 17):
        with pytest.raises(VersificationGapError):
            vrs.convert_range(parse_reference(f"Jdt {chapter}:1"), "vul")


def test_only_the_vulgates_own_judith_stands_apart(vrs: Versification) -> None:
    """Confined to `vul` deliberately. The Nova Vulgata went back to the Greek for Judith
    and its verse counts are identical to org's, so eng, lxx, org and nvl line up with one
    another and only Jerome's numbering is unreachable."""
    assert convert(vrs, "JDT 6:1", "eng", "org") == "JDT 6:1"
    assert convert(vrs, "JDT 6:1", "eng", "nvl") == "JDT 6:1"
    assert convert(vrs, "JDT 16:1", "eng", "nvl") == "JDT 16:1"


def test_wisdom_and_baruch_are_not_swept_up_with_them(vrs: Versification) -> None:
    """The Vulgate follows the Greek for these, so they convert throughout and must keep
    doing so. Marking a book unreliable is a book-wide refusal and the temptation is to
    reach for it too readily."""
    assert convert(vrs, "WIS 3:1", "eng", "vul") == "WIS 3:1"
    assert convert(vrs, "BAR 1:1", "eng", "vul") == "BAR 1:1"


def test_sirach_is_left_mappable_because_it_partly_is(vrs: Versification) -> None:
    """The opposite call from Judith, and the reason the two are treated differently:
    Sirach 6 has a verified mapping, so a book-wide refusal would throw away a fix. Its
    unmapped chapters still refuse through the per-chapter guard."""
    assert convert(vrs, "SIR 6:23", "eng", "vul") == "SIR 6:24"
    with pytest.raises(VersificationGapError):
        vrs.convert_range(parse_reference("Sir 24:1"), "vul")


# --------------------------------------------------------------------------------------
# Editions that divide the same words differently
# --------------------------------------------------------------------------------------


def test_the_greek_malachi_puts_the_law_of_moses_last(vrs: Versification) -> None:
    """A three-verse rotation, not a shift, which is why a monotonic alignment could only
    ever report two thirds of it.

    Swete has "Remember the law of Moses my servant" at 4:6, after Elijah at 4:4 and the
    turning of hearts at 4:5; the Hebrew has the law first, at 3:22. Brenton, who numbers
    the chapter to 24 rather than splitting a fourth chapter off, prints the same order.
    Two Greek witnesses in two numberings, so this is the Septuagint and not one edition.
    """
    assert convert(vrs, "Mal 3:22", "org", "lxx") == "MAL 3:24"
    assert convert(vrs, "Mal 3:23", "org", "lxx") == "MAL 3:22"
    assert convert(vrs, "Mal 3:24", "org", "lxx") == "MAL 3:23"
    assert convert(vrs, "Mal 3:24", "lxx", "org") == "MAL 3:22"


def test_the_clementine_puts_the_meek_before_those_who_mourn(vrs: Versification) -> None:
    """A real variant of the Latin tradition rather than a numbering habit: latvuc 5:4 is
    "Beati mites" and 5:5 "Beati qui lugent", where the Greek, the Nova Vulgata and every
    English witness have them the other way round. Upstream recorded identity, so both
    beatitudes answered with the wrong verse."""
    assert convert(vrs, "Matt 5:4", "org", "vul") == "MAT 5:5"
    assert convert(vrs, "Matt 5:5", "org", "vul") == "MAT 5:4"
    assert convert(vrs, "Matt 5:3", "org", "vul") == "MAT 5:3"
    assert convert(vrs, "Matt 5:6", "org", "vul") == "MAT 5:6"


def test_a_merged_verse_names_the_one_the_identity_will_not_reach(vrs: Versification) -> None:
    """The rule that keeps both halves of a merged verse reachable.

    A verse carrying two org verses can name only one of them, because the forward
    direction is one to one, and the reverse fills gaps with the identity. So the target to
    name is the one the identity will *not* reach.

    Where the system is in step before the merge and one behind after -- the Douay's
    Matthew 17:14, which carries both "there came to him a man falling down on his knees"
    and "Lord, have mercy on my son" -- name the second, and the identity still covers the
    first. Naming the first instead left org 17:15 resolving to "and I brought him to thy
    disciples".
    """
    assert convert(vrs, "Matt 17:14", "org", "vul") == "MAT 17:14"
    assert convert(vrs, "Matt 17:15", "org", "vul") == "MAT 17:14"
    assert convert(vrs, "Matt 17:16", "org", "vul") == "MAT 17:15"

    # And the mirror image: where the system is one ahead before the merge and in step
    # after, name the first, because there the identity covers the second. The Douay's
    # Micah 5:11 carries org 5:10 and 5:11, and org 5:11 gets home by the identity.
    assert convert(vrs, "Mic 5:10", "org", "vul") == "MIC 5:11"
    assert convert(vrs, "Mic 5:11", "org", "vul") == "MIC 5:11"
    assert convert(vrs, "Mic 5:9", "org", "vul") == "MIC 5:10"


def test_the_douay_splits_the_law_of_the_menstruant(vrs: Versification) -> None:
    """Found as a run of four consecutive contradicted verses in the exhaustive walk, and
    it was a real fault rather than the repetition it looked like.

    The Hebrew's Leviticus 15:19 carries both "she shall be seven days in her impurity"
    and "whoever touches her shall be unclean until the evening"; the Douay divides them at
    15:19 and 15:20 while the Nova Vulgata keeps them together. Everything to 15:23 was
    displaced, so "everything that she lies on shall be unclean" answered with "every one
    that toucheth her".
    """
    assert convert(vrs, "Lev 15:19", "org", "vul") == "LEV 15:19-20"
    assert convert(vrs, "Lev 15:20", "org", "vul") == "LEV 15:21"
    assert convert(vrs, "Lev 15:22", "org", "vul") == "LEV 15:23"
    assert convert(vrs, "Lev 15:24", "org", "vul") == "LEV 15:24"
    # The Nova Vulgata follows the Hebrew here, so the two Latin editions differ.
    assert convert(vrs, "Lev 15:20", "org", "nvl") == "LEV 15:20"


def test_the_two_latin_editions_agree_about_nehemiah_7(vrs: Versification) -> None:
    """org has no counterpart to the horses of Nehemiah 7:68 -- the Leningrad Codex gives
    the chapter 72 verses and goes straight from the singers to the camels -- and the
    Clementine said so while the Nova Vulgata and the English did not. That made three
    traditions disagree across five verses they in fact number alike."""
    for system in ("eng", "vul", "nvl"):
        assert convert(vrs, "Neh 7:68", system, "org") == "NEH 7:67", system
        assert convert(vrs, "Neh 7:69", system, "org") == "NEH 7:68", system
        assert convert(vrs, "Neh 7:72", system, "org") == "NEH 7:71", system
    # The Clementine numbers a 73rd verse where the Nova Vulgata folds it into its 72nd.
    assert convert(vrs, "Neh 7:73", "vul", "org") == "NEH 7:72"


def test_the_greek_numbers_moves_the_cloud_to_the_end_of_the_chapter(vrs: Versification) -> None:
    """The second three-verse rotation in the data, and the same shape as Malachi's.

    Brenton has "Arise, O Lord" at 10:34 and "and the cloud overshadowed them by day" at
    10:36; the Hebrew, the Clementine and the Nova Vulgata all put the cloud first, at
    10:34, with the two sayings after it. Upstream recorded identity, so all three answered
    with the wrong verse.
    """
    assert convert(vrs, "Num 10:34", "org", "lxx") == "NUM 10:36"
    assert convert(vrs, "Num 10:35", "org", "lxx") == "NUM 10:34"
    assert convert(vrs, "Num 10:36", "org", "lxx") == "NUM 10:35"
    assert convert(vrs, "Num 10:34", "lxx", "org") == "NUM 10:35"
    # The Latin follows the Hebrew here, so lxx and vul disagree and eng and vul do not.
    assert convert(vrs, "Num 10:34", "org", "vul") == "NUM 10:34"


def test_the_daughters_plea_is_missing_from_both_latin_and_greek(vrs: Versification) -> None:
    """org's Numbers 27:4 -- "why should the name of our father be withdrawn from among his
    family, because he has no son?" -- has no counterpart in the Clementine or the
    Septuagint, both of which go straight from the sedition to Moses referring the case.

    The Septuagint entry was already written; the Clementine's was not, so the two Latin
    editions disagreed across four verses -- the Nova Vulgata restores the plea at its own
    27:4.
    """
    for system in ("lxx", "vul"):
        assert convert(vrs, "Num 27:4", system, "org") == "NUM 27:5", system
        assert convert(vrs, "Num 27:7", system, "org") == "NUM 27:8", system
    assert convert(vrs, "Num 27:4", "nvl", "org") == "NUM 27:4"
    assert convert(vrs, "Num 27:5", "eng", "vul") == "NUM 27:4"


def test_a_merge_and_a_split_that_cancel(vrs: Versification) -> None:
    """Both chapters end at the same verse and the numbering still diverges in the middle,
    which is exactly the case verse counts cannot see.

    Greek Numbers 21 runs org's 21:19 and 21:20 together at its own 21:19, then splits
    org's 21:22 across its 21:21 and 21:22. The two cancel, so the chapter ends at 35 on
    both sides while three verses in between were displaced.
    """
    assert convert(vrs, "Num 21:19", "lxx", "org") == "NUM 21:20"
    assert convert(vrs, "Num 21:21", "lxx", "org") == "NUM 21:22"
    assert convert(vrs, "Num 21:23", "lxx", "org") == "NUM 21:23"
    assert vrs.max_verse("lxx", "NUM", 21) == vrs.max_verse("org", "NUM", 21) == 35

    # The Douay does the same thing in Numbers 15, merging org 15:15 and 15:16 and then
    # splitting org 15:18. Both chapters end at 41.
    assert convert(vrs, "Num 15:15", "vul", "org") == "NUM 15:16"
    assert convert(vrs, "Num 15:19", "vul", "org") == "NUM 15:19"
    assert vrs.max_verse("vul", "NUM", 15) == vrs.max_verse("org", "NUM", 15) == 41
