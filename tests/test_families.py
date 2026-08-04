"""What the derived families are, and what the derivation is allowed to claim.

The point of :mod:`biblereference.families` is to stop *assuming* which numbering a corpus
follows, so these tests are mostly about the honesty of the answer rather than its content:
that a corpus too small to place is not placed, that a corpus exact to two families is
reported as exact to two families, and that the one ordering rule the algorithm depends on
is stated and stable.

The corpus-backed tests skip without a built store, because a missing corpus is not a
broken derivation.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from biblereference.families import (
    MIN_OVERLAP,
    Derivation,
    Signature,
    derive,
    disagreements,
    read_signatures,
)
from biblereference.store import DataHome

# --------------------------------------------------------------------------------------
# The algorithm, on signatures built by hand
# --------------------------------------------------------------------------------------


def spread(count: int, verses: int = 20, book: str = "GEN") -> Signature:
    """A signature over `count` chapters, every one `verses` long."""
    return {(book, n): verses for n in range(1, count + 1)}


def test_a_corpus_that_disagrees_anywhere_founds_its_own_family() -> None:
    """One chapter of disagreement settles it. Two editions that number a chapter
    differently are not one numbering, however much else they share."""
    big = spread(400)
    odd = spread(400) | {("GEN", 7): 19}

    result = derive({"big": big, "odd": odd})

    assert len(result.families) == 2
    assert result.family_of("big") != result.family_of("odd")


def test_a_corpus_too_small_to_judge_is_not_placed() -> None:
    """A four-chapter edition agreeing with a family on all four chapters is not evidence
    of anything. Before this was gated on overlap, `glw`, `e2t` and `swete-daniel` each came
    out of the derivation as a *family*, every one of them zero chapters distant from a
    dozen others."""
    result = derive({"whole": spread(400), "tiny": spread(4)})

    assert [f.name for f in result.families] == ["whole"]
    assert result.family_of("tiny") is None
    assert [p.corpus for p in result.unplaceable] == ["tiny"]


def test_a_corpus_exact_to_two_families_is_reported_not_assigned() -> None:
    """The heart of it. Two families differing only where a third corpus has no text: the
    third is exact to both, and choosing one would manufacture a fact.

    This is the real King James against Revised Version case -- they differ on 2 Esdras 7
    and Sirach 23, so every Protestant-canon Bible agrees with both.
    """
    left = spread(200) | spread(60, book="TOB")
    right = spread(200) | spread(60, verses=21, book="TOB")
    middle = spread(200)

    result = derive({"left": left, "right": right, "middle": middle})

    assert len(result.families) == 2
    assert result.family_of("middle") is None
    assert [p.corpus for p in result.ambiguous] == ["middle"]
    assert set(result.ambiguous[0].candidates) == {"left", "right"}


def test_compatibility_is_measured_against_the_finished_partition() -> None:
    """During growth a corpus joins when exactly one family fits *at that moment*, so a
    family founded later can fit it too. The canonical answer has to be recomputed at the
    end, and it is that answer -- not the assignment -- which says whether a corpus is
    really determined."""
    signatures = {
        "left": spread(200) | {("TOB", n): 20 for n in range(1, 61)},
        "right": spread(200) | {("TOB", n): 21 for n in range(1, 61)},
        "middle": spread(200),
    }
    result = derive(signatures)

    assert result.compatibility(signatures)["middle"] == ["left", "right"]
    assert result.compatibility(signatures)["left"] == ["left"]


def test_disagreements_only_counts_chapters_both_sides_hold() -> None:
    assert disagreements(spread(10), spread(5)) == []
    assert disagreements(spread(10), spread(10) | {("GEN", 3): 19}) == [("GEN", 3)]


# --------------------------------------------------------------------------------------
# The derivation over the built corpus
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def signatures() -> dict[str, Signature]:
    # The real store, not the isolated one `conftest` installs: these tests are about what
    # the built corpus says, and an empty data home would silently skip them all.
    home = DataHome(Path.home() / ".local/share/biblereference")
    if not Path(home.database).exists():
        pytest.skip("corpus not built; run `biblereference fetch`")
    found = read_signatures(home)
    if len(found) < 20:
        pytest.skip("corpus too small to derive families from")
    return found


@pytest.fixture(scope="module")
def derivation(signatures: dict[str, Signature]) -> Derivation:
    return derive(signatures)


def test_the_partition_does_not_depend_on_how_ties_are_broken(
    signatures: dict[str, Signature],
) -> None:
    """The one ordering rule the algorithm rests on is 'largest coverage first'. It is a
    stated rule rather than a discovered fact -- compatibility is not transitive, so no
    canonical partition exists, and growing the families in a *random* order reproduces this
    answer roughly once in two hundred tries.

    What has to hold is that the rule determines the answer by itself: corpora of equal
    coverage may be visited in any order without changing the partition.
    """
    canonical = frozenset(frozenset(f.members) for f in derive(signatures).families)

    for seed in range(25):
        shuffled = dict(
            sorted(
                signatures.items(),
                key=lambda kv: (-len(kv[1]), random.Random(seed).random()),
            )
        )
        assert frozenset(frozenset(f.members) for f in derive(shuffled).families) == canonical


def test_no_corpus_is_assigned_to_a_family_it_is_not_compatible_with(
    derivation: Derivation, signatures: dict[str, Signature]
) -> None:
    """The assignment must never contradict the canonical answer. Where a corpus is
    determined, the partition has to agree with what determined it."""
    compatible = derivation.compatibility(signatures)
    for corpus, families in compatible.items():
        assigned = derivation.family_of(corpus)
        if assigned is not None:
            assert assigned in families, (
                f"{corpus} assigned to {assigned}, compatible with {families}"
            )


def test_families_are_far_apart_and_members_are_identical(derivation: Derivation) -> None:
    """Within a family the distance is zero by construction, so the number that carries the
    evidence is how far apart the families are. If neighbouring families differed by one
    chapter and distant ones by two, the partition would be measuring noise."""
    distances = derivation.distances()
    assert distances, "no family pairs to compare"
    assert max(distances.values()) > 100, "no family is far from any other -- suspect"


def test_the_septuagint_editions_do_not_share_a_family(derivation: Derivation) -> None:
    """Swete and Brenton are both filed under `lxx` upstream and are not one numbering:
    they disagree on 83 chapters. Brenton sits with the Updated Brenton, which is the
    edition derived from it."""
    if derivation.family_of("swete") is None or derivation.family_of("brenton") is None:
        pytest.skip("septuagint corpora not present")
    assert derivation.family_of("swete") != derivation.family_of("brenton")


def test_the_hebrew_and_the_orthodox_jewish_bible_do_not_share_a_family(
    derivation: Derivation,
) -> None:
    """Both are filed under `org`. The Leningrad Codex is exact to it on all 929 chapters
    and the OJB is off on ten, so they cannot be one numbering -- which is what made the
    OJB a bad witness and killed thirteen findings of an earlier sweep."""
    if derivation.family_of("wlc") is None or derivation.family_of("ojb") is None:
        pytest.skip("hebrew corpora not present")
    assert derivation.family_of("wlc") != derivation.family_of("ojb")


def test_the_two_vulgate_editions_do_not_share_a_family(derivation: Derivation) -> None:
    """Douay-Rheims against Vulgata Clementina: both filed `vul`, differing on 14 chapters."""
    if derivation.family_of("dra") is None or derivation.family_of("latvuc") is None:
        pytest.skip("vulgate corpora not present")
    assert derivation.family_of("dra") != derivation.family_of("latvuc")


def test_editions_of_one_translation_do_share_a_family(derivation: Derivation) -> None:
    """The counterweight. If the rule split everything it would be worthless -- the eight
    World English Bible editions are one numbering and must come out as one family."""
    web = {"web", "webbe", "webu", "webc", "webp", "webpb", "wmb", "wmbb"}
    present = {c for c in web if derivation.family_of(c) is not None}
    if len(present) < 4:
        pytest.skip("world english bible editions not present")
    assert len({derivation.family_of(c) for c in present}) == 1


def test_min_overlap_is_below_the_new_testament(signatures: dict[str, Signature]) -> None:
    """A New Testament is 260 chapters and every family here numbers it alike, so a
    threshold above it would let a Greek New Testament be *placed* rather than reported as
    fitting everything. The threshold guards the opposite mistake, and must stay under it.
    """
    assert MIN_OVERLAP < 260
