"""The Antoniades transliterator and build: letter-exact or refused.

The upstream is Online-Bible ASCII, not TLG betacode -- y is θ, c is χ, q is ψ -- and
the build verifies every verse's letters against the upstream's own Unicode conversion,
so the real acceptance runs at build time over all 7,957 verses. These tests pin the
scheme on known text, the refusal on unmapped characters, and the parser on the
upstream's own defects (a verse jammed mid-line, a dropped space).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biblereference.corpora.antoniades import _BOOKS, _verses, build, transliterate

ARCHIVE = sorted(
    (Path.home() / ".local/share/biblereference/sources/antoniades").glob("*"),
    reverse=True,
)


def test_the_scheme_is_online_bible_not_tlg() -> None:
    assert transliterate("yeov") == "θεος", "y is theta, and final sigma is spelled v"
    assert transliterate("cristou") == "χριστου", "c is chi"
    assert transliterate("anepemqa") == "ανεπεμψα", "q is psi"
    assert transliterate("doxa") == "δοξα", "x is xi"
    assert transliterate("ekklhsia:") == "εκκλησια·", "the colon is the ano teleia"
    assert transliterate("swmatov, -- ou") == "σωματος,— ου", (
        "a doubled hyphen is their em-dash, closed up to the word before"
    )


def test_an_unmapped_character_refuses_rather_than_passes() -> None:
    with pytest.raises(ValueError, match="no Greek"):
        transliterate("kai & yeov")


def test_the_parser_splits_refs_wherever_the_upstream_jammed_them(tmp_path: Path) -> None:
    """John 4:2 ends 4:1's line in the upstream's JOH.txt; the parser must see it."""
    path = tmp_path / "sample.txt"
    path.write_text("4:1 αλφα βητα4:2 γαμμα\n4:3 δελτα\n  εψιλον\n", "utf-8")
    assert list(_verses(path)) == [
        (4, 1, "αλφα βητα"),
        (4, 2, "γαμμα"),
        (4, 3, "δελτα εψιλον"),
    ]


@pytest.mark.skipif(not ARCHIVE, reason="antoniades archive not fetched")
def test_the_real_build_is_letter_exact_across_the_canon() -> None:
    (corpus,) = build(ARCHIVE[0])
    assert corpus.id == "grcant" and corpus.versification == "org"
    assert len(corpus.verses) > 7_900
    assert {ref.book for ref, _ in corpus.verses} == set(_BOOKS.values())
    jhn = {(ref.chapter, ref.verse): text for ref, text in corpus.verses if ref.book == "JHN"}
    assert jhn[(4, 2)].startswith("—"), "the jammed verse exists, dash and all"
    assert jhn[(1, 1)] == (
        "εν αρχη ην ο λογος, και ο λογος ην προς τον θεον, και θεος ην ο λογος."
    )
