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


#: 1 Enoch 1:1 as the Ethiopian Orthodox Bible prints it, wordspaces and all.
GEEZ_ENOCH = "ቃለ፡ በረከት፡ ዘሄኖክ፡ ዘከመ፡ ባረከ፡ ኅሩያነ፡ ወጻድቃነ።"


def test_the_ethiopic_wordspace_separates_words_rather_than_joining_them() -> None:
    """Ge'ez writes a mark between every pair of words, and it is not part of either.

    Without this the token is `ቃለ፡` and never meets `ቃለ` anywhere else in the corpus --
    which is the whole of what a fold is for.
    """
    assert fold(GEEZ_ENOCH, "gez") == "ቃለ በረከት ዘሄኖክ ዘከመ ባረከ ኅሩያነ ወጻድቃነ"


def test_the_geez_fold_does_nothing_else() -> None:
    """Deliberately the least it can do.

    Ethiopic is a syllabary with no case and precomposed characters, so the lowercasing and
    the NFD mark-strip are both no-ops on it. What is *not* done is the orthographic tier --
    manuscripts confuse ሀ/ሐ/ኀ and አ/ዐ the way Greek ones confuse ι/ει/η -- and those letters
    must still be distinct until that is measured rather than guessed.
    """
    assert fold("ሀሐኀ", "gez") == "ሀሐኀ"
    assert fold("አዐ", "gez") == "አዐ"


def test_adding_ethiopic_marks_changed_no_other_language() -> None:
    """`_WORD_SEPARATORS` is not language-scoped, so this had to be checked rather than
    assumed. Of the 1,642,720 verses held when the marks were added, zero contained one."""
    assert fold("Ἰησοῦς", "grc") == "ιησουσ"
    assert fold("Jesus justitia", "la") == "iesus iustitia"
    assert fold("ܡܪܝܐ܂", "syc") == "ܡܪܝܐ"


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

    Conditional since fold 7: only a transcription asks for it. In a printed edition an
    editor expanded these long ago, so a contraction found there is an ordinary word wearing
    the same letters -- which is how ἔσται came to be indexed as ἐσταύρωται 4,412 times.
    """
    assert fold(written, "grc", transcription=True) == expected
    assert fold(written, "grc") == fold(written.lower(), "grc")


def test_a_contraction_expands_in_the_middle_of_a_sentence() -> None:
    """The contraction is a property of the whole word, which is why this cannot be done
    character by character as the rest of the fold is."""
    folded = fold("ἦν πρὸς τὸν ΘΝ", "grc", transcription=True)
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
    assert fold("θς") != fold("θς", "grc", transcription=True)


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
    marked = apply_spans(text, [Emphasis("προσ", "θεον", "italic")], "grc", transcription=True)
    assert marked == "ἦν *πρὸς τὸν ΘΝ*"


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

    assert FOLD_VERSION == 8
    assert fold("Ἰησοῦς Χριστός, ᾧ ἡ δόξα", "grc") == "ιησουσ χριστοσ, ω η δοξα"
    assert fold("Jesu naVe", "la") == "iesu naue"
    assert fold("הָעַלְמָ֗ה אַל־תִּפְגְּעִי", "he") == "העלמה אל תפגעי"

    # Version 3's own canaries. The three above still pass unchanged, which is the point of
    # keeping them: Latin and Hebrew answer exactly as they did at version 1, and the Greek
    # one exercises no rule that moved.
    assert fold("τῶι οἴκωι τῆι πόληι", "grc") == "τω οικω τη πολη"
    assert fold("οὕτως γὰρ οὕτω", "grc") == "ουτω γαρ ουτω"
    # Changed twice. Version 5 deleted `ανουσ` because ἀνούς is *senseless*, an adjective the
    # corpora use twelve times and never as a contraction. Version 7 put it back and made the
    # *expansion* conditional instead: it is a real contraction in a manuscript, which
    # churchfathers counted 96% of the time, and an ordinary word in the editions held here.
    assert fold("ἀνούς καὶ ἀνοι, κε", "grc", transcription=True) == "ανθρωπουσ και ανθρωποι, κυριε"
    # An edition expands none of them, so ἀνούς stays the adjective it is.
    assert fold("ἀνούς καὶ ἀνοι, κε", "grc") == "ανουσ και ανοι, κε"
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


def test_a_full_vowel_iota_is_not_an_adscript() -> None:
    """The adscript rule folds `τωι` to `τω` because a dative is written three ways. Some
    words end in `-ωι` because the iota is a vowel of its own, and folding those is a
    corruption -- twice over for `νηι` and `θεκωι`, whose shortened forms are words the
    corpora already use, so the fold merged two different words into one key.

    Every firing of the rule across the 2,509,521 Greek word tokens in the library was one
    of these six; the genuine adscripts it exists for (`παντηι`, `λαθρηι`) live in the
    Diorisis lemma vocabulary, and those must keep folding.
    """
    for genuine in ("πρωι", "ελωι", "νηι", "θεκωι", "αχωι", "ρηι"):
        assert fold(genuine, "grc") == genuine

    # Marked or unmarked, a word folds the same way: only 172 of the 660 tokens carry the
    # diaeresis, and a rule that fired on the marked spelling alone would put the index and
    # the query on different sides of the same word.
    assert fold("πρωΐ", "grc") == fold("πρωι", "grc") == "πρωι"
    assert fold("ἐλωΐ", "grc") == fold("ελωι", "grc") == "ελωι"
    assert fold("νηὶ", "grc") == fold("νηί", "grc") == "νηι"

    # ...and the rule still does its job where the iota really is an adscript.
    assert fold("τωι", "grc") == "τω"
    assert fold("λογωι", "grc") == "λογω"
    assert fold("παντηι", "grc") == "παντη"
    assert fold("λαθρηι", "grc") == "λαθρη"


def test_a_contraction_never_takes_a_real_word() -> None:
    """The *nomina sacra* are expanded so a quotation can meet a manuscript transcription.
    This library holds printed critical editions, where an editor has already expanded
    them -- so the contraction forms are free to collide with ordinary Greek, and eleven
    of them did, on 4,537 words that were never contractions at all.

    The worst took ἔσται, "will be", on 4,412 occurrences and returned ἐσταύρωται, "has
    been crucified", against five real ones. Each of these is a word the corpora actually
    use; none of them was ever a contraction there.
    """
    for word, folded in (
        ("ἔσται", "εσται"),  # future of εἰμί, not ἐσταύρωται
        ("θῶ", "θω"),  # ἕως ἂν θῶ τοὺς ἐχθρούς σου -- τίθημι, not θεῷ
        ("ὗς", "υσ"),  # the sow that washed, not υἱός
        ("ὗν", "υν"),  # the pig of the dietary law, not υἱόν
        ("Κῶ", "κω"),  # the island of Cos, not κυρίῳ
        ("Ἰήλ", "ιηλ"),  # a name, not Ἰσραήλ
        ("ἄνους", "ανουσ"),  # senseless, not ἀνθρώπους
    ):
        assert fold(word, "grc") == folded

    # ...and the contractions that are contractions still expand, for a transcription.
    assert fold("θς", "grc", transcription=True) == "θεοσ"
    assert fold("κς", "grc", transcription=True) == "κυριοσ"
    assert fold("χς", "grc", transcription=True) == "χριστοσ"


def test_an_editorial_mark_does_not_hide_a_word_from_the_fold() -> None:
    """Every rule in `_greek_word` is a lookup on the whole head, so a bracket or a dash
    made the lookup miss -- and `_WORD_RE` then discarded the mark anyway, putting the
    unfolded spelling in the index with nothing to show for it.

    Swete supplies a reading as `[οὕτως].`, WH as `[Οὕτως`, and Rahlfs opens speech with
    `—οὕτως`. The mark is kept, because the offsets are anchored on what was written.
    """
    assert fold("[οὕτως].", "grc") == "[ουτω]."
    assert fold("—οὕτως", "grc") == "—ουτω"
    assert fold("[Οὕτως", "grc") == "[ουτω"
    assert fold("[θς]", "grc", transcription=True) == "[θεοσ]"
    assert fold("«πρωΐ»", "grc") == "«πρωι»"
    # the bare word folds the same way, which is the whole point
    assert fold("οὕτως", "grc") == "ουτω"

    # A mark *inside* the word, which trimming the ends does not reach. Rahlfs opens a
    # parenthesis with no space around it, so this is one token to a rule that looks up the
    # whole head -- and the word tokeniser then splits it and files the unfolded half.
    assert fold("πολλοί—οὕτως", "grc") == "πολλοι—ουτω"
    assert fold("ταῦτα—οὕτως", "grc") == "ταυτα—ουτω"
    # and a piece that is only marks must not send the splitter round again
    assert fold("—", "grc") == "—"
    assert fold("[]", "grc") == "[]"


def test_a_contraction_expands_only_for_a_transcription() -> None:
    """A scribe contracts; an editor of a printed text expanded these centuries ago. So in an
    edition every "contraction" found is an ordinary word wearing the same letters, and in a
    transcription it may be the real thing. The expansion is conditional from fold 7.

    Fold 5 tried to settle it by deleting the eleven that collide, and that split a formula:
    `τοῦ κυ ἡμῶν ἰῦ χῦ` expanded Christ and left the Lord contracted, because `ιυ` and `χυ`
    survived the cut while `κυ` did not. churchfathers found it by running our own audit
    against their corpora, where all the survivors occur and 89% sit inside a manuscript.
    """
    formula = "τοῦ κυ ἡμῶν ἰῦ χῦ"
    # An edition expands none of it, so the four stay consistent with each other.
    assert fold(formula, "grc") == "του κυ ημων ιυ χυ"
    # A transcription expands all four -- of our Lord Jesus Christ.
    assert fold(formula, "grc", transcription=True) == "του κυριου ημων ιησου χριστου"

    # Ordinary words are never touched in an edition, whatever the table holds.
    for word, folded in (("ἔσται", "εσται"), ("θῶ", "θω"), ("ὗς", "υσ"), ("Κῶ", "κω")):
        assert fold(word, "grc") == folded

    # ...and the five withheld entries are not expanded even for a transcription, because
    # nobody has yet counted which reading dominates *inside* a manuscript.
    for word in ("ἔσται", "ὗς", "Κῶ"):
        assert fold(word, "grc", transcription=True) == fold(word, "grc")
    # while a contraction that is not also a word does expand there
    assert fold("θς", "grc", transcription=True) == "θεοσ"
    assert fold("θς", "grc") == "θσ"


def test_the_breathing_decides_whether_iota_nu_is_a_contraction() -> None:
    """`ιν` is two words. Elided ἵνα takes the rough breathing; ἰν for Ἰησοῦν takes the
    smooth. Both reach the table as `ιν`, because breathing is a combining mark and the NFD
    pass drops it before anything looks the word up -- so fold 7 withheld the entry, and
    withholding split the accusative formula exactly as the genitive one split before `κυ`
    came back.

    churchfathers' transcriptions mark it every time: 311 rough against 101 smooth, 78 of the
    latter in `τὸν κν ἡμῶν ἰν χν` identically across Ms44-Ms48. So the fold now carries that
    one bit past its own strip.
    """
    import unicodedata

    # Every precomposed iota-with-breathing, checked against its own Unicode name rather
    # than against a hand-written list -- the polarity is the whole correctness of this.
    for codepoint in range(0x1F30, 0x1F3A):
        letter = chr(codepoint)
        rough = "DASIA" in unicodedata.name(letter)
        folded = fold(letter + "ν", "grc", transcription=True)
        assert folded == ("ιν" if rough else "ιησουν"), unicodedata.name(letter)

    # A bare form carries no breathing, so the scribe did not say: left alone rather than
    # guessed at, which is what fold 7 did with every spelling.
    assert fold("ιν", "grc", transcription=True) == "ιν"
    assert fold("ῖν", "grc", transcription=True) == "ιν"

    # The formula the withholding broke, whole again -- and its genitive unchanged.
    assert fold("τὸν κν ἡμῶν ἰν χν", "grc", transcription=True) == "τον κυριον ημων ιησουν χριστον"
    assert fold("τοῦ κυ ἡμῶν ἰῦ χῦ", "grc", transcription=True) == "του κυριου ημων ιησου χριστου"

    # An edition expands none of it, breathing or not.
    assert fold("τὸν κν ἡμῶν ἰν χν", "grc") == "τον κν ημων ιν χν"
    assert fold("ἰν", "grc") == "ιν"


def test_a_mark_the_scribe_wrote_decides_the_three_remaining_contractions() -> None:
    """`κω`, `υσ` and `υν` are each a contraction and something else, and the something else
    carries a mark. churchfathers counted every occurrence in their transcriptions by form,
    so these numbers are complete rather than sampled.

    `κω` is κυρίῳ, except where it is Κῶ, the island of Acts 21:1. The dative ending survives
    on the contraction as an iota subscript -- 83 `κῳ` and 8 `κῷ` of 349 -- while the island
    carries a perispomeni and no subscript, which is the 4 `κῶ`.

    `υσ`/`υν` are υἱός/υἱόν. ὗς the pig takes a rough breathing *and* a perispomeni: zero of
    645. What the perispomeni does catch is a word broken across a line -- their `ῦς` and `ὖν`
    are νοῦς and οὖν split, visible in *ὁ νο ὖν ῦς διακρίνῃ*, the same fault as the
    `θυ γατέρας` split that cost us fold 5.
    """
    # κω: the subscript expands, the bare perispomeni refuses.
    assert fold("κῳ", "grc", transcription=True) == "κυριω"
    assert fold("κῷ", "grc", transcription=True) == "κυριω"
    assert fold("κῶ", "grc", transcription=True) == "κω"

    # υσ / υν: a perispomeni means a fragment or the pig, and refuses either way.
    assert fold("ῦς", "grc", transcription=True) == "υσ"
    assert fold("ὖν", "grc", transcription=True) == "υν"
    assert fold("ὗς", "grc", transcription=True) == "υσ"
    assert fold("υς", "grc", transcription=True) == "υιοσ"
    assert fold("υν", "grc", transcription=True) == "υιον"

    # All three formulas whole -- genitive, accusative, dative. Each split in turn, and each
    # split was the same fault found a version later than the last.
    assert fold("τοῦ κυ ἡμῶν ἰῦ χῦ", "grc", transcription=True) == "του κυριου ημων ιησου χριστου"
    assert fold("τὸν κν ἡμῶν ἰν χν", "grc", transcription=True) == "τον κυριον ημων ιησουν χριστον"
    assert (
        fold("τῷ ἰδίῳ λόγῳ τῷ κω ἡμῶν ἰῦ χῷ", "grc", transcription=True)
        == "τω ιδιω λογω τω κυριω ημων ιησου χριστω"
    )

    # An edition expands none of it.
    assert fold("τῷ κω ἡμῶν ἰῦ χῷ", "grc") == "τω κω ημων ιυ χω"


def test_a_guard_reads_the_whole_word_not_its_first_letter() -> None:
    """`ἰν` carries its breathing on the iota, so reading only the first character worked and
    hid the assumption. `κῶ` carries its perispomeni on the omega, and reading the first
    character let the island expand to κυρίῳ -- caught by checking a mark that does not sit
    where the last one did.
    """
    assert fold("κῶ", "grc", transcription=True) == "κω"
    assert fold("ἰν", "grc", transcription=True) == "ιησουν"
