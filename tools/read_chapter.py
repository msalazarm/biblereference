"""One chapter across every witness that carries it, side by side.

The instrument that settles things. Both the alignment and the model produce *candidates* --
a run of verses where something looks displaced -- and neither can tell a real fault from a
loose translation of repetitive material. Only reading can. Greek Exodus 25 was flagged at
twenty-two verses by a model and is mapped perfectly correctly; Brenton's "ark of testimony
of incorruptible wood" is the World English Bible's "ark of acacia wood", verse for verse
down the chapter, and five minutes of this would have said so.

    tools/read_chapter.py JDT 16                    # every corpus that carries it
    tools/read_chapter.py MAT 23 --corpus n1904 web latvuc
    tools/read_chapter.py EXO 39 --range 18-30 --width 120
    tools/read_chapter.py JDT 16 --from nvl         # add what the mapping claims

``--from`` is the one worth remembering: it prints, beside each source verse, the verse the
mapping currently sends it to, so a displacement shows up as text that does not match rather
than as a number to work out.
"""

from __future__ import annotations

import argparse

from biblereference.audit import _Texts
from biblereference.canon import book_title, resolve_book
from biblereference.refs import VerseRef
from biblereference.store import DataHome, SqliteCorpus
from biblereference.versification import PIVOT, Versification, VersificationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one chapter across the corpora.")
    parser.add_argument("book", help="USFM code or a name, e.g. JDT or Judith")
    parser.add_argument("chapter", type=int)
    parser.add_argument("--corpus", nargs="*", help="only these, in this order")
    parser.add_argument("--range", help="verses, as 4-12")
    parser.add_argument("--width", type=int, default=96, help="characters per line")
    parser.add_argument(
        "--from",
        dest="source",
        help="a versification: also print where its mapping sends each verse, which is what "
        "turns a suspicion into a reading",
    )
    args = parser.parse_args()

    home = DataHome()
    book = resolve_book(args.book)
    low, _, high = (args.range or "").partition("-")
    first = int(low) if low else 0
    last = int(high) if high else 10_000

    texts = _Texts(home)
    try:
        held = SqliteCorpus.load_all(home)
        wanted = args.corpus or [
            corpus.id
            for corpus in sorted(held.values(), key=lambda c: (c.versification, c.language, c.id))
            if texts.chapter(corpus.id, book, args.chapter)
        ]
        if not wanted:
            print(f"no corpus carries {book_title(book)} {args.chapter}")
            return 1

        chapters = {corpus: texts.chapter(corpus, book, args.chapter) for corpus in wanted}
        label = {
            corpus: f"{corpus} ({held[corpus].versification})"
            for corpus in wanted
            if corpus in held
        }
        width = max(len(name) for name in label.values()) if label else 12
        verses = sorted({verse for rows in chapters.values() for verse in rows})
        print(f"{book_title(book)} {args.chapter} -- {len(wanted)} corpora\n")

        vrs = Versification.load() if args.source else None
        for verse in verses:
            if not first <= verse <= last:
                continue
            print(f"  verse {verse}")
            for corpus in wanted:
                text = chapters[corpus].get(verse)
                if text is None:
                    continue
                print(f"    {label.get(corpus, corpus):{width}}  {text[: args.width]}")
            if vrs is not None:
                _say_mapping(vrs, texts, book, args.chapter, verse, args.source, args.width)
            print()
    finally:
        texts.close()
    return 0


def _say_mapping(
    vrs: Versification, texts: _Texts, book: str, chapter: int, verse: int, source: str, width: int
) -> None:
    """Where the mapping sends this verse, and what stands there."""
    try:
        targets = vrs.convert_all(VerseRef(book, chapter, verse, vrs=source), PIVOT)
    except VersificationError as exc:
        print(f"    -> {source} refuses: {exc}"[: width + 20])
        return
    for target in targets:
        for corpus in ("wlc", "n1904", "web", "brenton"):
            text = texts.verse(corpus, target)
            if text:
                print(f"    -> maps to {target} · {corpus}: {text[:width]}")
                break


if __name__ == "__main__":
    raise SystemExit(main())
