"""Reading verses out of TEI.

The tests are ordered by how badly the failure would go unnoticed. The first one is the
worst thing that could happen here and would pass every other check this project has.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from biblereference.corpora.tei import (
    GAP,
    ab_verses,
    cts_verses,
    flatten,
    milestone_verses,
    parse_n,
    read_licence,
)

NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def parse(markup: str) -> etree._Element:
    return etree.fromstring(f"<TEI {NS}>{markup}</TEI>".encode())


# --------------------------------------------------------------------------------------
# The apparatus, which is the one that matters
# --------------------------------------------------------------------------------------


def test_an_apparatus_keeps_the_reading_the_editor_chose_and_drops_the_rest() -> None:
    """7,028 of these across the Greek, 829 in Matthew alone.

    Joining all the text under an <app> yields the editor's reading followed by every one
    he rejected. The result is plausible Greek of about the right length, and it passes
    verse counts, chapter ends and the whole coverage walk. Nothing else here would catch
    it, which is why this is the first test in the file.
    """
    verse = parse(
        "<ab>"
        "<w>Σαλμὼν</w><w>δὲ</w><w>ἐγέννησεν</w><w>τὸν</w>"
        '<app type="variants">'
        '<lem source="#WH #NIV"><w>Βόες</w><w>ἐκ</w><w>τῆς</w><w>Ῥαχάβ</w></lem>'
        '<rdg source="#Treg">Βοὸς … Βοὸς</rdg>'
        '<rdg source="#RP">Βοὸζ … Βοὸζ</rdg>'
        "</app>"
        "<w>δὲ</w>"
        "</ab>"
    )[0]
    assert flatten(verse) == "Σαλμὼν δὲ ἐγέννησεν τὸν Βόες ἐκ τῆς Ῥαχάβ δὲ"
    assert "Βοὸς" not in flatten(verse)
    assert "Βοὸζ" not in flatten(verse)


# --------------------------------------------------------------------------------------
# Spacing
# --------------------------------------------------------------------------------------


def test_words_are_separated_and_punctuation_is_not() -> None:
    """The Greek New Testament writes one element per word with no whitespace between
    them, so a naive join gives ΒίβλοςγενέσεωςἸησοῦ.
    """
    verse = parse("<ab><w>Βίβλος</w><w>γενέσεως</w><w>Ἰησοῦ</w><pc>.</pc></ab>")[0]
    assert flatten(verse) == "Βίβλος γενέσεως Ἰησοῦ."


def test_punctuation_attaches_even_across_the_indentation_between_them() -> None:
    """The files are pretty-printed, so the whitespace between <w> and <pc> is real text
    in the tree. Stripping it after the fact fails the moment anything sits between them.
    """
    verse = parse("<ab>\n  <w>Ἀβραάμ</w>\n  <pc>,</pc>\n  <w>Ἰσαὰκ</w>\n</ab>")[0]
    assert flatten(verse) == "Ἀβραάμ, Ἰσαὰκ"


def test_prose_keeps_its_own_spacing() -> None:
    """Most of the Old Testament is a <p> of ordinary running text, not one word per
    element, and it must come through unchanged apart from collapsed whitespace.
    """
    verse = parse("<p>Ἐν ἀρχῇ ἐποίησεν ὁ θεὸς\n     τὸν οὐρανὸν καὶ τὴν γῆν.</p>")[0]
    assert flatten(verse) == "Ἐν ἀρχῇ ἐποίησεν ὁ θεὸς τὸν οὐρανὸν καὶ τὴν γῆν."


def test_a_line_break_that_says_the_word_continues_does_not_split_it() -> None:
    verse = parse('<p>Χανα<lb break="no"/>ναίους</p>')[0]
    assert flatten(verse) == "Χαναναίους"
    plain = parse('<p>πρὸς<lb n="2"/>αὐτούς</p>')[0]
    assert flatten(plain) == "πρὸς αὐτούς"


# --------------------------------------------------------------------------------------
# What is text and what is not
# --------------------------------------------------------------------------------------


def test_editorial_notes_are_not_text() -> None:
    """Ottley's Isaiah carries 707 of them and the Greek Judges puts a manuscript siglum
    in the middle of a sentence.
    """
    verse = parse(
        '<p>καὶ ἐπηρώτων οἱ υἱοὶ <note type="marginal">Β</note> Ἰσραὴλ διὰ τοῦ κυρίου</p>'
    )[0]
    assert flatten(verse) == "καὶ ἐπηρώτων οἱ υἱοὶ Ἰσραὴλ διὰ τοῦ κυρίου"


def test_a_lacuna_leaves_a_mark_rather_than_closing_over() -> None:
    """The Old Latin gospels are printed from mutilated manuscripts and the editor set the
    holes rather than filling them. Healing one silently invents a reading.
    """
    verse = parse("<p>Liber generatio<gap/>Christi filii Da<gap/>Abraham</p>")[0]
    assert flatten(verse) == f"Liber generatio {GAP} Christi filii Da {GAP} Abraham"


def test_supplied_and_emphasised_text_is_still_text() -> None:
    verse = parse("<p>and <supplied>the</supplied> <hi rend='italic'>word</hi></p>")[0]
    assert flatten(verse) == "and the word"


# --------------------------------------------------------------------------------------
# The @n grammar, measured over all 177 archive files rather than assumed
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12", (12, "")),
        ("1", (1, "")),
        # Esther's and Daniel's Greek additions, which run 12a through 12x. The letter is
        # a subverse, which VerseRef already models and already prints.
        ("12a", (12, "a")),
        ("13g", (13, "g")),
        # A superscription. Verse 0 is what the shipped versification means by a title.
        ("t", (0, "")),
        (" 7 ", (7, "")),
    ],
)
def test_the_n_grammar(value: str, expected: tuple[int, str]) -> None:
    assert parse_n(value) == expected


@pytest.mark.parametrize("value", [None, "", "p", "24a-b", "iv", "unnumbered"])
def test_what_is_not_a_verse_number_is_refused(value: str | None) -> None:
    """Sirach's prologue is chapter `p`, and Greek Proverbs has chapters 24a, 30a and 31a
    that the Hebrew does not. No versification declares any of them, so importing them
    would put verses where nothing can cite them.
    """
    assert parse_n(value) is None


# --------------------------------------------------------------------------------------
# The three shapes
# --------------------------------------------------------------------------------------


def test_cts_textparts() -> None:
    root = parse(
        '<body><div type="edition" xml:lang="grc">'
        "<head><title>ΓΕΝΕΣΙΣ</title></head>"
        '<div type="textpart" subtype="chapter" n="1">'
        '<div type="textpart" subtype="verse" n="1"><p>Ἐν ἀρχῇ</p></div>'
        '<div type="textpart" subtype="verse" n="2"><p>ἡ δὲ γῆ</p></div>'
        "</div></div></body>"
    )
    assert list(cts_verses(root)) == [(1, 1, "", "Ἐν ἀρχῇ"), (1, 2, "", "ἡ δὲ γῆ")]


def test_cts_accepts_a_translation_and_a_section() -> None:
    """The German Enoch and Ottley's Isaiah are translations rather than editions, and one
    of the two Greek recensions of 1 Enoch divides itself into sections.
    """
    root = parse(
        '<body><div type="translation" xml:lang="deu">'
        '<div type="textpart" subtype="chapter" n="3">'
        '<div type="textpart" subtype="section" n="4"><p>Und ich sah</p></div>'
        "</div></div></body>"
    )
    assert list(cts_verses(root)) == [(3, 4, "", "Und ich sah")]


def test_ab_verses_read_their_numbers_rather_than_counting() -> None:
    """Every verse element in the Digital Syriac Corpus carries an n. The 472 that do not
    are titles and rubrics, and counting positionally would let them shift every verse
    after them by one, silently.
    """
    root = parse(
        '<body><div type="title" n="0"><ab xml:lang="syr">ܐܘܢܓܠܝܘܢ ܕܡܬܝ</ab></div>'
        '<div type="chapter" n="1" xml:lang="syr">'
        '<head xml:lang="en">Chapter 1</head>'
        '<ab type="verse" n="1">ܟܬܒܐ</ab>'
        '<ab type="verse" n="2">ܐܒܪܗܡ</ab>'
        "</div></body>"
    )
    assert list(ab_verses(root)) == [(1, 1, "", "ܟܬܒܐ"), (1, 2, "", "ܐܒܪܗܡ")]


def test_milestones_take_the_text_between_them() -> None:
    """The verse is loose text between two empty markers, not the content of anything. A
    reader looking for an element that holds a verse reports every number correctly and
    extracts nothing at all.
    """
    root = parse(
        '<body><div1 n="1" id="Gen"><head>ΓΕΝΕΣΙΣ</head>'
        '<div2 n="1"><head>Caput 1</head>'
        '<p><milestone unit="verse" n="1"/>In principio creavit Deus caelum et terram. '
        '<milestone unit="verse" n="2"/>Terra autem erat inanis et vacua.</p>'
        "</div2></div1></body>"
    )
    assert list(milestone_verses(root)) == [
        (1, 1, "", "In principio creavit Deus caelum et terram."),
        (1, 2, "", "Terra autem erat inanis et vacua."),
    ]


def test_a_milestone_verse_spanning_several_paragraphs_is_not_truncated() -> None:
    root = parse(
        '<body><div2 n="2">'
        '<p><milestone unit="verse" n="5"/>first part</p>'
        "<p>and the rest of it</p>"
        '<p><milestone unit="verse" n="6"/>the next verse</p>'
        "</div2></body>"
    )
    assert list(milestone_verses(root)) == [
        (2, 5, "", "first part and the rest of it"),
        (2, 6, "", "the next verse"),
    ]


# --------------------------------------------------------------------------------------
# The licence, read per file
# --------------------------------------------------------------------------------------


def test_the_licence_comes_from_the_file(tmp_path: Path) -> None:
    """It varies inside one version: PTA's pta-syc1 is CC BY-NC over the Peshitta Old
    Testament and CC BY over the New Testament beside it. Reading one header gets the
    wrong answer for two thirds of it.
    """
    path = tmp_path / "one.xml"
    path.write_text(
        f"<TEI {NS}><teiHeader><fileDesc><publicationStmt><availability>"
        '<licence target="https://creativecommons.org/licenses/by-nc/4.0/">'
        "Available under a Creative Commons Attribution NonCommercial 4.0 International "
        "License</licence></availability></publicationStmt></fileDesc></teiHeader></TEI>",
        encoding="utf-8",
    )
    licence = read_licence(path)
    assert licence is not None and licence.id == "cc-by-nc-4.0"


def test_a_file_that_declares_no_licence_says_so(tmp_path: Path) -> None:
    """Corpus Corporum has an <availability> element and nothing inside it. The caller has
    to fall back to what the source says and record that it had to.
    """
    path = tmp_path / "bare.xml"
    path.write_text(
        f"<TEI {NS}><teiHeader><fileDesc><publicationStmt><availability/>"
        "</publicationStmt></fileDesc></teiHeader></TEI>",
        encoding="utf-8",
    )
    assert read_licence(path) is None


def test_a_book_of_one_chapter_prints_no_chapter_and_is_still_read() -> None:
    """Obadiah, Jude, the Letter of Jeremiah, Susanna and Bel all hang their verses
    directly off the edition. A reader that insisted on a chapter division would drop
    every one of them without a word.
    """
    root = parse(
        '<body><div type="edition" xml:lang="grc">'
        "<head><title>ΑΒΔΙΟΥ</title></head>"
        '<div type="textpart" subtype="verse" n="1"><p>Ὅρασις Αβδιου.</p></div>'
        '<div type="textpart" subtype="verse" n="2"><p>ἰδοὺ ὀλιγοστὸν</p></div>'
        "</div></body>"
    )
    assert list(cts_verses(root)) == [(1, 1, "", "Ὅρασις Αβδιου."), (1, 2, "", "ἰδοὺ ὀλιγοστὸν")]


def test_verses_under_a_chapter_nobody_declares_are_not_swept_into_chapter_one() -> None:
    """Greek Proverbs has chapters 24a, 30a and 31a that the Hebrew does not, and no
    versification declares them. Deciding orphanhood by "does the file have chapters at
    all" rather than "does this verse have one above it" would file their verses as
    Proverbs 1, which is both wrong and undetectable.
    """
    root = parse(
        '<body><div type="edition">'
        '<div type="textpart" subtype="chapter" n="24">'
        '<div type="textpart" subtype="verse" n="1"><p>real</p></div></div>'
        '<div type="textpart" subtype="chapter" n="24a">'
        '<div type="textpart" subtype="verse" n="1"><p>a Greek plus</p></div></div>'
        "</div></body>"
    )
    assert list(cts_verses(root)) == [(24, 1, "", "real")]
