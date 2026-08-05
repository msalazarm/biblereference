from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.base import VerseUnavailable
from biblereference.refs import VerseRef
from biblereference.render import Config, Renderer
from biblereference.store import (
    DataHome,
    ManifestEntry,
    SourceMeta,
    SqliteCorpus,
    add_chapter,
    default_data_home,
    library_digest,
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


# --------------------------------------------------------------------------------------
# Dropping a corpus
# --------------------------------------------------------------------------------------


SHARED = SourceMeta(
    corpus="twin",
    label="Shares a verse with the demo",
    language="grc",
    versification="lxx",
    license="Public domain.",
)


def test_dropping_a_corpus_takes_its_verses_and_its_index(home: DataHome) -> None:
    from biblereference.search import build_index
    from biblereference.store import drop_corpora, open_store

    write_corpus(home, META, VERSES)
    build_index(home)
    assert drop_corpora(home, ["demo"]) == {"demo": 3}

    with open_store(home) as connection:
        for table in ("verse", "source_meta", "search_ref", "search_state"):
            rows = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert rows == 0, f"{table} still holds rows for a dropped corpus"
        # The index must not outlive the text: a hit here would resolve to a corpus the
        # store can no longer render.
        assert connection.execute("SELECT COUNT(*) FROM search_text").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM search_fts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM search_df").fetchone()[0] == 0


def test_dropping_keeps_text_another_corpus_still_shares(home: DataHome) -> None:
    """``search_text`` is deduplicated by hash across corpora. A verse two translations
    render identically has one row, and dropping either must not take it -- the survivor
    still points at it, and a dangling ``text_id`` would make its verse unfindable."""
    from biblereference.search import build_index
    from biblereference.store import drop_corpora, open_store

    write_corpus(home, META, VERSES)
    write_corpus(home, SHARED, VERSES[:1])  # same text as demo's first verse
    build_index(home)

    with open_store(home) as connection:
        before = connection.execute("SELECT COUNT(*) FROM search_text").fetchone()[0]
    assert before == 3, "identical texts should share one row"

    drop_corpora(home, ["demo"])

    with open_store(home) as connection:
        rows = connection.execute("SELECT text_id FROM search_ref WHERE corpus = 'twin'").fetchall()
        assert len(rows) == 1
        kept = connection.execute(
            "SELECT COUNT(*) FROM search_text WHERE id = ?", (rows[0][0],)
        ).fetchone()[0]
        assert kept == 1, "dropped a text the surviving corpus still points at"


def test_dropping_something_absent_is_not_an_error(home: DataHome) -> None:
    from biblereference.store import drop_corpora

    write_corpus(home, META, VERSES)
    assert drop_corpora(home, ["never-fetched"]) == {"never-fetched": 0}


def test_scripture_portions_are_not_offered_as_translations() -> None:
    """Four eBible entries are selections rather than Bibles -- they print some verses of a
    chapter and not others. A partial chapter is worse than none here: a search hit resolves
    to a verse the edition never claimed to translate, and the structural checks read the
    excerpting as a versification fault.

    The catalogue cannot identify them. "Barkly Bible Portions" declares 26.8 verses per
    chapter, squarely among the complete Bibles, because its chapters are whole and merely
    few. Only the measured share of complete chapters separates them, which is why this is
    a fixed list rather than a rule.
    """
    from biblereference.corpora.ebible import ENGLISH, PORTIONS, english_table

    assert set(PORTIONS) == {"nna", "barkly", "pev", "aoi"}
    ids = {row["id"] for row in english_table()}
    assert ids.isdisjoint(PORTIONS)
    assert {source.id for source in ENGLISH}.isdisjoint(PORTIONS)
    # Small but complete editions stay: Jonah alone, four books, and the Pentateuch.
    assert {"e2t", "glw", "oke"} <= ids


# --------------------------------------------------------------------------------------
# The library digest
# --------------------------------------------------------------------------------------


def test_the_digest_is_stable_and_says_what_it_covers(home: DataHome) -> None:
    """Two runs over one library must agree, or comparing two machines means nothing."""
    write_corpus(home, META, VERSES)
    first, second = library_digest(home), library_digest(home)

    assert first == second
    assert first.verse_count == len(VERSES)
    assert first.library in first.describe()


def test_the_digest_notices_a_changed_verse(home: DataHome) -> None:
    """The point of hashing the text and not only the downloads.

    Identical sources can still yield different databases -- a half-finished build, a
    corrupted page, or the chapters `resolve` fetches one at a time from BibleGateway,
    which are real content and appear in no manifest. So the sources digest holds and the
    texts digest moves, which is also how you tell those cases apart.
    """
    write_corpus(home, META, VERSES)
    before = library_digest(home)

    altered = [(VERSES[0][0], "something else entirely"), *VERSES[1:]]
    write_corpus(home, META, altered)
    after = library_digest(home)

    assert after.texts != before.texts
    assert after.library != before.library
    assert after.sources == before.sources, "nothing was fetched, so the archive is the same"
    assert after.verse_count == before.verse_count


def test_the_digest_ignores_when_a_source_was_fetched(home: DataHome) -> None:
    """Two machines that synced on different days hold the same library.

    The manifest records a dated path and a timestamp per download, and both differ
    between machines holding byte-identical archives -- so neither is hashed. Only the
    newest fetch of each source counts, because fetching something twice does not make a
    machine different from one that fetched it once.
    """
    entry = ManifestEntry(
        source="asv",  # a registered source, because only those are counted
        url="https://example.invalid/demo.zip",
        path="asv/2026-01-01/demo.zip",
        sha256="abc123",
        bytes=10,
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    home.record(entry)
    first = library_digest(home)

    # The same bytes, fetched again on another day, into another dated directory.
    from dataclasses import replace

    home.record(
        replace(entry, path="asv/2026-06-06/demo.zip", fetched_at="2026-06-06T00:00:00+00:00")
    )
    assert library_digest(home).sources == first.sources
    assert library_digest(home).source_count == 1

    # Different bytes is a different library, which is the whole point.
    home.record(replace(entry, sha256="def456", fetched_at="2026-07-07T00:00:00+00:00"))
    assert library_digest(home).sources != first.sources


def test_an_empty_data_home_still_answers(tmp_path: Path) -> None:
    """`doctor` runs before anything is fetched, so this cannot raise."""
    digest = library_digest(DataHome(tmp_path / "nothing"))
    assert digest.verse_count == 0
    assert digest.source_count == 0
    assert len(digest.library) == 64


def test_a_source_the_code_no_longer_registers_is_not_a_difference(home: DataHome) -> None:
    """Found by comparing two real machines, where it was a false alarm.

    An archive is never deleted, so a machine that once fetched a source since dropped
    from the list keeps its files and manifest lines forever -- four abridged translations,
    in the case that turned this up. Counting them would mean that machine could never
    again match a fresh install however often either was synced, which is a permanent
    false alarm rather than a finding. They are reported instead.
    """
    fresh = library_digest(home)

    home.record(
        ManifestEntry(
            source="an-abridgement-we-dropped",
            url="https://example.invalid/gone.zip",
            path="an-abridgement-we-dropped/2026-01-01/gone.zip",
            sha256="abc123",
            bytes=10,
            fetched_at="2026-01-01T00:00:00+00:00",
        )
    )
    after = library_digest(home)

    assert after.library == fresh.library, "a dropped source must not change the digest"
    assert after.unregistered == ("an-abridgement-we-dropped",)
    assert "no longer registered" in after.describe()


def test_a_chapter_resolved_from_the_web_is_not_a_difference(home: DataHome) -> None:
    """The other false alarm from the same comparison.

    `resolve` stores chapters one at a time as it attributes quotations, so they are real
    content that no sync produces and that accumulates wherever the resolving happens to
    be run. Counting them would make a machine that has ever resolved anything differ from
    its own freshly-synced twin, so they are hashed separately and reported.
    """
    write_corpus(home, META, VERSES)
    before = library_digest(home)

    add_chapter(
        home,
        SourceMeta(
            corpus="niv", label="New International Version", language="en", versification="eng"
        ),
        "ISA",
        53,
        {1: "Who has believed our message?", 2: "He grew up before him like a tender shoot."},
    )
    after = library_digest(home)

    assert after.library == before.library, "resolving a chapter must not change the digest"
    assert after.verse_count == before.verse_count
    assert after.online_verses == 2
    assert after.online != before.online
    assert "resolved from the web" in after.describe()
