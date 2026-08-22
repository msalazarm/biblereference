"""Assembling a lexicon from more than one upstream.

Greek reads two: Morpheus's inventory, which keeps a single analysis per spelling, and
Diorisis's observations, which record what a lemmatiser actually assigned in running text.
The inventory's single choice is very often the verb -- `θεοῦ` resolves to θεάομαι and meets
nothing -- so the two are unioned and neither wins.

Hermetic. `test_real_lexicon.py` asks whether the union fixed the words people actually
quote; this asks only whether the union happens at all, and runs in milliseconds against
files it writes itself.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from biblereference.lemmata import (
    LEXICONS,
    LexiconSource,
    LexiconUnavailable,
    _diorisis_pairs,
    _from_beta,
    build_lexicon,
    require_current_lexicon,
)
from biblereference.store import DataHome, open_store


def _archive(home: DataHome, source_id: str, name: str, write: object) -> None:
    """Put a file where `home.latest_archive` will find it."""
    where = home.sources / source_id / "2026-01-01"
    where.mkdir(parents=True, exist_ok=True)
    write(where / name)  # type: ignore[operator]


@pytest.fixture
def two_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataHome:
    """A language whose lexicon comes from a CLTK-shaped file and a Diorisis-shaped zip.

    The two disagree about `θεου` on purpose: the inventory calls it a verb, the
    observations call it the noun. That is the real defect in miniature.
    """
    home = DataHome(tmp_path / "home")

    def cltk(path: Path) -> None:
        path.write_text("LEMMATA = {'θεου': 'θεάομαι', 'λογοσ': 'λόγος'}", encoding="utf-8")

    def diorisis(path: Path) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "one.xml",
                '<sentence><word form="qeou=" ><lemma entry="θεός"/></word>'
                '<word form="lo/gou"><lemma entry="λόγος"/></word></sentence>',
            )

    grc = LEXICONS["grc"]
    _archive(home, grc.parts[0].source.id, grc.parts[0].source.files[0].name, cltk)
    _archive(home, grc.parts[1].source.id, grc.parts[1].source.files[0].name, diorisis)
    return home


def test_build_lexicon_unions_every_part(two_part: DataHome) -> None:
    """Both readings of one form survive; neither upstream wins."""
    build_lexicon(two_part, "grc")
    with open_store(two_part) as connection:
        readings = {
            str(form): {
                str(lemma)
                for (lemma,) in connection.execute(
                    "SELECT lemma FROM lemma_form WHERE language = 'grc' AND form = ?", (form,)
                )
            }
            for (form,) in connection.execute(
                "SELECT DISTINCT form FROM lemma_form WHERE language = 'grc'"
            )
        }
    assert readings["θεου"] == {"θεαομαι", "θεοσ"}, "the union keeps both analyses"
    assert "λογου" in readings, "a form only the second part knows is still added"


def test_the_state_row_records_which_sources_built_it(two_part: DataHome) -> None:
    """A fold stamp cannot see a missing *source*, so the sources are recorded too."""
    build_lexicon(two_part, "grc")
    with open_store(two_part) as connection:
        (recorded,) = connection.execute(
            "SELECT sources FROM lemma_form_state WHERE language = 'grc'"
        ).fetchone()
    assert recorded == ",".join(part.source.id for part in LEXICONS["grc"].parts)


def test_a_lexicon_built_from_fewer_sources_is_refused(
    two_part: DataHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this guard exists for: a table spelled at the current fold, and short.

    A Greek lexicon built from Morpheus alone carries `fold_version = 8` and passes every
    freshness test this library had, while missing the noun reading of the commonest
    genitive in scripture. The fold version is structurally unable to see that.
    """
    grc = LEXICONS["grc"]
    monkeypatch.setitem(
        LEXICONS, "grc", LexiconSource(language="grc", parts=(grc.parts[0],))
    )
    build_lexicon(two_part, "grc")
    require_current_lexicon(two_part, "grc")  # consistent with what built it

    monkeypatch.setitem(LEXICONS, "grc", grc)
    with pytest.raises(LexiconUnavailable, match="are not all of them"):
        require_current_lexicon(two_part, "grc")


def test_a_part_that_was_never_fetched_says_which_one(tmp_path: Path) -> None:
    """Naming the part, because "the lexicon has not been fetched" is now ambiguous."""
    home = DataHome(tmp_path / "empty")
    with pytest.raises(LexiconUnavailable, match="lemmata-grc"):
        build_lexicon(home, "grc")


@pytest.mark.parametrize(
    ("beta", "greek"),
    [
        ("qeo/s", "θεοσ"),
        ("ku/rios", "κυριοσ"),
        ("h(me/ra", "ημερα"),
        ("*)abraa/m", "αβρααμ"),
        ("lo/gwn", "λογων"),
    ],
)
def test_beta_code_becomes_greek(beta: str, greek: str) -> None:
    """Validated at scale elsewhere: 391,667 of 391,691 decoded forms are already keys in
    the Morpheus table, and all 24 that are not are genuine Attic ξυν- spellings."""
    assert _from_beta(beta) == greek


def test_every_lemma_child_is_taken(tmp_path: Path) -> None:
    """Ambiguity is kept and surprisal decides it. Picking a winner here would repeat the
    mistake the single-analysis inventory made."""
    archive = tmp_path / "d.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "a.xml",
            '<word form="a)/rh|"><lemma entry="αἴρω"/><lemma entry="ἀραρίσκω"/></word>',
        )
    assert {lemma for _, lemma in _diorisis_pairs(archive)} == {"αἴρω", "ἀραρίσκω"}
