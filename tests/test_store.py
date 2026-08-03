from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.base import VerseUnavailable
from biblereference.refs import VerseRef
from biblereference.render import Config, Renderer
from biblereference.store import (
    DataHome,
    SourceMeta,
    SqliteCorpus,
    default_data_home,
    read_meta,
    write_corpus,
)


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    home = DataHome(tmp_path / "brhome")
    home.prepare()
    return home


META = SourceMeta(
    corpus="demo",
    label="Demonstration Text",
    language="grc",
    versification="lxx",
    license="Public domain.",
    attribution="Demo attribution line.",
)

VERSES = [
    (VerseRef("PSA", 22, 1, vrs="lxx"), "Κύριος ποιμαίνει με"),
    (VerseRef("PSA", 22, 2, vrs="lxx"), "εἰς τόπον χλόης"),
    (VerseRef("SIR", 24, 1, vrs="lxx"), "Ἡ σοφία αἰνέσει ψυχὴν αὐτῆς"),
]


# --------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------


def test_layout_keeps_sources_and_database_apart(home: DataHome) -> None:
    assert home.sources.is_dir()
    assert home.database.parent.is_dir()
    assert home.manifest.parent == home.sources


def test_data_home_honours_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIBLEREFERENCE_HOME", "/tmp/somewhere-else")
    assert default_data_home() == Path("/tmp/somewhere-else")
    monkeypatch.delenv("BIBLEREFERENCE_HOME")
    assert default_data_home().name == "biblereference"


# --------------------------------------------------------------------------------------
# The archive
# --------------------------------------------------------------------------------------


def test_stored_files_are_recorded_with_a_checksum(home: DataHome) -> None:
    path = home.store_file(
        "demo",
        "text.txt",
        b"hello",
        url="https://example.invalid/text.txt",
        license="Public domain.",
    )
    assert path.read_bytes() == b"hello"

    (entry,) = home.entries("demo")
    assert entry.url == "https://example.invalid/text.txt"
    assert entry.bytes == 5
    assert len(entry.sha256) == 64
    assert entry.license == "Public domain."
    assert entry.fetched_at


def test_refetching_adds_to_the_archive_rather_than_replacing_it(home: DataHome) -> None:
    """The archive is the point: an old copy survives a bad upstream change."""
    home.store_file("demo", "a.txt", b"one", url="u")
    home.store_file("demo", "b.txt", b"two", url="u")
    assert len(home.entries("demo")) == 2
    assert home.latest_archive("demo") is not None


def test_latest_archive_is_none_before_anything_is_fetched(home: DataHome) -> None:
    assert home.latest_archive("never-fetched") is None


def test_the_manifest_filters_by_source(home: DataHome) -> None:
    home.store_file("one", "a.txt", b"a", url="u")
    home.store_file("two", "b.txt", b"b", url="u")
    assert len(home.entries()) == 2
    assert [e.source for e in home.entries("two")] == ["two"]


# --------------------------------------------------------------------------------------
# The database
# --------------------------------------------------------------------------------------


def test_written_verses_come_back(home: DataHome) -> None:
    assert write_corpus(home, META, VERSES) == 3

    corpus = SqliteCorpus(home, read_meta(home)[0])
    assert corpus.id == "demo"
    assert corpus.language == "grc"
    assert corpus.versification == "lxx"
    assert corpus.attribution == "Demo attribution line."
    assert corpus.has_book("PSA") and corpus.has_book("SIR")
    assert not corpus.has_book("GEN")

    (verse,) = corpus.fetch([VerseRef("PSA", 22, 1, vrs="lxx")])
    assert verse.text == "Κύριος ποιμαίνει με"


def test_a_missing_verse_is_reported_not_returned_empty(home: DataHome) -> None:
    write_corpus(home, META, VERSES)
    corpus = SqliteCorpus(home, read_meta(home)[0])
    with pytest.raises(VerseUnavailable, match="Psalms 99:1"):
        corpus.fetch([VerseRef("PSA", 99, 1, vrs="lxx")])


def test_rebuilding_replaces_rather_than_merges(home: DataHome) -> None:
    """A parser that starts dropping a book must show up as a smaller corpus, not as
    stale rows left over from the last build."""
    write_corpus(home, META, VERSES)
    assert write_corpus(home, META, VERSES[:1]) == 1

    corpus = SqliteCorpus(home, read_meta(home)[0])
    assert corpus.meta.verse_count == 1
    with pytest.raises(VerseUnavailable):
        corpus.fetch([VerseRef("SIR", 24, 1, vrs="lxx")])


def test_metadata_records_what_is_held(home: DataHome) -> None:
    write_corpus(home, META, VERSES)
    (meta,) = read_meta(home)
    assert meta.label == "Demonstration Text"
    assert meta.verse_count == 3
    assert meta.built_at


def test_reading_an_unbuilt_database_is_empty_not_an_error(tmp_path: Path) -> None:
    assert read_meta(DataHome(tmp_path / "nothing")) == []


def test_several_corpora_live_side_by_side(home: DataHome) -> None:
    write_corpus(home, META, VERSES)
    other = SourceMeta(corpus="other", label="Other", language="en", versification="eng")
    write_corpus(home, other, [(VerseRef("LUK", 2, 42, vrs="eng"), "And when he was...")])

    loaded = SqliteCorpus.load_all(home)
    assert set(loaded) == {"demo", "other"}
    assert loaded["other"].fetch([VerseRef("LUK", 2, 42, vrs="eng")])[0].text.startswith("And")


# --------------------------------------------------------------------------------------
# End to end through the renderer
# --------------------------------------------------------------------------------------


def test_a_built_corpus_renders(home: DataHome) -> None:
    write_corpus(home, META, VERSES)
    renderer = Renderer(Config(roles={"lxx": ("demo",)}, notices=False))
    for corpus in SqliteCorpus.load_all(home).values():
        renderer.add_corpus(corpus)

    out, report = renderer.render_text('[passage="Ps 23:1" original="lxx"]')
    assert report.ok, report.errors
    assert "Κύριος ποιμαίνει με" in out
    # Cited as Psalm 23, quoted from Psalm 22: the Greek numbering, said out loud.
    assert "Psalms 22:1" in out


def test_attribution_is_emitted_for_texts_that_require_it(home: DataHome) -> None:
    """This one keeps the notices on -- they are what carries the attribution."""
    write_corpus(home, META, VERSES)
    renderer = Renderer(Config(roles={"lxx": ("demo",)}))
    for corpus in SqliteCorpus.load_all(home).values():
        renderer.add_corpus(corpus)

    out, report = renderer.render_text('[passage="Ps 23:1" original="lxx"]')
    assert "Demo attribution line." in out
    assert report.attributions == ["Demo attribution line."]
