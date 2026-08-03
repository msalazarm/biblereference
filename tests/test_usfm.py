"""USFM extraction.

The samples below are shaped like what eBible.org actually distributes, including the
word-level markup that carries lemma data -- the thing that, left in, puts
``|strong="H6032"`` in the middle of a quoted sentence.
"""

from __future__ import annotations

from biblereference.corpora.usfm import clean, parse_usfm

SAMPLE = """\\id TOB
\\h Tobit
\\toc1 Tobit
\\mt1 TOBIT
\\c 1
\\p
\\v 1 Tobias of the tribe of Nephtali,
\\v 2 When he was made captive in the days of Salmanasar,
\\c 2
\\p
\\v 1 But after this, when there was a festival of the Lord,
"""


def test_reads_book_chapter_and_verse() -> None:
    assert list(parse_usfm(SAMPLE)) == [
        ("TOB", 1, 1, "Tobias of the tribe of Nephtali,"),
        ("TOB", 1, 2, "When he was made captive in the days of Salmanasar,"),
        ("TOB", 2, 1, "But after this, when there was a festival of the Lord,"),
    ]


def test_headings_are_not_verse_text() -> None:
    verses = dict(((c, v), t) for _, c, v, t in parse_usfm(SAMPLE))
    assert "TOBIT" not in verses[(1, 1)]
    assert "Tobit" not in verses[(1, 1)]


def test_word_level_markup_keeps_the_word_and_drops_the_lemma() -> None:
    text = '\\v 24 \\w And|strong="H6032"\\w* \\w they|strong="H0116"\\w* walked'
    assert clean(text.split(" ", 2)[2]) == "And they walked"


def test_footnotes_and_cross_references_are_dropped() -> None:
    body = (
        "In the beginning \\f + \\fr 1.1 \\ft Or, when God began to create \\f* "
        "God created heaven\\x - \\xo 1.1 \\xt Ps 33:6\\x*, and earth."
    )
    assert clean(body) == "In the beginning God created heaven, and earth."


def test_character_styles_keep_their_text() -> None:
    assert clean("The Lord \\add is\\add* my shepherd") == "The Lord is my shepherd"
    assert clean("\\nd Lord\\nd* God") == "Lord God"


def test_punctuation_stays_against_its_word() -> None:
    assert clean("\\wj Peace\\wj* , be still .") == "Peace, be still."
    assert clean("( \\add so\\add* )") == "(so)"


def test_a_verse_spanning_several_lines_is_joined() -> None:
    text = "\\id GEN\n\\c 1\n\\v 1 In the beginning\n\\q1 God created\n\\q2 heaven and earth.\n"
    assert list(parse_usfm(text)) == [
        ("GEN", 1, 1, "In the beginning God created heaven and earth.")
    ]


def test_a_verse_range_marker_takes_its_first_number() -> None:
    text = "\\id GEN\n\\c 1\n\\v 1-2 In the beginning God created heaven and earth.\n"
    assert next(iter(parse_usfm(text)))[2] == 1


def test_a_file_without_an_id_yields_nothing() -> None:
    assert list(parse_usfm("\\c 1\n\\v 1 orphaned text\n")) == []


def test_empty_verses_are_skipped() -> None:
    text = "\\id GEN\n\\c 1\n\\v 1 \n\\v 2 Real text.\n"
    assert [v for _, _, v, _ in parse_usfm(text)] == [2]
