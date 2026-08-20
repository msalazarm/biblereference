"""Does any *nomina sacra* contraction take a word the corpora actually use?

The expansion exists so a quotation can meet a manuscript transcription, where the scribe
wrote ``θ̅ς̅`` for θεός. This library holds printed critical editions, where an editor has
already expanded them -- so the contraction forms never appear as contractions, and are free
to collide with ordinary Greek. Eleven of them did, on 4,537 words. ``εσται`` alone took
ἔσται, "will be", 4,412 times and returned ἐσταύρωται, "has been crucified".

**Counted on bare corpus words, never against the lemma lexicon.** The lexicon's forms are
folded by this very rule, so it files ἔσται under ``εσταυρωται`` and answers "no collision"
for ``εσται`` -- an instrument folded by the thing it is measuring. That test was run, and
returned a clean zero for a table with a four-thousand-word fault in it.

A key that occurs is not automatically wrong -- in a manuscript corpus it may be the
contraction it claims. It is *undecided*, and this prints what a person needs to read.

    venv/bin/python tools/nomina_sacra_audit.py
"""

from __future__ import annotations

import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.emphasis import _NOMINA_SACRA
from biblereference.store import DataHome

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _bare(word: str) -> str:
    """Folded the way the fold folds, minus every rule under test."""
    decomposed = unicodedata.normalize("NFD", word)
    kept = "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()
    return kept.replace("ς", "σ")


def main() -> int:
    home = DataHome()
    db = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    greek = [
        corpus
        for corpus, language in db.execute("SELECT corpus, language FROM source_meta")
        if language == "grc"
    ]
    holes = ",".join("?" * len(greek))
    keys = set(_NOMINA_SACRA)
    seen: collections.Counter[str] = collections.Counter()
    where: dict[str, str] = {}
    for corpus, book, chapter, verse, text in db.execute(
        f"SELECT corpus, book, chapter, verse, text FROM verse WHERE corpus IN ({holes})",
        greek,
    ):
        for word in _WORD.findall(text):
            bare = _bare(word)
            if bare in keys:
                seen[bare] += 1
                where.setdefault(bare, f"{corpus} {book} {chapter}:{verse}")

    print(f"{len(greek)} Greek corpora, {len(_NOMINA_SACRA)} contractions\n")
    if not seen:
        print("No contraction occurs as a bare word in the corpora. Nothing to decide.")
        return 0
    print(f"{'contraction':<12}{'occurs':>8}  {'would become':<16}first seen")
    for key, count in seen.most_common():
        print(f"{key:<12}{count:>8}  {_NOMINA_SACRA[key]:<16}{where[key]}")
    print(
        f"\n{len(seen)} contraction(s) occur as bare words. Read each one in context: it is "
        f"either a genuine contraction this corpus preserves, or a real word the fold is "
        f"about to destroy. Do not guess from the count alone."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
