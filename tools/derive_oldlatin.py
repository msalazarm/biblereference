"""Derive verse boundaries for the two Old Latin gospels Bianchini printed unnumbered.

Migne's PL 12 prints four manuscripts. Two carry Bianchini's verse numbers and are imported
from them. Two do not:

    Brixianus (f)      continuous prose, four gospels, no numbers anywhere
    Corbeiensis (ff2)  continuous prose for Matthew only; see oldlatin.SKIPPED for the rest

Their text is real and this library holds no other pre-Vulgate Latin, so the choice is
between deriving verse divisions and not holding them at all. This derives them, by monotone
alignment of the manuscript's word stream against the Clementine, and writes the cut points
to a data file so that the import itself does no guessing and the guess is inspectable in
version control.

**The derivation is measured against held-out truth, not against itself.** Scoring derived
boundaries by similarity to the Vulgate measures the objective the derivation maximised: it
returns a median 0.86 and 0.0% drift, which look excellent and mean nothing. The honest test
is to throw away Bianchini's numbers on Vercellensis and Veronensis, re-derive them by this
same procedure, and see how often it puts the boundary back where the editor put it. It is
run by ``--validate`` and its result is recorded in the output file.

Run:  venv/bin/python tools/derive_oldlatin.py --validate
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Final

from lxml import etree

from biblereference.audit import _Texts
from biblereference.corpora.oldlatin import _APPARATUS, _CODEX, _GOSPEL, read
from biblereference.corpora.tei import flatten
from biblereference.emphasis import fold
from biblereference.store import DataHome

#: Where the import reads the result back from.
OUT: Final = Path(__file__).resolve().parent.parent / "src/biblereference/data/oldlatin_bounds.json"

#: The manuscripts that need deriving, and the gospels of each that are continuous text
#: rather than apparatus.
DERIVE: Final = {"Brixianus": ("MAT", "MRK", "LUK", "JHN"), "Corbeiensis": ("MAT",)}


def _fold(word: str) -> str:
    """Latin spelling folded to what two editions can be expected to agree on.

    **The library's own fold has to run first, and the first version of this did not let
    it.** Stripping to ``[a-z]`` directly deletes the ligatures rather than expanding them:
    the Clementine writes *cælorum* and Migne writes *caelorum*, and ``re.sub`` turns the
    first into ``clorum`` and the second into ``celorum``, which cannot match. Every
    æ-bearing word in the Vulgate -- *caelum*, *quaerere*, *praedicare*, *Pharisaei* --
    was invisible to the alignment. ``emphasis.fold`` expands them, and its own comment
    says why it exists: "The Clementine writes flammæ, an anchor will not."
    """
    letters = re.sub(r"[^a-z]", "", fold(word, "la"))
    for source, target in (("ae", "e"), ("oe", "e"), ("j", "i"), ("v", "u"), ("y", "i")):
        letters = letters.replace(source, target)
    return letters.replace("h", "")


def streams(path: Path) -> dict[tuple[str, str], list[str]]:
    """The continuous, unnumbered manuscripts as one word list each.

    Apparatus sections are dropped by the same rule the import uses; without it the
    Vindobonensis collation that follows Corbeiensis in Luke and Mark is read as if it were
    Corbeiensis, which inflates it by 759 paragraphs of variant readings.
    """
    root = etree.parse(str(path)).getroot()
    book = codex = ""
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = element.tag.split("}")[-1]
        if name == "head":
            text = flatten(element)
            if _APPARATUS.search(text):
                codex = ""
                continue
            for word, code in _GOSPEL.items():
                if word in text.upper():
                    book = code
            found = _CODEX.search(text)
            if found:
                codex = found.group(1).title()
            continue
        if name == "p" and book and codex:
            out[(codex, book)].extend(flatten(element).split())
    return dict(out)


def clementine(texts: _Texts, book: str) -> list[tuple[tuple[int, int], list[str]]]:
    verses = []
    for chapter in range(1, 30):
        found = texts.chapter("latvuc", book, chapter)
        if not found:
            break
        verses.extend(((chapter, verse), found[verse].split()) for verse in sorted(found))
    return verses


def _project(blocks: list[difflib.Match], index: int) -> int:
    """A Vulgate word index carried across to the manuscript's stream, monotonically."""
    best = 0
    for block in blocks:
        if block.a <= index:
            best = block.b + min(index - block.a, block.size)
        else:
            break
    return best


def cuts(manuscript: list[str], vulgate: list[tuple[tuple[int, int], list[str]]]) -> dict[str, int]:
    """Where each Vulgate verse begins in the manuscript's word stream."""
    folded_ms = [_fold(word) for word in manuscript]
    folded_vg: list[str] = []
    starts: list[tuple[tuple[int, int], int]] = []
    for ref, words in vulgate:
        starts.append((ref, len(folded_vg)))
        folded_vg.extend(_fold(word) for word in words)
    blocks = difflib.SequenceMatcher(
        None, folded_vg, folded_ms, autojunk=False
    ).get_matching_blocks()
    return {f"{ref[0]}:{ref[1]}": _project(blocks, index) for ref, index in starts}


def validate(path: Path, texts: _Texts) -> dict[str, dict[str, float]]:
    """Re-derive the boundaries of the two numbered manuscripts and score the recovery.

    This is the only non-circular measurement available: Bianchini's numbers are independent
    of the alignment, so agreement with them is evidence and agreement with the Vulgate is
    not.
    """
    truth: dict[tuple[str, str], list[tuple[tuple[int, int], str]]] = defaultdict(list)
    for codex, ref, text in read(path):
        truth[(codex, ref.book)].append(((int(ref.chapter), ref.verse), text))

    scores: dict[str, dict[str, float]] = {}
    for (codex, book), rows in sorted(truth.items()):
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
        offsets = [
            abs(derived[f"{ref[0]}:{ref[1]}"] - position)
            for ref, position in actual
            if f"{ref[0]}:{ref[1]}" in derived
        ]
        offsets.sort()
        scores[f"{codex} {book}"] = {
            "verses": len(offsets),
            "exact": round(100 * sum(1 for o in offsets if o == 0) / len(offsets), 1),
            "within_2_words": round(100 * sum(1 for o in offsets if o <= 2) / len(offsets), 1),
            "p90_offset": offsets[int(len(offsets) * 0.9)],
        }
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true", help="run the held-out recovery test")
    args = parser.parse_args()

    home = DataHome()
    archive = home.latest_archive("oldlatin")
    if archive is None:
        raise SystemExit("oldlatin has not been fetched")
    path = archive / "cc-6898.xml"
    texts = _Texts(home)

    found = streams(path)
    bounds: dict[str, dict[str, object]] = {}
    for codex, books in DERIVE.items():
        for book in books:
            stream = found.get((codex, book))
            if not stream:
                continue
            digest = hashlib.sha256(" ".join(stream).encode()).hexdigest()[:16]
            bounds.setdefault(codex, {})[book] = {
                "words": len(stream),
                # The import refuses to apply offsets to a stream that is not the one they
                # were measured on. Without this a parser change silently shifts every verse.
                "digest": digest,
                "cuts": cuts(stream, clementine(texts, book)),
            }
            cuts_made = len(bounds[codex][book]["cuts"])  # type: ignore[index,call-overload]
            print(f"{codex:<14}{book}  {len(stream):>6,} words  {cuts_made:>5} cuts")

    payload: dict[str, object] = {
        "note": (
            "Verse divisions DERIVED by monotone alignment against the Clementine Vulgate, "
            "not printed by Bianchini. See tools/derive_oldlatin.py."
        ),
        "bounds": bounds,
    }
    if args.validate:
        payload["recovery"] = validate(path, texts)
        print("\nheld-out recovery of Bianchini's own numbering:")
        for name, score in payload["recovery"].items():
            print(
                f"  {name:<20} n={score['verses']:<5} exact {score['exact']:>5}%  "
                f"within 2 words {score['within_2_words']:>5}%  p90 {score['p90_offset']}"
            )
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
