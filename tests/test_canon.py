from __future__ import annotations

import pytest

from biblereference.canon import (
    CANONICAL_ORDER,
    SINGLE_CHAPTER_BOOKS,
    AmbiguousBookError,
    Canon,
    NamingScheme,
    UnknownBookError,
    book_canon,
    book_title,
    normalize_book,
    resolve_book,
)
from biblereference.emphasis import fold

DR = NamingScheme.DR
LXX = NamingScheme.LXX
MODERN = NamingScheme.MODERN


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Genesis", "GEN"),
        ("gen", "GEN"),
        ("Gn.", "GEN"),
        ("1 Cor", "1CO"),
        ("1Cor", "1CO"),
        ("I Corinthians", "1CO"),
        ("First Corinthians", "1CO"),
        ("1st Corinthians", "1CO"),
        ("II Machabees", "2MA"),
        ("2 Macc.", "2MA"),
        ("Song of Solomon", "SNG"),
        ("Canticle of Canticles", "SNG"),
        ("Apocalypse", "REV"),
        ("Ecclesiasticus", "SIR"),
        ("Sirach", "SIR"),
        ("Bel and the Dragon", "BEL"),
        ("Prayer of Azariah", "S3Y"),
        ("Letter of Jeremiah", "LJE"),
        ("Psalm 151", "PS2"),
    ],
)
def test_resolves_common_names(name: str, expected: str) -> None:
    assert resolve_book(name) == expected


@pytest.mark.parametrize(
    ("name", "scheme", "expected"),
    [
        # Douay-Rheims counts Samuel and Kings together as four books of Kings.
        ("1 Kings", MODERN, "1KI"),
        ("1 Kings", DR, "1SA"),
        ("2 Kings", DR, "2SA"),
        ("3 Kings", MODERN, "1KI"),  # unambiguous: no tradition means anything else
        ("4 Kings", DR, "2KI"),
        ("1 Paralipomenon", MODERN, "1CH"),
        # "1 Esdras" is Ezra in Douay-Rheims, the Greek Esdras in the Septuagint.
        ("1 Esdras", DR, "EZR"),
        ("1 Esdras", LXX, "1ES"),
        ("2 Esdras", DR, "NEH"),
        ("2 Esdras", LXX, "2ES"),
        # A USFM code is a code, not a tradition-bound name.
        ("1ES", MODERN, "1ES"),
        ("1KI", DR, "1KI"),
    ],
)
def test_naming_schemes(name: str, scheme: NamingScheme, expected: str) -> None:
    assert resolve_book(name, scheme) == expected


@pytest.mark.parametrize("name", ["1 Esdras", "1 Esd", "2 Esdras", "2 Esd"])
def test_ambiguous_names_raise_rather_than_guess(name: str) -> None:
    """Modern usage is split between the Douay-Rheims sense (Ezra, Nehemiah) and the
    Septuagint / KJV-Apocrypha sense (the Greek Esdras, 4 Ezra). A wrong guess here
    produces a citation that looks right and is not."""
    with pytest.raises(AmbiguousBookError, match="ambiguous"):
        resolve_book(name, MODERN)


def test_kings_resolves_per_tradition_without_raising() -> None:
    """Unlike Esdras, every tradition has a reading for "1 Kings": Douay-Rheims means
    1 Samuel, and the Septuagint says "Kingdoms" so only the modern sense is available."""
    assert resolve_book("1 Kings", DR) == "1SA"
    assert resolve_book("1 Kings", MODERN) == "1KI"
    assert resolve_book("1 Kings", LXX) == "1KI"


def test_ambiguous_error_names_the_alternatives() -> None:
    with pytest.raises(AmbiguousBookError) as excinfo:
        resolve_book("1 Esdras", MODERN)
    message = str(excinfo.value)
    assert "Ezra" in message and "1 Esdras" in message
    assert "dr" in message and "lxx" in message


@pytest.mark.parametrize("name", ["Hezekiah", "", "   ", "Gospel of Thomas"])
def test_unknown_names_raise(name: str) -> None:
    with pytest.raises(UnknownBookError):
        resolve_book(name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Hb", "HEB"), ("Heb", "HEB"), ("Hab", "HAB"), ("Habacuc", "HAB")],
)
def test_hb_is_hebrews_not_habakkuk(name: str, expected: str) -> None:
    """Both books have claimed "Hb" in the wild; Hebrews is the common usage."""
    assert resolve_book(name) == expected


def test_bare_ez_is_rejected_as_too_ambiguous() -> None:
    """Writers use "Ez" for both Ezekiel and Ezra, so it resolves to neither."""
    with pytest.raises(UnknownBookError):
        resolve_book("Ez")
    assert resolve_book("Ezk") == "EZK"
    assert resolve_book("Ezr") == "EZR"


@pytest.mark.parametrize(
    ("book", "canon"),
    [
        ("GEN", Canon.HEBREW),
        ("PSA", Canon.HEBREW),
        ("SIR", Canon.DEUTERO),
        ("TOB", Canon.DEUTERO),
        ("SUS", Canon.DEUTERO),
        ("1MA", Canon.DEUTERO),
        ("LUK", Canon.NT),
        ("4MA", Canon.APPENDIX),
        ("PS2", Canon.APPENDIX),
    ],
)
def test_canon_membership(book: str, canon: Canon) -> None:
    assert book_canon(book) is canon


def test_deuterocanon_is_scripture_not_appendix() -> None:
    """The Catholic deuterocanon is a first-class canon group, distinct from the
    Septuagint extras that Catholics do not receive as scripture."""
    deutero = {b for b in CANONICAL_ORDER if book_canon(b) is Canon.DEUTERO}
    assert {"TOB", "JDT", "WIS", "SIR", "BAR", "LJE", "1MA", "2MA"} <= deutero
    assert {"SUS", "BEL", "S3Y", "ESG", "DAG"} <= deutero
    assert not deutero & {"3MA", "4MA", "PS2", "1ES", "2ES", "MAN"}


def test_canonical_order_places_deuterocanon_where_a_catholic_bible_prints_it() -> None:
    order = CANONICAL_ORDER.index
    assert order("NEH") < order("TOB") < order("JDT") < order("EST")
    assert order("SNG") < order("WIS") < order("SIR") < order("ISA")
    assert order("LAM") < order("BAR") < order("LJE") < order("EZK")
    assert order("MAL") < order("MAT")


def test_normalize_collapses_spelling_variants() -> None:
    assert normalize_book("1 Corinthians") == normalize_book("I Corinthians")
    assert normalize_book("1 Corinthians") == normalize_book("1st  Corinthians.")
    assert normalize_book("Song of Songs") == normalize_book("song-of-songs")


def test_single_chapter_books_include_short_deuterocanonical_pieces() -> None:
    assert {"SUS", "BEL", "LJE", "S3Y", "MAN", "PS2"} <= SINGLE_CHAPTER_BOOKS
    assert "SIR" not in SINGLE_CHAPTER_BOOKS


def test_every_ordered_book_has_a_title_and_a_canon() -> None:
    for book in CANONICAL_ORDER:
        assert book_title(book) != book or book in {"EZA", "JSA"}
        assert isinstance(book_canon(book), Canon)


# --------------------------------------------------------------------------------------
# Titles per tradition
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "modern", "dr"),
    [
        ("1CH", "1 Chronicles", "1 Paralipomenon"),
        ("SIR", "Sirach", "Ecclesiasticus"),
        ("REV", "Revelation", "Apocalypse"),
        ("SNG", "Song of Songs", "Canticle of Canticles"),
        ("1SA", "1 Samuel", "1 Kings"),
        ("1KI", "1 Kings", "3 Kings"),
        ("HOS", "Hosea", "Osee"),
        ("TOB", "Tobit", "Tobias"),
        ("ZEP", "Zephaniah", "Sophonias"),
    ],
)
def test_douay_rheims_titles(code: str, modern: str, dr: str) -> None:
    """A reader checking a citation in a Douay-Rheims will not find '1 Chronicles' in it."""
    assert book_title(code) == modern
    assert book_title(code, NamingScheme.DR) == dr


def test_books_the_vulgate_prints_inside_another_say_where_to_look() -> None:
    assert book_title("SUS", NamingScheme.DR) == "Daniel 13"
    assert book_title("BEL", NamingScheme.DR) == "Daniel 14"
    assert book_title("LJE", NamingScheme.DR) == "Baruch 6"


def test_septuagint_titles() -> None:
    assert book_title("1SA", NamingScheme.LXX) == "1 Kingdoms"
    assert book_title("1ES", NamingScheme.LXX) == "Esdras A"
    assert book_title("SIR", NamingScheme.LXX) == "Wisdom of Sirach"


def test_a_book_with_no_special_title_keeps_the_modern_one() -> None:
    for scheme in NamingScheme:
        assert book_title("LUK", scheme) == "Luke"
        assert book_title("GEN", scheme) == "Genesis"


# --------------------------------------------------------------------------------------
# Accents, and the German names they made unreachable
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Sprüche", "spruche"),
        ("Spruche", "spruche"),
        ("Hebräer", "hebraer"),
        ("Lérins", "lerins"),
        ("Æthelred", "aethelred"),
    ],
)
def test_normalize_book_decomposes_rather_than_deleting(written: str, expected: str) -> None:
    """The last step used to be ``[^a-z0-9]``, which does not fold a combining mark into
    its base letter -- it takes the letter with it. ``Sprüche`` normalised to ``sprche``
    and ``Lérins`` to ``lrins``, so an accented name and its unaccented spelling could
    never reach each other and an alias table only worked for whichever was written into
    it. The ligature path must keep working alongside the fix."""
    assert normalize_book(written) == expected


def test_normalize_book_and_fold_agree_on_accents() -> None:
    """Two normalisations that disagree are a bug factory: a name is looked up through one
    and its text is searched through the other."""
    for word in ["Sprüche", "Hebräer", "Lérins", "Ἰησοῦς", "λόγος"]:
        assert normalize_book(word) == fold(word).replace(" ", "")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Sacharja", "ZEC"),
        ("Sach", "ZEC"),
        ("1 Korinther", "1CO"),
        ("1Ko", "1CO"),
        ("Hebräer", "HEB"),
        ("Hebr", "HEB"),
        ("Offenbarung", "REV"),
        ("Prediger", "ECC"),
        ("Sprüche", "PRO"),
        ("Sprueche", "PRO"),
        ("Richter", "JDG"),
        ("Hoheslied", "SNG"),
        ("Klagelieder", "LAM"),
        ("Apostelgeschichte", "ACT"),
        ("Weisheit", "WIS"),
        ("1 Makkabäer", "1MA"),
        # The Pentateuch is numbered in German: 1. Mose is Genesis and 5. Mose Deuteronomy.
        ("1. Mose", "GEN"),
        ("5. Mose", "DEU"),
    ],
)
def test_german_book_names_resolve(name: str, code: str) -> None:
    assert resolve_book(name, NamingScheme.DE) == code


def test_both_spellings_of_an_umlaut_reach_the_same_book() -> None:
    """Two aliases of one book, not two books. A source may print either and a reader may
    type either, and before the normalisation fix neither could reach the other."""
    for umlaut, transliterated in [("Sprüche", "Sprueche"), ("Hebräer", "Hebraeer")]:
        assert resolve_book(umlaut, NamingScheme.DE) == resolve_book(
            transliterated, NamingScheme.DE
        )


def test_german_names_do_not_leak_into_the_modern_scheme() -> None:
    """Otherwise a German abbreviation silently shadows an English one."""
    for name in ["Sach", "Sprüche", "Offenbarung", "Apg", "Hebräer"]:
        with pytest.raises(UnknownBookError):
            resolve_book(name, NamingScheme.MODERN)


def test_no_german_alias_claims_a_book_an_english_one_already_means() -> None:
    """A cross-scheme collision resolves silently and wrongly, which is the failure mode
    this whole module exists to prevent. Within a scheme ``_expand`` raises on a duplicate;
    across schemes nothing does, so it is asserted here.

    Names shared with English -- Daniel, Amos, Titus -- are fine precisely because they
    mean the same book.
    """
    from biblereference.canon import _BY_SCHEME, _COMMON

    german = _BY_SCHEME[NamingScheme.DE]
    clashes = {
        key: (code, _COMMON[key])
        for key, code in german.items()
        if key in _COMMON and _COMMON[key] != code
    }
    assert clashes == {}


def test_a_scheme_without_titles_of_its_own_falls_back_to_english() -> None:
    """DE exists so German citations can be read. Rendering titles in German is a separate
    thing, and a half-built table would be worse than English."""
    assert book_title("LUK", NamingScheme.DE) == "Luke"
