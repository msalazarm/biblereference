"""What `scan` and `search` return today, recorded so it cannot move by accident.

The consumer this exists for holds 513,047 findings resting on the present behaviour, and
asked for one thing above every feature: that a change improving recall must not alter a
single existing match, because discovering what moved would mean re-adjudicating half a
million records.

So the expected output in ``data/scan-golden.json`` was generated **before** the inflected
matching was written, from the unmodified code, and committed. It cannot have been fitted to
the behaviour it guards. Regenerate it only when a change to the matcher is intended, and
never in the same commit as one that is not:

    BIBLEREFERENCE_REGENERATE_GOLDEN=1 venv/bin/python -m pytest tests/test_regression.py

The corpus is small, fixed and real: authentic verses from `n1904` and the Clementine
Vulgate, with deterministic filler so that document frequencies -- which decide which query
terms survive -- resemble a real library rather than a handful of sentences in which every
word is rare.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from biblereference.refs import VerseRef
from biblereference.search import Searcher, build_index
from biblereference.store import DataHome, SourceMeta, write_corpus

GOLDEN = Path(__file__).parent / "data" / "scan-golden.json"

#: Real verses, as `n1904` holds them. These are the passages the request's fixtures quote,
#: so the guard covers exactly the ground the new matching path will touch.
GREEK = {
    "MAT 3:15": "ἀποκριθεὶς δὲ ὁ Ἰησοῦς εἶπεν αὐτῷ Ἄφες ἄρτι· οὕτως γὰρ πρέπον ἐστὶν ἡμῖν "
    "πληρῶσαι πᾶσαν δικαιοσύνην. τότε ἀφίησιν αὐτόν.",
    "MAT 10:16": "Ἰδοὺ ἐγὼ ἀποστέλλω ὑμᾶς ὡς πρόβατα ἐν μέσῳ λύκων· γίνεσθε οὖν φρόνιμοι ὡς "
    "οἱ ὄφεις καὶ ἀκέραιοι ὡς αἱ περιστεραί.",
    "MAT 19:12": "εἰσὶν γὰρ εὐνοῦχοι οἵτινες ἐκ κοιλίας μητρὸς ἐγεννήθησαν οὕτως, καὶ εἰσὶν "
    "εὐνοῦχοι οἵτινες εὐνουχίσθησαν ὑπὸ τῶν ἀνθρώπων, καὶ εἰσὶν εὐνοῦχοι οἵτινες εὐνούχισαν "
    "ἑαυτοὺς διὰ τὴν βασιλείαν τῶν οὐρανῶν. ὁ δυνάμενος χωρεῖν χωρείτω.",
    "LUK 24:39": "ἴδετε τὰς χεῖράς μου καὶ τοὺς πόδας μου, ὅτι ἐγώ εἰμι αὐτός· ψηλαφήσατέ με "
    "καὶ ἴδετε, ὅτι πνεῦμα σάρκα καὶ ὀστέα οὐκ ἔχει καθὼς ἐμὲ θεωρεῖτε ἔχοντα.",
    "JHN 3:8": "τὸ πνεῦμα ὅπου θέλει πνεῖ, καὶ τὴν φωνὴν αὐτοῦ ἀκούεις, ἀλλ’ οὐκ οἶδας πόθεν "
    "ἔρχεται καὶ ποῦ ὑπάγει· οὕτως ἐστὶν πᾶς ὁ γεγεννημένος ἐκ τοῦ Πνεύματος.",
    "ACT 6:3": "ἐπισκέψασθε δέ, ἀδελφοί, ἄνδρας ἐξ ὑμῶν μαρτυρουμένους ἑπτὰ πλήρεις Πνεύματος "
    "καὶ σοφίας, οὓς καταστήσομεν ἐπὶ τῆς χρείας ταύτης·",
    "ACT 20:21": "διαμαρτυρόμενος Ἰουδαίοις τε καὶ Ἕλλησιν τὴν εἰς Θεὸν μετάνοιαν καὶ πίστιν "
    "εἰς τὸν Κύριον ἡμῶν Ἰησοῦν.",
    "ROM 1:3": "περὶ τοῦ Υἱοῦ αὐτοῦ τοῦ γενομένου ἐκ σπέρματος Δαυεὶδ κατὰ σάρκα,",
    "1CO 1:4": "Εὐχαριστῶ τῷ Θεῷ πάντοτε περὶ ὑμῶν ἐπὶ τῇ χάριτι τοῦ Θεοῦ τῇ δοθείσῃ ὑμῖν ἐν "
    "Χριστῷ Ἰησοῦ,",
    "1CO 6:9": "ἢ οὐκ οἴδατε ὅτι ἄδικοι Θεοῦ βασιλείαν οὐ κληρονομήσουσιν; μὴ πλανᾶσθε· οὔτε "
    "πόρνοι οὔτε εἰδωλολάτραι οὔτε μοιχοὶ οὔτε μαλακοὶ οὔτε ἀρσενοκοῖται",
    "1CO 11:1": "μιμηταί μου γίνεσθε, καθὼς κἀγὼ Χριστοῦ.",
    "2CO 9:8": "δυνατεῖ δὲ ὁ Θεὸς πᾶσαν χάριν περισσεῦσαι εἰς ὑμᾶς, ἵνα ἐν παντὶ πάντοτε πᾶσαν "
    "αὐτάρκειαν ἔχοντες περισσεύητε εἰς πᾶν ἔργον ἀγαθόν,",
    "GAL 5:21": "φθόνοι, μέθαι, κῶμοι, καὶ τὰ ὅμοια τούτοις, ἃ προλέγω ὑμῖν καθὼς προεῖπον ὅτι "
    "οἱ τὰ τοιαῦτα πράσσοντες βασιλείαν Θεοῦ οὐ κληρονομήσουσιν.",
    "EPH 5:25": "Οἱ ἄνδρες, ἀγαπᾶτε τὰς γυναῖκας, καθὼς καὶ ὁ Χριστὸς ἠγάπησεν τὴν ἐκκλησίαν "
    "καὶ ἑαυτὸν παρέδωκεν ὑπὲρ αὐτῆς,",
    "PHP 2:3": "μηδὲν κατ’ ἐριθείαν μηδὲ κατὰ κενοδοξίαν, ἀλλὰ τῇ ταπεινοφροσύνῃ ἀλλήλους "
    "ἡγούμενοι ὑπερέχοντας ἑαυτῶν,",
    "1TH 5:17": "ἀδιαλείπτως προσεύχεσθε,",
}

#: The Clementine Vulgate, likewise.
LATIN = {
    "GEN 1:1": "In principio creavit Deus cælum et terram.",
    "PSA 22:1": "Psalmus David. [Dominus regit me, et nihil mihi deerit:",
    "JHN 1:14": "Et Verbum caro factum est, et habitavit in nobis: et vidimus gloriam ejus, "
    "gloriam quasi unigeniti a Patre plenum gratiæ et veritatis.",
    "ROM 12:1": "Obsecro itaque vos fratres per misericordiam Dei, ut exhibeatis corpora "
    "vestra hostiam viventem, sanctam, Deo placentem, rationabile obsequium vestrum.",
}

ENGLISH = {
    "JHN 1:1": "In the beginning was the Word, and the Word was with God, and the Word was God.",
    "JHN 3:16": "For God so loved the world, that he gave his only begotten Son, that "
    "whosoever believeth in him should not perish, but have everlasting life.",
    "PSA 23:1": "The LORD is my shepherd; I shall not want.",
    "EPH 2:8": "For by grace are ye saved through faith; and that not of yourselves: it is "
    "the gift of God:",
}

#: What a father actually wrote, quoting those verses. Two kinds on purpose: quotations
#: today's scanner finds, so the guard has something to protect, and quotations it cannot
#: find because the words have been re-inflected, so the guard also pins the *absences* --
#: which is what a new matching path is most likely to disturb.
DOCUMENTS = {
    "grc": "Πολλὰ περὶ τούτων ἐν ταῖς ἐπιστολαῖς εἴρηται. ψηλαφήσατέ με καὶ ἴδετε ὅτι οὐκ "
    "εἰμὶ δαιμόνιον ἀσώματον, φησίν. καὶ πάλιν· οἶδεν γάρ πόθεν ἔρχεται καὶ ποῦ ὑπάγει. "
    "φρόνιμος γίνου ὡς ὁ ὄφις ἐν ἅπασιν καὶ ἀκέραιος εἰς ἀεὶ ὡς ἡ περιστερά. "
    "ἀγαπᾶν τὰς συμβίους ὡς ὁ κύριος τὴν ἐκκλησίαν. ἐστίν ὁ χωρῶν χωρείτω. "
    "ἀνδρὸς μεμαρτυρημένου δεῖ τὴν χειροτονίαν εἶναι, καὶ εἰς θεὸν μετανοεῖν.",
    "la": "De hoc mysterio locutus est evangelista, significans quod Verbum caro fieret. "
    "Et vidimus gloriam ejus, gloriam quasi unigeniti a Patre. "
    "Amantissimo fratri per misericordiam scribimus, ut placentem Deo rationem vestram "
    "exhibeatis in suscipiendo novitio.",
    "en": "As the evangelist says, In the beginning was the Word, and the Word was with God, "
    "and the Word was God. And again, The LORD is my shepherd; I shall not want.",
}

#: The tuning the consumer actually runs, per language. The guard is worth little at
#: settings nobody uses.
TUNING: dict[str, dict[str, Any]] = {
    "grc": {"coverage": 0.50, "min_run": lambda n: max(4, min(6, n // 2))},
    "la": {"coverage": 0.70, "min_run": lambda n: max(4, min(6, n // 2))},
    "en": {},
}


def _filler(language: str) -> dict[str, str]:
    """Ordinary prose in the right script, so common words acquire a realistic frequency.

    Without it every word in a tiny corpus looks rare, every phrase looks distinctive, and
    the commonness ceiling that decides which query terms survive is computed from nothing.
    Deterministic, because a guard that matched by luck would be worse than none.
    """
    pools = {
        "grc": (
            "λαοσ βασιλευσ ιερευσ προφητησ οικοσ πολισ ορος αγροσ".split(),
            "ειπεν εποιησεν ηλθεν εδωκεν εστη εξηλθεν απεκριθη ηκουσεν".split(),
            "ιερουσαλημ γαλιλαια ιουδαια αιγυπτοσ βαβυλων νινευη σαμαρεια χανααν".split(),
        ),
        "la": (
            "populus rex sacerdos propheta domus civitas mons ager".split(),
            "dixit fecit venit dedit stetit exivit respondit audivit".split(),
            "hierusalem galilaea iudaea aegyptus babylon ninive samaria chanaan".split(),
        ),
        "en": (
            "people elders priests scribes shepherds fishermen craftsmen judges".split(),
            "gathered departed returned answered laboured rested journeyed waited".split(),
            "valley hillside gateway courtyard vineyard threshing harbour storehouse".split(),
        ),
    }
    subjects, verbs, places = pools[language]
    verses: dict[str, str] = {}
    index = 0
    for chapter in range(1, 26):
        for verse in range(1, 21):
            index += 1
            verses[f"GEN {chapter}:{verse}"] = (
                f"{subjects[index % 8]} {verbs[(index // 3) % 8]} {places[(index // 7) % 8]} "
                f"{subjects[(index // 11) % 8]} {verbs[(index // 13) % 8]}"
            )
    return verses


#: The verses that are actually scripture here, apart from the filler around them.
REAL = {"grc": GREEK, "la": LATIN, "en": ENGLISH}

CORPORA = {
    "grc": ("n1904", "org", {**GREEK, **_filler("grc")}),
    "la": ("latvuc", "vul", {**LATIN, **_filler("la")}),
    "en": ("asv", "eng", {**ENGLISH, **_filler("en")}),
}


def _build(home: DataHome) -> None:
    for language, (corpus, vrs, verses) in CORPORA.items():
        rows = []
        for reference, text in verses.items():
            book, position = reference.split(" ")
            chapter, verse = position.split(":")
            rows.append((VerseRef(book, int(chapter), int(verse), vrs=vrs), text))
        write_corpus(
            home,
            SourceMeta(
                corpus=corpus,
                label=corpus.upper(),
                language=language,
                versification=vrs,
                license="Public domain.",
            ),
            rows,
        )
    build_index(home)


def _records(home: DataHome) -> dict[str, Any]:
    """Everything `scan` and `search` say about the fixed documents, in a stable order."""
    out: dict[str, Any] = {}
    for language, document in sorted(DOCUMENTS.items()):
        with Searcher(home, languages=[language], **TUNING[language]) as searcher:
            scanned = [match.to_dict() for match in searcher.scan(document)]
            # Sorted, because the guard is about *what* was found; the order scan returns
            # them in is pinned separately by the tests in test_search.
            out[f"scan:{language}"] = sorted(scanned, key=lambda row: str(row["span"]))
            # The real verses, not the filler: searching a verse's own words must find that
            # verse, so this half of the guard pins attribution and ranking rather than
            # merely recording that repetitive filler matches nothing.
            verses = REAL[language]
            out[f"search:{language}"] = {
                query: [match.to_dict() for match in searcher.search(text)]
                for query, text in sorted(verses.items())
            }
    return out


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    where = DataHome(tmp_path / "brhome")
    _build(where)
    return where


def test_scan_and_search_return_what_they_returned_before(home: DataHome) -> None:
    """Requirement 0. Every match, and every field of it, exactly as recorded.

    The recording predates the inflected matching path, so passing this cannot be a matter
    of the expectation having been adjusted to suit.
    """
    found = _records(home)

    if os.environ.get("BIBLEREFERENCE_REGENERATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", "utf-8")
        pytest.skip(f"regenerated {GOLDEN}")

    assert GOLDEN.exists(), f"{GOLDEN} is missing; regenerate it deliberately, not by accident"
    expected = json.loads(GOLDEN.read_text("utf-8"))
    assert list(found) == list(expected), "a whole language's results appeared or vanished"
    for key in expected:
        assert _without_additions(found[key]) == expected[key], f"{key} moved"


#: Keys `Match.to_dict` gained when inflected matching was added. The promise made was that
#: nothing already returned would change, not that nothing would ever be added -- the
#: consumer asked for the grade in the same document. Listing them here is what keeps the
#: difference between the two honest: an addition has to be named to be tolerated, and
#: anything else moving still fails.
ADDED: frozenset[str] = frozenset(
    {"grade", "run", "lemma_run", "chain", "bits", "matched_lemmas", "formula"},
) | frozenset(
    # The positional flag, added for the consumer's salutation/farewell combination --
    # threshold-free, computed from the store's own numbering, and like `formula` it
    # reports evidence without acting on it.
    {"positional_candidate"},
)


def _without_additions(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_additions(v) for k, v in value.items() if k not in ADDED}
    if isinstance(value, list):
        return [_without_additions(v) for v in value]
    return value


def test_the_only_thing_that_changed_is_what_was_added(home: DataHome) -> None:
    """The other half of the promise: the new keys are present and are not empty of meaning.

    Without this, `_without_additions` above could hide a regression by growing.
    """
    with Searcher(home, languages=["en"], **TUNING["en"]) as searcher:
        found = searcher.scan(DOCUMENTS["en"])
    assert found, "the English document quotes two verses verbatim"
    for match in found:
        record = match.to_dict()
        assert set(record) >= ADDED, "a promised key is missing"
        assert record["grade"] == "direct", "an exact match is what direct means"
        assert record["run"] >= 6, "today's rule found it, so its identical run is visible"
