"""Price our spelling tiers against REAL scribal variation.

churchfathers transcribe each codex separately, so the differences between two of their
witnesses to one work are what scribes actually wrote -- not an editor's apparatus and not
synthetic noise. That is the sample the itacised, recovery and nomen-sacrum tiers were
always priced without.

Method: for every locus two manuscripts of one work share, align their token streams and
take the 1:1 substitutions. Each is one real variant. Then ask what bridges it.
"""

import collections
import difflib
import pathlib
import re
import sqlite3
import unicodedata

from biblereference.emphasis import fold

db = pathlib.Path.home() / ".local/share/churchfathers/db/corpus.sqlite"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

works = [
    r[0]
    for r in c.execute("""SELECT work FROM witness
  WHERE source LIKE '%/pta/%' AND language='grc' AND kind='manuscript'
    AND id NOT LIKE '%+divided' AND (redundant_of IS NULL OR redundant_of='')
  GROUP BY work HAVING COUNT(DISTINCT id)>1""")
]

TOK = re.compile(r"[^\W\d_]+", re.U)
pairs = collections.Counter()
loci_used = 0
for work in works:
    ws = [
        r[0]
        for r in c.execute(
            """SELECT id FROM witness WHERE work=? AND kind='manuscript'
        AND source LIKE '%/pta/%' AND id NOT LIKE '%+divided'
        AND (redundant_of IS NULL OR redundant_of='') ORDER BY id""",
            (work,),
        )
    ]
    if len(ws) < 2:
        continue
    texts = collections.defaultdict(dict)
    marks = ",".join("?" * len(ws))
    for wid, locus, text in c.execute(
        f"SELECT witness, locus, text FROM passage WHERE witness IN ({marks})", ws
    ):
        if text:
            texts[locus][wid] = text
    for byw in texts.values():
        if len(byw) < 2:
            continue
        loci_used += 1
        base = sorted(byw)[0]
        a = TOK.findall(byw[base])
        for other in sorted(byw)[1:]:
            b = TOK.findall(byw[other])
            if not a or not b:
                continue
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, a, b, autojunk=False
            ).get_opcodes():
                if tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
                    x, y = a[i1], b[j1]
                    if x != y:
                        pairs[(x, y)] += 1

print(
    f"works {len(works)}, shared loci {loci_used:,}, distinct 1:1 substitutions {len(pairs):,}, "
    f"occurrences {sum(pairs.values()):,}\n"
)

bridged = unbridged = 0
miss = collections.Counter()
for (x, y), n in pairs.items():
    if fold(x, "grc") == fold(y, "grc"):
        bridged += n
    else:
        unbridged += n
        miss[(x, y)] += n
tot = bridged + unbridged
print(f"our fold already bridges  {bridged:>7,} of {tot:,}  ({100 * bridged / tot:.1f}%)")
print(f"still different after fold {unbridged:>7,}              ({100 * unbridged / tot:.1f}%)\n")
print("the 30 most frequent variants our fold does NOT bridge:")
for (x, y), n in miss.most_common(30):
    fx, fy = fold(x, "grc"), fold(y, "grc")
    print(f"   {n:>5}x  {x:<16} / {y:<16}   folded: {fx:<14} / {fy}")

# ---- classify the residue -------------------------------------------------------------

IOTA = {
    "ͅ": "",
    "ῳ": "ω",
    "ῷ": "ω",
    "ῲ": "ω",
    "ᾳ": "α",
    "ᾷ": "α",
    "ᾲ": "α",
    "ῃ": "η",
    "ῇ": "η",
    "ῂ": "η",
}


def strip_iota(w):
    w = unicodedata.normalize("NFD", w)
    w = "".join(ch for ch in w if ch != "ͅ")
    w = unicodedata.normalize("NFC", w)
    return fold(w, "grc").rstrip("ι") if fold(w, "grc").endswith("ι") else fold(w, "grc")


def nu_moveable(a, b):
    return (a.endswith("ν") and a[:-1] == b) or (b.endswith("ν") and b[:-1] == a)


def sigma_final(a, b):
    return (a.endswith("σ") and a[:-1] == b) or (b.endswith("σ") and b[:-1] == a)


cls = collections.Counter()
examples = collections.defaultdict(list)
for (x, y), n in pairs.items():
    fx, fy = fold(x, "grc"), fold(y, "grc")
    if fx == fy:
        continue
    if strip_iota(x) == strip_iota(y):
        k = "iota adscript / subscript"
    elif nu_moveable(fx, fy):
        k = "movable nu"
    elif sigma_final(fx, fy):
        k = "final sigma (ουτως/ουτω)"
    else:
        k = "genuine variant or unknown"
    cls[k] += n
    if len(examples[k]) < 3:
        examples[k].append(f"{x}/{y}")
print("\n--- what the unbridged 36.5% actually is ---")
for k, n in cls.most_common():
    print(
        f"  {k:<28} {n:>6,}  ({100 * n / unbridged:>4.1f}% of residue,"
        f" {100 * n / tot:>4.1f}% of all)   e.g. {', '.join(examples[k])}"
    )
gain = cls["iota adscript / subscript"] + cls["movable nu"] + cls["final sigma (ουτως/ουτω)"]
print(
    f"\n  folding those three conventions would take us from"
    f" {100 * bridged / tot:.1f}% to {100 * (bridged + gain) / tot:.1f}%"
)
