"""The entity index: every biblical proper noun, with everywhere it stands.

The allusion pass's foundation, and the user's own design idea validated by the research
pass: gather all the proper-noun names in each language with the verses they occur in,
and a father naming Ἀβραάμ and Μελχισέδεκ in one breath has pointed at Genesis 14 without
quoting a word of it. Word-matching cannot see that; an entity index can.

Two sources, both licensed and fetched whole into the archive:

* **TIPNR** (Tyndale House STEPBible-Data, CC BY 4.0) — every proper noun in scripture
  with every reference, the Hebrew and Greek surface forms cross-linked *per individual*:
  the twelve different men named Ἰωσήφ are twelve entities, which is exactly what keeps a
  co-mention from meaning nothing. Its header asks that others be referred to
  github.com/STEPBible rather than re-distributing — honoured the same way every
  fetched-not-redistributed source here is.
* **Theographic** (CC BY-SA 4.0) — the per-verse people/places tables and the narrative
  event index. ShareAlike binds published derivative *datasets*, tracked in licences.py;
  fetched now, parsed when the episode index is built.

The build writes a standalone ``entities.sqlite`` beside the corpus database — the
profiles precedent: derived data, rebuildable from the archive, and writable while the
corpus file is frozen under a consumer's sweep. References arrive in TIPNR's English
numbering and are stored in the Greek's own, through the same conversion discipline as
the parallel-family build.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .emphasis import fold
from .licences import get
from .sources import BuiltCorpus, RemoteFile, Source

__all__ = ["THEOGRAPHIC", "TIPNR", "Entities", "build_entities"]


def _refuse(archive: Path) -> list[BuiltCorpus]:
    raise RuntimeError(
        "proper nouns are an index, not a corpus; build them with `build_entities`"
    )


_TIPNR_FILE: Final = (
    "TIPNR - Translators Individualised Proper Names with all References - STEPBible.org CC BY.txt"
)

TIPNR: Final = Source(
    id="tipnr",
    label="Tyndale Individualised Proper Names with all References (STEPBible)",
    homepage="https://github.com/STEPBible/STEPBible-Data",
    license="CC BY 4.0, per the file's own header. The header asks that others be "
    "referred to github.com/STEPBible rather than redistributing the data -- honoured: "
    "fetched for indexing, never republished.",
    terms=get("cc-by-4.0"),
    attribution="Proper-noun data created by www.STEPBible.org based on work at Tyndale "
    "House Cambridge, used under CC BY 4.0.",
    files=(
        RemoteFile(
            url="https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/"
            "Proper%20Nouns/" + _TIPNR_FILE.replace(" ", "%20"),
            name="tipnr.txt",
        ),
    ),
    build=_refuse,
)

_THEOGRAPHIC_RAW: Final = (
    "https://raw.githubusercontent.com/robertrouse/theographic-bible-metadata/master/CSV"
)

THEOGRAPHIC: Final = Source(
    id="theographic",
    label="Theographic Bible Metadata (people, places, events, per verse)",
    homepage="https://github.com/robertrouse/theographic-bible-metadata",
    license="CC BY-SA 4.0. ShareAlike binds any published derivative dataset; the "
    "internal index is not one, and nothing from it is redistributed.",
    terms=get("cc-by-sa-4.0"),
    attribution="Theographic Bible Metadata by Robert Rouse, used under CC BY-SA 4.0.",
    files=tuple(
        RemoteFile(url=f"{_THEOGRAPHIC_RAW}/{name}", name=name)
        for name in ("People.csv", "Places.csv", "Events.csv", "Verses.csv")
    ),
    build=_refuse,
)


# -- the TIPNR parse --------------------------------------------------------------------

#: A reference token this build will take: `Book.Chapter.Verse`, nothing appended.
#: TIPNR's per-form reference lists are dotted and clean; the compressed `Total` lines
#: (`Exo.4.27ff; 9.8,27`) are summaries of the same data and are skipped rather than
#: half-parsed.
_REF_RE: Final = re.compile(r"^[1-3]?[A-Za-z]+\.\d+\.\d+$")

#: Sub-record significances whose surface forms belong in the index. `Total` is a
#: summary; the parenthesised kinds repeat a previous line's refs under bookkeeping
#: variations.
_FORMS: Final = frozenset(
    {"Named", "Greek", "Spelled", "Aramaic", "Name combined", "Spelled combined",
     "Aramaic combined", "Group"}
)


@dataclass(frozen=True, slots=True)
class _Record:
    entity: str
    kind: str
    forms: tuple[tuple[str, str], ...]
    """(language, folded surface form) -- `he` for H-strongs, `grc` for G-strongs."""
    refs: tuple[str, ...]
    """Dotted English-numbered references, deduplicated."""


def _parse_tipnr(text: str) -> Iterator[_Record]:
    kind = "person"
    record_lines: list[str] = []

    def flush() -> _Record | None:
        if not record_lines:
            return None
        head = record_lines[0].split("\t")[0].strip()
        if "@" not in head:
            return None
        name = head.split("@")[0].strip()
        if not name:
            return None
        forms: list[tuple[str, str]] = []
        refs: list[str] = []
        for line in record_lines[1:]:
            fields = line.split("\t")
            significance = fields[0].lstrip("–- ").strip()
            if significance not in _FORMS or len(fields) < 3:
                continue
            strongs = fields[2]
            if "=" in strongs:
                surface = strongs.split("=", 1)[1].strip()
                if surface:
                    language = "grc" if strongs.lstrip("–- ").startswith("G") else "he"
                    folded = fold(surface, language)
                    if folded:
                        forms.append((language, folded))
            listed = fields[-1] if len(fields) >= 5 else ""
            for token in listed.split(";"):
                token = token.strip()
                if _REF_RE.match(token):
                    refs.append(token)
        if not refs:
            return None
        return _Record(
            entity=head,
            kind=kind,
            forms=tuple(dict.fromkeys(forms)),
            refs=tuple(dict.fromkeys(refs)),
        )

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("$="):
            done = flush()
            if done:
                yield done
            record_lines = []
            upper = line.upper()
            kind = "person" if "PERSON" in upper else "place" if "PLACE" in upper else "other"
            continue
        if record_lines or ("@" in line.split("\t")[0] and not line.startswith(("–", "@", " "))):
            record_lines.append(line)
    done = flush()
    if done:
        yield done


# -- the build --------------------------------------------------------------------------

_SCHEMA: Final = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE entity (id TEXT PRIMARY KEY, label TEXT, kind TEXT);
CREATE TABLE entity_form (entity TEXT, language TEXT, form TEXT);
CREATE INDEX entity_form_lookup ON entity_form (language, form);
CREATE TABLE entity_verse (entity TEXT, vrs TEXT, book TEXT, chapter INTEGER, verse INTEGER);
CREATE INDEX entity_verse_ref ON entity_verse (book, chapter, verse);
CREATE INDEX entity_verse_entity ON entity_verse (entity);
"""


@dataclass(frozen=True, slots=True)
class EntitiesResult:
    entities: int
    forms: int
    references: int
    unconvertible: int


def build_entities(
    home: object,
    out: Path | None = None,
    report: Callable[[str], None] = lambda line: None,
) -> EntitiesResult:
    """Parse the fetched TIPNR into ``entities.sqlite``, coordinates in the Greek's own.

    Reference conversion is the parallel-family build's own discipline — English
    numbering in, `numbering(book)` deciding the target, `None` counted rather than
    guessed where the mapping has no answer.
    """
    from .parallels import _greek_ref
    from .store import DataHome
    from .versification import Versification

    assert isinstance(home, DataHome)
    archive = max(
        (home.sources / TIPNR.id).iterdir(), key=lambda path: path.name, default=None
    )
    if archive is None:
        raise FileNotFoundError(f"no archive for {TIPNR.id}; fetch it first")
    target = out or home.root / "db" / "entities.sqlite"

    verses = Versification.load()
    text = (archive / "tipnr.txt").read_text("utf-8")

    target.unlink(missing_ok=True)
    db = sqlite3.connect(target)
    db.executescript(_SCHEMA)

    entities = forms = references = unconvertible = 0
    for record in _parse_tipnr(text):
        rows: list[tuple[str, str, str, int, int]] = []
        for token in record.refs:
            ref = _greek_ref(verses, token)
            if ref is None or not isinstance(ref.chapter, int):
                # Unmappable, or a lettered chapter (Esther's additions) the numbered
                # index cannot hold.
                unconvertible += 1
                continue
            rows.append((record.entity, ref.vrs, ref.book, ref.chapter, ref.verse))
        if not rows:
            continue
        label = record.entity.split("@")[0]
        db.execute(
            "INSERT OR IGNORE INTO entity (id, label, kind) VALUES (?, ?, ?)",
            (record.entity, label, record.kind),
        )
        db.executemany(
            "INSERT INTO entity_form (entity, language, form) VALUES (?, ?, ?)",
            [(record.entity, language, form) for language, form in record.forms],
        )
        db.executemany(
            "INSERT INTO entity_verse (entity, vrs, book, chapter, verse) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        entities += 1
        forms += len(record.forms)
        references += len(rows)
        if entities % 2000 == 0:
            report(f"  {entities:,} entities")
    db.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        {
            "source": TIPNR.id,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "entities": str(entities),
            "references": str(references),
            "unconvertible": str(unconvertible),
        }.items(),
    )
    db.commit()
    db.close()
    return EntitiesResult(entities, forms, references, unconvertible)


class Entities:
    """Reads the entity index. Silent — empty answers — where it was never built."""

    def __init__(self, path: Path) -> None:
        self._db: sqlite3.Connection | None = None
        if path.exists():
            self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self._verse_count: int = int(
                self._db.execute("SELECT COUNT(DISTINCT book||chapter||verse) FROM entity_verse")
                .fetchone()[0]
            )

    @property
    def held(self) -> bool:
        return self._db is not None

    def by_form(self, language: str, forms: list[str]) -> dict[str, set[str]]:
        """``folded form -> entity ids`` for every form the index knows."""
        if self._db is None or not forms:
            return {}
        marks = ",".join("?" * len(forms))
        out: dict[str, set[str]] = {}
        for form, entity in self._db.execute(
            f"SELECT form, entity FROM entity_form WHERE language = ? AND form IN ({marks})",
            (language, *forms),
        ):
            out.setdefault(str(form), set()).add(str(entity))
        return out

    def verses_of(self, entity: str) -> int:
        if self._db is None:
            return 0
        return int(
            self._db.execute(
                "SELECT COUNT(*) FROM entity_verse WHERE entity = ?", (entity,)
            ).fetchone()[0]
        )

    def co_mentions(
        self, entity_ids: set[str], least: int = 2, spread: int = 4
    ) -> list[tuple[str, str, int, int, int, frozenset[str]]]:
        """Passages where at least ``least`` of these entities stand near each other.

        Clustered within a chapter at ``spread`` verses, not per verse: Melchizedek
        meets Abram across Genesis 14:18-19, and a co-mention that demanded one verse
        would see them together only where Hebrews retells it. Returns
        ``(vrs, book, chapter, first, last, entities)``, most entities first, tightest
        cluster breaking ties.
        """
        if self._db is None or len(entity_ids) < least:
            return []
        marks = ",".join("?" * len(entity_ids))
        rows = self._db.execute(
            f"SELECT entity, vrs, book, chapter, verse FROM entity_verse "
            f"WHERE entity IN ({marks}) ORDER BY book, chapter, verse",
            sorted(entity_ids),
        ).fetchall()
        chapters: dict[tuple[str, str, int], list[tuple[int, str]]] = {}
        for entity, vrs, book, chapter, verse in rows:
            chapters.setdefault((str(vrs), str(book), int(chapter)), []).append(
                (int(verse), str(entity))
            )
        out: list[tuple[str, str, int, int, int, frozenset[str]]] = []
        for (vrs, book, chapter), mentions in chapters.items():
            mentions.sort()
            cluster: list[tuple[int, str]] = []
            for verse, entity in [*mentions, (10_000, "")]:
                if cluster and verse - cluster[-1][0] > spread:
                    names = frozenset(e for _, e in cluster)
                    if len(names) >= least:
                        out.append(
                            (vrs, book, chapter, cluster[0][0], cluster[-1][0], names)
                        )
                    cluster = []
                if entity:
                    cluster.append((verse, entity))
        out.sort(key=lambda row: (-len(row[5]), row[4] - row[3]))
        return out

    @property
    def verse_count(self) -> int:
        return self._verse_count if self._db is not None else 0
