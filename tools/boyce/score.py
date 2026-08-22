"""Score Boyce's golden set against a sweep, counting what suppression cost us.

Forked from `churchfathers/tools/build_boyce_page.py`. The scoring rule is theirs
unchanged -- `parts`/`same` do interval overlap, and a match is credited when its target
*or any member of its family* meets one of the citation's targets. That rule was checked
against their file before forking and is not the defect.

What this adds is a third column. `boycesofar.md` reports found / gated / unseen; this
reports found / gated / **suppressed** / unseen, where *suppressed* means the matcher
generated a match meeting Boyce's target and :func:`_without_overlaps` deleted it before
anything downstream could see it. A citation in that column needs no new retrieval method.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

CHURCHFATHERS = Path("/home/marcollm/churchfathers")
GOLDEN = CHURCHFATHERS / "data" / "golden-boyce.json"
GATES = ((3, 0, 0, 35.0), (0, 6, 0, 25.0), (0, 0, 8, 40.0))


def parts(one: str) -> tuple[str, int, int]:
    book, _, rest = one.partition(" ")
    chapter, _, verses = rest.partition(":")
    low, _, high = verses.partition("-")
    start = int("".join(c for c in low if c.isdigit()) or 0)
    end = int("".join(c for c in high if c.isdigit()) or 0) or start
    return f"{book} {chapter}", start, end


def same(found: str, wanted: str) -> bool:
    try:
        a, a_low, a_high = parts(found)
        b, b_low, b_high = parts(wanted)
    except Exception:
        return False
    return a == b and a_low <= b_high and b_low <= a_high


def admitted(match: dict) -> bool:
    """Their `admits`: the gate applied to exact matches too, which `gate=` does not do."""
    axes = (int(match.get("run") or 0), int(match.get("lemma_run") or 0),
            int(match.get("chain") or 0), float(match.get("bits") or 0.0))
    if not any(axes):
        return True
    return any(all(need <= have for need, have in zip(gate, axes, strict=True) if need)
               for gate in GATES)


def address(match: dict) -> str:
    """Where this match says it is. `to_dict` calls it `passage`; churchfathers' sweep
    renames it `target` on the way out, so both spellings arrive here."""
    return match.get("target") or match["passage"]


def best_for(matches: list[dict], targets: list[str], *, alternates: bool = False) -> dict | None:
    best = None
    for match in matches:
        every = [address(match), *match.get("family", ())]
        if alternates:
            every.extend(match.get("alternates", ()) or ())
        if not any(same(one, want) for one in every for want in targets):
            continue
        if best is None or match["bits"] > best["bits"]:
            best = match
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", required=True, help="output of tools/boyce/sweep.py")
    parser.add_argument("--floor", default="", help="churchfathers' review/boyce-floor.json")
    parser.add_argument("--out", default="", help="write the scored rows as JSON")
    arguments = parser.parse_args()

    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    sweep = json.loads(Path(arguments.sweep).read_text(encoding="utf-8"))["sections"]
    floor = ({} if not arguments.floor else
             json.loads(Path(arguments.floor).read_text(encoding="utf-8"))["sections"])

    rows = []
    for one in gold["positives"]:
        if one.get("language", "grc") != "grc":
            continue
        found = suppressed = gated = None
        where = one["loci"][0]
        for locus in one["loci"]:
            section = sweep.get(f'{one["work"]}|{locus}', {})
            hit = best_for([m for m in section.get("kept", ()) if admitted(m)], one["targets"])
            if hit and (found is None or hit["bits"] > found["bits"]):
                found, where = hit, locus
            lost = best_for(section.get("dropped", ()), one["targets"])
            if lost and (suppressed is None or lost["bits"] > suppressed["bits"]):
                suppressed = lost
            seen = best_for(floor.get(f'{one["work"]}|{locus}', []), one["targets"])
            if seen and (gated is None or seen["bits"] > gated["bits"]):
                gated = seen
        status = ("found" if found else "suppressed" if suppressed
                  else "gated" if gated else "unseen")
        rows.append({**one, "locus": where, "status": status,
                     "match": found or suppressed or gated})

    tally = Counter(r["status"] for r in rows)
    print(f"  {len(rows)} Greek citations in the golden set")
    for name in ("found", "suppressed", "gated", "unseen"):
        print(f"    {name:<12} {tally[name]:>4}")
    print()
    by_grade: dict[str, Counter] = {}
    for row in rows:
        by_grade.setdefault(row["grade"], Counter())[row["status"]] += 1
    print(f"  {'grade':<10} {'found':>6} {'suppr':>6} {'gated':>6} {'unseen':>7}")
    for grade, counts in sorted(by_grade.items()):
        print(f"  {grade:<10} {counts['found']:>6} {counts['suppressed']:>6} "
              f"{counts['gated']:>6} {counts['unseen']:>7}")

    if arguments.out:
        Path(arguments.out).write_text(json.dumps({"rows": rows}, ensure_ascii=False),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
