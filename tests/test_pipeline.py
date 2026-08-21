"""The rebuild pipeline: what it refuses to do is the point of it."""

from __future__ import annotations

from pathlib import Path

from biblereference.pipeline import STEPS, PipelineResult, Step, StepResult, rebuild
from biblereference.store import DataHome


def test_the_dependency_order_puts_profiles_after_parallel_families() -> None:
    """The edge a hand-written setup guide got wrong.

    `build_profiles` reads `parallel_family` for its anchors, so a guide that ran the
    lemma steps and then profiles -- without `parallels` in between -- built the profiles
    against an empty families table. No error, no warning, a profile set that looks built.
    That is why the order lives in code and not in a document.
    """
    order = [step.name for step in STEPS]
    assert order.index("parallel families") < order.index("verse profiles")
    assert order.index("lemma index") < order.index("parallel families")
    assert order.index("lemma lexicon") < order.index("lemma index")
    assert order.index("verses") < order.index("search index")

    needs = {step.name: step.needs for step in STEPS}
    assert needs["verse profiles"] == ("parallel families",)
    # The lemma *index*, not merely the lexicon: `build_parallels` scores every pair off
    # `lemma_df`/`lemma_total`, and an unbuilt index reads as zero bits rather than absent,
    # so every pair fails the floor and the table is created empty.
    assert needs["parallel families"] == ("lemma index",)


def test_every_step_can_be_named_and_none_needs_a_step_that_follows_it() -> None:
    names = [step.name for step in STEPS]
    assert len(names) == len(set(names))
    for position, step in enumerate(STEPS):
        for need in step.needs:
            assert need in names, f"{step.name} needs unknown step {need!r}"
            assert names.index(need) < position, f"{step.name} needs a later step {need!r}"


def test_an_empty_home_fails_loudly_rather_than_building_empty_layers(
    tmp_path: Path,
) -> None:
    """Nothing to build from, so nothing builds -- and the run says so.

    The failure being tested is the opposite one: builders that return happily on zero.
    `build_parallels` drops the table, creates it, inserts nothing and reports success;
    `build_profiles` reads that and writes an empty profile set, equally cheerfully. Both
    then look present to `doctor` for ever.
    """
    home = DataHome(tmp_path)
    outcome = rebuild(home)

    assert outcome.failed, "an empty home must not report success"
    assert not outcome.worked

    first = outcome.steps[0]
    assert first.name == "verses"
    assert first.state == "failed"
    assert "empty layer" in first.detail

    # Everything downstream is skipped rather than run against nothing.
    downstream = {s.name: s for s in outcome.steps[1:]}
    assert all(s.state == "skipped" for s in downstream.values())
    assert "did not build" in downstream["search index"].detail
    assert downstream["verse profiles"].detail.startswith("needs parallel families")


def test_asking_for_one_late_step_refuses_when_its_needs_are_unbuilt(
    tmp_path: Path,
) -> None:
    """`--step` must not become a way around the ordering."""
    home = DataHome(tmp_path)
    outcome = rebuild(home, only=["verse profiles"])

    assert len(outcome.steps) == 1
    assert outcome.steps[0].state == "skipped"
    assert "parallel families" in outcome.steps[0].detail
    assert not outcome.worked, "a run that built nothing must not exit zero"


def test_a_run_that_builds_nothing_is_not_a_run_that_worked() -> None:
    """Skipped is not failed, but neither is it success.

    Asking for a layer, receiving nothing, and being told everything is fine is the exact
    shape this module exists to refuse. It must not come back through the exit code.
    """
    only_skipped = PipelineResult(
        steps=[StepResult("verse profiles", "skipped", detail="needs parallel families")]
    )
    assert not only_skipped.failed
    assert not only_skipped.worked

    built = PipelineResult(steps=[StepResult("verses", "built", 10, "verses")])
    assert built.worked

    mixed = PipelineResult(
        steps=[
            StepResult("verses", "built", 10, "verses"),
            StepResult("search index", "failed", detail="built 0 verses"),
        ]
    )
    assert not mixed.worked


def test_a_step_producing_zero_is_reported_failed_not_built(tmp_path: Path) -> None:
    """An empty table is not a built table, whoever wrote it."""
    from biblereference import pipeline

    empty = Step("verses", "verses", lambda home, report: 0)
    original = pipeline.STEPS
    try:
        pipeline.STEPS = (empty,)
        outcome = rebuild(DataHome(tmp_path))
    finally:
        pipeline.STEPS = original

    assert outcome.steps[0].state == "failed"
    assert "not a built one" in outcome.steps[0].detail


def test_a_step_that_raises_is_reported_and_does_not_stop_the_others(
    tmp_path: Path,
) -> None:
    """One broken layer must not hide the state of the rest."""
    from biblereference import pipeline

    def _boom(home: DataHome, report: object) -> int:
        raise RuntimeError("the archive is a banana")

    original = pipeline.STEPS
    try:
        pipeline.STEPS = (
            Step("verses", "verses", _boom),
            Step("entity index", "references", lambda home, report: 7),
        )
        outcome = rebuild(DataHome(tmp_path))
    finally:
        pipeline.STEPS = original

    assert outcome.steps[0].state == "failed"
    assert "banana" in outcome.steps[0].detail
    assert outcome.steps[1].state == "built"
    assert not outcome.worked, "a failure anywhere means the run did not work"


def test_the_description_names_what_did_not_happen(tmp_path: Path) -> None:
    outcome = rebuild(DataHome(tmp_path))
    described = outcome.describe()
    assert "FAILED" in described
    assert "SKIPPED" in described
    for step in STEPS:
        assert step.name in described, f"{step.name} missing from the report"
