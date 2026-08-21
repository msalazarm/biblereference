"""The whole derived library, in order, from an archive that is already here.

`mirror` used to copy `sources/`, run `build` and `index`, and stop — leaving the lemma
lexicon, the lemma index, the parallel families, the entity index and the profiles absent.
That was a documented decision ("the database is derived, and rebuilding it locally is both
faster than transferring 600 MB and a stronger check") and it was right about the corpus. It
was never right about the rest, and the gap was silent in the worst way: `scan --inflected`
returns *nothing* against a library with no lemma index, with no error, because
:class:`~biblereference.search.LemmaWeights` reads an empty table as zero bits rather than as
a missing one.

Everything here builds from bytes the archive already holds. The CLTK lexicon zips, TIPNR,
the four Theographic files and the OpenBible cross-reference zip all carry manifest lines, so
after a mirror they are on disk and `fetch_source` no-ops — these steps need no network at
all. Nobody was running them.

**Two rules, and both are the point of the module.**

*A step whose needs did not succeed does not run.* Not "does not run if the table is
missing" — did not *succeed*. `build_parallels` gates every pair on a surprisal floor read
off `lemma_df`/`lemma_total`; with an empty lemma index every pair scores zero bits, so it
drops the table, creates it, inserts nothing and returns a cheerful result. `build_profiles`
then reads that empty table and writes an empty profile set, equally cheerfully. Two layers
of nothing, exit code 0, and a `doctor` that reports both as present.

*A step that produces none of its unit has failed.* An empty table is not a built table. This
is the same rule, enforced at the other end, because the first rule only helps when the
dependency is one this module knows about.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .store import DataHome

Reporter = Callable[[str], None]


def _silent(line: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class StepResult:
    """What one step did, and — where it did nothing — why."""

    name: str
    state: str
    """``built`` | ``skipped`` | ``failed``."""
    count: int = 0
    unit: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "built"


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    unit: str
    run: Callable[[DataHome, Reporter], int]
    needs: tuple[str, ...] = ()
    optional: bool = False
    """A step whose absence degrades the library rather than breaking it. Its failure is
    reported and does not stop the run, but it still blocks anything that needs it."""


def _build_verses(home: DataHome, report: Reporter) -> int:
    from .fetch import build_source, iter_sources

    total = 0
    for source in iter_sources(None):
        try:
            total += build_source(source, home, report=report).verses
        except FileNotFoundError as exc:
            report(f"  skipped: {exc}")
    return total


def _build_search(home: DataHome, report: Reporter) -> int:
    from .search import build_index

    return build_index(home, report=_silent).verses


def _build_lexicon(home: DataHome, report: Reporter) -> int:
    from .lemmata import LEXICONS, LexiconUnavailable, build_lexicon

    total = 0
    for language in sorted(LEXICONS):
        try:
            total += build_lexicon(home, language, report=report)
        except LexiconUnavailable as exc:
            report(f"  {language}: {exc}")
    return total


def _build_lemma_index(home: DataHome, report: Reporter) -> int:
    from .search import build_lemma_index

    return build_lemma_index(home, report=_silent).verses


def _build_parallels(home: DataHome, report: Reporter) -> int:
    from .parallels import build_parallels

    return build_parallels(home, report=report).verified


def _build_entities(home: DataHome, report: Reporter) -> int:
    from .entities import build_entities

    return build_entities(home, report=report).references


def _build_profiles(home: DataHome, report: Reporter) -> int:
    from .profiles import build_profiles

    return build_profiles(home, report=report).anchors


#: In dependency order. `needs` names steps that must have *succeeded*, not merely run.
STEPS: Final[tuple[Step, ...]] = (
    Step("verses", "verses", _build_verses),
    Step("search index", "verses", _build_search, needs=("verses",)),
    Step("lemma lexicon", "readings", _build_lexicon, needs=("verses",)),
    # The lemma index is what `scan --inflected` reads. Without it that command returns
    # nothing at all and says nothing about why, which is the failure this module exists for.
    Step("lemma index", "verses", _build_lemma_index, needs=("lemma lexicon",)),
    # Needs the lemma *index*, not just the lexicon: it scores every pair against
    # `lemma_df`/`lemma_total`, and an unbuilt index reads as zero bits rather than as absent.
    Step("parallel families", "pairs", _build_parallels, needs=("lemma index",)),
    Step("entity index", "references", _build_entities, needs=("verses",), optional=True),
    Step("verse profiles", "anchors", _build_profiles, needs=("parallel families",)),
)


@dataclass
class PipelineResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def failed(self) -> list[StepResult]:
        return [s for s in self.steps if s.state == "failed"]

    @property
    def skipped(self) -> list[StepResult]:
        return [s for s in self.steps if s.state == "skipped"]

    @property
    def built(self) -> list[StepResult]:
        return [s for s in self.steps if s.state == "built"]

    @property
    def worked(self) -> bool:
        """Whether the run did anything at all.

        A run where every step was skipped exits non-zero even though nothing *failed*.
        Asking for a layer, receiving nothing and being told everything is fine is the
        shape of error this module exists to refuse; it should not be reintroduced by the
        exit code.
        """
        return bool(self.built) and not self.failed

    def describe(self) -> str:
        width = max((len(s.name) for s in self.steps), default=0)
        lines = []
        for step in self.steps:
            if step.state == "built":
                lines.append(f"  {step.name:<{width}}  {step.count:>9,} {step.unit}")
            else:
                lines.append(f"  {step.name:<{width}}  {step.state.upper():>9}  {step.detail}")
        return "\n".join(lines)


def rebuild(
    home: DataHome,
    *,
    report: Reporter = _silent,
    only: Sequence[str] | None = None,
) -> PipelineResult:
    """Build every derived layer the archive can produce, in order.

    :param only: run just these steps by name. Their needs are still checked against what
        is already built, so asking for one step out of order refuses rather than writing
        an empty layer.
    """
    result = PipelineResult()
    succeeded: set[str] = set()

    for step in STEPS:
        if only is not None and step.name not in only:
            # Not asked for, but its state still gates what follows. Treat a layer that is
            # already present and non-empty as satisfied, and an absent one as not.
            if _already_built(home, step):
                succeeded.add(step.name)
            continue

        missing = [need for need in step.needs if need not in succeeded]
        if missing and only is not None:
            missing = [need for need in missing if not _already_built(home, step_by_name(need))]
        if missing:
            result.steps.append(
                StepResult(
                    step.name,
                    "skipped",
                    unit=step.unit,
                    detail=f"needs {', '.join(missing)}, which did not build",
                )
            )
            continue

        report(f"\n{step.name}...")
        try:
            count = step.run(home, report)
        except Exception as exc:  # reported, and the run continues
            result.steps.append(
                StepResult(
                    step.name, "failed", unit=step.unit, detail=f"{type(exc).__name__}: {exc}"
                )
            )
            continue

        if count <= 0:
            # An empty layer is a failed layer. Saying so here is the whole point: the
            # builders below return happily on zero, and a later `doctor` sees a table that
            # exists and calls it done.
            result.steps.append(
                StepResult(
                    step.name,
                    "failed",
                    unit=step.unit,
                    detail=f"built 0 {step.unit} -- an empty layer, not a built one",
                )
            )
            continue

        result.steps.append(StepResult(step.name, "built", count, step.unit))
        succeeded.add(step.name)

    return result


def step_by_name(name: str) -> Step:
    for step in STEPS:
        if step.name == name:
            return step
    raise KeyError(name)


#: ``step name -> (file under db/ or None for the corpus, count query)``, for deciding
#: whether a layer that this run did not build is nonetheless present and non-empty.
_PRESENCE: Final[dict[str, tuple[str | None, str]]] = {
    "verses": (None, "SELECT COUNT(*) FROM verse"),
    "search index": (None, "SELECT COUNT(*) FROM search_ref"),
    "lemma lexicon": (None, "SELECT COUNT(*) FROM lemma_form"),
    "lemma index": (None, "SELECT COUNT(*) FROM lemma_ref"),
    "parallel families": (None, "SELECT COUNT(*) FROM parallel_family"),
    "entity index": ("entities.sqlite", "SELECT COUNT(*) FROM entity_verse"),
    "verse profiles": ("profiles.sqlite", "SELECT COUNT(*) FROM profile"),
}


def _already_built(home: DataHome, step: Step) -> bool:
    """Whether a layer is present *and non-empty*. Presence alone is not the question."""
    import sqlite3

    where = _PRESENCE.get(step.name)
    if where is None:
        return False
    filename, query = where
    path = Path(home.database) if filename is None else Path(home.root) / "db" / filename
    if not path.exists():
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return int(db.execute(query).fetchone()[0]) > 0
    except sqlite3.Error:
        return False
