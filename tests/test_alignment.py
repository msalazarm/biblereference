"""Mappings checked against the text they claim to align.

A wrong mapping is silent. It returns the neighbouring verse with no error and no warning,
and every quotation built on it is wrong in a way nothing downstream can detect. These
tests are the guard: each pins an alignment that was verified against the actual words of
two editions, so a change to the versification data that breaks one fails here rather than
in someone's treatise.

The method is differential. Two translations of one verse may share almost no vocabulary --
the Douay-Rheims and the Orthodox Jewish Bible render Psalm 23:1 at 0.15 similarity and are
plainly the same verse -- so nothing here asserts that a mapping scores *well*. It asserts
that it scores *better than its neighbours*, which is what survives translation.

See :mod:`biblereference.audit` for the instrument and ``docs/versification-audit.md`` for
what the full sweep found.
"""

from __future__ import annotations

import pytest

from biblereference.canon import CANONICAL_ORDER
from biblereference.refs import VerseRef
from biblereference.versification import (
    AVAILABLE_SYSTEMS,
    PIVOT,
    Versification,
    VersificationError,
)


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


def convert(vrs: Versification, ref: str, source: str, target: str) -> str:
    book, position = ref.split(" ")
    chapter, verse = position.split(":")
    out = vrs.convert_all(VerseRef(book, int(chapter), int(verse), vrs=source), target)
    return str(out[0]) if out else ""


# --------------------------------------------------------------------------------------
# Jonah: found by the audit, one verse out in every Vulgate citation
# --------------------------------------------------------------------------------------


def test_the_vulgate_puts_the_great_fish_at_jonah_2_1(vrs: Versification) -> None:
    """The Vulgate follows the Hebrew here: Jonah 1 ends at verse 16 and the fish opens
    chapter 2. Only the English tradition has a seventeenth verse in chapter 1.

    The vendored data carried the *English* mapping inside the Vulgate file -- including a
    source verse, JON 1:17, that the Vulgate does not have -- so every Vulgate citation of
    Jonah 2 resolved one verse late and 'Jonah 2:1' returned the prayer instead of the fish
    that prompted it.
    """
    assert convert(vrs, "JON 2:1", "vul", "org") == "JON 2:1"
    assert convert(vrs, "JON 2:10", "vul", "org") == "JON 2:10"


def test_the_english_tradition_still_puts_it_at_jonah_1_17(vrs: Versification) -> None:
    """The other half of the same fix. English really is offset here, and correcting the
    Vulgate must not flatten that -- otherwise the fix trades one wrong answer for another.
    """
    assert convert(vrs, "JON 1:17", "eng", "org") == "JON 2:1"
    assert convert(vrs, "JON 2:1", "eng", "org") == "JON 2:2"


def test_the_septuagint_agrees_with_the_hebrew_on_jonah(vrs: Versification) -> None:
    """Brenton's Septuagint and the Douay-Rheims both put the fish at 2:1, which is the
    independent evidence that made the Vulgate entry indefensible."""
    assert convert(vrs, "JON 2:1", "lxx", "org") == "JON 2:1"


# --------------------------------------------------------------------------------------
# Bel and the Dragon: one verse out for its whole length
# --------------------------------------------------------------------------------------


def test_the_clementine_closes_susanna_with_the_astyages_verse(vrs: Versification) -> None:
    """Daniel 13:65 is 'Et rex Astyages appositus est ad patres suos', the opening of Bel
    in the Greek. The Clementine prints it as the last verse of Susanna rather than the
    first of Bel, so its chapter 14 begins at the Greek's second verse."""
    assert convert(vrs, "DAN 13:65", "vul", "org") == "BEL 1:1"
    assert convert(vrs, "DAN 14:1", "vul", "org") == "BEL 1:2"


def test_bel_runs_one_behind_for_the_whole_book(vrs: Versification) -> None:
    """The data carried both 'DAN 13:65 -> BEL 1:1' and 'DAN 14:1 -> BEL 1:1' and an
    earlier reading of this file took them for two printings of one verse. They are two
    different verses, and taking them otherwise displaced all forty-two."""
    assert convert(vrs, "DAN 14:2", "vul", "org") == "BEL 1:3"
    assert convert(vrs, "DAN 14:41", "vul", "org") == "BEL 1:42"


def test_bel_resolves_back_to_the_verse_the_clementine_prints_it_at(
    vrs: Versification,
) -> None:
    assert convert(vrs, "BEL 1:1", "org", "vul") == "DAN 13:65"
    assert convert(vrs, "BEL 1:2", "org", "vul") == "DAN 14:1"


# --------------------------------------------------------------------------------------
# Baruch: two separate faults, one at each end of the book
# --------------------------------------------------------------------------------------


def test_the_english_merges_the_star_passage_in_baruch_3(vrs: Versification) -> None:
    """English Baruch 3 has 37 verses where every other system has 38, because it runs
    'The stars shone in their watches, and were glad' together with 'they said, Here we
    are' as a single 3:34. No mapping recorded it, so the last three verses resolved one
    early -- and 3:36 is 'This is our God, and there shall no other be accounted of in
    comparison to him', which is not an obscure verse to get wrong."""
    assert convert(vrs, "BAR 3:34", "eng", "org") == "BAR 3:34"
    assert convert(vrs, "BAR 3:35", "eng", "org") == "BAR 3:36"
    assert convert(vrs, "BAR 3:37", "eng", "org") == "BAR 3:38"


def test_the_english_counts_the_letter_of_jeremiah_heading_as_a_verse(
    vrs: Versification,
) -> None:
    """'A copy of a letter that Jeremy sent' is verse 1 in English and unnumbered in the
    Latin, so the English runs one ahead for all seventy-two verses. The old mapping sent
    its last verse to LJE 1:73, which org does not have -- the same ghost that identified
    the Jonah fault, pointing the other way."""
    assert convert(vrs, "BAR 6:2", "eng", "org") == "LJE 1:1"
    assert convert(vrs, "BAR 6:73", "eng", "org") == "LJE 1:72"
    assert convert(vrs, "BAR 6:1", "vul", "org") == "LJE 1:1"


# --------------------------------------------------------------------------------------
# Structural proofs: no corpora, no similarity, no judgement
# --------------------------------------------------------------------------------------


def test_no_conversion_can_return_a_verse_that_does_not_exist() -> None:
    """The strongest guarantee here, and the only one that is a proof rather than a
    measurement: convert every verse of every system into the pivot and check that what
    comes back is a verse the pivot actually has.

    A verse with no mapping keeps its coordinates and is relabelled, which is right for
    almost everything. But where a system carries text the pivot does not -- the six extra
    verses of Greek Joshua 24, the pluses in Greek Proverbs, the Esdras material, the
    sixty-eighth verse of the Song of the Three -- that fall-through used to invent a
    reference: it looked like an answer and pointed at nothing. Eighteen such conversions
    existed. They are refusals now, which is what this library does everywhere else it
    cannot resolve something.

    This covers `rsc` and `rso` too, which no textual audit can reach because no corpus
    exists in either.
    """
    vrs = Versification.load(AVAILABLE_SYSTEMS)
    invented: list[str] = []

    for system in AVAILABLE_SYSTEMS:
        if system == PIVOT:
            continue
        for book in CANONICAL_ORDER:
            for chapter in range(1, vrs.chapter_count(system, book) + 1):
                low = vrs.first_verse(system, book, chapter)
                high = vrs.max_verse(system, book, chapter)
                for verse in range(low, high + 1):
                    ref = VerseRef(book, chapter, verse, vrs=system)
                    try:
                        targets = vrs.convert_all(ref, PIVOT)
                    except VersificationError:
                        continue  # a refusal is an answer
                    for target in targets:
                        if vrs.chapter_count(PIVOT, target.book) == 0 or target.verse == 0:
                            continue
                        try:
                            top = vrs.max_verse(PIVOT, target.book, int(target.chapter))
                        except VersificationError:
                            invented.append(f"{system}: {ref} -> {target}")
                            continue
                        if target.verse > top:
                            invented.append(f"{system}: {ref} -> {target} (max {top})")

    assert invented == []


def test_no_mapping_targets_a_verse_the_pivot_lacks() -> None:
    """The mirror of the ghost-source invariant below, and the one that would have caught
    the Letter of Jeremiah. A mapping may not send a verse somewhere org cannot hold it."""
    import json
    import re
    from importlib import resources

    pattern = re.compile(r"^(\w+) (\d+):(\d+)(?:-(\d+))?$")
    data = resources.files("biblereference.versification").joinpath("data")
    org = json.loads(data.joinpath("org.json").read_text(encoding="utf-8"))["maxVerses"]
    corrections = json.loads(data.joinpath("corrections.json").read_text(encoding="utf-8"))

    ghosts: list[str] = []
    for system in ("eng", "vul"):
        loaded = json.loads(data.joinpath(f"{system}.json").read_text(encoding="utf-8"))
        dropped = {
            key for entry in corrections["drop_mapped"].get(system, []) for key in entry["keys"]
        }
        added = corrections["add_mapped"].get(system, {})
        mappings = {k: v for k, v in loaded["mappedVerses"].items() if k not in dropped}
        mappings.update({k: spec["to"] for k, spec in added.items()})

        for key, target in mappings.items():
            for one in target if isinstance(target, list) else [target]:
                match = pattern.match(str(one).strip())
                if not match:
                    continue
                book, chapter, first, last = match.groups()
                rows = org.get(book)
                if not rows or int(chapter) > len(rows):
                    continue
                top = int(rows[int(chapter) - 1])
                if int(last or first) > top:
                    ghosts.append(f"{system}: {key} -> {one}, but org {book} {chapter} has {top}")

    assert ghosts == []


def test_no_mapping_names_a_verse_its_own_system_lacks() -> None:
    """The invariant the Jonah fault broke, and the cheapest way to catch its whole class.

    A mapping file describes one Bible. An entry keyed on a verse that Bible does not have
    is describing a different one -- which is exactly how the English Jonah mapping was
    identified inside the Vulgate file, since it was keyed on JON 1:17 and the Vulgate's
    Jonah 1 stops at 16.
    """
    import json
    import re
    from importlib import resources

    pattern = re.compile(r"^(\w+) (\d+):(\d+)(?:-(\d+))?$")
    data = resources.files("biblereference.versification").joinpath("data")
    # After corrections, not before: the vendored files are upstream's and are left as
    # they came, so the invariant belongs to the data the loader actually builds.
    corrections = json.loads(data.joinpath("corrections.json").read_text(encoding="utf-8"))

    ghosts: list[str] = []
    for system in ("vul", "nvl", "rsc"):
        loaded = json.loads(data.joinpath(f"{system}.json").read_text(encoding="utf-8"))
        highest = loaded["maxVerses"]
        dropped = {
            key for entry in corrections["drop_mapped"].get(system, []) for key in entry["keys"]
        }
        for key in set(loaded["mappedVerses"]) - dropped:
            match = pattern.match(key.strip())
            if not match:
                continue
            book, chapter, _, last = match.groups()
            rows = highest.get(book)
            if not rows or int(chapter) > len(rows):
                continue
            top = int(rows[int(chapter) - 1])
            if int(last or match.group(3)) > top:
                ghosts.append(f"{system}: {key} but {book} {chapter} has {top} verses")

    assert ghosts == []


# --------------------------------------------------------------------------------------
# Found by deriving the mapping from the text rather than checking the one on file
# --------------------------------------------------------------------------------------


def test_english_greek_daniel_reaches_the_pivot_at_all(vrs: Versification) -> None:
    """org has no DAG book: Greek Daniel lives there as DAN plus S3Y, SUS and BEL. lxx.json
    spells the correspondence out and eng.json recorded only Susanna and Bel, so every
    English citation of Greek Daniel 1-12 fell through to 'org DAG x:y' -- a book the pivot
    does not have.

    It was silent because the ghost-reference guard skips books the target lacks rather than
    refusing them, so nothing anywhere in the project could see it.
    """
    assert convert(vrs, "DAG 1:1", "eng", "org") == "DAN 1:1"
    assert convert(vrs, "DAG 12:13", "eng", "org") == "DAN 12:13"


def test_english_greek_daniel_keeps_the_aramaic_chapter_break(vrs: Versification) -> None:
    """The English tradition prints 'Darius the Mede received the kingdom' as 5:31 and the
    Greek opens chapter 6 with it, so English Greek Daniel 5 has 31 verses to the Greek's 30
    and the whole of chapter 6 runs one behind.

    Measured on web against brenton: chapters 1-4 and 7-12 align at offset 0, and all 28
    verses of chapter 6 sit at +1.
    """
    assert convert(vrs, "DAG 5:30", "eng", "org") == "DAN 5:30"
    assert convert(vrs, "DAG 5:31", "eng", "org") == "DAN 6:1"
    assert convert(vrs, "DAG 6:1", "eng", "org") == "DAN 6:2"
    # 'My God has sent his angel and shut the lions' mouths' -- not an obscure verse to lose.
    assert convert(vrs, "DAG 6:22", "eng", "org") == "DAN 6:23"
    assert convert(vrs, "DAG 6:28", "eng", "org") == "DAN 6:29"


def test_ordinary_daniel_is_not_dragged_into_greek_daniels_numbering(
    vrs: Versification,
) -> None:
    """The other half of that fix. Mapping DAG onto org's DAN gives the reverse lookup two
    answers for the whole book, and DAG sorts first -- so an ordinary citation of Daniel came
    back in Greek Daniel's numbering, which no English protocanon corpus can render."""
    assert convert(vrs, "DAN 4:1", "org", "eng") == "DAN 4:4"
    assert convert(vrs, "DAN 6:23", "org", "eng") == "DAN 6:22"


def test_the_vulgate_splits_a_verse_in_sirach_6(vrs: Versification) -> None:
    """latvuc 6:19 'Quasi is qui arat et seminat accede ad eam' and 6:20 'In opere enim
    ipsius exiguum laborabis' are together org's single 6:19. Fifteen verses ran one late
    behind the split, and the chapter passed every count-based check because the Vulgate
    also lacks org 6:35 -- 37 verses either side, divided differently.

    Which side was wrong was settled by triangulation: eng and lxx agree with org verse for
    verse across the whole chapter.
    """
    assert convert(vrs, "SIR 6:19", "vul", "org") == "SIR 6:19"
    assert convert(vrs, "SIR 6:20", "vul", "org") == "SIR 6:19"
    assert convert(vrs, "SIR 6:24", "vul", "org") == "SIR 6:23"
    assert convert(vrs, "SIR 6:36", "vul", "org") == "SIR 6:36"


def test_the_clementine_splits_the_levites_in_nehemiah_7(vrs: Versification) -> None:
    """latvuc 7:43 'filii Josue et Cedmihel filiorum' and 7:44 'Oduiae, septuaginta quatuor'
    are the Nova Vulgata's single 7:43."""
    assert convert(vrs, "NEH 7:44", "vul", "org") == "NEH 7:43"
    assert convert(vrs, "NEH 7:45", "vul", "org") == "NEH 7:44"
    assert convert(vrs, "NEH 7:47", "vul", "org") == "NEH 7:46"


def test_one_corrected_chapter_does_not_vouch_for_a_whole_book() -> None:
    """The guard is per chapter, and it has to be.

    It used to be per book: any mapping anywhere vouched for all of it. Adding the verified
    Sirach 6 mapping above therefore switched the refusal off for all fifty-one chapters,
    and Sirach 24 -- which Jerome translated from a different text and which nothing maps --
    began converting by identity into a chapter containing different words.
    """
    from biblereference.refs import parse_reference

    vrs = Versification.load()
    with pytest.raises(VersificationError):
        vrs.convert_range(parse_reference("Sir 24:1"), "vul")
    assert vrs.convert_range(parse_reference("Sir 6:23"), "vul")[0].start.verse == 24


def test_baruch_1_converts_despite_a_wrong_upstream_verse_count(vrs: Versification) -> None:
    """eng.json gives Baruch 1 twenty-one verses where org gives twenty-two, so the
    per-chapter guard read it as a real division difference and refused. It is not: the
    World English Bible, Douay-Rheims, Vulgata Clementina and Nova Vulgata all print
    twenty-two and align verse for verse. The count is simply wrong upstream."""
    assert convert(vrs, "BAR 1:1", "eng", "org") == "BAR 1:1"
    assert convert(vrs, "BAR 1:21", "eng", "org") == "BAR 1:21"


def test_the_septuagint_omits_a_verse_in_leviticus_8(vrs: Versification) -> None:
    """org 8:19 is 'He killed it; and Moses sprinkled the blood around on the altar', and
    the Greek has no counterpart -- so eleven verses of the consecration run one behind.

    Both number the chapter at 36 regardless, because the Greek splits org's 8:30 in two,
    which is why no count-based check could ever have seen this. Three independent pairs
    flagged it and eng agrees with org verse for verse throughout the chapter.
    """
    assert convert(vrs, "LEV 8:18", "lxx", "org") == "LEV 8:18"
    assert convert(vrs, "LEV 8:19", "lxx", "org") == "LEV 8:20"
    assert convert(vrs, "LEV 8:28", "lxx", "org") == "LEV 8:29"
    assert convert(vrs, "LEV 8:31", "lxx", "org") == "LEV 8:31"


def test_greek_ezekiel_7_transposes_two_blocks(vrs: Versification) -> None:
    """The Greek runs the Hebrew's 6,7,8,9 first and then its 3,4,5, and nothing recorded
    it, so seven verses resolved into the wrong half of the chapter.

    The alignment that found this could not describe it -- monotonic alignment cannot
    express a swap, so it reported a plain one-verse shift over part of the block. The
    correspondence was established by reading the texts: 'The end is come' is Brenton's 7:3
    and org's 7:6; 'Now the end is come to thee, and I will send judgment upon thee' is his
    7:7 and org's 7:3.
    """
    assert convert(vrs, "EZK 7:3", "lxx", "org") == "EZK 7:6"
    assert convert(vrs, "EZK 7:6", "lxx", "org") == "EZK 7:9"
    assert convert(vrs, "EZK 7:7", "lxx", "org") == "EZK 7:3"
    assert convert(vrs, "EZK 7:9", "lxx", "org") == "EZK 7:5"
    assert convert(vrs, "EZK 7:10", "lxx", "org") == "EZK 7:10"


def test_the_septuagint_omits_the_daughters_plea_in_numbers_27(vrs: Versification) -> None:
    """org 27:4 is 'Why should the name of our father be withdrawn from among his family,
    because he has no son?' and the Greek has no counterpart, so four verses run behind."""
    assert convert(vrs, "NUM 27:4", "lxx", "org") == "NUM 27:5"
    assert convert(vrs, "NUM 27:6", "lxx", "org") == "NUM 27:7"
    assert convert(vrs, "NUM 27:9", "lxx", "org") == "NUM 27:9"
