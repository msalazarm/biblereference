"""Build the scripture-side n-gram model, in the same artifact schema as the consumer's.

Stratum R's LLR scan needs two models: the father's own (the consumer's build, from their
corpus) and scripture's (this one, from the held corpora). Same schema — ``meta``,
``totals``, ``ngram``, ``works`` — same fold, same space-joined keys, so the one reader in
`biblereference.ngram_models` serves both files and neither side re-normalises.

``author`` is the corpus id here, with ``''`` the pool of every corpus in the language —
the same convention as their shelves. N-grams are counted within verses, never across a
verse boundary: the verse is the unit scripture is quoted in, and a 5-gram bridging Malachi
into Matthew is not a phrase anybody said.

Writes a NEW standalone file; reads corpus.sqlite read-only. Safe during a sweep freeze.

    nice -n 19 venv/bin/python tools/scripture_ngrams.py --language grc
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biblereference.emphasis import FOLD_VERSION, fold
from biblereference.store import DataHome

ORDERS = (1, 2, 3, 4, 5)
#: Orders 3-5 pruned below this, exactly as the consumer's build: unpruned high-order
#: counts are a file nobody wants, and a count of 0 there means "at most 1", documented
#: on the reader.
MIN_COUNT = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="grc", help="which language's corpora to pool")
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="artifact path (default: <data home>/db/ngrams-scripture-<language>.sqlite3)",
    )
    args = parser.parse_args()

    home = DataHome()
    out = Path(args.out) if args.out else home.root / "db" / (
        f"ngrams-scripture-{args.language}.sqlite3"
    )
    corpus_db = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    corpora = [
        str(row[0])
        for row in corpus_db.execute(
            "SELECT corpus FROM source_meta WHERE language = ? ORDER BY corpus",
            (args.language,),
        )
    ]
    if not corpora:
        print(f"no corpora in language {args.language!r}", file=sys.stderr)
        return 1
    print(f"{len(corpora)} corpora: {', '.join(corpora)}")

    out.unlink(missing_ok=True)
    model = sqlite3.connect(out)
    model.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE totals (author TEXT, "order" INTEGER, tokens INTEGER,
                             PRIMARY KEY (author, "order"));
        CREATE TABLE ngram (author TEXT, "order" INTEGER, fold TEXT, count INTEGER,
                            PRIMARY KEY (author, "order", fold)) WITHOUT ROWID;
        CREATE TABLE works (author TEXT, work TEXT, witness TEXT, words INTEGER);
        """
    )

    streams: dict[str, list[list[str]]] = {}
    words_total = 0
    for corpus in corpora:
        verses = [
            fold(str(text), args.language).split()
            for (text,) in corpus_db.execute(
                "SELECT text FROM verse WHERE corpus = ?", (corpus,)
            )
        ]
        verses = [tokens for tokens in verses if tokens]
        streams[corpus] = verses
        n = sum(len(v) for v in verses)
        words_total += n
        model.execute(
            "INSERT INTO works (author, work, witness, words) VALUES (?, ?, ?, ?)",
            (corpus, corpus, corpus, n),
        )

    # One order at a time, counted then written then dropped, so the peak memory is one
    # order's table rather than five.
    for order in ORDERS:
        pooled: dict[str, int] = {}
        for corpus, verses in streams.items():
            counts: dict[str, int] = {}
            positions = 0
            for tokens in verses:
                for start in range(0, len(tokens) - order + 1):
                    gram = " ".join(tokens[start : start + order])
                    counts[gram] = counts.get(gram, 0) + 1
                    positions += 1
            model.execute(
                'INSERT INTO totals (author, "order", tokens) VALUES (?, ?, ?)',
                (corpus, order, positions),
            )
            floor = MIN_COUNT if order >= 3 else 1
            model.executemany(
                'INSERT INTO ngram (author, "order", fold, count) VALUES (?, ?, ?, ?)',
                ((corpus, order, gram, n) for gram, n in counts.items() if n >= floor),
            )
            for gram, n in counts.items():
                pooled[gram] = pooled.get(gram, 0) + n
        model.execute(
            'INSERT INTO totals (author, "order", tokens) VALUES (?, ?, ?)',
            ("", order, sum(pooled.values())),
        )
        floor = MIN_COUNT if order >= 3 else 1
        model.executemany(
            'INSERT INTO ngram (author, "order", fold, count) VALUES (?, ?, ?, ?)',
            (("", order, gram, n) for gram, n in pooled.items() if n >= floor),
        )
        model.commit()
        print(f"order {order}: {len(pooled):,} pooled grams")

    digest = hashlib.sha256(",".join(corpora).encode()).hexdigest()[:12]
    meta = {
        "language": args.language,
        "corpus_language": args.language,
        "side": "scripture",
        "orders": ",".join(str(n) for n in ORDERS),
        "min_count": str(MIN_COUNT),
        "fold": "biblereference.emphasis.fold, surface forms, space-joined",
        "fold_version": str(FOLD_VERSION),
        "corpora": ",".join(corpora),
        "corpora_digest": digest,
        "words": str(words_total),
        "unit": "verse -- n-grams never cross a verse boundary",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    model.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
    model.commit()
    model.close()
    print(f"\n{words_total:,} words of {args.language} scripture into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
