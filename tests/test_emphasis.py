"""Emphasis spans.

The Greek and Hebrew here are the real texts from the built corpora, because the whole
point of the folding is that an anchor typed without accents or points finds them.
"""

from __future__ import annotations

import pytest

from biblereference.emphasis import SpanNotFoundError, apply_spans, fold
from biblereference.tags import Emphasis

ASV_LUKE = "And when he was twelve years old, they went up after the custom of the feast;"
GREEK_LUKE = "Καὶ ὅτε ἐγένετο ἐτῶν δώδεκα, ἀναβαινόντων αὐτῶν κατὰ τὸ ἔθος τῆς ἑορτῆς,"
HEBREW_ISAIAH = "הִנֵּ֣ה הָעַלְמָ֗ה הָרָה֙ וְיֹלֶ֣דֶת בֵּ֔ן"


def bold(start: str, end: str) -> Emphasis:
    return Emphasis(start, end, "bold")


# --------------------------------------------------------------------------------------
# Folding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "folded"),
    [
        ("δώδεκα", "δωδεκα"),
        ("Ἰησοῦς", "ιησουσ"),  # breathings, circumflex, and final sigma
        ("ᾧ", "ω"),  # iota subscript
        ("הָעַלְמָ֗ה", "העלמה"),  # niqqud and cantillation
        ("אַל־תִּפְגְּעִי", "אל תפגעי"),  # maqqef reads as a space
        ("  spaced   out  ", "spaced out"),
    ],
)
def test_folding_removes_what_an_anchor_will_not_be_typed_with(written: str, folded: str) -> None:
    assert fold(written) == folded


def test_final_sigma_folds_to_medial() -> None:
    """So an anchor can end a word without knowing where the quotation will cut it."""
    assert fold("λόγος") == fold("λόγοσ")


# --------------------------------------------------------------------------------------
# Applying spans
# --------------------------------------------------------------------------------------


def test_english_span() -> None:
    assert apply_spans(ASV_LUKE, [bold("twelve years", "feast")]) == (
        "And when he was **twelve years old, they went up after the custom of the feast**;"
    )


def test_a_single_anchor_marks_just_that_phrase() -> None:
    assert apply_spans(ASV_LUKE, [bold("twelve years", "twelve years")]) == (
        "And when he was **twelve years** old, they went up after the custom of the feast;"
    )


def test_italic_uses_one_marker() -> None:
    out = apply_spans(ASV_LUKE, [Emphasis("twelve", "years", "italic")])
    assert "*twelve years*" in out and "**" not in out


def test_unaccented_greek_anchor_finds_accented_text() -> None:
    out = apply_spans(GREEK_LUKE, [Emphasis("ετων δωδεκα", "εορτης", "italic")])
    assert out.startswith("Καὶ ὅτε ἐγένετο *ἐτῶν δώδεκα")
    assert out.endswith("τῆς ἑορτῆς*,")


def test_unpointed_hebrew_anchor_finds_pointed_text() -> None:
    out = apply_spans(HEBREW_ISAIAH, [bold("העלמה", "הרה")])
    assert "**הָעַלְמָ֗ה" in out


def test_a_hebrew_span_keeps_its_pointing_inside_the_markers() -> None:
    """A closing marker between a letter and its cantillation would split the word."""
    out = apply_spans(HEBREW_ISAIAH, [bold("העלמה", "הרה")])
    assert "הָרָה֙**" in out
    assert "הָרָה**֙" not in out


def test_text_outside_the_span_is_untouched() -> None:
    out = apply_spans(GREEK_LUKE, [bold("δωδεκα", "δωδεκα")])
    assert out.replace("**", "") == GREEK_LUKE


def test_several_spans_in_one_verse() -> None:
    out = apply_spans(
        ASV_LUKE,
        [bold("twelve", "years"), Emphasis("custom", "feast", "italic")],
    )
    assert "**twelve years**" in out and "*custom of the feast*" in out


def test_spans_apply_left_to_right_regardless_of_the_order_given() -> None:
    out = apply_spans(
        ASV_LUKE,
        [Emphasis("custom", "feast", "italic"), bold("twelve", "years")],
    )
    assert out.index("**twelve years**") < out.index("*custom of the feast*")


# --------------------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------------------


def test_a_missing_anchor_raises_and_shows_the_text() -> None:
    with pytest.raises(SpanNotFoundError) as excinfo:
        apply_spans(ASV_LUKE, [bold("unicorn", "feast")])
    assert "could not find 'unicorn'" in str(excinfo.value)
    assert ASV_LUKE in str(excinfo.value)


def test_an_end_anchor_before_the_start_raises() -> None:
    with pytest.raises(SpanNotFoundError, match="but not 'twelve' after it"):
        apply_spans(ASV_LUKE, [bold("feast", "twelve")])


def test_overlapping_spans_raise() -> None:
    with pytest.raises(SpanNotFoundError, match="overlap"):
        apply_spans(ASV_LUKE, [bold("twelve", "went"), bold("old", "custom")])


def test_no_spans_leaves_the_text_alone() -> None:
    assert apply_spans(ASV_LUKE, []) == ASV_LUKE


# --------------------------------------------------------------------------------------
# Latin
# --------------------------------------------------------------------------------------

CLEMENTINE = "[Exultavit cor meum in Domino, et exaltatum est cornu meum in Deo meo;"


@pytest.mark.parametrize(
    ("written", "folded"),
    [("flammæ", "flammae"), ("cælis", "caelis"), ("pœna", "poena")],
)
def test_ligatures_fold_in_every_language(written: str, folded: str) -> None:
    """NFD does not decompose them, and no one types an anchor with a ligature."""
    assert fold(written) == folded


@pytest.mark.parametrize(
    ("written", "latin"),
    [("Jesus", "iesus"), ("justitia", "iustitia"), ("ejus", "eius"), ("universa", "uniuersa")],
)
def test_latin_folds_j_to_i_and_v_to_u(written: str, latin: str) -> None:
    """The Clementine writes Jesus, the Nova Vulgata Iesus. Same word, same letters."""
    assert fold(written, "la") == latin


def test_that_folding_is_not_applied_to_other_languages() -> None:
    """Folding v to u globally would turn English 'have' into 'haue'."""
    assert fold("have") == "have"
    assert fold("Jesus") == "jesus"


def test_a_latin_anchor_finds_either_spelling() -> None:
    assert "**Exultavit cor meum in Domino**" in apply_spans(
        CLEMENTINE, [bold("exultauit cor meum", "Domino")], "la"
    )
    assert "**Exultavit cor meum in Domino**" in apply_spans(
        CLEMENTINE, [bold("Exultavit", "Domino")], "la"
    )


def test_the_clementines_quotation_brackets_do_not_block_an_anchor() -> None:
    """It brackets canticles and quoted speech, often opening in one verse and closing in
    another, so a single verse can carry a stray bracket an anchor will not include."""
    assert fold("[Dominus regit me", "la") == "dominus regit me"
    out = apply_spans("[Dominus regit me, et nihil", [bold("Dominus", "me")], "la")
    assert out.startswith("[**Dominus regit me**")


def test_the_two_vulgates_differ_where_they_really_differ() -> None:
    """Folding must not hide a real textual variant: regit against pascit."""
    assert fold("Dominus regit me", "la") != fold("Dominus pascit me", "la")
    assert fold("vocabitur nomen ejus", "la") == fold("uocabitur nomen eius", "la")


# --------------------------------------------------------------------------------------
# Greek: the contractions a scribe writes instead of the words
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("ΘΣ", "θεοσ"),
        ("θς", "θεοσ"),
        ("ΚΣ", "κυριοσ"),
        ("ΙΣ", "ιησουσ"),
        ("ΧΣ", "χριστοσ"),
        ("ΧΝ", "χριστον"),
        ("ΠΝΑ", "πνευμα"),
        ("ΙΛΗΜ", "ιερουσαλημ"),
    ],
)
def test_nomina_sacra_expand(written: str, expected: str) -> None:
    """Without this a quotation matched against a manuscript transcription fails on its
    most frequent words -- God, Lord, Jesus, Christ -- which are exactly the words a
    quotation of scripture is most likely to contain.

    Note the expansions end in a plain sigma: fold normalises the final sigma, and an
    expansion that ended in one would be a different string from every other rendering of
    the same word.
    """
    assert fold(written, "grc") == expected


def test_a_contraction_expands_in_the_middle_of_a_sentence() -> None:
    """The contraction is a property of the whole word, which is why this cannot be done
    character by character as the rest of the fold is."""
    folded = fold("ἦν πρὸς τὸν ΘΝ", "grc")
    assert folded == "ην προσ τον θεον"


def test_a_word_that_merely_starts_like_a_contraction_is_left_alone() -> None:
    """``θς`` is Θεός; ``θσι`` is not, and expanding on a prefix would corrupt ordinary
    words."""
    assert fold("θσι", "grc") == "θσι"


def test_accents_and_breathings_already_fold() -> None:
    """Regression: this worked before the Greek branch existed and must keep working."""
    assert fold("Ἰησοῦς", "grc") == fold("ιησους", "grc")


def test_final_sigma_already_folds() -> None:
    assert fold("λόγος", "grc") == fold("λογοσ", "grc")


def test_itacism_is_opt_in() -> None:
    """It collapses words that are genuinely distinct in classical Greek -- ὑμεῖς and
    ἡμεῖς, *you* and *we* -- so it must not be the default. It is the right trade against a
    manuscript and the wrong one against an edited text."""
    assert fold("ὑμεῖς", "grc") != fold("ἡμεῖς", "grc")
    assert fold("ὑμεῖς", "grc", orthographic=True) == fold("ἡμεῖς", "grc", orthographic=True)


def test_folding_latin_is_unchanged() -> None:
    """Regression: the j/i and v/u rule must not move."""
    assert fold("IESVS", "la") == fold("Iesus", "la")


def test_folding_english_does_not_apply_the_other_languages_rules() -> None:
    """v to u would turn *have* into *haue*, and a Greek rule has no business here."""
    assert fold("have") == "have"
    # Final sigma folds whatever the language -- that is not a Greek-only rule -- but the
    # contraction must not expand without being told the text is Greek.
    assert fold("θς") == "θσ"
    assert fold("θς") != fold("θς", "grc")


def test_an_unchanged_greek_word_keeps_its_own_offsets() -> None:
    """The offset map is what apply_spans marks up through, and collapsing every character
    of a word onto its first broke it quietly: a span ending on λόγος ended after the
    lambda, so the wrong text was emphasised and nothing raised."""
    text = "ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος"
    assert apply_spans(text, [Emphasis("λογος", "λογος", "bold")], "grc") == (
        "ἐν ἀρχῇ ἦν ὁ **λόγος** καὶ ὁ λόγος"
    )


def test_a_span_ending_on_a_contraction_covers_what_was_written() -> None:
    """An expansion is longer than its source, so its tail is anchored on the source's last
    character. Otherwise a span ending on ΘΝ would mark up only the theta."""
    text = "ἦν πρὸς τὸν ΘΝ"
    assert apply_spans(text, [Emphasis("προσ", "θεον", "italic")], "grc") == ("ἦν *πρὸς τὸν ΘΝ*")


# --------------------------------------------------------------------------------------
# The fold is memoised, and that must be invisible
# --------------------------------------------------------------------------------------


def test_folding_the_same_text_twice_costs_nothing_the_second_time() -> None:
    """One scan folded 33,292 times over 8,008 distinct inputs -- three quarters of it
    repeated, because every stage that compares a quotation with a verse re-folds the verse.
    """
    from biblereference.emphasis import _folded

    _folded.cache_clear()
    text = "Ἰδοὺ ἐγὼ ἀποστέλλω ὑμᾶς ὡς πρόβατα ἐν μέσῳ λύκων"
    first = fold(text, "grc")
    assert _folded.cache_info().misses == 1
    for _ in range(20):
        assert fold(text, "grc") == first
    assert _folded.cache_info().misses == 1, "the same question was asked again"
    assert _folded.cache_info().hits == 20


def test_the_cache_does_not_conflate_languages() -> None:
    """The one way a memoised fold could corrupt a corpus silently.

    `la` folds *v* to *u* and `en` must not -- it would turn *have* into *haue* -- so a cache
    keyed on the text alone would hand one language the other's answer, and every subsequent
    comparison would be against a word nobody wrote.
    """
    latin, english = fold("VIVAT", "la"), fold("VIVAT", "en")
    assert latin != english
    assert fold("VIVAT", "la") == latin, "and again, from the cache this time"
    assert fold("VIVAT", "en") == english


def test_the_cache_does_not_conflate_the_orthographic_fold() -> None:
    """`orthographic` collapses itacism, which makes ὑμεῖς and ἡμεῖς -- *you* and *we* -- one
    string. Right against a manuscript, wrong against an edited text, and catastrophic if a
    cache handed one caller the other's answer."""
    plain, collapsed = fold("ὑμεῖς", "grc"), fold("ὑμεῖς", "grc", orthographic=True)
    assert plain != collapsed
    assert fold("ὑμεῖς", "grc") == plain
    assert fold("ὑμεῖς", "grc", orthographic=True) == collapsed


def test_the_keyword_and_positional_spellings_are_one_entry() -> None:
    """`lru_cache` keys on the call signature, so `fold(x, "grc")` and `fold(x,
    language="grc")` would otherwise be two entries answering one question."""
    from biblereference.emphasis import _folded

    _folded.cache_clear()
    fold("ἀλήθεια", "grc")
    fold("ἀλήθεια", language="grc")
    assert _folded.cache_info().misses == 1


def test_the_fold_version_moves_when_the_fold_does() -> None:
    """`FOLD_VERSION` is a promise to consumers who bake folded text into artefacts --
    the patristic n-gram tables record it in their `meta`, and a model built on a stale
    fold is silently wrong. These canaries pin the current output across every folding
    rule a language exercises; if one of them fails, the fold changed, and the fix is to
    bump `FOLD_VERSION`, not to update the canary in place.

    It has already earned itself: the elision fix below tripped it, which is exactly how
    the consumer learned their n-gram model needed rebuilding.
    """
    from biblereference.emphasis import FOLD_VERSION

    assert FOLD_VERSION == 3
    assert fold("Ἰησοῦς Χριστός, ᾧ ἡ δόξα", "grc") == "ιησουσ χριστοσ, ω η δοξα"
    assert fold("Jesu naVe", "la") == "iesu naue"
    assert fold("הָעַלְמָ֗ה אַל־תִּפְגְּעִי", "he") == "העלמה אל תפגעי"

    # Version 3's own canaries. The three above still pass unchanged, which is the point of
    # keeping them: Latin and Hebrew answer exactly as they did at version 1, and the Greek
    # one exercises no rule that moved.
    assert fold("τῶι οἴκωι τῆι πόληι", "grc") == "τω οικω τη πολη"
    assert fold("οὕτως γὰρ οὕτω", "grc") == "ουτω γαρ ουτω"
    assert fold("ἀνούς καὶ ἀνοι, κε", "grc") == "ανθρωπουσ και ανθρωποι, κυριε"
    # Punctuation must not decide whether a rule fires. Written first as a lookup on the
    # whole token, this folded `οὕτως γὰρ` and missed `οὕτως,`, and the document frequency
    # of the word came out 2 where the corpus holds 3.
    assert fold("οὕτως, οὕτως·", "grc") == "ουτω, ουτω·"
    # Movable nu is deliberately NOT folded: μέν must not become με. See _GREEK_CONVENTIONS.
    assert fold("μέν", "grc") != fold("με", "grc")
    assert fold("οὐδέν", "grc") != fold("οὐδέ", "grc")
    # Long-alpha datives are deliberately left alone: -αι is a plural, not an adscript.
    assert fold("μαγεῖαι", "grc") != fold("μαγείᾳ", "grc")


def test_a_language_this_library_cannot_name_is_refused_rather_than_ignored() -> None:
    """`fold("Jesus", "lat")` returned *jesus* -- unfolded, no error, and indistinguishable
    from the Latin rule not working. The branch tested `language == "la"` against a raw
    string, so every name but the exact code fell through to no folding at all.

    It is the failure this project keeps meeting: an unknown input answered with a plausible
    value instead of a refusal. It cost the consumer twenty minutes, and it was the first
    thing they typed -- every other language here is a three-letter code and Latin is two.

    `tags.LANGUAGES` already knew the aliases; nothing needed inventing, only consulting.
    """
    assert fold("Jesus vobis", "lat") == fold("Jesus vobis", "la") == "iesus uobis"
    assert fold("Jesus vobis", "latin") == "iesus uobis"
    assert fold("Jesus vobis", "Latin ") == "iesus uobis", "trimmed and case-folded"
    assert fold("ᾧ", "greek") == fold("ᾧ", "grc") == "ω"

    # None is not a language this library cannot name; it is the absence of a claim, and it
    # still means no language-specific folding.
    assert fold("Jesus", None) == "jesus"

    for unknown in ("nonsense", "grk", "lateen", ""):
        with pytest.raises(ValueError, match="does not know the language"):
            fold("Jesus", unknown)


def test_every_spelling_of_an_elision_folds_the_same_way() -> None:
    """Five characters for one mark, and folding kept all but the combining one -- so
    `μετ᾽` and `μετ̓`, the same word digitised by two projects, folded to different
    tokens and no run could cross either. U+02BC is the worst: Unicode calls it a letter,
    so it survived the word tokeniser too and sat inside the token."""
    spellings = ["̓", "᾽", "ʼ", "’", "᾿", "'"]
    assert {fold("μετ" + mark, "grc") for mark in spellings} == {"μετ"}


def test_a_smooth_breathing_is_not_an_elision_mark() -> None:
    """The combining comma above is both, depending on where it sits: elision after a
    consonant, a smooth breathing over a vowel -- and in NFD text every breathing *is*
    that character. So it is left to the accent-stripping pass, which removes it either
    way, rather than being treated as punctuation and turned into a word break. Fold a
    decomposed word and a composed one and they must still agree."""
    import unicodedata

    for word in ("ἀλήθεια", "ὁ", "ἥξει", "ἐν"):
        assert fold(unicodedata.normalize("NFD", word), "grc") == fold(word, "grc")
    assert fold("ἀλήθεια", "grc") == "αληθεια"


def test_the_elision_rule_is_greek_only() -> None:
    """An apostrophe in English is a contraction, which is a different thing, and every
    other language must answer exactly as it did at version 1."""
    assert fold("don't") == "don't"
    assert fold("Lord’s", "en") == "lord’s"
