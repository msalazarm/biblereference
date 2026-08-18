"""The V5 breadth corpora: Van Dyck Arabic and the Elizabeth Slavonic.

Both are positioning texts -- no father quotes them -- so what the tests defend is
structural: the zText slot walk cannot misfile a verse (it refuses instead), the
Synodal shape survives (Psalm 151), and the Arabic build lands whole through the same
USFM machinery every eBible text uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.slavonic import _plain, _walk
from biblereference.corpora.slavonic import build as build_slavonic

SOURCES = Path.home() / ".local/share/biblereference/sources"


def _latest(name: str) -> Path | None:
    hits = sorted((SOURCES / name).glob("*")) if (SOURCES / name).is_dir() else []
    return hits[-1] if hits else None


def test_osis_markup_is_stripped_and_notes_go_whole() -> None:
    markup = (
        'Слово <note type="study">the editor speaking</note> '
        "<w lemma='x'>Бог</w> &amp; свет"
    )
    assert _plain(markup) == "Слово Бог & свет"


def test_a_broken_slot_walk_refuses_rather_than_misfiles(tmp_path: Path) -> None:
    """A chapter marker that does not continue the open book means every following
    verse would be misfiled -- the walk must stop dead instead."""
    import struct
    import zipfile
    import zlib

    slots = [
        b'<div osisID="Gen" type="book"/>',
        b'<chapter osisID="Exod.5"/>',  # wrong book, wrong number
        b"text",
    ]
    block = b"".join(slots)
    packed = zlib.compress(block)
    bzv = b""
    at = 0
    for slot in slots:
        bzv += struct.pack("<IIH", 0, at, len(slot))
        at += len(slot)
    with zipfile.ZipFile(tmp_path / "CSlElizabeth.zip", "w") as bundle:
        base = "modules/texts/ztext/cslelizabeth/"
        bundle.writestr(base + "ot.bzv", bzv)
        bundle.writestr(base + "ot.bzs", struct.pack("<III", 0, len(packed), len(block)))
        bundle.writestr(base + "ot.bzz", packed)
    with pytest.raises(ValueError, match="refusing to misfile"):
        list(_walk(tmp_path, "ot"))


@pytest.mark.skipif(_latest("slavonic") is None, reason="slavonic archive not fetched")
def test_the_real_elizabeth_bible_has_its_orthodox_shape() -> None:
    (corpus,) = build_slavonic(_latest("slavonic"))
    assert corpus.id == "chuelz" and corpus.versification == "rso"
    assert len(corpus.verses) > 35_000
    psalms = [ref for ref, _ in corpus.verses if ref.book == "PSA"]
    assert max(ref.chapter for ref in psalms) == 151, "the Orthodox Psalter"
    gen = next(t for ref, t in corpus.verses if ref.book == "GEN" and ref.chapter == 1)
    assert gen == "В начале сотвори Бог небо и землю."
    assert "<" not in " ".join(t for _, t in corpus.verses[:500]), "no tag survives"


@pytest.mark.skipif(_latest("arbvd") is None, reason="arb-vd archive not fetched")
def test_the_real_van_dyck_lands_whole() -> None:
    from biblereference.corpora.ebible import build_arbvd

    (corpus,) = build_arbvd(_latest("arbvd"))
    assert corpus.id == "arbvd" and corpus.language == "ar"
    assert len(corpus.verses) > 31_000
    assert len({ref.book for ref, _ in corpus.verses}) == 66


# -- the Sahidic OT and the Samaritan Pentateuch ----------------------------------------


def test_the_tt_parser_reads_bound_groups_and_skips_paratext() -> None:
    from biblereference.corpora.sahidicot import _verses

    body = (
        '<verse_n vname="Genesis 1:1" verse_n="1">\n'
        '<norm_group orig_group="x" norm_group="ϩⲛⲧⲁⲣⲭⲏ">\n'
        '<norm xml:id="u1" norm="ϩⲛ">\nϩⲛ\n</norm>\n'
        "</norm_group>\n"
        '<norm_group norm_group="ⲁⲡⲛⲟⲩⲧⲉ">\n</norm_group>\n'
        "</verse_n>\n"
        '<verse_n vname="Leviticus 0:1" verse_n="1">\n'
        '<norm_group norm_group="paratext">\n</norm_group>\n'
        "</verse_n>\n"
    )
    assert list(_verses(body)) == [("Genesis", 1, 1, "ϩⲛⲧⲁⲣⲭⲏ ⲁⲡⲛⲟⲩⲧⲉ")], (
        "bound groups joined, morphs ignored, chapter-0 paratext skipped"
    )


def test_the_tf_reader_handles_anchors_implicit_advance_and_ranges(tmp_path: Path) -> None:
    from biblereference.corpora.samaritan import _features, _slots

    feature = tmp_path / "f.tf"
    feature.write_text("@node\n@valueType=str\n\n5\talpha\nbeta\n\ndelta\n9-10\tsame\n", "utf-8")
    assert _features(feature) == {
        5: "alpha", 6: "beta", 7: "", 8: "delta", 9: "same", 10: "same"
    }, "explicit anchor, implicit advance, empty line as empty value, range assignment"
    edges = tmp_path / "o.tf"
    edges.write_text("@edge\n@oslots\n\n40\t1-10\n11-20,25\n", "utf-8")
    assert _slots(edges) == {40: (1, 10), 41: (11, 25)}


@pytest.mark.skipif(_latest("sahidicot") is None, reason="sahidic archive not fetched")
def test_the_real_sahidic_ot_holds_its_advertised_shape() -> None:
    from biblereference.corpora.sahidicot import build as build_sahot

    (corpus,) = build_sahot(_latest("sahidicot"))
    assert corpus.id == "sahot" and corpus.language == "cop"
    assert len(corpus.verses) > 19_000
    psalms = [ref.chapter for ref, _ in corpus.verses if ref.book == "PSA"]
    assert max(psalms) == 151, "the full Psalter, Greek-numbered"
    gen = next(t for ref, t in corpus.verses if ref.book == "GEN" and ref.chapter == 1)
    assert gen.startswith("ϩⲛⲧⲁⲣⲭⲏ"), "the bound-group text, not the morph splits"
    assert min(ref.chapter for ref, _ in corpus.verses) >= 1, "no chapter-0 paratext"


@pytest.mark.skipif(_latest("samaritan") is None, reason="samaritan archive not fetched")
def test_the_real_samaritan_pentateuch_rejoins_its_clitics() -> None:
    from biblereference.corpora.samaritan import build as build_smp

    (corpus,) = build_smp(_latest("samaritan"))
    assert corpus.id == "smp" and corpus.language == "hbo" and corpus.versification == "org"
    assert len(corpus.verses) == 5_841
    assert sorted({ref.book for ref, _ in corpus.verses}) == ["DEU", "EXO", "GEN", "LEV", "NUM"]
    gen = next(t for ref, t in corpus.verses if ref.book == "GEN" and ref.chapter == 1)
    assert gen.startswith("בראשׁית ברא"), "the clitic trailer rejoined the split word"
