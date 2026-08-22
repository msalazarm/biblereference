"""Which dictionary form a spelling belongs to, for Greek and Latin.

The search index knows spellings. A father quoting scripture does not reuse its spellings:
he bends the grammar to his own sentence, and in an inflected language that changes almost
every word. Ignatius, telling one bishop to be wise as the serpent, shares fourteen words
with Matthew 10:16 and not two of them in a row are spelled alike -- Matthew is addressing
disciples in the plural. Measured over 5,770 quotations that editors marked by hand, 27.5%
have no four consecutive words spelled as the source spells them.

This module is the lookup that closes that gap, and it is deliberately the dullest possible
one: a fetched table of ``form -> lemma``, no analyser, no model, no guessing. A suffix
heuristic was tried by the people who asked for this and does not work for Greek, because
Greek inflects the ending and the ending is inside any truncation:

    ἀνδρὸς → ανδρος → 'ανδρο'
    ἄνδρας → ανδρας → 'ανδρα'      the same noun, and now two different stems

Ambiguity is kept rather than resolved. ``ἄρῃ`` can be three different verbs and all three
are stored; two words match if they share *any* reading. Choosing between them here would be
a guess made in the one place where there is no context to make it with, and the gates that
hold the looseness down live in the matcher, where the surrounding words are.

Not vendored. The two lexicons are 33 MB together and descend from Perseus's Morpheus and
the Collatinus project, so they are fetched into the data home like any other upstream and
their terms recorded, rather than redistributed from an MIT repository.
"""

from __future__ import annotations

import ast
import re
import sqlite3
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .emphasis import FOLD_VERSION, _language, fold
from .licences import LICENCES, Licence
from .sources import BuiltCorpus, RemoteFile, Source
from .store import DataHome, open_store

__all__ = [
    "LEXICONS",
    "Lexicon",
    "LexiconSource",
    "LexiconUnavailable",
    "build_lexicon",
    "lexicon_coverage",
    "lexicon_folds",
    "require_current_lexicon",
]


class LexiconUnavailable(LookupError):
    """No lexicon is built for a language something asked to match by lemma in."""


def _cltk_pairs(path: Path) -> Iterator[tuple[str, str]]:
    """Read one of CLTK's lemma maps: a Python module holding a single dict literal.

    ``ast.literal_eval`` rather than an import, because a downloaded file is data and
    executing it would make it code.

    **One lemma per form.** The Greek file holds 949,453 entries and every value is a bare
    string; the Latin holds 270,227 and likewise. This docstring used to say a list was
    the ordinary case and that ``ἄρῃ`` was stored as three verbs -- neither is true of the
    data as fetched. ``fold('ἄρῃ')`` does carry five readings, but they arrive from five
    differently accented spellings colliding under the fold, not from upstream ambiguity.

    Where a spelling could be a noun's case or a verb's form, whatever generated these files
    kept one analysis and it is very often the verb: ``κύριον -> κυρέω``, ``ναός -> ναῦς``,
    ``θεοῦ -> θεάομαι``. That is why :data:`LEXICONS` reads Greek from two sources rather
    than one. The list branch below is kept as defence against a shape upstream has never
    shipped.
    """
    text = path.read_text(encoding="utf-8")
    _, _, body = text.partition("=")
    table = ast.literal_eval(body.strip())
    for form, lemmas in table.items():
        if isinstance(lemmas, str):
            lemmas = [lemmas]
        for lemma in lemmas:
            yield str(form), str(lemma)


#: Beta code to Greek letters. An upstream *encoding*, so it lives here beside the reader
#: that needs it rather than in `emphasis`, which is about how this library spells a word
#: once it is Greek.
_BETA = str.maketrans(
    "abgdezhqiklmncoprstufxyw",
    "αβγδεζηθικλμνξοπρστυφχψω",
)

#: Diacritics, word-splitting marks and the sigma-position digits beta code carries. All
#: dropped: `fold` is applied straight after, and it removes accents anyway.
_BETA_NOISE = str.maketrans("", "", "*)(/\\=|+'_^0123456789")


def _from_beta(word: str) -> str:
    """Beta code as Greek letters. ``qeo/s`` is ``θεος``.

    Validated against the Greek lexicon already held: of 391,691 forms decoded from
    Diorisis, **391,667 are already keys in the CLTK table** -- 99.9939%. All 24 that are
    not are genuine Attic ``ξυν-`` spellings (``ξυγκεκραμενον``, ``ξυμβιωσει``) that the
    Morpheus table simply lacks, which is the union working rather than the decoder failing.
    """
    return word.translate(_BETA_NOISE).lower().translate(_BETA)


_DIORISIS_WORD = re.compile(r"<word\b[^>]*\bform=\"([^\"]*)\"[^>]*>(.*?)</word>", re.S)
_DIORISIS_LEMMA = re.compile(r"<lemma\b[^>]*\bentry=\"([^\"]+)\"")


def _diorisis_pairs(path: Path) -> Iterator[tuple[str, str]]:
    """Read Diorisis: ten million analyses a lemmatiser assigned in running Greek.

    The Morpheus table is an *inventory* -- one analysis per spelling, chosen once. This is
    an *observation*: every ``<word form=…><lemma entry=…>`` a corpus of 10.2M words was
    actually tagged with. Where the inventory kept the verb, the observations usually hold
    the noun as well, and unioning them is what puts ``θεοῦ`` back with ``θεός``.

    Every ``<lemma>`` child is taken, not the disambiguated one. This module keeps ambiguity
    and lets surprisal decide; picking a winner here would be the same mistake the inventory
    made.

    The corpus is already fetched for the PPMI vectors, so this costs a parse and no new
    download. Terms are recorded as the TEI headers state them (CC BY-SA 3.0 US), which is
    stricter than the figshare record's CC BY 4.0.
    """
    with zipfile.ZipFile(path) as archive:
        for entry in archive.namelist():
            if not entry.lower().endswith(".xml"):
                continue
            text = archive.read(entry).decode("utf-8", "replace")
            for form, inner in _DIORISIS_WORD.findall(text):
                if not form:
                    continue
                decoded = _from_beta(form)
                if not decoded:
                    continue
                for lemma in _DIORISIS_LEMMA.findall(inner):
                    yield decoded, _from_beta(lemma)


@dataclass(frozen=True, slots=True)
class LexiconPart:
    """One upstream a language's lexicon is assembled from."""

    source: Source
    parse: Callable[[Path], Iterator[tuple[str, str]]]
    """Reads the archived file, yielding ``(form, lemma)`` as the upstream spells them.
    Folding happens once, in :func:`build_lexicon`."""


@dataclass(frozen=True, slots=True)
class LexiconSource:
    """One language's lexicon: the upstreams it is assembled from, in order.

    Plural because one is not enough for Greek. Morpheus keeps a single analysis per
    spelling and it is very often the verb, so `θεοῦ` -- the commonest genitive in
    scripture, 1,747 occurrences -- resolves to θεάομαι and shares no lemma with `θεός`.
    Readings from every part are unioned; none of them wins.
    """

    language: str
    parts: tuple[LexiconPart, ...]


def _refuse_lexicon_build(_: Path) -> Iterable[BuiltCorpus]:
    """A lexicon part is fetched and never built as a corpus. See :func:`_lexicon_source`."""
    raise TypeError("this is a lexicon, not a corpus; build it with `biblereference lemmata`")


def _lexicon_source(language: str, label: str, url: str, name: str, terms: Licence) -> Source:
    def _refuse(_: Path) -> Iterable[BuiltCorpus]:
        # `Source` exists to be fetched *and* built, and this one is only ever fetched: the
        # archive machinery, the manifest and `mirror` are all worth reusing, and a lexicon
        # is still not a corpus. Saying so here is better than a build that silently yields
        # nothing, which is the shape of fault this library has already been bitten by once.
        raise TypeError(
            f"{name} is a lexicon, not a corpus; build it with `biblereference lemmata`"
        )

    return Source(
        id=f"lemmata-{language}",
        label=label,
        homepage="https://github.com/cltk",
        license=terms.summary,
        files=(RemoteFile(url=url, name=name),),
        build=_refuse,
        terms=terms,
    )


#: Diorisis as a *lexicon* part rather than as the vector corpus it was fetched for.
#:
#: Declared here with its own id so the archive machinery, the manifest and `mirror` all see
#: it the same way; the files it names are the ones `ppmi.DIORISIS` already fetched, so a
#: library that has built vectors has this already. Terms follow the TEI headers, which
#: declare CC BY-SA 3.0 US -- stricter than the figshare record's CC BY 4.0, and the
#: stricter of two claims about the same bytes is the one to record.
_DIORISIS_LEXICON: Final = Source(
    id="diorisis",
    label="The Diorisis Ancient Greek Corpus (Vatri & McGillivray), as observed lemmata",
    homepage="https://doi.org/10.6084/m9.figshare.6187256",
    license="CC BY-SA 3.0 US, per the corpus's own TEI headers.",
    terms=LICENCES["cc-by-sa-3.0"],
    attribution="The Diorisis Ancient Greek Corpus, A. Vatri & B. McGillivray.",
    files=(
        RemoteFile(
            url="https://ndownloader.figshare.com/files/11296247",
            name="Diorisis.zip",
        ),
    ),
    build=_refuse_lexicon_build,
    note="10.2M words of lemmatised Greek. Read here for the form->lemma pairs a "
    "lemmatiser actually assigned, which is what Morpheus's one-analysis-per-spelling "
    "inventory is missing.",
)


#: The two lexicons, by this library's language code.
#:
#: Both come through the Classical Language Toolkit's model repositories, which is where they
#: are actually maintained; the data behind them is older than either. The Greek is Morpheus
#: output -- Perseus's morphological analyser, the reference implementation for the language
#: -- and the Latin descends from the Collatinus project. Their terms are recorded as their
#: strictest ancestor rather than as the repository's own declaration, because a repository
#: cannot relicense data it did not make.
LEXICONS: Final[dict[str, LexiconSource]] = {
    "grc": LexiconSource(
        language="grc",
        parts=(
            LexiconPart(
                source=_lexicon_source(
                    "grc",
                    "Ancient Greek lemmata (Morpheus, via CLTK)",
                    "https://raw.githubusercontent.com/cltk/grc_models_cltk/master/"
                    "lemmata/greek_lemmata_cltk.py",
                    "greek_lemmata_cltk.py",
                    LICENCES["cc-by-sa-3.0"],
                ),
                parse=_cltk_pairs,
            ),
            # The observations, against Morpheus's inventory. Already fetched for the PPMI
            # vectors, so this is a parse and no new download. Measured over LXX and NT:
            # paradigm slots orphaned from their own lemma fall 4.6% -> 1.5%, broken
            # sibling bridges 9.2% -> 1.0%, and no bridge that worked before is lost.
            LexiconPart(source=_DIORISIS_LEXICON, parse=_diorisis_pairs),
        ),
    ),
    "la": LexiconSource(
        language="la",
        parts=(
            LexiconPart(
                source=_lexicon_source(
                    "la",
                    "Latin lemmata (Collatinus, via CLTK)",
                    "https://raw.githubusercontent.com/cltk/lat_models_cltk/master/"
                    "lemmata/latin_lemmata_cltk.py",
                    "latin_lemmata_cltk.py",
                    LICENCES["gpl-3.0"],
                ),
                parse=_cltk_pairs,
            ),
        ),
        # Latin has the same defect at the same size -- 241 of 2,582 lemmas analysed only
        # as some other word, `anima`->`animo`, `gloria`->`glorior` -- and no second source
        # here fixes it. Diorisis is Greek only. Recorded rather than left as an absence.
    ),
}


def build_lexicon(
    home: DataHome, language: str, *, report: Callable[[str], None] | None = None
) -> int:
    """Fold one fetched lexicon into ``lemma_form``. Returns the rows written.

    Folded on the way in, with :func:`~biblereference.emphasis.fold`, so that a lookup costs
    one indexed read and cannot disagree with the tokeniser about what a word is. Folding
    collides some entries -- Greek accents distinguish homographs that the search has always
    treated alike -- and the readings are unioned rather than one of them winning.
    """
    say = report or (lambda _: None)
    spec = LEXICONS.get(language)
    if spec is None:
        raise LexiconUnavailable(
            f"no lexicon is defined for {language!r}. This library has: {', '.join(LEXICONS)}"
        )

    rows: set[tuple[str, str, str]] = set()
    for part in spec.parts:
        archive = home.latest_archive(part.source.id)
        wanted = part.source.files[0].name
        if archive is None or not (archive / wanted).exists():
            raise LexiconUnavailable(
                f"the {language} lexicon's {part.source.id} part has not been fetched. "
                f"Run `biblereference lemmata --language {language}`"
            )
        before = len(rows)
        for form, lemma in part.parse(archive / wanted):
            folded, root = fold(form, language), fold(lemma, language)
            if folded and root:
                rows.add((language, folded, root))
        say(f"  {part.source.id}: {len(rows) - before:,} readings this library did not have")

    forms = len({row[1] for row in rows})
    with open_store(home) as connection:
        connection.execute("DELETE FROM lemma_form WHERE language = ?", (language,))
        connection.executemany(
            "INSERT OR IGNORE INTO lemma_form (language, form, lemma) VALUES (?, ?, ?)",
            sorted(rows),
        )
        # Stamped in the same transaction as the rows it describes, so the two cannot
        # disagree about which fold spelled these forms.
        connection.execute(
            "INSERT OR REPLACE INTO lemma_form_state "
            "(language, built_at, fold_version, forms, readings, sources) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                language,
                datetime.now(UTC).isoformat(timespec="seconds"),
                FOLD_VERSION,
                forms,
                len(rows),
                # Which upstreams built it, so a table assembled from fewer of them cannot
                # pass a freshness check. A CLTK-only table carries a current fold stamp and
                # is missing `θεοῦ`; the fold version cannot see that, and this can.
                ",".join(part.source.id for part in spec.parts),
            ),
        )
    say(f"lemmata: {language} {forms:,} forms, {len(rows):,} readings")
    return len(rows)


def lexicon_folds(home: DataHome) -> dict[str, int | None]:
    """``language -> the fold that built its table``, or ``None`` where it was built before
    the stamp existed and nothing can say.

    An unstamped table is reported as unknown rather than assumed current: the forms are
    folded on the way in, so one built under a superseded rule is spelled wrong throughout,
    and guessing would be the reassurance this exists to withhold.
    """
    if not home.database.exists():
        return {}
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            held = {
                str(language)
                for (language,) in connection.execute("SELECT DISTINCT language FROM lemma_form")
            }
        except sqlite3.OperationalError:
            return {}
        # Asked separately, and after: an install whose database predates the stamp has the
        # forms but not the table, and that is precisely the case worth reporting. Folding
        # the two queries into one `try` reported nothing at all for it -- the silence this
        # function exists to break.
        try:
            stamped = {
                str(language): int(fold_version)
                for language, fold_version in connection.execute(
                    "SELECT language, fold_version FROM lemma_form_state"
                )
            }
        except sqlite3.OperationalError:
            stamped = {}
    return {language: stamped.get(language) for language in sorted(held)}


def require_current_lexicon(home: DataHome, language: str) -> None:
    """Refuse to build *from* a lexicon folded under a rule this library no longer applies.

    The stamp was added when `lemma_form` was found six folds stale; for a day afterwards
    only ``doctor`` read it, which is the same fault one level up — a stamp nobody consults
    cannot stop anything. Every builder that looks a form up here now asks first, so a
    stale lexicon cannot quietly become a freshly stamped index, family table or profile
    set. That is exactly how `profiles.sqlite` came to record fold 8 honestly while its
    anchors were six folds old.

    Silent on an *empty* lexicon: absence is the caller's own problem and is already
    reported as an unbuilt layer. This refuses the populated-but-wrong case only.
    """
    folds = lexicon_folds(home)
    if language not in folds:
        return

    # Which upstreams built it, checked before the fold. A Greek table assembled from
    # Morpheus alone is spelled at the current fold and passes every freshness test this
    # library had, while `θεοῦ` -- 1,747 occurrences -- resolves to θεάομαι and meets
    # nothing. The fold version is structurally unable to see a missing *source*, so the
    # sources are recorded and read here.
    spec = LEXICONS.get(language)
    if spec is not None:
        wanted = ",".join(part.source.id for part in spec.parts)
        recorded_sources = _lexicon_sources(home).get(language)
        if recorded_sources is not None and recorded_sources != wanted:
            raise LexiconUnavailable(
                f"the {language} lexicon was built from {recorded_sources or 'nothing recorded'} "
                f"and this library assembles it from {wanted}. The forms it holds are spelled "
                f"correctly and are not all of them. Run `biblereference lemmata --language "
                f"{language}`, then `biblereference index --lemmata`."
            )

    recorded = folds[language]
    if recorded == FOLD_VERSION:
        return
    said = "does not say which fold built it" if recorded is None else f"was folded at {recorded}"
    raise LexiconUnavailable(
        f"the {language} lexicon {said} and this library folds at {FOLD_VERSION}. Its forms "
        f"are spelled the way the old rule spelled them, so anything built from it now would "
        f"carry a current stamp over stale lookups. Run `biblereference lemmata --language "
        f"{language}`, then `biblereference index --lemmata`."
    )


def _lexicon_sources(home: DataHome) -> dict[str, str | None]:
    """``language -> the comma-joined source ids that built it``, or None where unrecorded.

    None is not "nothing": it means the table predates the column, which is the same
    convention `search_state.fold_version` uses and for the same reason.
    """
    if not home.database.exists():
        return {}
    with open_store(home) as connection:
        present = {row[1] for row in connection.execute("PRAGMA table_info(lemma_form_state)")}
        if "sources" not in present:
            return {}
        return {
            str(language): (None if sources is None else str(sources))
            for language, sources in connection.execute(
                "SELECT language, sources FROM lemma_form_state"
            )
        }


def lexicon_coverage(home: DataHome) -> dict[str, int]:
    """``language -> distinct folded forms held``, for everything built."""
    if not home.database.exists():
        return {}
    with closing(sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute(
                "SELECT language, COUNT(DISTINCT form) FROM lemma_form GROUP BY language"
            ).fetchall()
        except sqlite3.OperationalError:  # pragma: no cover - database predates the table
            return {}
    return {str(language): int(count) for language, count in rows}


class Lexicon:
    """``form -> lemmas``, read from the store and remembered for the process.

    Looked up in batches. A scan of a patristic work asks about hundreds of thousands of
    words, and one ``SELECT`` per word would spend the whole run in SQLite; one per few
    hundred distinct words, cached, spends almost none of it there. The cache holds misses
    too, which are the common case in a language whose lexicon is thinner than its corpus.
    """

    #: Words per query. Below SQLite's parameter ceiling with room to spare.
    BATCH: Final = 400

    def __init__(self, home: DataHome, connection: sqlite3.Connection | None = None) -> None:
        """
        :param connection: Read through this instead of opening one. Indexing must pass the
            connection it already holds: SQLite locks the database for the writer, and a
            second connection reading the lexicon mid-build deadlocks against it.
        """
        self.home = home
        self._shared = connection
        self._known: dict[str, dict[str, frozenset[str]]] = {}
        self._held: dict[str, int] | None = None

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        if self._shared is not None:
            yield self._shared
            return
        with closing(sqlite3.connect(f"file:{self.home.database}?mode=ro", uri=True)) as db:
            yield db

    def holds(self, language: str) -> bool:
        language = _language(language) or language
        if self._held is None:
            try:
                with self._read() as db:
                    rows = db.execute(
                        "SELECT language, COUNT(DISTINCT form) FROM lemma_form GROUP BY language"
                    ).fetchall()
            except sqlite3.OperationalError:  # pragma: no cover - database not built yet
                rows = []
            self._held = {str(language): int(count) for language, count in rows}
        return self._held.get(language, 0) > 0

    def require(self, language: str) -> None:
        """Raise unless this language can be matched by lemma, saying what to run.

        The name is resolved first. `require("lat")` used to report *no lat lexicon is
        built* -- true of the string, false of the fact, since the Latin lexicon is built
        and is called `la`. An error that names the wrong cause costs more than no error.
        """
        language = _language(language) or language
        if not self.holds(language):
            raise LexiconUnavailable(
                f"no {language} lexicon is built, so inflected matching cannot be done in it. "
                f"Run `biblereference lemmata --language {language}`"
                + (
                    ""
                    if language in LEXICONS
                    else f". This library defines lexicons for: {', '.join(LEXICONS)}"
                )
            )

    def lemmas(self, form: str, language: str) -> frozenset[str]:
        """Every dictionary form this spelling can belong to. Empty if it is unknown."""
        return self.of([form], language).get(form, frozenset())

    def of(self, forms: Sequence[str], language: str) -> dict[str, frozenset[str]]:
        """The same for many spellings at once, which is how a scan should ask."""
        language = _language(language) or language
        known = self._known.setdefault(language, {})
        missing = sorted({form for form in forms if form not in known})
        if missing:
            self._load(missing, language, known)
        return {form: known.get(form, frozenset()) for form in forms}

    def _load(self, missing: list[str], language: str, known: dict[str, frozenset[str]]) -> None:
        found: dict[str, set[str]] = {}
        with self._read() as db:
            for start in range(0, len(missing), self.BATCH):
                chunk = missing[start : start + self.BATCH]
                marks = ", ".join("?" * len(chunk))
                for form, lemma in db.execute(
                    f"SELECT form, lemma FROM lemma_form WHERE language = ? AND form IN ({marks})",
                    (language, *chunk),
                ):
                    found.setdefault(str(form), set()).add(str(lemma))
        for form in missing:
            # Misses are remembered as well, or every scan re-asks about every word the
            # lexicon has never heard of -- which in patristic Greek is a great many.
            known[form] = frozenset(found.get(form, ()))
