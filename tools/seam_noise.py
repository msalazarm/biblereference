"""Do the derived verse divisions in `f` and `ff2` invent variant columns?

`derive_oldlatin.py` cuts two unnumbered manuscripts into verses by aligning their word
stream against the Clementine. A cut in the wrong place moves a token into a neighbouring
verse, and in a profile a displaced token is a column where that manuscript alone has a
reading -- a variant the scribe never wrote.

Two earlier attempts at this measurement were circular and are not quoted anywhere as an
answer: verse-level agreement with the Clementine (which the derivation maximised), and edge
bleed (which the derivation minimised by construction). Both measured the objective.

**This one is not, and the reason is the reference witness.** Vercellensis and Veronensis
carry Bianchini's own verse numbers, arrived at independently of any alignment. So: throw one
manuscript's numbers away, re-derive them by the same procedure, and count the variant columns
it shows *against the other manuscript* -- which the derivation never saw. The Clementine is
deliberately not the reference: the derived cuts were fitted to it, so scoring against it
would flatter them.

    columns(derived vs other) - columns(true vs other) = columns the derivation invented

Run:  venv/bin/python tools/seam_noise.py
"""

from __future__ import annotations

import argparse
import difflib
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from derive_oldlatin import _fold, clementine, cuts

from biblereference.audit import _Texts
from biblereference.corpora.oldlatin import read
from biblereference.store import DataHome

#: The two manuscripts Bianchini numbered. Each takes a turn as the one being re-derived and
#: as the independent reference.
NUMBERED = ("Vercellensis", "Veronensis")


def _columns(left: list[str], right: list[str]) -> int:
    """Alignment positions where the two witnesses do not read the same word.

    A profile column is a position in the alignment; a column carries a *variant* where the
    witnesses differ. Counted with the same matcher the profiles use, and on folded words, so
    spelling is not mistaken for substance.
    """
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    same = sum(block.size for block in matcher.get_matching_blocks())
    return max(len(left), len(right)) - same


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=None)
    args = parser.parse_args()

    home = DataHome()
    if args.source:
        path = args.source
    else:
        archive = home.latest_archive("oldlatin")
        if archive is None:
            print("oldlatin has not been fetched")
            return 2
        path = archive / "cc-6898.xml"
    if not Path(path).exists():
        print(f"cannot find the Old Latin source at {path}")
        return 2
    texts = _Texts(home)

    verses: dict[tuple[str, str], list[tuple[tuple[int, int], str]]] = defaultdict(list)
    for codex, ref, text in read(Path(path)):
        verses[(codex, ref.book)].append(((int(ref.chapter), ref.verse), text))

    print(
        f"{'manuscript / book':<26}{'verses':>7}{'true':>9}{'derived':>9}{'excess':>9}  per verse"
    )
    totals: list[tuple[int, int, int]] = []
    for codex in NUMBERED:
        other = NUMBERED[1] if codex == NUMBERED[0] else NUMBERED[0]
        for (held_codex, book), rows in sorted(verses.items()):
            if held_codex != codex:
                continue
            reference = {ref: text for ref, text in verses.get((other, book), [])}
            if not reference:
                continue

            stream: list[str] = []
            actual: list[tuple[tuple[int, int], int]] = []
            for ref, text in rows:
                actual.append((ref, len(stream)))
                stream.extend(text.split())

            held = {ref for ref, _ in rows}
            vulgate = [(ref, words) for ref, words in clementine(texts, book) if ref in held]
            if not vulgate:
                continue
            derived = cuts(stream, vulgate)

            # The derived cut points, in order, become the derived verse texts over the very
            # same word stream -- so any difference in columns is the cutting, not the words.
            starts = [
                (ref, derived[f"{ref[0]}:{ref[1]}"])
                for ref, _ in actual
                if f"{ref[0]}:{ref[1]}" in derived
            ]
            starts.sort(key=lambda pair: pair[1])
            derived_text = {
                ref: stream[start : starts[i + 1][1] if i + 1 < len(starts) else len(stream)]
                for i, (ref, start) in enumerate(starts)
            }

            true_columns = derived_columns = counted = 0
            for ref, text in rows:
                if ref not in reference or ref not in derived_text:
                    continue
                against = [_fold(w) for w in reference[ref].split()]
                if not against:
                    continue
                counted += 1
                true_columns += _columns([_fold(w) for w in text.split()], against)
                derived_columns += _columns([_fold(w) for w in derived_text[ref]], against)
            if not counted:
                continue
            excess = derived_columns - true_columns
            totals.append((counted, true_columns, derived_columns))
            print(
                f"  {codex + ' ' + book:<24}{counted:>7,}{true_columns:>9,}"
                f"{derived_columns:>9,}{excess:>+9,}  {excess / counted:+.2f}"
            )

    if not totals:
        print("\nnothing measurable -- no book had both manuscripts")
        return 1
    verses_n = sum(t[0] for t in totals)
    true_n = sum(t[1] for t in totals)
    der_n = sum(t[2] for t in totals)
    print(
        f"\n  {'TOTAL':<24}{verses_n:>7,}{true_n:>9,}{der_n:>9,}{der_n - true_n:>+9,}"
        f"  {(der_n - true_n) / verses_n:+.2f}"
    )
    print(
        f"\n  Deriving the boundaries changes the variant columns this manuscript shows "
        f"against\n  an independent witness by {100 * (der_n - true_n) / true_n:+.1f}% "
        f"({(der_n - true_n) / verses_n:+.2f} columns per verse).\n"
        f"  The reference is the *other* Old Latin manuscript, never the Clementine the cuts\n"
        f"  were fitted to. Median true columns per verse across books: "
        f"{statistics.median(t[1] / t[0] for t in totals):.2f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
