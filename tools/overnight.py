"""The overnight run: put every verse that can be judged to the models, and report.

Lab equipment, not library code. Five phases, in this order and for this reason:

1. **Suspicions.** Verses where a deterministic witness already prefers a different
   position. The control is that rival, so the model chooses between two live candidates
   rather than between a mapping and a verse picked to be wrong.
2. **The gap.** Verses no same-language witness can reach at all -- overwhelmingly the
   Nova Vulgata, which this repository holds only in Latin while no other family holds
   Latin, so not one of its conversions has ever been checked against a word of text.
3. **Second opinion.** Verses the deterministic instrument already confirmed, put to an
   instrument that fails differently. Agreement between two such is worth far more than
   either alone; disagreement is worth more than a hundred agreements.
4. **Reseed.** Everything flagged above, judged again with fresh seeds. A finding that
   does not reproduce is noise, and at this scale a one percent instability is hundreds of
   false alarms.
5. **The deterministic instruments again**, to confirm nothing drifted underneath.

Nothing here writes to the versification data. It produces evidence for a person to read.

    venv/bin/python tools/overnight.py
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
import time
from pathlib import Path

from biblereference.adjudicate import (
    _UNREACHABLE,
    Task,
    build_work,
    calibrate,
    run_tasks,
    shuffled,
)
from biblereference.audit import _Texts
from biblereference.judge import Judge, Verdict, open_judgements
from biblereference.store import DataHome
from biblereference.versification import PIVOT, Versification

#: All four, when nothing else wants them. Two of these -- ``100.98.85.58:8090`` and
#: ``127.0.0.1:8080`` -- belong to another project and must be dropped from this tuple the
#: moment it needs them again; the run is resumable, so stopping and restarting on two
#: costs only the judgements in flight.
#:
#: The bottleneck is the round-robin share each server gets rather than any one server's
#: slots, which is why the count matters more than which ones: measured on two, this run
#: does about six judgements a second, and 128,000 verses is eight hours of that.
SERVERS = (
    "http://100.98.85.58:8080",
    "http://100.98.85.58:8090",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
)

HOME = DataHome()
AUDIT = HOME.root / "audit"
REPORT = AUDIT / "overnight.md"
LOG = AUDIT / "overnight.log"


def say(message: str = "") -> None:
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}] {message}" if message else ""
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def note(text: str) -> None:
    """Append to the report as the run goes, so it is readable even if interrupted."""
    with REPORT.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def phase_tally(connection, phase: str) -> collections.Counter[str]:
    """What the *database* holds for a phase, not what this attempt happened to judge.

    The difference matters after a restart: an attempt that resumed with two thirds already
    done would otherwise report a third of the work as though it were all of it. Every
    number in the report is read back from disk for the same reason.
    """
    rows = connection.execute(
        "SELECT verdict, COUNT(*) FROM judgement WHERE right_family = ? GROUP BY verdict",
        (f"{PIVOT}:{phase}",),
    )
    return collections.Counter({str(verdict): int(count) for verdict, count in rows})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Matched to the slots actually available: sixteen workers against five slots only
    # queued requests inside llama.cpp, where they could be neither timed out nor retried.
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--database", default="judgement2.sqlite")
    parser.add_argument("--phases", default="suspicions,gap,confirmed")
    parser.add_argument("--skip-reruns", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="rebuild the report from judgement.sqlite without judging anything",
    )
    args = parser.parse_args()

    AUDIT.mkdir(parents=True, exist_ok=True)
    # Started fresh each attempt. Nothing here is a record -- judgement.sqlite is the
    # record, and every figure below is read back out of it -- so a crash at 3am costs the
    # half-written report and not one judged verse.
    REPORT.write_text("", encoding="utf-8")
    vrs = Versification.load()
    # 60s, not 180. A request this model answers in under two seconds is not going to be
    # rescued by a three-minute wait, and a long timeout only holds a worker against a
    # server that has stopped talking. The verse is left unjudged and a later run takes it.
    judge = Judge(SERVERS, timeout=60.0)
    # A new database rather than the first run's. That run's witness for `org` was an
    # English-tradition corpus, so its answers rest on a different and weaker basis;
    # resuming into it would blend the two and lose the ability to ask which flags were
    # the witness rather than the mapping.
    connection = open_judgements(AUDIT / args.database)

    note(f"# Overnight adjudication — written {time.strftime('%Y-%m-%d %H:%M')}\n")
    if args.report_only:
        work = build_work(HOME, vrs, report=say)
        for phase in ("suspicions", "gap", "confirmed"):
            note(f"\n## Phase: {phase}\n\n```\n{_summary(phase_tally(connection, phase))}\n```\n")
            _write_findings(connection, vrs, phase, work[phase])
        _write_unreachable()
        say(f"report rebuilt: {REPORT}")
        return 0

    # Narrowed to the servers that answered, not merely reported. `Judge` round-robins
    # over whatever list it holds, so leaving the dead ones in sends three of every four
    # requests to a closed port -- which never showed while all four were up, and stopped
    # the first Slavonic run dead when only one was.
    alive = judge.available()
    say(f"servers alive: {len(alive)} of {len(SERVERS)}")
    if not alive:
        say("no model server answering; nothing to do")
        return 1
    judge = Judge(alive, timeout=60.0)

    # -- calibration, which is the only reason to believe anything that follows ----------
    say("calibrating against mappings whose answer is known...")
    calibration = calibrate(judge, HOME, vrs, report=say)
    say("\n" + calibration.describe())
    note("## Calibration\n\n```\n" + calibration.describe() + "\n```\n")

    total_right = sum(calibration.correct.values())
    total_informative = sum(calibration.informative.values())
    if total_informative and total_right / total_informative < 0.8:
        say("model cannot read pairs whose answer is known; refusing to run")
        note("\n**Run refused: calibration failed.** Nothing below was judged.\n")
        return 1
    say(f"calibration: {total_right}/{total_informative} correct. Proceeding.\n")

    # -- the work ------------------------------------------------------------------------
    say("building work-lists (one walk of all 155,578 conversions)...")
    work = build_work(HOME, vrs, report=say)
    note("## Work\n\n| phase | verses |\n|---|---|")
    for phase in ("suspicions", "gap", "confirmed"):
        note(f"| {phase} | {len(work[phase]):,} |")
    note(f"| unreachable by any instrument | {sum(_UNREACHABLE.values()):,} |\n")

    tallies: dict[str, collections.Counter[str]] = {}
    for phase in args.phases.split(","):
        phase = phase.strip()
        if not work.get(phase):
            continue
        say(f"\n=== phase: {phase} ({len(work[phase]):,} verses)")
        tallies[phase] = run_tasks(
            shuffled(list(work[phase])),
            judge,
            connection,
            phase=phase,
            home=HOME,
            workers=args.workers,
            report=say,
            calibration=calibration,
        )
        note(f"\n## Phase: {phase}\n\n```\n{_summary(phase_tally(connection, phase))}\n```\n")
        _write_findings(connection, vrs, phase, work[phase])

    # -- the deterministic instruments, to confirm nothing drifted -----------------------
    if not args.skip_reruns:
        say("\n=== re-running the deterministic instruments")
        note("\n## The deterministic instruments, after the run\n")
        for label, command in (
            ("coverage", ["venv/bin/biblereference", "coverage"]),
            ("tests", ["venv/bin/python", "-m", "pytest", "-q", "--no-header"]),
        ):
            say(f"  {label}...")
            done = subprocess.run(
                command, capture_output=True, text=True, cwd=Path(__file__).parent.parent
            )
            tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-14:])
            say(f"  {label}: exit {done.returncode}")
            note(f"### {label} (exit {done.returncode})\n\n```\n{tail}\n```\n")

    _write_unreachable()
    say(f"\ndone. Report: {REPORT}")
    return 0


def _summary(counts: collections.Counter[str]) -> str:
    total = sum(counts.values())
    if not total:
        return "nothing judged"
    informative = counts[Verdict.CONFIRMED] + counts[Verdict.CONTRADICTED]
    lines = [f"{name:15} {count:>7,}" for name, count in sorted(counts.items())]
    lines.append(f"{'informative':15} {informative / total:>7.1%} of {total:,}")
    return "\n".join(lines)


def _write_findings(connection, vrs: Versification, phase: str, tasks: list[Task]) -> None:
    """Every contradiction, with the texts, ranked so the worst is first.

    A contradiction is a reason to read, never a reason to edit -- which is why this prints
    the words rather than a verdict, and why nothing in this run touches the mapping data.
    """
    by_verse = {
        (t.source.vrs, t.source.book, int(t.source.chapter), t.source.verse): t for t in tasks
    }
    rows = list(
        connection.execute(
            "SELECT left_family, book, chapter, verse, mapped_book, mapped_chapter, "
            "mapped_verse FROM judgement WHERE right_family = ? AND verdict = 'contradicted' "
            "ORDER BY left_family, book, chapter, verse",
            (f"{PIVOT}:{phase}",),
        )
    )
    if not rows:
        note(f"No contradictions in **{phase}**.\n")
        return

    note(f"### Contradictions in {phase}: {len(rows):,}\n")
    by_book = collections.Counter(f"{r[0]} {r[1]}" for r in rows)
    note("| system + book | flagged |\n|---|---|")
    for name, count in by_book.most_common(25):
        note(f"| {name} | {count} |")
    note("")

    texts = _Texts(HOME)
    try:
        note("<details><summary>The first 300, with their texts</summary>\n")
        for row in rows[:300]:
            system, book, chapter, verse = row[0], row[1], int(row[2]), int(row[3])
            task = by_verse.get((system, book, chapter, verse))
            if task is None:
                continue
            source = texts.verse(task.source_corpus, task.source) or "(absent)"
            mapped = texts.verse(task.target_corpus, task.mapped) or "(absent)"
            control = texts.verse(task.target_corpus, task.control) or "(absent)"
            kind = "rival" if task.rival else "neighbour"
            note(
                f"**{system} {book} {chapter}:{verse}** → `{task.mapped}` "
                f"({task.source_corpus} / {task.target_corpus}, {task.languages})\n\n"
                f"- asked: {source[:300]}\n"
                f"- mapped: {mapped[:300]}\n"
                f"- {kind}: {control[:300]}\n"
            )
        note("</details>\n")
    finally:
        texts.close()


def _write_unreachable() -> None:
    note("\n## Reachable by nothing\n")
    note(
        "No witness this machine holds carries one side of these, in any language, so no "
        "instrument can speak to them. This is a missing corpus rather than a missing "
        "analysis, and it is a shopping list rather than a percentage.\n"
    )
    note("| system + book | verses |\n|---|---|")
    for name, count in _UNREACHABLE.most_common(40):
        note(f"| {name} | {count:,} |")
    note(f"\n**{sum(_UNREACHABLE.values()):,} total.**\n")


if __name__ == "__main__":
    sys.exit(main())
