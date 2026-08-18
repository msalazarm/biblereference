"""Measure what inflected matching actually finds, against quotations editors marked by hand.

The thresholds in `Searcher` are two numbers with a great deal resting on them, and there is
exactly one honest way to choose them: run the matcher over quotations somebody who reads
Greek has already identified, and count. Nineteen fixtures cannot calibrate two thresholds.

The ground truth is the Patristic Text Archive's `editor_reference` table, held by the
sibling `churchfathers` project. Every row is an editor saying *this span quotes this verse*.

    venv/bin/python tools/calibrate_inflected.py --sample 1200
    venv/bin/python tools/calibrate_inflected.py --full

The first thing it prints is the baseline at `inflected=False`. If that does not land near
the 38.6% the request reports, the harness is wrong and nothing below it means anything --
so it is printed first and compared out loud rather than assumed.

Not shipped as a command: it needs a corpus this library does not own, and a number measured
against somebody else's data belongs in a report rather than in a CLI.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.canon import AmbiguousBookError, UnknownBookError, resolve_book
from biblereference.lemmata import Lexicon
from biblereference.search import (
    GRADES,
    Gate,
    LemmaWeights,
    Searcher,
    _tokens,
    lemma_chain,
    lemma_readings,
    lemma_run,
    longest_run,
    shared_bits,
)
from biblereference.store import DataHome

MARKS = Path.home() / ".local/share/churchfathers/db/corpus.sqlite"

#: The tuning `churchfathers` actually runs Greek at, so the baseline is *their* baseline
#: rather than a number reached with settings nobody uses.
GREEK = {"coverage": 0.50, "min_run": lambda n: max(4, min(6, n // 2))}

#: How the editors' reference prefixes map onto this library's numbering systems.
SYSTEMS = {"NA": "org", "LXX": "lxx"}


@dataclass(frozen=True, slots=True)
class Mark:
    book: str
    chapter: int
    verse: int
    vrs: str
    quoted: str
    announced: bool = False
    """Whether a citation formula stands within reach before the quotation *in the
    witness document* -- judged by the library's own `preceding`, so "announced" means
    here exactly what `Match.formula` means on a match."""


def marks(limit: int | None, seed: int = 0) -> list[Mark]:
    """Editor-marked Greek quotations that name a verse this library could hold.

    Each mark carries whether its document announced it, read from the passage the editor
    marked it in. Recall stratified on that bit is the report §10 asks for: an announced
    quotation the matcher misses is the loudest kind of false negative, and averaging it
    together with unannounced ones is how a recall number hides it.
    """
    from biblereference.formulae import preceding

    db = sqlite3.connect(f"file:{MARKS}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT e.raw, e.quoted, e.offset, p.text FROM editor_reference e "
        "JOIN witness w ON w.id = e.witness "
        "LEFT JOIN passage p ON p.witness = e.witness AND p.locus = e.locus "
        "WHERE w.language = 'grc' AND e.quoted IS NOT NULL AND e.quoted <> ''"
    ).fetchall()
    out: list[Mark] = []
    for raw, quoted, offset, context in rows:
        parts = str(raw).split(":")
        if len(parts) != 4 or parts[0] not in SYSTEMS:
            continue
        system, book, chapter, verse = parts
        try:
            usfm = resolve_book(book)
        except (UnknownBookError, AmbiguousBookError):
            continue
        if not chapter.isdigit() or not verse.isdigit():
            continue
        quoted = str(quoted)
        announced = False
        if context:
            # The recorded offset when it is real, else the span found by eye; either
            # way the question is the library's own: what stood within REACH before it?
            start = int(offset) if offset is not None and int(offset) >= 0 else -1
            if start < 0 or str(context)[start : start + len(quoted)] != quoted:
                start = str(context).find(quoted)
            if start > 0:
                announced = preceding(str(context), start, "grc") is not None
        out.append(
            Mark(usfm, int(chapter), int(verse), SYSTEMS[system], quoted, announced)
        )
    if limit and len(out) > limit:
        # Sampled deterministically, so two runs of the same size are comparable.
        out = random.Random(seed).sample(out, limit)
    return out


def run(home: DataHome, found: list[Mark], **options: object) -> dict[str, int]:
    """How many marks the searcher lands on, by grade of the match that found them --
    and, for POD stratification, split by whether the document announced the mark.

    `family` counts the marks recovered *only* through the parallel-family index: the
    scholar names Isaiah 53, the searcher lands on Acts 8:32, and the two are the same
    words. Counted apart from `hit`, never inside it, so every older number in every
    older report stays comparable. Zero until `biblereference parallels` has built the
    index -- silence, not an error."""
    from biblereference.parallels import Parallels

    tally = {"marks": len(found), "hit": 0, "book": 0, **{grade: 0 for grade in GRADES}}
    tally["announced"] = sum(1 for mark in found if mark.announced)
    tally["announced_hit"] = 0
    tally["family"] = 0
    index = Parallels(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True))
    with Searcher(home, languages=["grc"], **GREEK, **options) as searcher:  # type: ignore[arg-type]
        for mark in found:
            matches = searcher.search(mark.quoted, limit=5)
            landed = False
            for match in matches:
                span = match.passage
                if span.book != mark.book:
                    continue
                tally["book"] += 1
                if span.start.verse <= mark.verse <= span.end.verse:
                    tally["hit"] += 1
                    tally[match.grade] += 1
                    landed = True
                    if mark.announced:
                        tally["announced_hit"] += 1
                break
            if landed:
                continue
            name = f"{mark.book} {mark.chapter}:{mark.verse}"
            for match in matches:
                span = match.passage
                family = index.of(
                    span.start.book, span.start.chapter, span.start.verse, span.end.verse
                )
                if name in family:
                    tally["family"] += 1
                    break
    return tally


def show(label: str, tally: dict[str, int]) -> None:
    total = tally["marks"] or 1
    loud = tally.get("announced", 0)
    quiet = total - loud
    quiet_hit = tally["hit"] - tally.get("announced_hit", 0)
    family = tally.get("family", 0)
    print(
        f"  {label:28} {tally['hit']:>5}/{total:<5} POD {100 * tally['hit'] / total:5.1f}%   "
        + (f"+family {100 * (tally['hit'] + family) / total:5.1f}%   " if family else "")
        + f"announced {100 * tally.get('announced_hit', 0) / (loud or 1):5.1f}%   "
        f"unannounced {100 * quiet_hit / (quiet or 1):5.1f}%   "
        f"book {100 * tally['book'] / total:5.1f}%   "
        + "  ".join(f"{grade} {tally[grade]}" for grade in GRADES)
    )


def sweep(
    home: DataHome, found: list[Mark], **tiers: object
) -> Iterator[tuple[str, dict[str, int]]]:
    """Recall for each candidate gate, one gate at a time, so the union can be read off.

    ``tiers`` switches on the opt-in reading tiers, so the recall half of a tier's price
    is measured here and the false-positive half on the control corpus -- the two
    together are what may move a default, and neither alone.
    """
    for gate in CANDIDATES:
        yield str(gate), run(home, found, inflected=True, gates=[gate], **tiers)
    yield "union of all", run(home, found, inflected=True, gates=CANDIDATES, **tiers)


def additive(home: DataHome, found: list[Mark]) -> tuple[int, int]:
    """Whether every passage found with the feature off is still found with it on.

    The promise the consumer cares about most, checked at scale rather than asserted. The
    fixed-corpus guard in `tests/test_regression.py` proves the fields do not move; this
    proves the *match set* does not shrink over thousands of real quotations.

    :returns: ``(marks checked, passages lost)``. The second must be zero.
    """
    lost = 0
    with (
        Searcher(home, languages=["grc"], **GREEK) as plain,  # type: ignore[arg-type]
        Searcher(home, languages=["grc"], inflected=True, **GREEK) as rich,  # type: ignore[arg-type]
    ):
        for mark in found:
            before = {str(m.passage) for m in plain.search(mark.quoted, limit=5)}
            after = {str(m.passage) for m in rich.search(mark.quoted, limit=5)}
            lost += len(before - after)
    return len(found), lost


#: Eras whose authors were dead before there was a New Testament to quote, so every match in
#: them is a false positive by construction. Read from `churchfathers`' own dating table --
#: the consumer's control group, not one invented here to be flattered by.
CONTROL_ERAS = {"classical", "pre-christian", "pre-septuagint"}

#: The permissive gate the sweep collects through. Every candidate gate below is stricter, so
#: one pass gathers the evidence for all of them and the sweep costs one scan, not twenty.
COLLECT = Gate(chain=2, bits=10.0)

#: What each evidence row records, in order. The four axes come off the *match itself* --
#: recomputing them here measured `bits` by the pre-Magnesians span-sum while every live
#: gate uses distinct chain lemmas, and a null calibrated on a statistic no live match
#: carries prices nothing. `offset_peak` and `formula` are the verification stage's
#: terms, finally given m/u tables to be calibrated from.
ROW_FIELDS = ("run", "lemma_run", "chain", "bits", "offset_peak", "formula")

#: Collection limit that makes `search()` provably pre-arbitration. Graded candidates
#: are bounded by `_PASSAGES` (12) per language and exact ones likewise, so with one
#: language 32 can never truncate -- and the consumer's arbitration finding was exactly
#: that a floor-collected survivor set is not a superset of any narrow gate's live
#: output: `_grade` refuses gate-failers *before* the `limit` contest, so the wide
#: floor's rivals crowd out what a narrow gate would have returned alone. Collecting
#: every candidate makes the null per-candidate, and every live emission at every gate
#: is then a subset: the residual error is conservative, never anti-.
COLLECT_LIMIT = 32


def control_text(cap: int) -> tuple[list[str], int]:
    """Greek by authors who cannot be quoting the New Testament, up to ``cap`` words."""
    import json

    dating = json.loads(
        (Path.home() / "churchfathers/src/churchfathers/data/dating.json").read_text("utf-8")
    )
    eras = {key: value.get("era") for key, value in dating.items() if isinstance(value, dict)}
    db = sqlite3.connect(f"file:{MARKS}?mode=ro", uri=True)
    witnesses = [
        wid
        for wid, work, _ in db.execute(
            # ORDER BY, so the deterministic shuffle below has a deterministic input:
            # without it the ordering rides on rowid order, which a VACUUM may change,
            # and `--resume`'s contiguous-prefix invariant rides on this list.
            "SELECT id, work, words FROM witness WHERE language = 'grc' AND words > 0 "
            "ORDER BY id"
        )
        if eras.get((work or "").split(".")[0]) in CONTROL_ERAS
    ]
    random.Random(11).shuffle(witnesses)
    out: list[str] = []
    words = 0
    for wid in witnesses:
        for (text,) in db.execute(
            "SELECT text FROM passage WHERE witness = ? AND text IS NOT NULL "
            "ORDER BY ordinal",
            (wid,),
        ):
            out.append(str(text))
            words += len(str(text).split())
            if words >= cap:
                return out, words
    return out, words


#: Per-process state for the evidence workers, built once by `_worker_init` -- the same
#: spawn-safe pattern as `web/jobs.worker_searcher`: a spawned child inherits nothing but
#: the environment, so each builds its own searcher against the (read-only) library.
_W: dict[str, object] = {}


def _worker_init(tiers: dict[str, bool] | None = None) -> None:
    """Per-process state. ``tiers`` switches on the opt-in reading tiers being priced --
    a tier can only *add* readings, so the difference it makes to the control table is
    its false-positive price, measured the same per-candidate way as everything else."""
    home = DataHome()
    _W["searcher"] = Searcher(
        home,
        languages=["grc"],
        inflected=True,
        min_query=3,
        gates=[COLLECT],
        **(tiers or {}),  # type: ignore[arg-type]
        **GREEK,
    )
    _W["lexicon"] = Lexicon(home)
    _W["weigh"] = LemmaWeights(home).of("grc")


def _evidence_one(
    text: str, window: int = 12, stride: int = 6
) -> tuple[list[tuple], int, int, int]:
    """One control text's evidence rows: ``(rows, windows, words, truncated)``.

    Each row is `ROW_FIELDS`: the match's OWN four axes (the recomputation this replaces
    measured `bits` by the pre-Magnesians span-sum -- a statistic no live match carries),
    plus the verification stage's two terms: the offset-histogram peak against the
    match's own best witness, and whether a citation formula stood within reach before
    the window -- measurable in control prose, where verbs of saying are ordinary Greek.

    Collected at `COLLECT_LIMIT`, which is pre-arbitration by construction; `truncated`
    counts windows where the limit filled, and any nonzero count means the bound needs
    raising -- it is reported, never swallowed.
    """
    from biblereference.formulae import REACH, preceding
    from biblereference.verification import offset_histogram

    searcher = _W["searcher"]
    lexicon = _W["lexicon"]
    weigh = _W["weigh"]
    rows: list[tuple] = []
    tokens = text.split()
    windows = truncated = 0
    for start in range(0, max(1, len(tokens) - window + 1), stride):
        windows += 1
        chunk = " ".join(tokens[start : start + window])
        before = " ".join(tokens[max(0, start - REACH) : start])
        announced = bool(before) and (
            preceding(before + " ", len(before) + 1, "grc") is not None
        )
        matches = searcher.search(chunk, limit=COLLECT_LIMIT)  # type: ignore[attr-defined]
        if len(matches) == COLLECT_LIMIT:
            truncated += 1
        mine = None
        for match in matches:
            if match.grade == "direct" or not match.witnesses:
                continue
            if mine is None:
                mine = lemma_readings(_tokens(chunk, "grc"), "grc", lexicon)  # type: ignore[arg-type]
            theirs = lemma_readings(
                _tokens(match.witnesses[0].text, "grc"), "grc", lexicon  # type: ignore[arg-type]
            )
            peak, _ = offset_histogram(mine, theirs, weigh)  # type: ignore[arg-type]
            rows.append(
                (
                    match.run,
                    match.lemma_run,
                    match.chain,
                    match.bits,
                    peak,
                    1.0 if announced else 0.0,
                )
            )
    return rows, windows, len(tokens), truncated


def evidence(
    home: DataHome, texts: list[str], window: int = 12, stride: int = 6
) -> tuple[list[tuple], int]:
    """Sequential wrapper over `_evidence_one`, kept for callers that want one pass in
    one process. `cmd_control` uses the pool instead."""
    _worker_init()
    found: list[tuple] = []
    windows = 0
    for text in texts:
        rows, seen, _, _ = _evidence_one(text, window, stride)
        found.extend(rows)
        windows += seen
    return found, windows


def full_row(
    text: str, verse: str, lexicon: Lexicon, weigh: object, announced: bool
) -> tuple[int, int, int, float, float, float]:
    """A `ROW_FIELDS` row for one text against one verse -- the m-side's collector.

    `bits` by the live `_grade` formula (distinct chain lemmas), NOT the span-sum
    `axes()` still computes for old-file comparability: a null and a gold sample must
    measure the statistic the live gates actually read, or they calibrate nothing.
    """
    from biblereference.verification import offset_histogram

    query, spelled = _tokens(text, "grc"), _tokens(verse, "grc")
    mine = lemma_readings(query, "grc", lexicon)
    theirs = lemma_readings(spelled, "grc", lexicon)
    chained = lemma_chain(mine, theirs, weigh)  # type: ignore[arg-type]
    peak, _ = offset_histogram(mine, theirs, weigh)  # type: ignore[arg-type]
    return (
        longest_run(query, spelled),
        lemma_run(mine, theirs, weigh).length,  # type: ignore[arg-type]
        chained.length,
        sum(weigh(lemma) for lemma in set(chained.lemmas)),  # type: ignore[operator]
        peak,
        1.0 if announced else 0.0,
    )


def axes(text: str, verse: str, lexicon: Lexicon, weigh: object) -> tuple[int, int, int, float]:
    """``(run, lemma_run, chain, bits)`` for one text against one verse."""
    query, spelled = _tokens(text, "grc"), _tokens(verse, "grc")
    mine = lemma_readings(query, "grc", lexicon)
    theirs = lemma_readings(spelled, "grc", lexicon)
    chained = lemma_chain(mine, theirs, weigh)  # type: ignore[arg-type]
    first, last = chained.span
    weight = shared_bits(mine[first:last], theirs, weigh) if last > first else 0.0  # type: ignore[arg-type]
    return (
        longest_run(query, spelled),
        lemma_run(mine, theirs, weigh).length,  # type: ignore[arg-type]
        chained.length,
        weight,
    )


CANDIDATES = [
    Gate(lemma_run=2, bits=60.0),
    Gate(lemma_run=4, bits=40.0),
    Gate(lemma_run=5, bits=35.0),
    Gate(chain=4, bits=50.0),
    Gate(chain=5, bits=40.0),
    Gate(chain=6, bits=35.0),
    Gate(chain=8, bits=40.0),
    Gate(chain=8, bits=30.0),
    Gate(chain=10, bits=25.0),
    Gate(run=3, bits=20.0),
    Gate(run=4, bits=15.0),
]


#: The four-axis order old files used before rows carried a `fields` key.
DEFAULT_ROW_FIELDS_STR = ["run", "lemma_run", "chain", "bits"]


def _axis_columns(fields: list[str]) -> tuple[int, int, int, int]:
    """Where the four gate axes sit in a row, by name -- `Gate.admits` takes exactly
    four arguments, and a six-wide row splatted into it is the transposition bug the
    named-fields convention exists to prevent."""
    return (
        fields.index("run"),
        fields.index("lemma_run"),
        fields.index("chain"),
        fields.index("bits"),
    )


def _checkpoint(
    saved: Path,
    *,
    words: int,
    windows: int,
    rows: list[tuple],
    done: int,
    cap: int,
    complete: bool,
) -> None:
    """Atomic: write beside, then replace. A crash mid-write leaves the last good file."""
    import json
    import os

    payload = json.dumps(
        {
            "words": words,
            "windows": windows,
            "axes": rows,
            "fields": list(ROW_FIELDS),
            "done_texts": done,
            "cap": cap,
            "complete": complete,
        }
    )
    scratch = saved.with_suffix(saved.suffix + ".tmp")
    scratch.write_text(payload, "utf-8")
    os.replace(scratch, saved)


def cmd_control(args: argparse.Namespace) -> int:
    import json
    import multiprocessing
    import time

    saved = Path(args.save) if args.save else None
    found: list[tuple] = []
    words = windows = done = truncated = 0

    if saved and saved.exists():
        record = json.loads(saved.read_text("utf-8"))
        complete = bool(record.get("complete", True))
        fields = list(record.get("fields", DEFAULT_ROW_FIELDS_STR))
        if complete and not args.resume:
            # The collected evidence is the expensive half; re-reading makes the gate
            # table reproducible without a rescan and hands the same file to the
            # composite build.
            words, windows = int(record["words"]), int(record["windows"])
            found = [tuple(row) for row in record["axes"]]
            print(f"control (from {saved}): {words:,} words\n")
            _gate_table(found, fields, words, windows)
            return 0
        if not complete and not args.resume:
            print(
                f"{saved} is an incomplete checkpoint ({record.get('done_texts', 0)} "
                f"texts in). Pass --resume to continue it, or delete it to start over.",
                file=sys.stderr,
            )
            return 2
        # Resuming: the partial must have been cut from the same cloth.
        if int(record.get("cap", -1)) != args.control:
            print(
                f"checkpoint cap {record.get('cap')} != --control {args.control}; "
                f"a resumed run must ask for the same corpus",
                file=sys.stderr,
            )
            return 2
        if fields != list(ROW_FIELDS):
            print(
                f"checkpoint fields {fields} != current {list(ROW_FIELDS)}; rows from "
                f"two schemas cannot be mixed -- start over",
                file=sys.stderr,
            )
            return 2
        words = int(record["words"])
        windows = int(record["windows"])
        found = [tuple(row) for row in record["axes"]]
        done = int(record.get("done_texts", 0))
        print(f"resuming {saved} at text {done:,} ({words:,} words in)\n")

    texts, capped_words = control_text(args.control)
    if done >= len(texts):
        print("checkpoint already covers every text; finishing")
    print(
        f"control: {capped_words:,} words of classical / pre-christian / pre-septuagint "
        f"Greek, {len(texts):,} texts, {args.workers} worker(s)\n"
    )

    remaining = texts[done:]
    last_write = time.monotonic()
    if remaining:
        context = multiprocessing.get_context("spawn")
        tiers = {
            name.strip(): True for name in str(args.tiers).split(",") if name.strip()
        }
        with context.Pool(
            args.workers, initializer=_worker_init, initargs=(tiers,)
        ) as pool:
            # Ordered imap: `done_texts` stays a contiguous prefix, which is the whole
            # resume invariant. chunksize amortises the pickle traffic.
            for rows, seen, length, cut in pool.imap(_evidence_one, remaining, chunksize=4):
                found.extend(rows)
                windows += seen
                words += length
                truncated += cut
                done += 1
                if saved and (done % 25 == 0 or time.monotonic() - last_write > 60):
                    _checkpoint(
                        saved, words=words, windows=windows, rows=found, done=done,
                        cap=args.control, complete=False,
                    )
                    last_write = time.monotonic()
                if done % 200 == 0:
                    print(f"  {done:,}/{len(texts):,} texts, {len(found):,} rows", flush=True)
    if saved:
        _checkpoint(
            saved, words=words, windows=windows, rows=found, done=done,
            cap=args.control, complete=True,
        )
        print(f"evidence written to {saved}\n")
    if truncated:
        print(
            f"WARNING: {truncated} window(s) filled the {COLLECT_LIMIT}-match collection "
            f"limit -- the per-candidate bound needs raising",
            file=sys.stderr,
        )
    _gate_table(found, list(ROW_FIELDS), words, windows)
    return 0


def _gate_table(found: list[tuple], fields: list[str], words: int, windows: int) -> None:
    print(f"collected at {COLLECT}: {len(found):,} candidate matches, all of them false")
    print(f"over {windows:,} windows -- the opportunities PFA is a probability of\n")
    print(f"{'gate':34} {'false positives':>15} {'per 1,000 words':>16} {'PFA':>10}")
    columns = _axis_columns(fields)
    for gate in CANDIDATES:
        n = sum(1 for row in found if gate.admits(*(row[c] for c in columns)))
        print(
            f"  {gate!s:32} {n:>15,} {n / (words or 1) * 1000:>16.4f} "
            f"{n / (windows or 1):>10.6f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1200, help="marks to measure (0 = all)")
    parser.add_argument("--full", action="store_true", help="every mark; slow")
    parser.add_argument(
        "--control",
        type=int,
        default=0,
        metavar="WORDS",
        help="instead, measure false positives over this many words of pre-Christian Greek",
    )
    parser.add_argument("--save", metavar="PATH", help="write/read the collected evidence")
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (__import__("os").cpu_count() or 2) - 2),
        help="processes for the control collection (default: all cores but two)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue an incomplete --save checkpoint instead of refusing it",
    )
    parser.add_argument(
        "--tiers",
        default="",
        metavar="NAMES",
        help="comma-separated opt-in tiers to switch on for this run (itacised, "
        "recovered, concave, seed_mask): the control table then prices them, because a "
        "tier can only add readings and the difference in false positives is its price",
    )
    args = parser.parse_args()
    if args.control:
        return cmd_control(args)

    if not MARKS.exists():
        print(f"no ground truth at {MARKS}", file=sys.stderr)
        return 1

    home = DataHome()
    found = marks(None if args.full or not args.sample else args.sample)
    print(f"{len(found):,} editor-marked Greek quotations naming a verse\n")

    print("baseline -- this must reproduce what the request reports, or nothing below counts")
    show("inflected=False", run(home, found))

    _, lost = additive(home, found)
    print(f"\nadditive: {lost} passage(s) found with the feature off and lost with it on")

    tiers = {name.strip(): True for name in str(args.tiers).split(",") if name.strip()}
    print("\ninflected, by gate" + (f" (tiers: {', '.join(sorted(tiers))})" if tiers else ""))
    for label, tally in sweep(home, found, **tiers):
        show(label, tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
