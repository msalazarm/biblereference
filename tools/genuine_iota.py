"""Which ``-ωι``/``-ηι`` words end in a full vowel rather than an iota adscript.

The fold folds ``τωι`` to ``τω`` because a dative is written three ways and the subscript
form already folds that way. Some words end in ``-ωι`` because the iota is a vowel in its
own right, and folding those is a corruption -- twice over where the shortened form is
itself a word (``νηι`` -> ``νη``).

Greek marks the separate iota with a diaeresis, so this counts every ``-ωι``/``-ηι`` type
in the Greek corpora against the spellings that carry one on the final iota. A type that is
ever marked is genuine. A type never marked is *reported, not decided* -- read it in context
and add it by hand, which is how the four unmarked ones in `_GENUINE_IOTA` were settled.

    venv/bin/python tools/genuine_iota.py
"""

from __future__ import annotations

import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.emphasis import _ADSCRIPT_AFTER, _GENUINE_IOTA
from biblereference.store import DataHome

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_DIAERESIS = "̈"


def _bare(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def _marked_on_final_iota(word: str) -> bool:
    """Does a diaeresis sit on this word's last iota, rather than anywhere in it?"""
    decomposed = unicodedata.normalize("NFD", word)
    iotas = [i for i, c in enumerate(decomposed) if c.lower() == "ι"]
    if not iotas:
        return False
    end = iotas[-1] + 1
    marks = ""
    while end < len(decomposed) and unicodedata.category(decomposed[end]) == "Mn":
        marks += decomposed[end]
        end += 1
    return _DIAERESIS in marks


def main() -> int:
    home = DataHome()
    db = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    greek = [
        corpus
        for corpus, language in db.execute("SELECT corpus, language FROM source_meta")
        if language == "grc"
    ]
    holes = ",".join("?" * len(greek))
    vocabulary: collections.Counter[str] = collections.Counter()
    fires: collections.Counter[str] = collections.Counter()
    marked: collections.Counter[str] = collections.Counter()
    for (text,) in db.execute(f"SELECT text FROM verse WHERE corpus IN ({holes})", greek):
        for word in _WORD.findall(text):
            bare = _bare(word)
            vocabulary[bare] += 1
            if len(bare) >= 3 and bare.endswith("ι") and bare[-2] in _ADSCRIPT_AFTER:
                fires[bare] += 1
                if _marked_on_final_iota(word):
                    marked[bare] += 1

    print(f"{len(greek)} Greek corpora, {sum(vocabulary.values()):,} word tokens\n")
    print(f"{'type':<12}{'tokens':>8}{'marked':>8}{'folds to':>12}{'collides':>10}  verdict")
    unlisted = []
    for bare, count in fires.most_common():
        shortened = bare[:-1]
        collides = vocabulary.get(shortened, 0)
        if bare in _GENUINE_IOTA:
            verdict = "listed genuine"
        elif marked[bare]:
            verdict = "GENUINE, NOT LISTED -- add it"
            unlisted.append(bare)
        else:
            verdict = "unmarked -- read it in context"
            unlisted.append(bare)
        print(
            f"{bare:<12}{count:>8}{marked[bare]:>8}{shortened:>12}{(collides or ''):>10}  {verdict}"
        )
    print(f"\n{len(_GENUINE_IOTA)} listed; {len(unlisted)} want a decision")
    return 1 if unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
