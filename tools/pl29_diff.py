"""How far Migne's PL 29 gospels stand from the Clementine we already hold.

The handover's own advice for §14 and §19 is "worth a diff rather than an import", and the
file bears that out: PL 29 marks chapters (Cap. I-XXVIII) and no verses at all -- the Roman
numerals beside them are Migne's column and line, not scripture. So this measures the two
prints against each other and lets the result decide whether a second Vulgate is worth
holding.
"""

import difflib
import re
from pathlib import Path

from lxml import etree

from biblereference.audit import _Texts
from biblereference.emphasis import fold as _libfold
from biblereference.store import DataHome

S = Path.home() / ".local/share/biblereference/sources-unregistered/pl29"
# Migne separates the chapter numeral from its column reference with a period in most
# places and a comma in six -- `[ Cap. XXIII, CCXXVII, 10.]`. Requiring the period lost
# three chapters of Matthew, one of Mark and two of Luke, each silently merged into the
# one before: Mark 13 came out with 1,655 words against the Clementine's 544.
CAP = re.compile(r"\[\s*Cap\.\s+([IVXLC]+)\s*[.,]", re.I)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman(text):
    total = 0
    for i, ch in enumerate(text.upper()):
        v = ROMAN[ch]
        nxt = ROMAN[text.upper()[i + 1]] if i + 1 < len(text) else 0
        total += -v if v < nxt else v
    return total


def fold(word):
    # emphasis.fold FIRST: the Clementine writes cælorum and Migne caelorum, and stripping
    # to [a-z] deletes the ligature instead of expanding it -- clorum vs celorum, never a
    # match. That alone cost 4 points of apparent agreement.
    w = re.sub(r"[^a-z]", "", _libfold(word, "la"))
    for a, b in (("ae", "e"), ("oe", "e"), ("j", "i"), ("v", "u"), ("y", "i")):
        w = w.replace(a, b)
    return w.replace("h", "")


def chapters(path):
    """PL 29 split on its own Cap. markers; the column marks are stripped as apparatus."""
    root = etree.parse(str(path)).getroot()
    body = []
    for e in root.iter():
        if isinstance(e.tag, str) and e.tag.split("}")[-1] == "p":
            body.append(" ".join("".join(e.itertext()).split()))
    text = " ".join(body)
    cuts = [(roman(m.group(1)), m.start()) for m in CAP.finditer(text)]
    out = {}
    for i, (num, start) in enumerate(cuts):
        end = cuts[i + 1][1] if i + 1 < len(cuts) else len(text)
        chunk = re.sub(r"\[[^\]]*\]", " ", text[start:end])
        out[num] = [fold(w) for w in chunk.split() if fold(w)]
    return out


t = _Texts(DataHome())
print(f"{'book':<5}{'ch':>4}{'PL29':>8}{'Clem':>8}{'match':>8}   ")
grand_m = grand_t = 0
rows = []
for bk in ("MAT", "MRK", "LUK", "JHN"):
    pl = chapters(S / f"pl29-{bk}.xml")
    for ch in sorted(pl):
        verses = t.chapter("latvuc", bk, ch)
        if not verses:
            continue
        clem = [fold(w) for v in sorted(verses) for w in verses[v].split() if fold(w)]
        sm = difflib.SequenceMatcher(None, clem, pl[ch], autojunk=False)
        m = sum(b.size for b in sm.get_matching_blocks())
        rows.append((bk, ch, len(pl[ch]), len(clem), m))
        grand_m += m
        grand_t += len(clem)
for bk in ("MAT", "MRK", "LUK", "JHN"):
    sub = [r for r in rows if r[0] == bk]
    tot_m = sum(r[4] for r in sub)
    tot_c = sum(r[3] for r in sub)
    tot_p = sum(r[2] for r in sub)
    print(f"{bk:<5}{len(sub):>4}{tot_p:>8}{tot_c:>8}{100 * tot_m / tot_c:>7.1f}%")
    worst = sorted(sub, key=lambda r: r[4] / max(r[3], 1))[:3]
    for w in worst:
        print(
            f"      lowest ch {w[1]:<3} PL29 {w[2]:>5} Clem {w[3]:>5}"
            f" match {100 * w[4] / max(w[3], 1):>5.1f}%"
        )
print(
    f"\nOVERALL  {100 * grand_m / grand_t:.1f}% of the Clementine's words matched,"
    f" {grand_t:,} words compared"
)
