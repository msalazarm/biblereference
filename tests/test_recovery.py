"""The recovery tier: exact at its stated bound, silent everywhere else.

The §4.4 promise is *provably nothing missed at the stated bound* -- so the exactness
test brute-forces the same answer with an unpruned reference implementation and demands
identity, which is the only way a prune earns its speed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biblereference.lemmata import Lexicon
from biblereference.recovery import Recovery, _bag, _bag_distance, _edit_within
from biblereference.store import DataHome


def reference_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def test_the_banded_dp_agrees_with_the_reference() -> None:
    words = ["κυριοσ", "κυριοσσ", "κυριο", "κυριον", "καιροσ", "χοιροσ", "αβγ", ""]
    for a in words:
        for b in words:
            for k in (0, 1, 2):
                assert _edit_within(a, b, k) == (reference_distance(a, b) <= k), (a, b, k)


def test_the_bag_prune_cannot_lose_a_candidate() -> None:
    """One edit moves at most one character out of the bag and one in, so distance <= k
    implies bag difference <= 2k -- asserted over every pair the DP accepts."""
    words = ["κυριοσ", "κυριον", "καιροσ", "μαρτυσ", "μαρτυρ", "αγιοσ", "αγιασ"]
    for a in words:
        for b in words:
            for k in (1, 2):
                if reference_distance(a, b) <= k:
                    assert _bag_distance(_bag(a), _bag(b)) <= 2 * k


def _fixture_recovery(tmp_path: Path, forms: list[tuple[str, str]]) -> Recovery:
    home = DataHome(tmp_path)
    home.prepare()
    db = sqlite3.connect(home.database)
    db.execute(
        "CREATE TABLE lemma_form (language TEXT, form TEXT, lemma TEXT, "
        "PRIMARY KEY (language, form, lemma))"
    )
    db.executemany(
        "INSERT INTO lemma_form VALUES ('grc', ?, ?)", forms
    )
    db.commit()
    db.close()
    return Recovery(home, "grc")


def test_recovery_is_exact_against_brute_force(tmp_path: Path) -> None:
    forms = [(f, f.upper()) for f in
             ["κυριοσ", "κυριον", "κυριου", "καιροσ", "χοιροσ", "μαρτυσ", "ανθρωποσ"]]
    recovery = _fixture_recovery(tmp_path, forms)
    for token in ["κυριοσ", "κυριωσ", "κυρι", "ξξξξξξ", "ανθροποσ"]:
        expected = tuple(sorted(
            f for f, _ in forms
            if f != token and reference_distance(token, f) <= recovery.bound(token)
        ))
        assert recovery.candidates(token) == expected, token


def test_short_tokens_get_the_tight_bound(tmp_path: Path) -> None:
    """At distance 2 a three-letter word reaches a third of the dictionary; the bound
    adapts so recovery does not become a different-word generator."""
    recovery = _fixture_recovery(tmp_path, [("και", "και"), ("κατ", "κατα")])
    assert recovery.bound("και") == 1
    assert recovery.bound("κυριοσ") == 2
    assert "κατ" in recovery.candidates("καπ")
    assert recovery.candidates("κξπ") == (), "two edits on a three-letter word is refused"


REAL = DataHome()

real = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)


@real
def test_a_scribal_slip_recovers_the_clean_answer_exactly() -> None:
    """One impossible character in a re-inflected quotation. Without the tier the chain
    loses its link and the scan settles for the weaker same-chapter rival; with it, the
    slip returns the *identical* answer the clean text gets -- passage, chain, and bits
    to the digit -- wearing the flag. And the clean text with the tier on is
    byte-identical to the tier off, because recovery fires only for spellings scripture
    has never used anywhere: Job stays Job and is never conjectured into Joab."""
    from biblereference.search import Searcher

    clean_text = (
        "λέγει γὰρ τὸν Ἰὼβ δίκαιον καὶ ἄμεμπτον, ἀληθινόν, θεοσεβῆ, "
        "ἀπεχόμενον ἀπὸ παντὸς κακοῦ"
    )
    slipped = clean_text.replace("ἄμεμπτον", "ἄμεμπτξν")
    opts = {"coverage": 0.50, "min_query": 3, "min_run": lambda n: max(4, min(6, n // 2))}

    def job_matches(searcher: Searcher, text: str) -> list:
        return [m for m in searcher.scan(text) if m.passage.book == "JOB"]

    with Searcher(REAL, languages=["grc"], inflected=True, **opts) as plain:  # type: ignore[arg-type]
        clean_before = job_matches(plain, clean_text)
        slip_before = job_matches(plain, slipped)
    with Searcher(
        REAL, languages=["grc"], inflected=True, recovered=True, **opts  # type: ignore[arg-type]
    ) as healer:
        clean_after = job_matches(healer, clean_text)
        slip_after = job_matches(healer, slipped)

    key = lambda m: (str(m.passage), m.chain, round(m.bits, 1))  # noqa: E731
    assert [key(m) for m in clean_after] == [key(m) for m in clean_before]
    assert not any(m.recovered for m in clean_after), "clean text never wears the flag"
    assert [key(m) for m in slip_after] == [key(m) for m in clean_before], (
        "the slip returns the clean answer exactly"
    )
    assert all(m.recovered for m in slip_after), "and says so"
    assert [key(m) for m in slip_before] != [key(m) for m in clean_before], (
        "without the tier, the slip was genuinely losing evidence"
    )
