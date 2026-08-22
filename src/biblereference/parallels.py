"""The Bible's internal parallels, verified verbally and held as an index.

Scripture repeats itself, and the largest class of "error" the consumer's hand-read
verdicts found — 34 of 102 — was the scanner being right in a way the scoring called
wrong: it names Acts 8:32 where the scholar names Isaiah 53, and *both are the same
words*, because Acts is quoting Isaiah. A doxology matches whichever epistle happens to
end with it. Psalm 14 and Psalm 53 are one poem printed twice. Naming one member and
scoring the rest as misses fabricates a precision the words do not carry.

The seed is OpenBible.info's cross-reference list (~345k verse pairs, CC BY, built on the
public-domain Treasury of Scripture Knowledge). A cross-reference is a *topical* link, and
only verbal parallels belong in this index — so every pair is verified with the library's
own :func:`~biblereference.search.lemma_chain`, in Greek, against the texts actually held:
the New Testament from Nestle 1904, the Old from Rahlfs' Septuagint, which is what makes an
OT↔NT pair comparable at all. A pair that cannot clear a conservative gate against itself
is dropped, and the axes of every kept pair are stored so a stricter consumer can re-gate
without rebuilding.

Coordinates in the table are the numbering the Greek is held in — ``org`` for the New
Testament, ``lxx`` for the Old — converted from the seed list's English numbering at build
time, which is why Psalm 121:2 is stored as Psalm 120:2. A family read off this table
speaks the same coordinates every Greek match already speaks.
"""

from __future__ import annotations

import sqlite3
import zipfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .canon import AmbiguousBookError, UnknownBookError, resolve_book
from .emphasis import FOLD_VERSION
from .licences import get
from .refs import VerseRange, VerseRef
from .sources import BuiltCorpus, RemoteFile, Source
from .store import DataHome
from .versification import Versification, VersificationError

__all__ = [
    "BITS_FLOOR",
    "CHAIN_FLOOR",
    "SOURCE",
    "Parallels",
    "build_parallels",
    "parallels_fold",
]

#: What a pair must chain against itself to count as a *verbal* parallel. Conservative on
#: purpose: the index exists to stop true findings being scored as misses, and a topical
#: link admitted here would misname findings instead. Both floors must hold — this is an
#: index build, not a match gate, and the union semantics of `Gate` would be looser than
#: either number reads.
CHAIN_FLOOR: Final = 4
BITS_FLOOR: Final = 25.0

#: The two Greek texts every pair is verified against: all 27 NT books, all of the LXX
#: including the deuterocanon, so no pair fails for want of a text.
_NT: Final = "n1904"
_OT: Final = "rahlfs"


def _refuse(archive: Path) -> list[BuiltCorpus]:
    raise RuntimeError(
        "cross-references are an index, not a corpus; build them with `biblereference parallels`"
    )


SOURCE: Final = Source(
    id="openbible-parallels",
    label="OpenBible.info cross references (Treasury of Scripture Knowledge lineage)",
    homepage="https://www.openbible.info/labs/cross-references/",
    license='CC BY. The file\'s own header: "www.openbible.info CC-BY".',
    terms=get("cc-by-4.0"),
    attribution="Cross-reference data from OpenBible.info, used under CC BY.",
    files=(
        RemoteFile(
            url="https://a.openbible.info/data/cross-references.zip",
            name="cross-references.zip",
        ),
    ),
    build=_refuse,
)


@dataclass(frozen=True, slots=True)
class ParallelsResult:
    pairs: int
    """Rows in the seed list."""
    resolved: int
    """Pairs whose both ends resolved to a held Greek verse."""
    verified: int
    """Pairs that cleared the verbal gate, and are now the index."""


def _greek_ref(verses: Versification, token: str) -> VerseRef | None:
    """``Gen.1.1`` in the seed's English numbering, as the coordinates the Greek is held
    in — or ``None`` where the book is unknown or the mapping has no answer."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    try:
        book = resolve_book(parts[0])
    except (UnknownBookError, AmbiguousBookError):
        return None
    ref = VerseRef(book, int(parts[1]), int(parts[2]), vrs="eng")
    try:
        return verses.convert(ref, numbering(book))
    except VersificationError:
        return None


#: The 27 New Testament books, spelled out because no versification system can be asked
#: "is this yours": `lxx` answers yes for Acts and `org` answers yes for the Psalms --
#: both carry the whole canon -- and choosing by has_book() labelled every New Testament
#: verse `lxx`, which the profiles build then keyed on and silently built nothing for.
_NEW_TESTAMENT: Final = frozenset(
    "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT "
    "PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split()
)


def numbering(book: str) -> str:
    """Which numbering the library's Greek holds this book in: ``org`` for the New
    Testament, ``lxx`` for everything the Septuagint carries."""
    return "org" if book in _NEW_TESTAMENT else "lxx"


#: Members a seed range may expand to before it is refused as not verse-shaped. The
#: longest ranges in the seed are whole-chapter "see also" links, exactly the topical
#: kind the verbal gate exists to refuse -- expanding them would buy nothing but the DP
#: time to refuse each member.
_MOST_MEMBERS: Final = 8


def _greek_refs(verses: Versification, token: str) -> list[VerseRef]:
    """The seed token as held-Greek coordinates: one ref, or a range's members.

    A ``To Verse`` may be a range -- ``Lev.8.16-Lev.8.17`` -- and a range is expanded to
    its member verses so the table stays verse-granular: each member is verified on its
    own words, and a member carrying none of the parallel is dropped by the same gate
    that drops any topical link.
    """
    first, dash, second = token.partition("-")
    left = _greek_ref(verses, first)
    if left is None:
        return []
    if not dash:
        return [left]
    right = _greek_ref(verses, second)
    if right is None or right.book != left.book:
        return [left]
    try:
        members = verses.expand(VerseRange(left, right))
    except (VersificationError, ValueError):
        # A range can invert under conversion -- the Septuagint reorders Exodus 36-39,
        # so an English range across them ends before it starts in Greek coordinates.
        return [left]
    return members if len(members) <= _MOST_MEMBERS else []


def build_parallels(
    home: DataHome, report: Callable[[str], None] = lambda line: None
) -> ParallelsResult:
    """Verify the seed list verbally and write the ``parallel_family`` table."""
    from .lemmata import Lexicon, require_current_lexicon
    from .search import LemmaWeights, Reading, _tokens, lemma_chain, lemma_readings

    # Every pair below is admitted on surprisal read off the folded lemma index, so a stale
    # lexicon would put a current stamp over stale scoring -- the fault this table itself
    # suffered for six folds.
    require_current_lexicon(home, "grc")

    archive = max((home.sources / SOURCE.id).iterdir(), key=lambda path: path.name, default=None)
    if archive is None:
        raise FileNotFoundError(
            f"no archive for {SOURCE.id}; run `biblereference parallels` to fetch it"
        )

    verses = Versification.load()
    lexicon = Lexicon(home)
    lexicon.require("grc")
    weigh = LemmaWeights(home).of("grc")

    connection = sqlite3.connect(home.database)
    held: dict[tuple[str, int, int], str] = {}
    for corpus in (_NT, _OT):
        for book, chapter, verse, text in connection.execute(
            "SELECT book, chapter, verse, text FROM verse WHERE corpus = ?", (corpus,)
        ):
            held[(book, chapter, verse)] = text

    readings: dict[tuple[str, int, int], list[Reading]] = {}

    def read(key: tuple[str, int, int]) -> list[Reading]:
        found = readings.get(key)
        if found is None:
            found = readings[key] = lemma_readings(_tokens(held[key], "grc"), "grc", lexicon)
        return found

    pairs = resolved = 0
    rows: list[tuple[str, str, int, int, str, str, int, int, int, float, int]] = []
    with zipfile.ZipFile(archive / "cross-references.zip") as bundle:
        lines = bundle.read("cross_references.txt").decode("utf-8").splitlines()
    seen: set[tuple[tuple[str, int, int], tuple[str, int, int]]] = set()
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) < 3:
            continue
        pairs += 1
        votes = int(columns[2]) if columns[2].lstrip("-").isdigit() else 0
        for left in _greek_refs(verses, columns[0]):
            for right in _greek_refs(verses, columns[1]):
                a = (left.book, left.chapter, left.verse)
                b = (right.book, right.chapter, right.verse)
                if a not in held or b not in held or a == b or (a, b) in seen:
                    continue
                seen.add((a, b))
                resolved += 1
                chained = lemma_chain(read(a), read(b), weigh)
                if chained.length < CHAIN_FLOOR or chained.bits < BITS_FLOOR:
                    continue
                rows.append(
                    (left.vrs, *a, right.vrs, *b, chained.length, round(chained.bits, 2), votes)
                )
                if len(rows) % 5000 == 0:
                    report(f"  {resolved:,} pairs verified so far, {len(rows):,} verbal")

    connection.execute("DROP TABLE IF EXISTS parallel_family")
    connection.execute(
        "CREATE TABLE parallel_family ("
        " vrs_a TEXT, book_a TEXT, chapter_a INTEGER, verse_a INTEGER,"
        " vrs_b TEXT, book_b TEXT, chapter_b INTEGER, verse_b INTEGER,"
        " chain INTEGER, bits REAL, votes INTEGER)"
    )
    connection.executemany("INSERT INTO parallel_family VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    connection.execute(
        "CREATE INDEX parallel_family_a ON parallel_family(book_a, chapter_a, verse_a)"
    )
    connection.execute(
        "CREATE INDEX parallel_family_b ON parallel_family(book_b, chapter_b, verse_b)"
    )
    # Stamped, and stamped late enough to be worth explaining. Every pair here cleared
    # `chained.bits < BITS_FLOOR`, and those bits come from `LemmaWeights(home).of("grc")` --
    # surprisal over the lemma index, which is folded. So this table is fold-dependent and
    # carried no way to say so.
    #
    # It cost something. Six fold bumps ran in two days and not one of them rebuilt this
    # table -- every rebuild script listed the lemma steps and went straight to profiles,
    # the same omission a setup guide made and a reader caught. `build_profiles` takes its
    # anchors from here, so `profiles.sqlite` was rebuilt at each fold and stamped honestly
    # at fold 8 while its anchors came from a table six folds old. A true stamp on an
    # artifact built from a stale input: the stamp only ever covers what the builder knew.
    connection.execute(
        "CREATE TABLE IF NOT EXISTS parallel_family_state ("
        " built_at TEXT NOT NULL, fold_version INTEGER NOT NULL,"
        " pairs INTEGER NOT NULL, resolved INTEGER NOT NULL, verified INTEGER NOT NULL)"
    )
    connection.execute("DELETE FROM parallel_family_state")
    connection.execute(
        "INSERT INTO parallel_family_state "
        "(built_at, fold_version, pairs, resolved, verified) VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(UTC).isoformat(timespec="seconds"),
            FOLD_VERSION,
            pairs,
            resolved,
            len(rows),
        ),
    )
    connection.commit()
    connection.close()
    return ParallelsResult(pairs=pairs, resolved=resolved, verified=len(rows))


def parallels_fold(home: DataHome) -> int | None:
    """The fold that built ``parallel_family``, or ``None`` where it cannot say.

    ``None`` for a table built before the stamp existed. Treating that as current is how it
    went six folds unnoticed, so callers must read it as "unknown", never as "fine".
    """
    import sqlite3

    if not home.database.exists():
        return None
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            row = connection.execute("SELECT fold_version FROM parallel_family_state").fetchone()
        except sqlite3.OperationalError:
            return None
    return int(row[0]) if row else None


class Parallels:
    """Reads the verified index. Silent — empty answers — where it was never built."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._held = bool(
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='parallel_family'"
            ).fetchone()
        )

    def of(self, book: str, chapter: int, first: int, last: int) -> tuple[str, ...]:
        """The family members of any verse in ``book chapter first..last``, as
        ``BOOK C:V`` strings in the coordinates the Greek is held in, best-chained
        first."""
        if not self._held:
            return ()
        rows = self._connection.execute(
            "SELECT book_b, chapter_b, verse_b, chain, bits FROM parallel_family"
            " WHERE book_a = ? AND chapter_a = ? AND verse_a BETWEEN ? AND ?"
            " UNION "
            "SELECT book_a, chapter_a, verse_a, chain, bits FROM parallel_family"
            " WHERE book_b = ? AND chapter_b = ? AND verse_b BETWEEN ? AND ?",
            (book, chapter, first, last, book, chapter, first, last),
        ).fetchall()
        ranked = sorted(rows, key=lambda row: (-row[3], -row[4]))
        out: list[str] = []
        for other_book, other_chapter, other_verse, _, _ in ranked:
            name = f"{other_book} {other_chapter}:{other_verse}"
            if name not in out:
                out.append(name)
        return tuple(out)
