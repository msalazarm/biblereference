"""Arbitrate the verse-boundary disagreements between the two Rahlfs transcriptions.

    venv/bin/python tools/rahlfs_boundaries.py            # the tally
    venv/bin/python tools/rahlfs_boundaries.py --list     # every case, readable
    venv/bin/python tools/rahlfs_boundaries.py --book EXO

`rahlfs` (Patristic Text Archive) and `rahlfs-cc` (Corpus Corporum) are two transcriptions
of *one printed edition*, so where they disagree one of them is simply wrong. About seven
hundred of their differences are not wording at all: they are places where the two put the
verse break in different places, so a clause sits at the end of verse *n* in one and the
start of *n+1* in the other.

**Arbitrated, not judged.** Swete and Brenton are independent editions of the same Greek --
different text, same verse divisions -- so the question "which transcription puts this
clause in the right verse" has a mechanical answer: whichever one's verse *n* shares more
of its words with the arbiter's verse *n*. No model, no reading, and repeatable.

What comes out is a tally per book and a queue. What it is *for* is the two things a tally
cannot say by itself: whether either transcription is systematically wrong somewhere (in
which case the corpus needs re-cutting rather than the queue reading), and whether any of
them implies that `lxx`'s own verse counts are wrong (in which case it is a correction).
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from biblereference.canon import CANONICAL_ORDER, book_title
from biblereference.refs import VerseRef
from biblereference.store import DataHome, SqliteCorpus, chapter_index

#: A boundary case, not a wording one: the two transcriptions differ in length by more than
#: this many words. Below it the difference is punctuation or a split word, which is a fact
#: about the source files and was settled in `docs/tei-corpora.md`.
LENGTH_GAP = 3


def fold(text: str) -> list[str]:
    """Words, without accent, breathing or case.

    The two transcriptions differ in their apostrophes (U+1FBD against U+2019) and in
    whether they keep the printed accents, and none of that bears on where a verse ends.
    """
    stripped = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in stripped if not unicodedata.combining(c))
    return [w for w in "".join(c if c.isalnum() else " " for c in plain).split() if w]


@dataclass(frozen=True, slots=True)
class Case:
    ref: VerseRef
    left: str
    right: str
    verdict: str  # "pta" | "cc" | "draw" | "no arbiter"
    scores: tuple[float, float]
    arbiter: str

    @property
    def shape(self) -> str:
        """Which way the boundary moved: one transcription's verse is longer."""
        return "pta longer" if len(fold(self.left)) > len(fold(self.right)) else "cc longer"


def overlap(candidate: str, arbiter: str) -> float:
    """Share of the arbiter's words this verse accounts for.

    Asymmetric on purpose. The question is whether this verse *contains the arbiter's
    verse*, not whether the two are the same length -- the whole disagreement is that one of
    them has absorbed a clause it should not have, and a symmetric ratio would punish the
    correct one for the arbiter's own wording differences.
    """
    wanted = fold(arbiter)
    if not wanted:
        return 0.0
    held = set(fold(candidate))
    return sum(1 for word in wanted if word in held) / len(wanted)


def disagreements(
    left: SqliteCorpus, right: SqliteCorpus, arbiters: list[SqliteCorpus], books: list[str]
) -> Iterator[Case]:
    """Every verse where the two transcriptions differ in length by more than LENGTH_GAP."""
    home = DataHome(Path.home() / ".local/share/biblereference")
    index = chapter_index(home)
    for book in books:
        chapters = index.get(left.id, {}).get(book, {})
        for chapter in sorted(chapters):
            here = {v.ref.verse: v.text for v in left.chapter(book, chapter)}
            there = {v.ref.verse: v.text for v in right.chapter(book, chapter)}
            judges = [
                (a.id, {v.ref.verse: v.text for v in a.chapter(book, chapter)}) for a in arbiters
            ]
            for verse in sorted(set(here) & set(there)):
                one, two = here[verse], there[verse]
                if abs(len(fold(one)) - len(fold(two))) <= LENGTH_GAP:
                    continue
                ref = VerseRef(book, chapter, verse, vrs=left.versification)
                best = ("no arbiter", 0.0, 0.0, "")
                for name, verses in judges:
                    text = verses.get(verse)
                    if not text or not fold(text):
                        continue
                    scored = (overlap(one, text), overlap(two, text))
                    if max(scored) > max(best[1], best[2]):
                        best = ("scored", scored[0], scored[1], name)
                if best[0] == "no arbiter":
                    yield Case(ref, one, two, "no arbiter", (0.0, 0.0), "")
                    continue
                _, first, second, who = best
                verdict = (
                    "draw" if abs(first - second) < 0.02 else ("pta" if first > second else "cc")
                )
                yield Case(ref, one, two, verdict, (first, second), who)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", help="one book, by USFM code")
    parser.add_argument("--list", action="store_true", help="print every case with its texts")
    parser.add_argument("--verdict", help="only cases with this verdict")
    args = parser.parse_args()

    home = DataHome(Path.home() / ".local/share/biblereference")
    built = SqliteCorpus.load_all(home)
    missing = [n for n in ("rahlfs", "rahlfs-cc") if n not in built]
    if missing:
        print(f"not built: {', '.join(missing)}", file=sys.stderr)
        return 1
    left, right = built["rahlfs"], built["rahlfs-cc"]
    arbiters = [built[n] for n in ("swete", "brenton") if n in built]

    books = [args.book] if args.book else [b for b in CANONICAL_ORDER if left.has_book(b)]
    cases = list(disagreements(left, right, arbiters, books))
    if args.verdict:
        cases = [c for c in cases if c.verdict == args.verdict]

    tally: dict[str, int] = {}
    per_book: dict[str, dict[str, int]] = {}
    for case in cases:
        tally[case.verdict] = tally.get(case.verdict, 0) + 1
        per_book.setdefault(case.ref.book, {})
        per_book[case.ref.book][case.verdict] = per_book[case.ref.book].get(case.verdict, 0) + 1

    if args.list:
        for case in cases:
            print(
                f"\n=== {case.ref}  {case.verdict}  ({case.arbiter} "
                f"{case.scores[0]:.2f}/{case.scores[1]:.2f})  {case.shape}"
            )
            print(f"  pta: {case.left[:220]}")
            print(f"  cc : {case.right[:220]}")

    print(f"\n{len(cases)} boundary disagreements")
    for verdict, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:12s} {count:4d}")

    print("\nby book, where either side wins five or more:")
    for book, counts in sorted(per_book.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counts.values())
        if total < 5:
            continue
        print(
            f"  {book_title(book):24s} {total:4d}  "
            f"pta {counts.get('pta', 0):3d}  cc {counts.get('cc', 0):3d}  "
            f"draw {counts.get('draw', 0):3d}  none {counts.get('no arbiter', 0):3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
