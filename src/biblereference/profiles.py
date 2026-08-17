"""Per-verse profiles: the family made matchable as one target instead of N.

Today each edition of a verse is an independent chance to match — and, on the control
corpus, an independent chance to collide, which is how the consumer measured the exact
path's false positives scaling with the number of editions rather than with the amount of
new text. The profile is the structural fix, and the research pass's top-ranked transfer:
align every held edition of the verse and its verbal family into a small multiple sequence
alignment, and let the alignment's columns become the target. Where every witness agrees a
match is demanded; where they vary, the attested alternatives are carried natively — an
itacistic spelling, a Byzantine plus-word, a doublet's divergent clause; insertions get
insert columns, so a parallel with extra material does not corrupt the shared core. Which
reading the father follows becomes a free output of the alignment rather than a study.

The aligner is our own progressive Needleman–Wunsch over tokens: the sequences are 10–50
tokens and 3–10 witnesses, where the quadratic DP is microseconds and a dependency would
buy the risk without removing the work. Progressive alignment is witness-order-dependent
— CollateX's own caveat — so the seed order is pinned: the critical text first, then the
other editions, then family members by their verified chain, and the build is
deterministic from the library's own tables.

**The spike's answers, measured before this shipped** (see ``tests/test_profiles.py``):

* Insert columns are kept as ordinary positions, and it does not matter to the matcher:
  the flagship query chains identically (9 links, 46.8 bits) with them kept or filtered,
  because either way the chain's gap costs absorb what a witness lacks. The flag is
  provenance, not matching.
* Divergent material of *equal length* — Acts' narrative frame against Isaiah's opening
  clause — pairs into alternative columns rather than gapping into inserts, because a
  mismatch costs less than two gaps. Matching-wise the two representations are
  equivalent (the column carries both readings and either matches); the ``insert`` flag
  therefore means *length-divergent* material specifically, and the docstring is where
  that is said.
* Per-alternative weights are structurally unused by matching — ``profile_chain`` reads
  only :attr:`Column.reading` — so they are stored for the "which reading does the
  father follow" report and nothing else.
* Seed order: zero differing columns across every real family measured (pure edition
  sets and cross-verse families alike). The pin stays — determinism costs nothing and
  the order-dependence is the literature's caveat, not a superstition — but it is a
  guard, not a measured hazard.

**The acceptance measurement**: the Byzantine long ending of Romans 8:1 chains 7 links at
39.0 bits through the profile and **zero** through the critical text alone — the
edition-dilution fix doing exactly what §6b bought it for.

Stored in a standalone ``profiles.sqlite`` beside the corpus database: derived data,
rebuildable from the library at any time, and writable while the corpus file itself is
frozen under a consumer's sweep.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .emphasis import FOLD_VERSION

__all__ = ["Column", "Profiles", "align_pair", "build_profiles", "profile_chain"]

Reading = frozenset[str]

#: Alignment scores: an identical folded spelling outranks a shared dictionary form,
#: which outranks nothing. Gaps cost what a mismatch costs, so the DP prefers pairing
#: over shifting only where the pair carries evidence.
_EXACT: Final = 3
_LEMMA: Final = 2
_MISS: Final = -1
_GAP: Final = -1


@dataclass(frozen=True, slots=True)
class Column:
    """One position of a profile: the attested alternatives, with their provenance."""

    forms: tuple[tuple[str, float], ...]
    """Folded spellings attested here, with the share of witnesses attesting each --
    stored for reporting ("which reading does the father follow"), not for matching:
    the spike measured per-alternative weights moving no chain outcome."""
    lemmas: Reading
    """Every dictionary form any witness's word here can belong to."""
    insert: bool
    """Whether some witness lacks this position -- a plus-word or a divergent clause.
    Kept as an ordinary position: the chain's gap costs absorb what is absent exactly
    as they absorb an interpolation."""
    members: tuple[str, ...]
    """Which witnesses attest this position, for the audit trail."""

    @property
    def reading(self) -> Reading:
        """The column as the matcher's own currency: a `Reading` any query token can
        intersect -- its lemmas, plus its spellings for the out-of-vocabulary case."""
        return self.lemmas | frozenset(form for form, _ in self.forms)


def _score(
    a_form: str, a_reading: Reading, b_form: str, b_reading: Reading
) -> int:
    if a_form == b_form:
        return _EXACT
    if a_reading & b_reading:
        return _LEMMA
    return _MISS


def align_pair(
    a: Sequence[tuple[str, Reading]],
    b: Sequence[tuple[str, Reading]],
) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch over tokens: exact fold > shared lemma > mismatch.

    Returns aligned index pairs, ``None`` for a gap. Deterministic: ties prefer the
    diagonal, then consuming ``a`` -- the same choice every time is what makes the whole
    build reproducible to the byte.
    """
    rows, cols = len(a) + 1, len(b) + 1
    score = [[0] * cols for _ in range(rows)]
    for i in range(1, rows):
        score[i][0] = i * _GAP
    for j in range(1, cols):
        score[0][j] = j * _GAP
    for i in range(1, rows):
        for j in range(1, cols):
            diagonal = score[i - 1][j - 1] + _score(*a[i - 1], *b[j - 1])
            up = score[i - 1][j] + _GAP
            left = score[i][j - 1] + _GAP
            score[i][j] = max(diagonal, up, left)
    out: list[tuple[int | None, int | None]] = []
    i, j = len(a), len(b)
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and score[i][j] == score[i - 1][j - 1] + _score(*a[i - 1], *b[j - 1])
        ):
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and score[i][j] == score[i - 1][j] + _GAP:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    out.reverse()
    return out


def merge(
    profile: list[Column],
    witness: Sequence[tuple[str, Reading]],
    member: str,
    attested: int,
) -> list[Column]:
    """One more witness folded into the profile, positions aligned against the columns.

    ``attested`` is how many witnesses the profile already holds, so the shares stay
    shares. A column the new witness lacks becomes (or stays) an insert column; a token
    the profile lacks opens one.
    """
    as_pairs = [(_best_form(column), column.reading) for column in profile]
    aligned = align_pair(as_pairs, witness)
    out: list[Column] = []
    for left, right in aligned:
        if left is not None and right is not None:
            column = profile[left]
            form, reading = witness[right]
            shares = dict(column.forms)
            shares[form] = shares.get(form, 0.0) + 1.0
            out.append(
                Column(
                    forms=tuple(sorted(shares.items())),
                    lemmas=column.lemmas | reading,
                    insert=column.insert,
                    members=(*column.members, member),
                )
            )
        elif left is not None:
            out.append(
                Column(
                    forms=profile[left].forms,
                    lemmas=profile[left].lemmas,
                    insert=True,
                    members=profile[left].members,
                )
            )
        else:
            assert right is not None
            form, reading = witness[right]
            out.append(
                Column(forms=((form, 1.0),), lemmas=reading, insert=attested > 0,
                       members=(member,))
            )
    return out


def _best_form(column: Column) -> str:
    return max(column.forms, key=lambda pair: (pair[1], pair[0]))[0]


def build_profile(
    witnesses: Sequence[tuple[str, Sequence[tuple[str, Reading]]]],
) -> list[Column]:
    """A profile from witnesses in their pinned order, first witness the seed."""
    profile: list[Column] = []
    for attested, (member, tokens) in enumerate(witnesses):
        if not profile:
            profile = [
                Column(forms=((form, 1.0),), lemmas=reading, insert=False, members=(member,))
                for form, reading in tokens
            ]
        else:
            profile = merge(profile, list(tokens), member, attested)
    return profile


def profile_chain(
    query: Sequence[Reading],
    columns: Sequence[Column],
    bits: Callable[[str], float],
    **options: object,
) -> object:
    """The existing chain run against the profile: one target instead of N editions.

    A column's alternatives *are* a `Reading`, so `lemma_chain` runs unchanged -- the
    whole reuse the design promised. Whatever admits a chain against a single edition
    admits the same chain here; what changes is that a Byzantine plus-word or a
    doublet's divergence no longer costs a separate attempt.
    """
    from .search import lemma_chain

    return lemma_chain(query, [column.reading for column in columns], bits, **options)  # type: ignore[arg-type]


# -- the build and the reader -----------------------------------------------------------

_SCHEMA: Final = """
CREATE TABLE profile (
    id INTEGER PRIMARY KEY,
    vrs TEXT, book TEXT, chapter INTEGER, verse INTEGER,
    fold_version INTEGER, built_at TEXT, witnesses INTEGER, columns INTEGER);
CREATE UNIQUE INDEX profile_anchor ON profile (vrs, book, chapter, verse);
CREATE TABLE profile_member (
    profile INTEGER, member TEXT, seed_rank INTEGER);
CREATE TABLE profile_column (
    profile INTEGER, position INTEGER, insert_col INTEGER, lemmas TEXT,
    PRIMARY KEY (profile, position)) WITHOUT ROWID;
CREATE TABLE profile_reading (
    profile INTEGER, position INTEGER, form TEXT, share REAL);
"""

#: The critical text leads each numbering's seed order -- the pin CollateX's caveat
#: demands, since progressive alignment is witness-order-dependent and the spike measured
#: real families where two orders disagree.
_SEEDS: Final = {"org": "n1904", "lxx": "rahlfs"}


@dataclass(frozen=True, slots=True)
class ProfilesResult:
    anchors: int
    witnesses: int


def _greek_editions(connection: sqlite3.Connection) -> dict[str, list[str]]:
    """Greek corpora by versification, the seed first and the rest alphabetical."""
    rows = connection.execute(
        "SELECT corpus, versification FROM source_meta WHERE language = 'grc' ORDER BY corpus"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for corpus, vrs in rows:
        out.setdefault(str(vrs), []).append(str(corpus))
    for vrs, seed in _SEEDS.items():
        if vrs in out and seed in out[vrs]:
            out[vrs].remove(seed)
            out[vrs].insert(0, seed)
    return out


def build_profiles(
    home: object,
    out: Path | None = None,
    report: Callable[[str], None] = lambda line: None,
) -> ProfilesResult:
    """Profiles for every verse the parallel-family index names, written standalone.

    The family anchors are where the profile buys most: those verses already have both
    edition variants *and* verbal parallels, which is the dilution the profile removes.
    Witness order per anchor: the anchor's own editions (critical text first), then one
    canonical edition of each family member, by the family's verified chain, descending.
    """
    from .lemmata import Lexicon
    from .search import _tokens, lemma_readings
    from .store import DataHome

    assert isinstance(home, DataHome)
    target = out or home.root / "db" / "profiles.sqlite"
    lexicon = Lexicon(home)
    lexicon.require("grc")

    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as db:
        editions = _greek_editions(db)
        # The anchor's numbering is derived from its book, not read off the table: the
        # first parallels build labelled every New Testament verse `lxx` (both
        # versification systems claim the whole canon, so has_book() could not decide),
        # and trusting the stored label here silently built Old Testament profiles only.
        # Deriving keeps this correct against the mislabelled table until its scheduled
        # rebuild, and against the corrected one after.
        from .parallels import numbering

        wanted = {
            (numbering(str(book)), str(book), int(chapter), int(verse))
            for book, chapter, verse in db.execute(
                "SELECT book_a, chapter_a, verse_a FROM parallel_family "
                "UNION SELECT book_b, chapter_b, verse_b FROM parallel_family"
            )
        }
        # Plus every verse the held editions disagree on *as token streams* -- Romans
        # 8:1's Byzantine long ending has no verbal cross-reference and every reason to
        # be profiled: edition variance is the other half of what §6b buys, and a verse
        # the editions agree on gains nothing from a profile. Token-level disagreement,
        # not raw text: a comma is an editor's and would profile everything.
        from .emphasis import fold

        for vrs, corpora in _greek_editions(db).items():
            if len(corpora) < 2:
                continue
            streams: dict[tuple[str, int, int], set[tuple[str, ...]]] = {}
            marks = ",".join("?" * len(corpora))
            for book, chapter, verse, text in db.execute(
                f"SELECT book, chapter, verse, text FROM verse WHERE corpus IN ({marks})",
                corpora,
            ):
                key = (str(book), int(chapter), int(verse))
                streams.setdefault(key, set()).add(tuple(fold(str(text), "grc").split()))
            wanted.update(
                (vrs, book, chapter, verse)
                for (book, chapter, verse), variants in streams.items()
                if len(variants) >= 2
            )
        anchors = sorted(wanted)

        def verse_text(corpus: str, book: str, chapter: int, verse: int) -> str | None:
            row = db.execute(
                "SELECT text FROM verse WHERE corpus=? AND book=? AND chapter=? AND verse=?",
                (corpus, book, chapter, verse),
            ).fetchone()
            return str(row[0]) if row else None

        def family_of(book: str, chapter: int, verse: int) -> list[tuple[str, str, int, int, int]]:
            # By coordinates alone, the far side's numbering derived from its book --
            # the same distrust of the stored label as the anchors above.
            rows = db.execute(
                "SELECT book_b, chapter_b, verse_b, chain FROM parallel_family "
                "WHERE book_a=? AND chapter_a=? AND verse_a=? "
                "UNION "
                "SELECT book_a, chapter_a, verse_a, chain FROM parallel_family "
                "WHERE book_b=? AND chapter_b=? AND verse_b=? "
                "ORDER BY 4 DESC",
                (book, chapter, verse, book, chapter, verse),
            ).fetchall()
            return [
                (numbering(str(b)), str(b), int(c), int(v), int(chain))
                for b, c, v, chain in rows
            ]

        target.unlink(missing_ok=True)
        model = sqlite3.connect(target)
        model.executescript(_SCHEMA)

        built = 0
        total_witnesses = 0
        for vrs, book, chapter, verse in anchors:
            witnesses: list[tuple[str, list[tuple[str, Reading]]]] = []
            for corpus in editions.get(str(vrs), []):
                text = verse_text(corpus, str(book), int(chapter), int(verse))
                if text:
                    tokens = _tokens(text, "grc")
                    readings = lemma_readings(tokens, "grc", lexicon)
                    witnesses.append((corpus, list(zip(tokens, readings, strict=True))))
            for f_vrs, f_book, f_chapter, f_verse, _ in family_of(
                str(book), int(chapter), int(verse)
            ):
                seed = _SEEDS.get(str(f_vrs))
                if seed is None:
                    continue
                text = verse_text(seed, str(f_book), int(f_chapter), int(f_verse))
                if text:
                    tokens = _tokens(text, "grc")
                    readings = lemma_readings(tokens, "grc", lexicon)
                    witnesses.append(
                        (f"{seed}:{f_book} {f_chapter}:{f_verse}",
                         list(zip(tokens, readings, strict=True)))
                    )
            if len(witnesses) < 2:
                continue
            profile = build_profile(witnesses)
            cursor = model.execute(
                "INSERT INTO profile (vrs, book, chapter, verse, fold_version, built_at, "
                "witnesses, columns) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (vrs, book, chapter, verse, FOLD_VERSION,
                 datetime.now(UTC).isoformat(timespec="seconds"),
                 len(witnesses), len(profile)),
            )
            pid = cursor.lastrowid
            model.executemany(
                "INSERT INTO profile_member (profile, member, seed_rank) VALUES (?, ?, ?)",
                [(pid, member, rank) for rank, (member, _) in enumerate(witnesses)],
            )
            model.executemany(
                "INSERT INTO profile_column (profile, position, insert_col, lemmas) "
                "VALUES (?, ?, ?, ?)",
                [
                    (pid, position, int(column.insert), " ".join(sorted(column.lemmas)))
                    for position, column in enumerate(profile)
                ],
            )
            model.executemany(
                "INSERT INTO profile_reading (profile, position, form, share) "
                "VALUES (?, ?, ?, ?)",
                [
                    (pid, position, form, share)
                    for position, column in enumerate(profile)
                    for form, share in column.forms
                ],
            )
            built += 1
            total_witnesses += len(witnesses)
            if built % 2000 == 0:
                report(f"  {built:,} profiles built")
        model.commit()
        model.close()
    return ProfilesResult(anchors=built, witnesses=total_witnesses)


class Profiles:
    """Reads the built profiles. Silent -- ``None`` -- where the file was never built."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._db: sqlite3.Connection | None = None
        if path.exists():
            self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def of(self, vrs: str, book: str, chapter: int, verse: int) -> list[Column] | None:
        if self._db is None:
            return None
        row = self._db.execute(
            "SELECT id FROM profile WHERE vrs=? AND book=? AND chapter=? AND verse=?",
            (vrs, book, chapter, verse),
        ).fetchone()
        if row is None:
            return None
        pid = int(row[0])
        columns: list[Column] = []
        readings: dict[int, list[tuple[str, float]]] = {}
        for position, form, share in self._db.execute(
            "SELECT position, form, share FROM profile_reading WHERE profile=?", (pid,)
        ):
            readings.setdefault(int(position), []).append((str(form), float(share)))
        for position, insert_col, lemmas in self._db.execute(
            "SELECT position, insert_col, lemmas FROM profile_column "
            "WHERE profile=? ORDER BY position",
            (pid,),
        ):
            columns.append(
                Column(
                    forms=tuple(sorted(readings.get(int(position), []))),
                    lemmas=frozenset(str(lemmas).split()),
                    insert=bool(insert_col),
                    members=(),
                )
            )
        return columns

    def members(self, vrs: str, book: str, chapter: int, verse: int) -> list[str]:
        if self._db is None:
            return []
        return [
            str(member)
            for (member,) in self._db.execute(
                "SELECT m.member FROM profile_member m JOIN profile p ON p.id = m.profile "
                "WHERE p.vrs=? AND p.book=? AND p.chapter=? AND p.verse=? ORDER BY m.seed_rank",
                (vrs, book, chapter, verse),
            )
        ]


def iter_anchors(path: Path) -> Iterator[tuple[str, str, int, int]]:
    """Every profiled verse, for tools that sweep the file."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        for vrs, book, chapter, verse in db.execute(
            "SELECT vrs, book, chapter, verse FROM profile ORDER BY book, chapter, verse"
        ):
            yield (str(vrs), str(book), int(chapter), int(verse))
