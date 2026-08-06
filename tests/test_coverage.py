"""Every conversion, walked rather than sampled.

The claim these tests defend is the strong one: not "the mappings look right where we
checked" but "every verse of every system converts to a verse that exists, and where any
corpus can check the result, it agrees". A sample cannot support that, so nothing here
samples.

Two tests, and they are deliberately different in kind:

* the structural one needs no corpus at all and admits no excuses -- a conversion that
  returns a verse the pivot does not have is a fault whatever the text says;
* the textual one needs the built corpus and is honest about its own reach, because half of
  the conversions have no faithful witness on both sides in one language and *saying so* is
  worth more than quietly counting them as fine.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from biblereference.audit import Coverage, runs_of, verify_every_verse
from biblereference.cli import COVERAGE_WITNESSES
from biblereference.store import DataHome
from biblereference.versification import PIVOT, Versification


@pytest.fixture(scope="module")
def vrs() -> Versification:
    return Versification.load()


@pytest.fixture(scope="module")
def home() -> DataHome:
    # The real store, not the isolated one `conftest` installs: these tests are about what
    # the built corpus says, and an empty data home would silently pass them all.
    data = DataHome(Path.home() / ".local/share/biblereference")
    if not Path(data.database).exists():
        pytest.skip("corpus not built; run `biblereference sync`")
    return data


# --------------------------------------------------------------------------------------
# Structural: no text needed, and no excuses available
# --------------------------------------------------------------------------------------


def test_no_conversion_invents_a_verse(home: DataHome, vrs: Versification) -> None:
    """Every verse of every system converts into a verse the pivot actually has.

    With no witnesses supplied this does the structural half alone, which is the half that
    cannot be argued with: if `vul 3:20` maps to a book `org` does not carry, or past the
    end of the chapter it does carry, that is wrong however the words read.

    It was not always zero. Daniel was the worst of it -- the Greek additions are a separate
    `DAG` in `org` and folded into `DAN` elsewhere, and the mappings pointed at 70 verses
    that did not exist. `MAX(verse)` over the corpus hid it, because the corpora carry those
    verses even where the versification does not declare them.
    """
    coverage, ghosts, _ = verify_every_verse(home, vrs, {})
    assert ghosts == []
    assert {row.system for row in coverage} == set(vrs.system_names) - {PIVOT}
    assert all(row.ghost == 0 for row in coverage)
    assert sum(row.total for row in coverage) > 150_000, "the walk stopped early"


def test_every_verse_lands_in_exactly_one_bucket(home: DataHome, vrs: Versification) -> None:
    """The accounting has to be exhaustive or the percentages mean nothing.

    A bucket that does not add up is how "99% confirmed" comes to be reported over a tenth
    of the corpus.
    """
    coverage, _, _ = verify_every_verse(home, vrs, {})
    for row in coverage:
        counted = (
            row.refused + row.ghost + row.confirmed + row.contradicted + row.weak + row.unwitnessed
        )
        assert counted == row.total, f"{row.system} loses {row.total - counted} verses"


def test_a_refusal_is_reported_as_a_refusal(home: DataHome, vrs: Versification) -> None:
    """Refusals must be counted, not confused with agreement.

    `vul` refuses most: Judith and Tobit are marked unreliable there because Jerome
    translated them from an Aramaic recension that differs by whole clauses, and the library
    says so rather than guessing. That number moving is a signal either way -- if it drops,
    something started guessing; if it climbs, something stopped mapping.
    """
    coverage, _, _ = verify_every_verse(home, vrs, {})
    refusals = {row.system: row.refused for row in coverage}
    assert refusals["vul"] > refusals["eng"], "the Vulgate declines the most, by a lot"
    assert all(
        count < total * 0.1 for count, total in ((refusals[r.system], r.total) for r in coverage)
    ), "a system refusing a tenth of itself is not a mapping"


# --------------------------------------------------------------------------------------
# Textual: the built corpus, and what it can and cannot reach
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def walked(
    home: DataHome, vrs: Versification
) -> tuple[list[Coverage], list[str], list[tuple[str, object, object]]]:
    # ~70 seconds over the whole corpus. Module-scoped so it is paid once.
    return verify_every_verse(home, vrs, COVERAGE_WITNESSES)  # type: ignore[return-value]


def test_the_text_confirms_the_mappings_wherever_it_can_reach_them(walked) -> None:  # type: ignore[no-untyped-def]
    """Where a faithful witness exists on both sides in one language, it agrees.

    Differential, never absolute: the question asked of each verse is not "do these two
    look alike" but "does the mapped position explain this text better than its neighbours
    do". An absolute threshold would fail every verse of the Vulgate's Sirach, which is
    translated from a different source text and *should* score badly while being right.
    """
    coverage, _, _ = walked
    checked = {row.system: row for row in coverage if row.checked}
    assert set(checked) >= {"eng", "lxx", "vul"}
    for system, row in checked.items():
        assert row.confirmed / row.checked > 0.97, f"{system}: {row.describe()}"


def test_the_unreachable_half_is_reported_rather_than_assumed(walked) -> None:  # type: ignore[no-untyped-def]
    """Half of the conversions cannot be checked against any text, and the number says so.

    `nvl` is the extreme case at 0%: its only witness is the Nova Vulgata itself, in Latin,
    and `org` has no Latin witness -- so there is no same-language pivot partner and not one
    of its 35,641 verses can be textually checked. It is verified against `vul` by the pair
    derivation instead, which is a weaker claim, and this test exists so that weaker claim
    is never mistaken for the stronger one.
    """
    coverage, _, _ = walked
    by_system = {row.system: row for row in coverage}
    assert by_system["nvl"].checked == 0
    assert by_system["nvl"].unwitnessed > 30_000
    total = sum(row.total for row in coverage)
    assert sum(row.checked for row in coverage) < total, "nothing checks everything"


def test_the_contradictions_that_remain_are_the_ones_we_can_name(walked) -> None:  # type: ignore[no-untyped-def]
    """Isolated flags are noise; runs are faults. Only runs are evidence.

    The runs left are each a known textual fact rather than a mapping error, and they are
    pinned here by name so a new one appearing is a test failure:

    * `EXO 39` -- the Douay condenses the tabernacle account rather than displacing it, so
      the correspondence is many-to-fewer and no offset is right.
    * `NUM 1` / `NUM 26` -- the censuses and the tribal lists, where every verse has the
      identical shape and a neighbour outscores the true match by accident. `NUM 1:6` is
      "Of Symeon, Salamiel the son of Surisadai" in Brenton and "Of Shim'on, Shelumiel ben
      Tzurishaddai" in the Orthodox Jewish Bible: the same verse, mapped by identity,
      correctly.

    Two entries used to be here and are the reason this test is worth having. `vul LEV 15`
    was not repetition -- the Douay splits org 15:19 in two and nothing recorded it, so
    three verses of the purity law resolved one early. `lxx EXO 36:28-38` was the longest
    run of all and was not reordering -- upstream had left one verse of the Greek vestment
    account unmapped and written the fifteen after it one low. Both runs went away when the
    reading was written down, which is what a real fault looks like when it is fixed.
    """
    _, _, contradicted = walked
    runs = {(system, book, chapter) for system, book, chapter, _, _ in runs_of(contradicted, 4)}
    assert runs == {
        ("lxx", "NUM", 26),
        ("lxx", "NUM", 1),
        ("vul", "EXO", 39),
        ("vul", "NUM", 1),
    }


def test_a_run_is_only_reported_when_it_is_consecutive() -> None:
    """The grouping itself, on data small enough to read.

    Scattered flags in one chapter are not a run however many there are -- that is the whole
    point of the measure, and getting it wrong turns a genealogy into a false fault report.
    """
    from biblereference.refs import VerseRef

    def flag(book: str, chapter: int, verse: int) -> tuple[str, VerseRef, VerseRef]:
        ref = VerseRef(book, chapter, verse, vrs="eng")
        return ("eng", ref, ref)

    scattered = [flag("GEN", 1, v) for v in (20, 22, 24, 26, 28)]
    assert runs_of(scattered, 4) == []

    run = [flag("GEN", 1, v) for v in (7, 4, 6, 5, 7)]
    assert runs_of(run, 4) == [("eng", "GEN", 1, 4, 7)]
    assert runs_of(run, 5) == []

    # Out of order, interleaved with noise, and with 5 and 7 appearing twice -- none of
    # which is a gap, and none of which may break the run.
    assert runs_of(scattered + run, 4) == [("eng", "GEN", 1, 4, 7)]


# --------------------------------------------------------------------------------------
# Covering conversion, over every conversion there is
# --------------------------------------------------------------------------------------


def _every_verse(vrs: Versification, system: str):  # type: ignore[no-untyped-def]
    from biblereference.canon import CANONICAL_ORDER
    from biblereference.refs import VerseRef
    from biblereference.versification import VersificationError

    for book in CANONICAL_ORDER:
        if not vrs.has_book(system, book):
            continue
        for chapter in range(1, vrs.chapter_count(system, book) + 1):
            try:
                low = vrs.first_verse(system, book, chapter)
                high = vrs.max_verse(system, book, chapter)
            except VersificationError:
                continue
            for verse in range(max(low, 0), high + 1):
                yield VerseRef(book, chapter, verse, vrs=system)


def test_covering_never_costs_you_an_answer(vrs: Versification) -> None:
    """The contract, over all 798,132 conversions between all twenty ordered system pairs.

    Covering is a looser question than the exact map answers, so it must never come back
    with *less*. Two ways it could, and neither is allowed:

    * it drops a verse the exact map named. Permitted in exactly one circumstance -- where
      the exact answer was the identity fall-through and the data itself contradicts it,
      because a verse that maps elsewhere cannot also be standing in for this one. The
      Douay's Exodus 40:14 is "Moses did all that the Lord commanded", not the bringing of
      Aaron's sons, and covering replacing that is a correction rather than a loss.
    * it refuses where the exact map answered. Never permitted: a guarantee that costs you
      answers is not worth having.
    """
    from biblereference.versification import DEFAULT_SYSTEMS, VersificationError

    def convert(ref, target, covering):  # type: ignore[no-untyped-def]
        try:
            return {
                (r.book, int(r.chapter), r.verse, r.subverse)
                for r in vrs.convert_all(ref, target, covering=covering)
            }
        except VersificationError:
            return None

    losses: list[tuple[str, str, str, object]] = []
    refusals = 0
    grew = 0
    for source, target in itertools.permutations(DEFAULT_SYSTEMS, 2):
        contradicted = vrs._system(target).to_org
        for ref in _every_verse(vrs, source):
            exact = convert(ref, target, False)
            if exact is None:
                continue
            covering = convert(ref, target, True)
            if covering is None:
                refusals += 1
                continue
            grew += covering > exact
            losses.extend(
                (source, target, str(ref), dropped)
                for dropped in exact - covering
                if contradicted.get(dropped, dropped) == dropped
            )

    assert losses == []
    assert refusals == 0
    assert grew > 0, "no conversion differs, so nothing here is being tested"


def test_the_round_trip_holds_where_a_cover_is_recorded(vrs: Versification) -> None:
    """Convert a verse into another system and back, and you must land on the text you
    started from. Measured through the pivot rather than by coordinates, because a book
    with two names is not a lost verse: English Greek Daniel 1:1 comes home as Daniel 1:1,
    which is the same words under the name English Bibles print.

    This does not pass everywhere and is not asserted to. 2,848 verses still fail it, and
    they are the honest work queue for this data -- Greek 2 Esdras and Esther, which are
    differently built books rather than differently numbered ones; the psalm
    superscriptions; and the Greek reorderings of Exodus and Jeremiah. What is asserted is
    that covering is *better* than the exact map here and that the recorded covers hold.
    """
    from biblereference.refs import VerseRef
    from biblereference.versification import DEFAULT_SYSTEMS, PIVOT, VersificationError

    def to_pivot(ref, covering):  # type: ignore[no-untyped-def]
        if ref.vrs == PIVOT:
            return {(ref.book, int(ref.chapter), ref.verse, ref.subverse)}
        try:
            return {
                (r.book, int(r.chapter), r.verse, r.subverse)
                for r in vrs.convert_all(ref, PIVOT, covering=covering)
            }
        except VersificationError:
            return None

    failures = {False: 0, True: 0}
    for source, target in itertools.permutations(DEFAULT_SYSTEMS, 2):
        for ref in _every_verse(vrs, source):
            for covering in (False, True):
                start = to_pivot(ref, covering)
                try:
                    out = vrs.convert_all(ref, target, covering=covering)
                except VersificationError:
                    continue
                if start is None:
                    continue
                home: set[tuple[str, int, int, str]] = set()
                for landed in out:
                    back = to_pivot(landed, covering)
                    if back:
                        home |= back
                failures[covering] += not start <= home

    assert failures[True] < failures[False], "covering must improve the round trip"
    assert failures[True] < 3000, f"round-trip failures climbed to {failures[True]}"

    # And the recorded covers themselves hold, which is the part that is claimed.
    for ref, target in (
        (VerseRef("LJE", 1, 43, vrs="org"), "eng"),
        (VerseRef("1MA", 1, 49, vrs="org"), "vul"),
        (VerseRef("MAT", 17, 14, vrs="vul"), "org"),
        (VerseRef("BAR", 6, 43, vrs="eng"), "vul"),
    ):
        landed = vrs.convert_all(ref, target, covering=True)
        home = {c for r in landed for c in (to_pivot(r, True) or set())}
        assert to_pivot(ref, True) <= home, (ref, target, landed)
