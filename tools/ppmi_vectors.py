"""Build the PPMI lemma vectors from the pinned Diorisis snapshot.

Two passes over the 820 lemmatised works, no randomness anywhere, so the artifact is a
pure function of the snapshot and this file (the digest test holds the promise):

1. **Count lemmas.** Content lemmas only (noun, verb, adjective, adverb, proper) --
   function words keep every company and would drown the signal PPMI exists to find.
   The vocabulary is lemmas seen at least ``--least`` times (default 10).
2. **Count company.** Symmetric co-occurrence in a ±5 content-word window, sentence
   bounded (the corpus's own sentence elements). Then PPMI --
   ``max(0, log2(p(a,b) / p(a)p(b)))`` -- and each row pruned to its ``--dims``
   strongest dimensions, which caps the artifact and denoises the tail.

Lemmas are folded with the library's own fold, so the vectors answer in the same
lemma-space `allusions()` already speaks.

    venv/bin/python tools/ppmi_vectors.py --save ~/.local/share/biblereference/db/ppmi-grc.sqlite3
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.emphasis import FOLD_VERSION, fold
from biblereference.ppmi import DIORISIS
from biblereference.store import DataHome

_CONTENT = frozenset({"noun", "verb", "adjective", "adverb", "proper"})
_SENTENCE_RE = re.compile(r"<sentence [^>]*>(.*?)</sentence>", re.S)
_LEMMA_RE = re.compile(r'<lemma [^>]*entry="([^"]+)" POS="([^"]+)"')
_WINDOW = 5


def sentences(archive: Path) -> list[list[str]]:
    """Every sentence as its folded content lemmas, in the zip's own sorted order."""
    out: list[list[str]] = []
    with zipfile.ZipFile(archive / "Diorisis.zip") as bundle:
        for name in sorted(bundle.namelist()):
            if not name.endswith(".xml"):
                continue
            body = bundle.read(name).decode("utf-8", "replace")
            for sentence in _SENTENCE_RE.finditer(body):
                lemmas = [
                    folded
                    for entry, pos in _LEMMA_RE.findall(sentence.group(1))
                    if pos in _CONTENT and (folded := fold(entry, "grc"))
                ]
                if len(lemmas) > 1:
                    out.append(lemmas)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", required=True, metavar="PATH")
    parser.add_argument("--least", type=int, default=10, help="minimum lemma count")
    parser.add_argument("--dims", type=int, default=200, help="dimensions kept per row")
    args = parser.parse_args()

    home = DataHome()
    archives = sorted((home.sources / DIORISIS.id).glob("*"))
    if not archives:
        print(f"no archive for {DIORISIS.id}; fetch it first", file=sys.stderr)
        return 1

    print("pass 1: lemma counts")
    stream = sentences(archives[-1])
    counts = Counter(lemma for sentence in stream for lemma in sentence)
    vocabulary = sorted(lemma for lemma, n in counts.items() if n >= args.least)
    index = {lemma: at for at, lemma in enumerate(vocabulary)}
    print(f"  {sum(counts.values()):,} content tokens, {len(vocabulary):,} lemmas kept")

    print("pass 2: co-occurrence")
    pairs: Counter[int] = Counter()
    margin = [0] * len(vocabulary)
    total = 0
    width = len(vocabulary)
    for sentence in stream:
        ids = [index[lemma] for lemma in sentence if lemma in index]
        for at, a in enumerate(ids):
            for b in ids[at + 1 : at + 1 + _WINDOW]:
                pairs[min(a, b) * width + max(a, b)] += 1
                margin[a] += 1
                margin[b] += 1
                total += 1
    print(f"  {total:,} pairs, {len(pairs):,} distinct")

    print("PPMI + prune")
    import math

    rows: dict[int, list[tuple[float, int]]] = {}
    for key, n in pairs.items():
        a, b = divmod(key, width)
        pmi = math.log2(n * 2 * total / (margin[a] * margin[b]))
        if pmi <= 0:
            continue
        rows.setdefault(a, []).append((pmi, b))
        rows.setdefault(b, []).append((pmi, a))
    target = Path(args.save)
    target.unlink(missing_ok=True)
    db = sqlite3.connect(target)
    db.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "CREATE TABLE vector (lemma TEXT, dim INTEGER, weight REAL);"
        "CREATE INDEX vector_lemma ON vector (lemma);"
        "CREATE TABLE dimension (dim INTEGER PRIMARY KEY, lemma TEXT);"
    )
    kept = 0
    for a in sorted(rows):
        strongest = sorted(rows[a], key=lambda pair: (-pair[0], pair[1]))[: args.dims]
        db.executemany(
            "INSERT INTO vector (lemma, dim, weight) VALUES (?, ?, ?)",
            [(vocabulary[a], dim, round(weight, 4)) for weight, dim in strongest],
        )
        kept += len(strongest)
    db.executemany(
        "INSERT INTO dimension (dim, lemma) VALUES (?, ?)", list(enumerate(vocabulary))
    )
    db.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        {
            "source": DIORISIS.id,
            "archive": archives[-1].name,
            "language": "grc",
            "fold_version": str(FOLD_VERSION),
            "least": str(args.least),
            "dims": str(args.dims),
            "window": str(_WINDOW),
            "vocabulary": str(len(vocabulary)),
            "weights": str(kept),
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        }.items(),
    )
    db.commit()
    db.close()
    print(f"artifact written to {target} ({kept:,} weights over {len(vocabulary):,} lemmas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
