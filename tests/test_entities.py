"""The entity index and the allusion pass: residue only, individuals not names.

Pinned here beside the behavior: the §13 refusal. Nine of the consumer's hand-read
indirect misses share zero content words with their verses; the design refuses to chase
them, and the zero-signal test asserts the pass stays silent there so nobody tunes
toward what the evidence cannot support.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.emphasis import fold
from biblereference.entities import Entities, _parse_tipnr, build_entities
from biblereference.lemmata import Lexicon
from biblereference.store import DataHome

FIXTURE = """TIPNR fixture
$========== PERSON(s)
Abraham@Gen.11.26-1Pe=H0085\tPatriarch\t\t\t\t\t\t#desc\tperson
– Named\tAbraham@Gen.11.26-1Pe\tH0085«H0085=אַבְרָהָם\tAbraham\thttps://x\tGen.14.19; Gen.22.1
– Greek\tAbraham@Gen.11.26-1Pe\tG0011«G0011=Ἀβραάμ\tAbraham\thttps://x\tHeb.7.1
– Total\tAbraham\tH0085, G0011\tGen.14.19ff; 22.1\t3
$========== PERSON(s)
Melchizedek@Gen.14.18-Heb=H4442\tKing of Salem\t\t\t\t\t\t#desc\tperson
– Named\tMelchizedek@Gen.14.18-Heb\tH4442«H4442=מַלְכִּי־צֶדֶק\tMelchizedek\thttps://x\tGen.14.18
– Greek\tMelchizedek@Gen.14.18-Heb\tG3198«G3198=Μελχισέδεκ\tMelchizedek\thttps://x\tHeb.7.1
$========== PLACE
Salem@Gen.14.18=H8004\tCity\t\t\t\t\t\t#desc\tplace
– Named\tSalem@Gen.14.18\tH8004«H8004=שָׁלֵם\tSalem\thttps://x\tGen.14.18
"""


def test_the_parser_reads_individuals_forms_and_clean_refs() -> None:
    records = list(_parse_tipnr(FIXTURE))
    assert [r.entity.split("@")[0] for r in records] == ["Abraham", "Melchizedek", "Salem"]
    abraham = records[0]
    assert ("grc", fold("Ἀβραάμ", "grc")) in abraham.forms
    assert ("he", fold("אַבְרָהָם", "he")) in abraham.forms
    assert "Gen.14.19" in abraham.refs and "Heb.7.1" in abraham.refs
    assert not any("ff" in ref for ref in abraham.refs), "compressed Total refs are skipped"
    assert records[2].kind == "place"


def test_the_build_converts_and_the_reader_clusters(tmp_path: Path) -> None:
    home = DataHome(tmp_path)
    archive = home.sources / "tipnr" / "2026-08-17"
    archive.mkdir(parents=True)
    (archive / "tipnr.txt").write_text(FIXTURE, "utf-8")
    out = tmp_path / "entities.sqlite"
    result = build_entities(home, out)
    assert result.entities == 3 and result.unconvertible == 0

    index = Entities(out)
    assert index.held
    found = index.by_form("grc", [fold("Μελχισέδεκ", "grc"), fold("Ἀβραάμ", "grc"), "junk"])
    assert len(found) == 2
    ids = set().union(*found.values())
    clusters = index.co_mentions(ids)
    assert clusters, "Abram and Melchizedek stand two verses apart in Genesis 14"
    tops = {(book, first, last) for _, book, _, first, last, _ in clusters}
    assert ("GEN", 18, 19) in tops, "the chapter cluster spans 14:18-19, not one verse"
    assert ("HEB", 1, 1) in tops


def test_an_unbuilt_index_is_silence(tmp_path: Path) -> None:
    index = Entities(tmp_path / "absent.sqlite")
    assert not index.held
    assert index.by_form("grc", ["αβρααμ"]) == {}
    assert index.co_mentions({"a", "b"}) == []


REAL = DataHome()
ENTITIES = REAL.root / "db" / "entities.sqlite"

real = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc") or not ENTITIES.exists(),
    reason="needs the built library, lexicon, and entities.sqlite",
)

#: 1 Clement 17.3, as `test_gates` carries it -- inlined rather than imported, because
#: importing that module after the conftest isolation fixture has run would capture the
#: temp home instead of the real one.
CLEMENT_17_3 = (
    "ἔτι δὲ καὶ περὶ Ἰὼβ οὕτως γέγραπται: Ἰὼβ δὲ ἦν δίκαιος καὶ ἄμεμπτος, ἀληθινός, "
    "θεοσεβής, ἀπεχόμενος ἀπὸ παντὸς κακοῦ."
)


def greek(**options: object) -> object:
    from biblereference.search import Searcher

    settings: dict[str, object] = {
        "coverage": 0.50,
        "min_query": 3,
        "min_run": lambda n: max(4, min(6, n // 2)),
    }
    settings.update(options)
    return Searcher(REAL, languages=["grc"], **settings)  # type: ignore[arg-type]


@real
def test_an_allusive_gesture_activates_on_the_residue_only() -> None:
    """The two-pass design: the quotation is scan's and stays scan's; the entity gesture
    in the remainder becomes an allusion with its own grade, its evidence named, and
    what lost carried in alternates."""
    doc = (
        CLEMENT_17_3
        + " καὶ γὰρ ὁ Ἀβραὰμ ἀπήντησεν τῷ Μελχισέδεκ βασιλεῖ Σαλὴμ καὶ εὐλογήθη ὑπ' "
        "αὐτοῦ καθὼς ἴσμεν ἐκ τῶν γραφῶν."
    )
    with greek(inflected=True) as rich:
        found = rich.scan(doc)
        gestures = rich.allusions(doc, matches=found)
    assert any(m.passage.book == "JOB" for m in found), "the quotation stays with scan"
    assert gestures, "the gesture activates"
    top = gestures[0]
    assert top.grade in ("allusion", "reference")
    assert top.grade not in {m.grade for m in found}, "the accounts never merge"
    named = {t for t in top.matched_lemmas}
    assert {"Abraham", "Melchizedek"} <= named
    told = {str(span) for span in top.alternates} | {str(top.passage)}
    assert any(name.startswith(("GEN 14", "HEB 7")) for name in told), (
        "Genesis 14 or Hebrews 7 -- and whichever lost is in alternates"
    )
    quotation_span = next(m.span for m in found if m.passage.book == "JOB")
    assert top.span and top.span[0] >= quotation_span[1], "activated on the residue only"


@real
def test_zero_signal_is_silence_and_stays_that_way() -> None:
    """The §13 refusal, pinned: nine of the consumer's indirect misses share zero
    content words with their verses, and this pass must not be tuned toward them --
    prose with no entities and no rare lemmas answers nothing."""
    with greek(inflected=True) as rich:
        assert rich.allusions("ταῦτα μὲν οὖν οὕτως ἔχει κατὰ τὴν παράδοσιν τῶν ἀρχαίων") == []


# -- the episode index (V6) -------------------------------------------------------------

AMBIGUOUS_FIXTURE = FIXTURE + """$========== PERSON(s)
Salem@Jdg.1.1=H9999\tA person confusingly named Salem\t\t\t\t\t\t#desc\tperson
– Named\tSalem@Jdg.1.1\tH9999«H9999=שָׁלֵם\tSalem\thttps://x\tJdg.1.1
"""


def _theographic_archive(home: DataHome) -> Path:
    archive = home.sources / "theographic" / "2026-08-17"
    archive.mkdir(parents=True)
    (archive / "People.csv").write_text(
        "personLookup,status,displayTitle\n"
        "abraham_1,ok,Abraham\n"
        "melchizedek_1,ok,Melchizedek\n",
        "utf-8",
    )
    (archive / "Places.csv").write_text(
        "placeLookup,status,displayTitle\nsalem_1,ok,Salem\n", "utf-8"
    )
    (archive / "Events.csv").write_text(
        "title,eventID,verses,participants,locations\n"
        'Melchizedek blesses Abram,evt1,"Gen.14.17,Gen.14.18,Gen.14.19,Gen.14.20,'
        'Gen.15.1","abraham_1,melchizedek_1",salem_1\n'
        'Abraham alone,evt2,"Gen.22.1",abraham_1,\n'
        'No verses at all,evt3,"not.a.ref",abraham_1,\n',
        "utf-8",
    )
    return archive


def test_the_episode_build_spans_chapters_and_counts_ambiguity(tmp_path: Path) -> None:
    home = DataHome(tmp_path)
    tipnr = home.sources / "tipnr" / "2026-08-17"
    tipnr.mkdir(parents=True)
    (tipnr / "tipnr.txt").write_text(AMBIGUOUS_FIXTURE, "utf-8")
    _theographic_archive(home)
    out = tmp_path / "entities.sqlite"
    build_entities(home, out)

    import sqlite3

    db = sqlite3.connect(out)
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["events"] == "2", "the unparseable-verses event is dropped"
    assert meta["crosswalk_ambiguous"] == "1", "two TIPNR entities named Salem: counted"
    linked = {row[0] for row in db.execute("SELECT entity FROM event_entity WHERE event='evt1'")}
    assert linked == {"Abraham@Gen.11.26-1Pe=H0085", "Melchizedek@Gen.14.18-Heb=H4442"}, (
        "the ambiguous Salem is never guessed"
    )

    index = Entities(out)
    episodes = index.episodes({"Abraham@Gen.11.26-1Pe=H0085", "Melchizedek@Gen.14.18-Heb=H4442"})
    assert len(episodes) == 1, "the one-participant event never meets least=2"
    title, _vrs, book, c1, v1, c2, v2, names = episodes[0]
    assert title == "Melchizedek blesses Abram"
    assert (book, c1, v1, c2, v2) == ("GEN", 14, 17, 15, 1), (
        "the episode span crosses the chapter line a co-mention window cannot"
    )
    assert names == frozenset({"Abraham@Gen.11.26-1Pe=H0085", "Melchizedek@Gen.14.18-Heb=H4442"})


def test_a_build_without_the_theographic_archive_still_stands(tmp_path: Path) -> None:
    home = DataHome(tmp_path)
    tipnr = home.sources / "tipnr" / "2026-08-17"
    tipnr.mkdir(parents=True)
    (tipnr / "tipnr.txt").write_text(FIXTURE, "utf-8")
    out = tmp_path / "entities.sqlite"
    result = build_entities(home, out)
    assert result.entities == 3
    assert Entities(out).episodes({"a", "b"}) == []


@real
def test_the_real_index_holds_a_cross_chapter_episode() -> None:
    index = Entities(ENTITIES)
    import sqlite3

    db = sqlite3.connect(ENTITIES)
    if not db.execute("SELECT name FROM sqlite_master WHERE name='event'").fetchone():
        pytest.skip("entities.sqlite predates the episode tables")
    ids = {
        str(row[0])
        for row in db.execute("SELECT id FROM entity WHERE label IN ('Abraham', 'Lot')")
    }
    spans = {(e[0], e[2], e[3], e[5]) for e in index.episodes(ids)}
    assert ("Sodom Destroyed", "GEN", 18, 19) in spans, (
        "Genesis 18-19 is one story, and only the episode index can say so"
    )


def test_the_index_has_a_command_of_its_own() -> None:
    """The gap another reader found: TIPNR and Theographic are indexes, not scripture, so
    they are absent from the registry `fetch --source` resolves against and both carry a
    `build` that refuses. Correct -- and it left the entity index with no CLI route at
    all, so a clean checkout could not build it without hand-written Python. That is the
    derivable-from-zero promise broken quietly, which is the worst way."""
    from biblereference.cli import build_parser

    parsed = build_parser().parse_args(["entities"])
    assert parsed.func.__name__ == "cmd_entities"
    assert parsed.force is False
