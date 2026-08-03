from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.cli import main
from biblereference.corpora.ebible import ENGLISH
from biblereference.fetch import iter_sources
from biblereference.refs import VerseRef
from biblereference.sources import FETCH_ORDER, all_sources, get_source
from biblereference.store import DataHome, SourceMeta, write_corpus


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "brhome"
    home = DataHome(root)
    write_corpus(
        home,
        SourceMeta(
            corpus="demo",
            label="Demo",
            language="grc",
            versification="lxx",
            license="Public domain.",
        ),
        [(VerseRef("PSA", 22, 1, vrs="lxx"), "Κύριος ποιμαίνει με")],
    )
    return root


# --------------------------------------------------------------------------------------
# The source registry
# --------------------------------------------------------------------------------------


def test_every_source_declares_its_licence_and_files() -> None:
    for source in all_sources().values():
        assert source.files, f"{source.id} has nothing to fetch"
        assert source.license, f"{source.id} does not say what its licence is"
        assert source.homepage.startswith("https://")


def test_the_catholic_canon_is_covered_by_the_registered_sources() -> None:
    """Hebrew, Greek, Septuagint, two Latins, and two English texts -- one Greek-numbered
    for the deuterocanon, one Vulgate-numbered. These are the texts the renderer reaches
    for by name; the bulk English corpus behind them is checked separately."""
    assert {
        "oshb",
        "swete",
        "nestle1904",
        "webc",
        "dra",
        "latvuc",
        "novavulgata",
    } <= set(all_sources())


def test_the_bulk_english_corpus_is_registered() -> None:
    """Fifty more English translations, held so that the search can tell one rendering
    from another. They must not collide with the named sources."""
    registered = set(all_sources())
    english = {source.id for source in ENGLISH}

    assert len(english) == 50
    assert english <= registered
    assert not english & {"webc", "dra", "latvuc", "oshb", "swete", "nestle1904"}
    assert {"asv", "kjv", "bsb", "net", "ylt"} <= english


def test_every_source_is_fetched_even_if_it_is_not_in_the_fetch_order() -> None:
    """Registering a source without naming it in FETCH_ORDER used to mean it was never
    fetched at all. Fifty-odd sources make that too easy a mistake to leave standing."""
    iterated = [source.id for source in iter_sources()]

    assert len(iterated) == len(set(iterated)), "a source was yielded twice"
    assert set(iterated) == set(all_sources())
    assert iterated[: len(FETCH_ORDER)] == list(FETCH_ORDER), "named texts still come first"


def test_an_unknown_source_names_the_known_ones() -> None:
    with pytest.raises(KeyError, match="swete"):
        get_source("vulgate-clementine")


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


def test_doctor_on_an_empty_home_says_what_to_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-home", str(tmp_path / "empty"), "doctor"]) == 0
    err = capsys.readouterr().err
    assert "not built" in err
    assert "biblereference fetch" in err


def test_doctor_lists_built_corpora(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data-home", str(home), "doctor"]) == 0
    err = capsys.readouterr().err
    assert "demo" in err
    assert "lxx" in err


def test_doctor_reports_chapters_it_cannot_convert(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Vulgate's Sirach is the headline case, and the CLI should say so unprompted."""
    main(["--data-home", str(home), "doctor"])
    err = capsys.readouterr().err
    assert "not convertible" in err
    assert "SIR" in err


def test_render_writes_to_a_file(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "in.md"
    target = tmp_path / "out.md"
    source.write_text("As {{Luke 2:42}} says.\n", encoding="utf-8")

    code = main(["--data-home", str(home), "render", str(source), "-o", str(target)])
    assert code == 0
    assert "twelve years old" in target.read_text(encoding="utf-8")
    assert "1/1 citations resolved" in capsys.readouterr().err


def test_render_writes_to_stdout_by_default(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "in.md"
    source.write_text("{{Luke 2:42}}\n", encoding="utf-8")
    assert main(["--data-home", str(home), "render", str(source)]) == 0
    assert "twelve years old" in capsys.readouterr().out


def test_render_exits_nonzero_when_a_citation_fails(home: Path, tmp_path: Path) -> None:
    """So it can gate a build."""
    source = tmp_path / "in.md"
    source.write_text("{{Hezekiah 1:1}}\n", encoding="utf-8")
    assert main(["--data-home", str(home), "render", str(source)]) == 1


def test_verify_writes_nothing(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "in.md"
    source.write_text("As {{Luke 2:42}} says.\n", encoding="utf-8")
    assert main(["--data-home", str(home), "verify", str(source)]) == 0
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "in.out.md").exists()


def test_verify_fails_on_a_bad_reference(home: Path, tmp_path: Path) -> None:
    source = tmp_path / "in.md"
    source.write_text("{{Sirach 51:31}}\n", encoding="utf-8")
    assert main(["--data-home", str(home), "verify", str(source)]) == 1


def test_render_uses_a_built_corpus_for_originals(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "in.md"
    source.write_text('[passage="Ps 23:1" original="lxx"]\n', encoding="utf-8")
    # The demo corpus is registered under the lxx role by config, not by default.
    main(["--data-home", str(home), "render", str(source)])
    # Without a role pointing at "demo" the Greek is missing, and that is reported.
    assert "no lxx text" in capsys.readouterr().err


def test_naming_scheme_reaches_the_renderer(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "in.md"
    source.write_text("{{1 Kings 2:3}}\n", encoding="utf-8")
    main(["--data-home", str(home), "render", str(source), "--naming", "dr"])
    # Douay-Rheims "1 Kings" is 1 Samuel.
    assert "Solomon" not in capsys.readouterr().out


def test_an_unreadable_input_is_an_error_not_a_traceback(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-home", str(home), "render", "/no/such/file.md"]) == 1
    assert "error:" in capsys.readouterr().err


def test_a_source_asking_for_a_crawl_delay_declares_one() -> None:
    """vatican.va publishes Crawl-delay: 2, and the Nova Vulgata is 73 pages of it."""
    assert get_source("novavulgata").crawl_delay == 2.0
    assert get_source("latvuc").crawl_delay == 0.0
