"""The online provider.

Nothing here touches the network. The fixture is shaped like a real BibleGateway
chapter page -- verse text split across several spans sharing one ``Book-Chapter-Verse``
class, headings and footnote markers interleaved -- and the archive path is exercised by
writing a page into the data home and reading it back, which is exactly what the provider
does on the second and every later run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.base import CorpusError, VerseUnavailable
from biblereference.corpora.web import (
    KNOWN_VERSIONS,
    BibleGatewayCorpus,
    parse_chapter,
    parse_copyright,
)
from biblereference.refs import VerseRef
from biblereference.render import Config, Renderer
from biblereference.store import DataHome

PAGE = """
<html><body>
<div class="passage-text">
  <h3>The Praise of Wisdom</h3>
  <p>
    <span class="text Sir-24-1"><span class="chapternum">24 </span>Wisdom praises herself,</span>
    <span class="text Sir-24-1">and tells of her glory<sup class="footnote">[a]</sup>
      in the midst of her people.</span>
    <span class="text Sir-24-2"><sup class="versenum">2 </sup>In the assembly of the Most High
      she opens her mouth,</span>
    <span class="text Sir-24-3"><sup class="versenum">3 </sup>&ldquo;I came forth from the mouth
      of the Most High<sup class="crossreference">(A)</sup>.</span>
  </p>
  <div class="footnotes"><li>Sirach 24:1 Other authorities read otherwise</li></div>
</div>
<div class="publisher-info-bottom">New Revised Standard Version Catholic Edition (NRSVCE)
  copyright &copy; 1989, 1993. Used by permission. All rights reserved.</div>
</body></html>
"""


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def test_verse_spans_are_grouped_into_verses() -> None:
    """A verse of poetry is several spans sharing one class, not one span."""
    verses = parse_chapter(PAGE)
    assert sorted(verses) == [1, 2, 3]
    assert verses[1] == "Wisdom praises herself, and tells of her glory in the midst of her people."


def test_headings_verse_numbers_and_apparatus_are_stripped() -> None:
    verses = parse_chapter(PAGE)
    assert "Praise of Wisdom" not in " ".join(verses.values())
    assert not verses[2].startswith("2")
    assert "24 " not in verses[1]
    assert "[a]" not in verses[1]
    assert "(A)" not in verses[3]
    assert "Other authorities" not in " ".join(verses.values())


def test_punctuation_stays_against_its_word() -> None:
    assert parse_chapter(PAGE)[3].endswith("Most High.")


def test_the_copyright_line_is_read() -> None:
    notice = parse_copyright(PAGE)
    assert notice is not None
    assert "New Revised Standard Version Catholic Edition" in notice
    assert "All rights reserved" in notice


def test_a_page_without_a_passage_is_an_error_not_an_empty_chapter() -> None:
    with pytest.raises(CorpusError, match="no passage found"):
        parse_chapter("<html><body>Nothing here.</body></html>")


# --------------------------------------------------------------------------------------
# The archive
# --------------------------------------------------------------------------------------


@pytest.fixture
def archived(tmp_path: Path) -> DataHome:
    """A data home with one chapter already fetched."""
    home = DataHome(tmp_path / "brhome")
    home.store_file("web", "NRSVCE/SIR_24.html", PAGE.encode("utf-8"), url="https://example")
    return home


def test_an_archived_chapter_is_served_without_fetching(archived: DataHome) -> None:
    corpus = BibleGatewayCorpus("NRSVCE", archived, offline=True)
    (verse,) = corpus.fetch([VerseRef("SIR", 24, 2, vrs="eng")])
    assert verse.text.startswith("In the assembly of the Most High")


def test_the_copyright_line_comes_from_the_archived_page(archived: DataHome) -> None:
    corpus = BibleGatewayCorpus("NRSVCE", archived, offline=True)
    corpus.fetch([VerseRef("SIR", 24, 1, vrs="eng")])
    assert corpus.attribution is not None
    assert "All rights reserved" in corpus.attribution


def test_a_verse_the_version_omits_is_reported(archived: DataHome) -> None:
    """The NRSV relegates some verses of Sirach to footnotes; they are simply absent."""
    corpus = BibleGatewayCorpus("NRSVCE", archived, offline=True)
    with pytest.raises(VerseUnavailable, match="Sirach 24:18"):
        corpus.fetch([VerseRef("SIR", 24, 18, vrs="eng")])


def test_offline_mode_never_reaches_for_the_network(archived: DataHome) -> None:
    corpus = BibleGatewayCorpus("NRSVCE", archived, offline=True)
    with pytest.raises(VerseUnavailable, match="fetching is switched off"):
        corpus.fetch([VerseRef("TOB", 1, 1, vrs="eng")])


def test_labels_and_identity(archived: DataHome) -> None:
    corpus = BibleGatewayCorpus("nrsvce", archived, offline=True)
    assert corpus.id == "nrsvce"
    assert corpus.label == KNOWN_VERSIONS["NRSVCE"]
    assert corpus.language == "en"
    assert corpus.versification == "eng"


# --------------------------------------------------------------------------------------
# Through the renderer
# --------------------------------------------------------------------------------------


def test_the_renderer_uses_an_archived_online_version(archived: DataHome) -> None:
    renderer = Renderer(
        Config(
            default_english="NRSVCE",
            deuterocanon_english="NRSVCE",
            data_home=archived.root,
            offline=True,
            original="none",
        ),
        corpora={},
    )
    out, report = renderer.render_text('[passage="Sir 24:1"]')
    assert report.ok, report.errors
    assert "Wisdom praises herself" in out
    assert "All rights reserved" in out  # the copyright notice is not optional


def test_online_lookups_can_be_switched_off_entirely(tmp_path: Path) -> None:
    renderer = Renderer(
        Config(
            default_english="NRSVCE",
            deuterocanon_english="NRSVCE",
            vulgate_english="NRSVCE",
            data_home=tmp_path,
            online=False,
            original="none",
        ),
        corpora={},
    )
    _, report = renderer.render_text('[passage="Sir 24:1"]')
    assert not report.ok
    assert "only available online" in report.errors[0]


def test_every_known_version_has_a_full_name() -> None:
    for code, name in KNOWN_VERSIONS.items():
        assert code.isupper()
        assert len(name) > len(code)
