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


# --------------------------------------------------------------------------------------
# Where the new corpora part company with the systems they declare
# --------------------------------------------------------------------------------------


def _ends_elsewhere(corpus: str, system: str, vrs: Versification) -> set[tuple[str, int]]:
    """Complete chapters this corpus ends somewhere its system does not.

    Complete only: a chapter the edition printed with a hole in it says nothing about
    numbering, and counting it would turn a missing page into a disagreement.
    """
    import sqlite3
    from pathlib import Path

    from biblereference.versification import VersificationError

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    out: set[tuple[str, int]] = set()
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT book, chapter, MIN(verse), MAX(verse), COUNT(DISTINCT verse) FROM verse "
            "WHERE corpus = ? AND verse > 0 GROUP BY book, chapter",
            (corpus,),
        ).fetchall()
    for book, chapter, low, high, count in rows:
        if count != high - low + 1:
            continue
        try:
            declared = vrs.max_verse(system, str(book), int(chapter))
        except VersificationError:
            continue
        if high != declared:
            out.add((str(book), int(chapter)))
    return out


def test_rahlfs_parts_from_lxx_in_sixteen_chapters_and_they_are_named(
    vrs: Versification,
) -> None:
    """The queue for a future `rahlfs` system, and mostly a reassurance.

    Rahlfs seeds its own family in `biblereference families`, so it is a numbering of its
    own rather than a member of `lxx`. This says how much of one: sixteen chapters out of
    1,135, and five of those are the Odes, which no two editions agree about.

    The interesting one is Deuteronomy. Rahlfs ends chapter 28 at verse 69 and chapter 29
    at 28 -- the Hebrew division, which is what `org` and the Peshitta use -- where Swete,
    Brenton, LXX2012 and `lxx` itself all use 28:68 and 29:29. So `lxx`'s Deuteronomy
    follows Swete and Brenton, and the standard critical text does not.

    Pinned rather than corrected: `faithful_chapters` already excludes these from every
    comparison, so nothing rests on them, and changing `lxx` to suit one witness would only
    make it differently wrong -- the same argument that keeps Swete filed where it is.
    """
    assert _ends_elsewhere("rahlfs", "lxx", vrs) == {
        ("2SA", 23),
        ("4MA", 12),
        ("DEU", 28),
        ("DEU", 29),
        ("EZR", 14),
        ("EZR", 19),
        ("NUM", 6),
        ("NUM", 33),
        ("ODA", 5),
        ("ODA", 6),
        ("ODA", 7),
        ("ODA", 8),
        ("ODA", 13),
        ("PRO", 30),
        ("PRO", 31),
        ("WIS", 17),
    }


def test_the_peshitta_parts_from_org_almost_only_where_no_edition_agrees(
    vrs: Versification,
) -> None:
    """Forty-seven chapters of 1,142, and the shape of them is the point.

    Fifteen are the Psalms of Solomon, ten are 4 Ezra, seven the Odes and four Tobit --
    books that survive in several recensions and that no two editions number alike. Strip
    those and twelve are left in the whole protocanon and deuterocanon: Joshua 10, two
    psalms, two chapters of Sirach, and a handful in Esdras and Maccabees.

    That is the case for calling the Peshitta an `org` corpus, and it is a strong one: a
    second-century translation made from the Hebrew agrees with the Hebrew's divisions
    almost everywhere it can be checked.
    """
    off = _ends_elsewhere("peshitta-ot", "org", vrs)
    assert len(off) == 47
    contested = {"PSS", "EZA", "ODA", "TOB"}
    assert sorted(book for book, _ in off if book not in contested) == [
        "1ES",
        "1ES",
        "1MA",
        "1MA",
        "4MA",
        "4MA",
        "JOS",
        "PSA",
        "PSA",
        "SIR",
        "SIR",
    ]


def test_the_two_rahlfs_transcriptions_differ_over_lettered_pluses(vrs: Versification) -> None:
    """Why two copies of one edition land in different families.

    Rahlfs prints material the Hebrew has not — Job's epilogue, the end of Joshua, Esther's
    Greek additions — and numbers it with letters. The Patristic Text Archive keeps the
    letters and Corpus Corporum renumbers them as plain verses running on from the last.

    `lxx` declares the lettered form, so PTA's numbering is the one that resolves and
    Corpus Corporum's extra verses are outside every shipped system. Worth pinning because
    it decides which of the two may be a witness: `rahlfs` can, `rahlfs-cc` cannot.
    """
    import sqlite3
    from pathlib import Path

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:

        def top(corpus: str, book: str, chapter: int) -> tuple[int, int]:
            rows = connection.execute(
                "SELECT verse, subverse FROM verse WHERE corpus = ? AND book = ? AND chapter = ?",
                (corpus, book, chapter),
            ).fetchall()
            return max(v for v, _ in rows), sum(1 for _, s in rows if s)

    for book, chapter in (("JOB", 42), ("JOS", 24), ("ESG", 10)):
        declared = vrs.max_verse("lxx", book, chapter)
        pta_top, pta_letters = top("rahlfs", book, chapter)
        cc_top, cc_letters = top("rahlfs-cc", book, chapter)
        assert pta_top == declared, f"{book} {chapter}: PTA should match what lxx declares"
        assert pta_letters > 0, f"{book} {chapter}: PTA should keep the letters"
        assert cc_top > declared, f"{book} {chapter}: Corpus Corporum should run past it"
        assert cc_letters == 0, f"{book} {chapter}: Corpus Corporum should have no letters"


def test_swete_carries_no_apparatus_markers_in_its_text() -> None:
    """Swete brackets a substituted reading and marks an interpolation, and this
    digitisation kept the marks: 634 of them across 402 verses, where Rahlfs, Brenton,
    Nestle 1904, the SBLGNT and Westcott-Hort carry none.

    They are in the text that gets searched, folded and quote-checked -- a reader looking
    for ὅτι τέθνηκεν ὁ κύριος ὑμῶν Σαούλ does not expect ⸂⸆⸃ in the middle of it. Found by
    diffing this digitisation against First1KGreek's of the same edition, which is the
    whole reason for holding two copies.
    """
    import sqlite3
    from pathlib import Path

    database = Path.home() / ".local/share/biblereference/db/corpus.sqlite"
    if not database.exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        offenders = connection.execute(
            "SELECT corpus, COUNT(*) FROM verse "
            "WHERE text LIKE '%⸂%' OR text LIKE '%⸃%' OR text LIKE '%⸆%' GROUP BY corpus"
        ).fetchall()
    assert offenders == []
