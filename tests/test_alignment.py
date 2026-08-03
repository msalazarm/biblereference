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

from biblereference.refs import VerseRef
from biblereference.versification import Versification


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
