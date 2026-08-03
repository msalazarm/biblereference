"""Generate the vendored table of redistributable English translations from eBible's
translations.csv. Run again to refresh; the output is committed so that Source objects
exist without the network."""

from __future__ import annotations

import csv
import json
import sys

# Already fetched under their own source ids; not duplicated in the bulk set.
ALREADY = {"eng-web-c": "webc", "engDRA": "dra"}

# Septuagint-derived Old Testaments: numbered like the Greek, not like the English.
# Verified by inspection rather than assumed -- each of these has 151 psalms and puts
# "The Lord tends me as a shepherd" at Psalm 22, where the English tradition has 150 and
# puts it at 23. engasvbt was a candidate and is *not* one of them: it carries the ASV's
# Old Testament, 150 psalms with the shepherd at 23, and only its deuterocanon is Greek.
LXX_BASED = {"eng-Brenton", "englxxup", "eng-lxx2012", "eng-uk-lxx2012"}

# English translations that follow the *Hebrew* verse divisions rather than the English
# tradition's. Both are Jewish texts, and both were found by scoring the parsed structure
# against every system rather than by assumption: each ends 99% of its chapters where the
# Masoretic numbering says and only 88% where the English does. The tell is Deuteronomy,
# which the Hebrew divides at 28:69 where the English begins chapter 29, and Numbers 25:19
# against the English 25:18.
#
# The Jewish Publication Society's 1917 translation is *not* among them -- it scores 100%
# against the English tradition -- which is why this is a checked list and not a guess
# about which communities number how.
HEBREW_NUMBERED = {"engojb", "engoke"}

# Where the derived id would be unhelpful or would collide.
ID_OVERRIDES = {
    "eng-uk-lxx2012": "lxx2012uk",
    "eng-kjv": "kjv",
    "eng-kjv2006": "kjv2006",
}


def corpus_id(translation_id: str) -> str:
    if translation_id in ID_OVERRIDES:
        return ID_OVERRIDES[translation_id]
    stem = translation_id
    for prefix in ("eng-", "eng"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return stem.lower().replace("-", "")


def main(path: str, out: str) -> None:
    with open(path, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    english = [
        r
        for r in rows
        if r["languageCode"].startswith("eng")
        and r["Redistributable"].strip().lower() in ("true", "yes", "1")
    ]

    entries = []
    seen: dict[str, str] = {}
    for r in sorted(english, key=lambda r: r["translationId"]):
        tid = r["translationId"]
        if tid in ALREADY:
            continue
        cid = corpus_id(tid)
        if cid in seen:
            raise SystemExit(f"id collision: {tid} and {seen[cid]} both -> {cid}")
        seen[cid] = tid
        copyright_ = (r["Copyright"] or "").strip()
        entries.append(
            {
                "id": cid,
                "ebible_id": tid,
                # eBible carries both a shortTitle and a title, and the title is the better
                # of the two for a label that will be printed inside a citation: it is the
                # publisher's own full name for the edition, and it is more informative
                # where the two differ -- "Revised Version with Apocrypha (1895)" against
                # "Revised Version", "Berean Standard Bible" against the odd "English
                # Berean Standard Bible".
                "label": r["title"].strip(),
                "title": r["title"].strip(),
                "copyright": copyright_,
                "public_domain": copyright_.lower().startswith("public domain"),
                "versification": (
                    "lxx" if tid in LXX_BASED else "org" if tid in HEBREW_NUMBERED else "eng"
                ),
                "declared": {
                    part: {
                        "books": int(r[f"{part}books"] or 0),
                        "chapters": int(r[f"{part}chapters"] or 0),
                        "verses": int(r[f"{part}verses"] or 0),
                    }
                    for part in ("OT", "NT", "DC")
                },
            }
        )

    with open(out, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2, ensure_ascii=False)
    print(f"{len(entries)} translations -> {out}")
    pd = sum(1 for e in entries if e["public_domain"])
    print(f"  {pd} public domain, {len(entries) - pd} redistributable by permission")
    for e in entries:
        if e["versification"] != "eng":
            print(f"  {e['id']:12} vrs={e['versification']}  {e['label'][:50]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
