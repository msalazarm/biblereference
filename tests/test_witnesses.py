"""Which corpus is allowed to speak for which versification family.

Every alignment result in the audit is a claim about two *systems* backed by a comparison
of two *texts*. If a text does not follow the system it is filed under, the comparison
measures the text and the conclusion is worthless -- and that is not hypothetical: using
the Orthodox Jewish Bible as the witness for `org` produced thirteen flagged runs that
dissolved the moment the Westminster Leningrad Codex was substituted for it.

So the witnesses are checked here rather than assumed, structurally and with no similarity
scoring at all. See ``docs/witness-validation.md``.

These tests need the corpora, which a fresh checkout does not have; they skip rather than
fail when it is absent, because a missing corpus is not a broken mapping.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biblereference.versification import Versification, VersificationError


@pytest.fixture(scope="module")
def corpus_db() -> sqlite3.Connection:
    path = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not path.exists():
        pytest.skip("corpus not built; run `biblereference fetch`")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def complete_chapters(db: sqlite3.Connection, corpus: str) -> dict[tuple[str, int], int]:
    """Chapters the corpus holds whole: verses 1..n with nothing missing.

    Judging on the highest *printed* verse instead scores an abridged corpus by how much it
    left out -- it rated the `nna` selection at 42% agreement and read as a catastrophic
    misfile, when in truth it holds only twelve complete chapters and is a reader's
    selection rather than a Bible.
    """
    rows = db.execute(
        "SELECT book, chapter, MAX(verse), COUNT(DISTINCT verse), MIN(verse) FROM verse "
        "WHERE corpus = ? AND verse > 0 GROUP BY book, chapter",
        (corpus,),
    )
    return {(b, ch): top for b, ch, top, n, low in rows if low == 1 and n == top}


def disagreements(vrs: Versification, shape: dict[tuple[str, int], int], system: str) -> list[str]:
    out: list[str] = []
    for (book, chapter), top in sorted(shape.items()):
        try:
            declared = vrs.max_verse(system, book, chapter)
        except VersificationError:
            continue  # the system does not carry this chapter; not a disagreement
        if top != declared:
            out.append(f"{book} {chapter}: corpus={top} {system}={declared}")
    return out


# --------------------------------------------------------------------------------------
# The witnesses the audit actually leans on
# --------------------------------------------------------------------------------------


def test_the_leningrad_codex_agrees_with_org_everywhere(
    corpus_db: sqlite3.Connection, vrs: Versification
) -> None:
    """The Hebrew witness is exact across all 929 chapters, which is what earns `org` the
    right to be the pivot every conversion routes through."""
    shape = complete_chapters(corpus_db, "wlc")
    if not shape:
        pytest.skip("wlc not present")
    assert len(shape) == 929
    assert disagreements(vrs, shape, "org") == []


def test_the_nova_vulgata_agrees_with_nvl_everywhere(
    corpus_db: sqlite3.Connection, vrs: Versification
) -> None:
    """`nvl` is the least independently checked system here -- its data was generated from
    the Vatican pages by this project rather than vendored from upstream -- and it is the
    one family with no second witness. Exact agreement is the whole of its evidence."""
    shape = complete_chapters(corpus_db, "novavulgata")
    if not shape:
        pytest.skip("novavulgata not present")
    assert disagreements(vrs, shape, "nvl") == []


def test_the_orthodox_jewish_bible_is_not_a_witness_for_org(
    corpus_db: sqlite3.Connection, vrs: Versification
) -> None:
    """It is still an `org` corpus -- 99.2%, and no system fits it better -- but it is not
    verse-exact, and an audit cannot tell 'the mapping is wrong' from 'the witness is
    idiosyncratic'. Where it and `wlc` disagree, `wlc` sides with `org` every time.

    This test pins the *disqualification*. If the OJB ever becomes exact, it fails, and
    that is the point: the reason to exclude it would be gone.
    """
    shape = complete_chapters(corpus_db, "ojb")
    if not shape:
        pytest.skip("ojb not present")
    assert disagreements(vrs, shape, "org") != []


def test_the_latin_witness_beats_the_english_one_for_the_vulgate(
    corpus_db: sqlite3.Connection, vrs: Versification
) -> None:
    """Douay-Rheims against Vulgata Clementina: 14 chapters differ, and `vul` sides with
    the Latin on 11 of them. The same shape as the OJB finding -- a translation carries its
    translators' chapter divisions, not its source's."""
    latin = complete_chapters(corpus_db, "latvuc")
    english = complete_chapters(corpus_db, "dra")
    if not latin or not english:
        pytest.skip("vulgate witnesses not present")
    assert len(disagreements(vrs, latin, "vul")) < len(disagreements(vrs, english, "vul"))


def test_lxx_follows_brenton_rather_than_swete(
    corpus_db: sqlite3.Connection, vrs: Versification
) -> None:
    """The one family where the *English* witness is authoritative, because the `lxx` data
    was built from the English tradition. Swete is a Greek critical edition following the
    Greek chapter divisions, and is filed under `lxx` incorrectly -- but it fits no other
    system either, so relabelling it would only make it differently wrong.
    """
    swete = complete_chapters(corpus_db, "swete")
    brenton = complete_chapters(corpus_db, "brenton")
    if not swete or not brenton:
        pytest.skip("septuagint witnesses not present")

    for_brenton = for_swete = 0
    for key in set(swete) & set(brenton):
        if swete[key] == brenton[key]:
            continue
        try:
            declared = vrs.max_verse("lxx", *key)
        except VersificationError:
            continue
        for_brenton += declared == brenton[key]
        for_swete += declared == swete[key]

    assert for_brenton > 5 * for_swete
    assert len(disagreements(vrs, swete, "lxx")) > 100


def test_every_corpus_declares_a_versification_this_library_ships() -> None:
    """An unshipped versification does not crash, and that is the problem.

    `write_corpus` does not validate it, `search` and `families` never convert, and both
    `render` and `compare` catch `VersificationError` -- so a corpus declaring `rahlfs`
    would build, index and search perfectly well while being *silently invisible to the
    renderer*. Nothing would say so. This does.
    """
    import sqlite3
    from pathlib import Path

    from biblereference.versification import AVAILABLE_SYSTEMS

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        declared = {
            (row[0], row[1])
            for row in connection.execute("SELECT corpus, versification FROM source_meta")
        }
    unknown = sorted(
        f"{corpus} -> {system}" for corpus, system in declared if system not in AVAILABLE_SYSTEMS
    )
    assert unknown == []


def test_rahlfs_follows_the_psalms_of_solomon_that_lxx_declares_and_swete_does_not(
    vrs: Versification,
) -> None:
    """The clearest case for having both Greek Septuagints rather than one.

    Rahlfs numbers each psalm's superscription as verse 0; Swete folds it into verse 1 and
    is one ahead from there down. Over the eighteen psalms, Rahlfs matches what `lxx`
    declares on **all eighteen** and Swete on three.

    This is the blind spot `faithful_chapters` documents, seen from the other side: a
    corpus that folds a title into verse 1 looks plausible chapter by chapter and is wrong
    all the way down, and only a second witness makes it visible.
    """
    import sqlite3
    from pathlib import Path

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:

        def tops(corpus: str) -> dict[int, int]:
            return {
                int(ch): int(top)
                for ch, top in connection.execute(
                    "SELECT chapter, MAX(verse) FROM verse WHERE corpus = ? AND book = 'PSS' "
                    "GROUP BY chapter",
                    (corpus,),
                )
            }

        swete, rahlfs = tops("swete"), tops("rahlfs")

    declared = {ch: vrs.max_verse("lxx", "PSS", ch) for ch in range(1, 19)}
    assert sum(rahlfs.get(ch) == top for ch, top in declared.items()) == 18
    assert sum(swete.get(ch) == top for ch, top in declared.items()) == 3


def test_the_syriac_new_testament_is_the_most_faithful_witness_to_the_pivot() -> None:
    """Worth stating because it is the opposite of what one would guess.

    `org`'s New Testament declares the traditional verse set, which includes verses the
    critical Greek editions omit -- so Nestle 1904, the SBLGNT and Westcott-Hort each have
    a dozen or more chapters that end short of what the pivot says. The Peshitta, being a
    Byzantine-tradition text, has them, and ends up counting as `org` says on 257 of its
    260 chapters.
    """
    from pathlib import Path

    from biblereference.audit import faithful_chapters
    from biblereference.store import DataHome

    data = DataHome(Path.home() / ".local/share/biblereference")
    if not Path(data.database).exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    vrs = Versification.load()
    scored = {
        corpus: len(faithful_chapters(data, corpus, "org", vrs))
        for corpus in ("peshitta-nt", "wh", "n1904", "sblgnt")
    }
    assert scored["peshitta-nt"] > max(scored[other] for other in ("wh", "n1904", "sblgnt"))
