"""Book identity, canon membership, and name normalisation.

The internal identity of a book is its **USFM 3.0 code** (``GEN``, ``SIR``, ``ESG``…).
That choice is not arbitrary: the Copenhagen Alliance versification maps -- which the
whole cross-versification machinery rests on -- are keyed on USFM codes, so any other
internal identity would mean translating at every boundary.

Two naming traps drive the design of this module:

1. ``1 Kings`` means 1 Samuel in Douay-Rheims and 1 Kings everywhere else.
2. ``1 Esdras`` means Ezra in Douay-Rheims and the apocryphal Greek Esdras in the
   Septuagint / KJV Apocrypha.

Guessing at either one silently miscites a treatise, so ambiguous names raise
:class:`AmbiguousBookError` unless a :class:`NamingScheme` settles them.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final

__all__ = [
    "SINGLE_CHAPTER_BOOKS",
    "AmbiguousBookError",
    "Canon",
    "NamingScheme",
    "UnknownBookError",
    "book_canon",
    "book_title",
    "canonical_order",
    "is_known",
    "normalize_book",
    "resolve_book",
]


class NamingScheme(StrEnum):
    """Which tradition's book names the input is written in."""

    MODERN = "modern"
    """Contemporary English usage (NRSV/NABRE/RSV-2CE style)."""

    DR = "dr"
    """Douay-Rheims / Clementine Vulgate: 1-4 Kings, Paralipomenon, 1-2 Esdras=Ezra-Neh."""

    LXX = "lxx"
    """Septuagint usage: 1 Esdras is Esdras A, the apocryphal Greek Esdras."""

    DE = "de"
    """German book names. The Patristic Text Archive is a German project and its
    translations cite in German -- *Sacharja*, *1 Korinther*, *Hebräer* -- and a corpus in
    any other language poses the same problem on the same axis."""


class Canon(StrEnum):
    """Which part of the canon a book belongs to.

    This drives ``original=auto``: Hebrew books get the WLC, deuterocanonical books
    get the Septuagint (there is no Hebrew for most of them), NT books get the Greek.
    """

    HEBREW = "hebrew"
    """Protocanonical Old Testament -- extant in Hebrew."""

    DEUTERO = "deutero"
    """Deuterocanonical, i.e. scripture for Catholics, extant in Greek."""

    NT = "nt"
    """New Testament."""

    APPENDIX = "appendix"
    """Present in the Septuagint or Vulgate appendices but not in the Catholic canon
    (3-4 Maccabees, Psalm 151, 2 Esdras/4 Ezra, Odes, Psalms of Solomon, Enoch…)."""


class UnknownBookError(ValueError):
    """A book name could not be resolved to any known book."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"unknown book name: {name!r}")


class AmbiguousBookError(ValueError):
    """A book name means different books in different naming traditions.

    Raised rather than guessed, because a wrong guess here produces a citation that
    looks correct and is not.
    """

    def __init__(self, name: str, options: dict[NamingScheme, str]) -> None:
        self.name = name
        self.options = options
        rendered = ", ".join(
            f"{scheme.value}={book_title(code)}" for scheme, code in sorted(options.items())
        )
        super().__init__(
            f"book name {name!r} is ambiguous across naming traditions ({rendered}); "
            f"set naming= to one of {sorted(s.value for s in options)} to resolve it"
        )


# --------------------------------------------------------------------------------------
# Canon membership
# --------------------------------------------------------------------------------------

_HEBREW: Final = (
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC "
    "SNG ISA JER LAM EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL"
).split()

_DEUTERO: Final = "TOB JDT ESG WIS SIR BAR LJE DAG S3Y SUS BEL 1MA 2MA".split()

_NT: Final = (
    "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE "
    "2PE 1JN 2JN 3JN JUD REV"
).split()

_APPENDIX: Final = "1ES 2ES MAN 3MA 4MA PS2 PSS ODA ENO JUB EZA JSA JDB TBS SST BLT DNT".split()

_CANON_OF: Final[dict[str, Canon]] = {
    **{c: Canon.HEBREW for c in _HEBREW},
    **{c: Canon.DEUTERO for c in _DEUTERO},
    **{c: Canon.NT for c in _NT},
    **{c: Canon.APPENDIX for c in _APPENDIX},
}

#: Reading order. Deuterocanonical books sit where a Catholic Bible prints them;
#: the Greek supplements to Esther and Daniel sit next to their host book.
CANONICAL_ORDER: Final[tuple[str, ...]] = tuple(
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH TOB JDT EST ESG 1MA "
    "2MA JOB PSA PRO ECC SNG WIS SIR ISA JER LAM BAR LJE EZK DAN DAG S3Y SUS BEL HOS JOL "
    "AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP "
    "COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV 1ES 2ES MAN 3MA 4MA "
    "PS2 PSS ODA ENO JUB EZA JSA JDB TBS SST BLT DNT".split()
)

_ORDER_INDEX: Final[dict[str, int]] = {c: i for i, c in enumerate(CANONICAL_ORDER)}

#: Books cited without a chapter -- "Jude 5" means Jude 1:5. Includes the short
#: deuterocanonical pieces, which are routinely cited by verse alone.
SINGLE_CHAPTER_BOOKS: Final[frozenset[str]] = frozenset(
    {"OBA", "PHM", "2JN", "3JN", "JUD", "SUS", "BEL", "LJE", "S3Y", "MAN", "PS2", "SST", "BLT"}
)

_TITLES: Final[dict[str, str]] = {
    "GEN": "Genesis",
    "EXO": "Exodus",
    "LEV": "Leviticus",
    "NUM": "Numbers",
    "DEU": "Deuteronomy",
    "JOS": "Joshua",
    "JDG": "Judges",
    "RUT": "Ruth",
    "1SA": "1 Samuel",
    "2SA": "2 Samuel",
    "1KI": "1 Kings",
    "2KI": "2 Kings",
    "1CH": "1 Chronicles",
    "2CH": "2 Chronicles",
    "EZR": "Ezra",
    "NEH": "Nehemiah",
    "EST": "Esther",
    "JOB": "Job",
    "PSA": "Psalms",
    "PRO": "Proverbs",
    "ECC": "Ecclesiastes",
    "SNG": "Song of Songs",
    "ISA": "Isaiah",
    "JER": "Jeremiah",
    "LAM": "Lamentations",
    "EZK": "Ezekiel",
    "DAN": "Daniel",
    "HOS": "Hosea",
    "JOL": "Joel",
    "AMO": "Amos",
    "OBA": "Obadiah",
    "JON": "Jonah",
    "MIC": "Micah",
    "NAM": "Nahum",
    "HAB": "Habakkuk",
    "ZEP": "Zephaniah",
    "HAG": "Haggai",
    "ZEC": "Zechariah",
    "MAL": "Malachi",
    "TOB": "Tobit",
    "JDT": "Judith",
    "ESG": "Esther (Greek)",
    "WIS": "Wisdom",
    "SIR": "Sirach",
    "BAR": "Baruch",
    "LJE": "Letter of Jeremiah",
    "DAG": "Daniel (Greek)",
    "S3Y": "Prayer of Azariah",
    "SUS": "Susanna",
    "BEL": "Bel and the Dragon",
    "1MA": "1 Maccabees",
    "2MA": "2 Maccabees",
    "MAT": "Matthew",
    "MRK": "Mark",
    "LUK": "Luke",
    "JHN": "John",
    "ACT": "Acts",
    "ROM": "Romans",
    "1CO": "1 Corinthians",
    "2CO": "2 Corinthians",
    "GAL": "Galatians",
    "EPH": "Ephesians",
    "PHP": "Philippians",
    "COL": "Colossians",
    "1TH": "1 Thessalonians",
    "2TH": "2 Thessalonians",
    "1TI": "1 Timothy",
    "2TI": "2 Timothy",
    "TIT": "Titus",
    "PHM": "Philemon",
    "HEB": "Hebrews",
    "JAS": "James",
    "1PE": "1 Peter",
    "2PE": "2 Peter",
    "1JN": "1 John",
    "2JN": "2 John",
    "3JN": "3 John",
    "JUD": "Jude",
    "REV": "Revelation",
    "1ES": "1 Esdras",
    "2ES": "2 Esdras",
    "MAN": "Prayer of Manasseh",
    "3MA": "3 Maccabees",
    "4MA": "4 Maccabees",
    "PS2": "Psalm 151",
    "PSS": "Psalms of Solomon",
    "ODA": "Odes",
    "ENO": "Enoch",
    "JUB": "Jubilees",
    "EZA": "4 Ezra (Apocalypse)",
    "JSA": "Joshua A",
    "JDB": "Judges B",
    "TBS": "Tobit (Sinaiticus)",
    "SST": "Susanna (Theodotion)",
    "BLT": "Bel and the Dragon (Theodotion)",
    "DNT": "Daniel (Theodotion)",
}


# --------------------------------------------------------------------------------------
# Name normalisation
# --------------------------------------------------------------------------------------

_ROMAN_PREFIX: Final = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}
_WORD_PREFIX: Final = {
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "1st": "1",
    "2nd": "2",
    "3rd": "3",
    "4th": "4",
}
_PREFIX_RE: Final = re.compile(r"^([a-z0-9]+)[\s.]+(?=\S)")


def normalize_book(name: str) -> str:
    """Reduce a book name to a lookup key.

    Case, punctuation, spacing, and the many ways of writing a leading ordinal all
    collapse: ``"II Machabees"``, ``"2 Macc."``, and ``"secondmaccabees"`` are treated
    as three spellings of one key.

    Accents are *decomposed and dropped*, matching :func:`biblereference.emphasis.fold`
    exactly. Until this was fixed the last step deleted anything outside ``[a-z0-9]``, so a
    combining mark did not fold into its base letter -- it took the letter with it.
    ``Sprüche`` normalised to ``sprche`` and ``Lérins`` to ``lrins``, which meant an
    accented name and its unaccented spelling could never reach each other and an alias
    table only worked for whichever one happened to be written into it.

    The two functions agreeing matters beyond the missing letters: a name is looked up
    through this and its text is searched through ``fold``, and two normalisations that
    disagree are a bug factory.
    """
    s = name.strip().lower()
    s = re.sub(r"[‐-―−]", "-", s)  # unicode dashes -> ascii hyphen
    # Before decomposition: these are distinct letters rather than composed ones, so NFD
    # leaves them alone and only an explicit substitution expands them.
    s = s.replace("æ", "ae").replace("œ", "oe").replace("ﬁ", "fi").replace("ﬂ", "fl")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("ς", "σ")  # as fold does, so a final sigma is not a different letter

    match = _PREFIX_RE.match(s)
    if match:
        head = match.group(1)
        digit = _ROMAN_PREFIX.get(head) or _WORD_PREFIX.get(head)
        if digit:
            s = digit + s[match.end() :]

    # Every alphanumeric survives, not merely the ASCII ones. `[^a-z0-9]` was what deleted
    # the umlauts above, and it also silently emptied any name in a non-Latin script.
    return re.sub(r"[\W_]", "", s)


def _expand(spec: dict[str, str]) -> dict[str, str]:
    """Normalise the keys of an alias table written in readable form.

    Raises on a duplicate key, since two entries claiming the same normalised name means
    one of them is silently unreachable -- exactly the sort of typo that would misroute
    a citation.
    """
    out: dict[str, str] = {}
    for names, code in spec.items():
        for name in names.split("|"):
            key = normalize_book(name)
            if key in out and out[key] != code:
                raise AssertionError(f"alias {name!r} claimed by both {out[key]} and {code}")
            out[key] = code
    return out


#: Names that mean the same book in every tradition.
_COMMON: Final[dict[str, str]] = _expand(
    {
        # --- Protocanonical Old Testament ---
        "Genesis|Gen|Gn": "GEN",
        "Exodus|Exod|Exo|Ex": "EXO",
        "Leviticus|Lev|Lv": "LEV",
        "Numbers|Num|Nm|Nb": "NUM",
        "Deuteronomy|Deut|Deu|Dt": "DEU",
        "Joshua|Josh|Jos|Josue|Jsh": "JOS",
        "Judges|Judg|Jdg|Jg": "JDG",
        "Ruth|Rut|Rth|Ru": "RUT",
        "1 Samuel|1 Sam|1 Sm|1 Sa": "1SA",
        "2 Samuel|2 Sam|2 Sm|2 Sa": "2SA",
        "3 Kings|3 Kgs|3 Kin": "1KI",
        "4 Kings|4 Kgs|4 Kin": "2KI",
        "1 Chronicles|1 Chron|1 Chr|1 Ch|1 Paralipomenon|1 Par": "1CH",
        "2 Chronicles|2 Chron|2 Chr|2 Ch|2 Paralipomenon|2 Par": "2CH",
        "Ezra|Ezr": "EZR",
        "Nehemiah|Neh|Ne|Nehemias": "NEH",
        "Esther|Esth|Est|Es": "EST",
        "Job|Jb": "JOB",
        "Psalms|Psalm|Pslm|Psa|Ps|Psm": "PSA",
        "Proverbs|Prov|Pro|Prv|Pr": "PRO",
        "Ecclesiastes|Eccles|Eccl|Ecc|Qoheleth|Qoh": "ECC",
        "Song of Songs|Song of Solomon|Song|Canticles|Canticle of Canticles"
        "|Sng|Sos|Sg|Ca|Cant": "SNG",
        "Isaiah|Isa|Is|Isaias": "ISA",
        "Jeremiah|Jer|Jr|Jeremias": "JER",
        "Lamentations|Lam|Lm": "LAM",
        # Bare "Ez" is deliberately absent: writers use it for both Ezekiel and Ezra.
        "Ezekiel|Ezek|Ezk|Eze|Ezechiel": "EZK",
        "Daniel|Dan|Dn": "DAN",
        "Hosea|Hos|Ho|Osee": "HOS",
        "Joel|Jol|Jl": "JOL",
        "Amos|Amo|Am": "AMO",
        "Obadiah|Obad|Oba|Ob|Abdias": "OBA",
        "Jonah|Jon|Jnh|Jonas": "JON",
        "Micah|Mic|Mi|Micheas": "MIC",
        "Nahum|Nah|Nam|Na": "NAM",
        # "Hb" is deliberately absent: it is Hebrews in common usage, not Habakkuk.
        "Habakkuk|Hab|Habacuc": "HAB",
        "Zephaniah|Zeph|Zep|Zp|Sophonias": "ZEP",
        "Haggai|Hag|Hg|Aggeus": "HAG",
        "Zechariah|Zech|Zec|Zc|Zacharias": "ZEC",
        "Malachi|Mal|Ml|Malachias": "MAL",
        # --- Deuterocanon ---
        "Tobit|Tob|Tb|Tobias": "TOB",
        "Judith|Jdt|Jth": "JDT",
        "Esther Greek|Greek Esther|Additions to Esther|Add Esth|Esg": "ESG",
        "Wisdom|Wisdom of Solomon|Wis|Ws|Wisd": "WIS",
        "Sirach|Sir|Si|Ecclesiasticus|Ecclus|Ben Sira": "SIR",
        "Baruch|Bar": "BAR",
        "Letter of Jeremiah|Epistle of Jeremiah|Ep Jer|Lje|Epj": "LJE",
        "Daniel Greek|Greek Daniel|Dag": "DAG",
        "Prayer of Azariah|Song of the Three|Song of the Three Young Men|"
        "Song of Three Children|Pr Azar|S3y|Azariah": "S3Y",
        "Susanna|Sus": "SUS",
        "Bel and the Dragon|Bel|Bel and Dragon": "BEL",
        "1 Maccabees|1 Macc|1 Mac|1 Ma|1 Machabees": "1MA",
        "2 Maccabees|2 Macc|2 Mac|2 Ma|2 Machabees": "2MA",
        # --- New Testament ---
        "Matthew|Matt|Mat|Mt": "MAT",
        "Mark|Mrk|Mar|Mk": "MRK",
        "Luke|Luk|Lk": "LUK",
        "John|Jhn|Joh|Jn": "JHN",
        "Acts|Act|Acts of the Apostles": "ACT",
        "Romans|Rom|Rm|Ro": "ROM",
        "1 Corinthians|1 Cor|1 Co": "1CO",
        "2 Corinthians|2 Cor|2 Co": "2CO",
        "Galatians|Gal|Ga": "GAL",
        "Ephesians|Eph|Ephes": "EPH",
        "Philippians|Phil|Php|Pp": "PHP",
        "Colossians|Col|Cl": "COL",
        "1 Thessalonians|1 Thess|1 Thes|1 Th": "1TH",
        "2 Thessalonians|2 Thess|2 Thes|2 Th": "2TH",
        "1 Timothy|1 Tim|1 Ti|1 Tm": "1TI",
        "2 Timothy|2 Tim|2 Ti|2 Tm": "2TI",
        "Titus|Tit|Ti": "TIT",
        "Philemon|Philem|Phlm|Phm|Pm": "PHM",
        "Hebrews|Heb|Hb": "HEB",
        "James|Jas|Jm": "JAS",
        "1 Peter|1 Pet|1 Pe|1 Pt": "1PE",
        "2 Peter|2 Pet|2 Pe|2 Pt": "2PE",
        "1 John|1 Jhn|1 Jn|1 Jo": "1JN",
        "2 John|2 Jhn|2 Jn|2 Jo": "2JN",
        "3 John|3 Jhn|3 Jn|3 Jo": "3JN",
        "Jude|Jud|Jde": "JUD",
        "Revelation|Rev|Apocalypse|Apoc|Rv": "REV",
        # --- Septuagint / Vulgate appendices ---
        "3 Esdras|3 Esd": "1ES",
        "4 Esdras|4 Esd|4 Ezra": "2ES",
        "Prayer of Manasseh|Pr Man|Man|Manasses": "MAN",
        "3 Maccabees|3 Macc|3 Mac|3 Ma": "3MA",
        "4 Maccabees|4 Macc|4 Mac|4 Ma": "4MA",
        "Psalm 151|Ps151|Ps 151|Ps2": "PS2",
        "Psalms of Solomon|Pss Sol|Pss": "PSS",
        "Odes|Oda|Ode": "ODA",
        "Enoch|1 Enoch|Eno": "ENO",
        "Jubilees|Jub": "JUB",
        "Daniel Theodotion|Theodotion Daniel|Dnt": "DNT",
        "Susanna Theodotion|Sst": "SST",
        "Bel Theodotion|Blt": "BLT",
        "Tobit Sinaiticus|Tbs": "TBS",
    }
)

#: Names whose meaning depends on the naming tradition.
_AMBIGUOUS: Final[dict[str, dict[NamingScheme, str]]] = {
    # "N Kings" is Samuel in Douay-Rheims. The Septuagint calls these books Kingdoms,
    # so under `lxx` the modern reading is the only sensible one.
    **{
        normalize_book(alias): {
            NamingScheme.MODERN: modern,
            NamingScheme.LXX: modern,
            NamingScheme.DR: dr,
        }
        for alias, modern, dr in [
            ("1 Kings", "1KI", "1SA"),
            ("1 Kgs", "1KI", "1SA"),
            ("1 Kin", "1KI", "1SA"),
            ("2 Kings", "2KI", "2SA"),
            ("2 Kgs", "2KI", "2SA"),
            ("2 Kin", "2KI", "2SA"),
        ]
    },
    # "1 Esdras" is Ezra in Douay-Rheims and the apocryphal Greek Esdras in the
    # Septuagint and KJV Apocrypha. Under `modern` it is left unresolved on purpose.
    **{
        normalize_book(alias): {NamingScheme.LXX: lxx, NamingScheme.DR: dr}
        for alias, lxx, dr in [
            ("1 Esdras", "1ES", "EZR"),
            ("1 Esd", "1ES", "EZR"),
            ("2 Esdras", "2ES", "NEH"),
            ("2 Esd", "2ES", "NEH"),
        ]
    },
}

#: Extra names valid only within one tradition.
_BY_SCHEME: Final[dict[NamingScheme, dict[str, str]]] = {
    NamingScheme.DR: _expand(
        {
            "Kings|Kgs": "1SA",
            "Esdras|Esd": "EZR",
        }
    ),
    NamingScheme.LXX: _expand(
        {
            "Esdras A|Esdras Alpha": "1ES",
            "Esdras B|Esdras Beta": "EZR",
            "Kingdoms 1|1 Kingdoms|1 Kgdms": "1SA",
            "Kingdoms 2|2 Kingdoms|2 Kgdms": "2SA",
            "Kingdoms 3|3 Kingdoms|3 Kgdms": "1KI",
            "Kingdoms 4|4 Kingdoms|4 Kgdms": "2KI",
        }
    ),
    NamingScheme.MODERN: {},
    #: German. :class:`NamingScheme` already models "the same book under another
    #: tradition's name"; a language is the same problem on a different axis, and these
    #: tables are the right home for it.
    #:
    #: Both spellings of every umlaut are listed -- ``Sprüche`` and ``Sprueche``, ``Hebräer``
    #: and ``Hebraeer`` -- because a source may print either and a reader may type either.
    #: They are two aliases of one book rather than two books, which is what ``_expand``'s
    #: duplicate-key guard is there to keep true. Note that they only reach each other at
    #: all because :func:`normalize_book` decomposes accents; while it deleted them,
    #: ``Sprüche`` normalised to ``sprche`` and matched nothing.
    #:
    #: The Pentateuch is cited by number in German -- *1. Mose* is Genesis and *5. Mose*
    #: Deuteronomy -- which the leading-ordinal handling in :func:`normalize_book` already
    #: reads.
    NamingScheme.DE: _expand(
        {
            "1 Mose|1 Mos|Genesis": "GEN",
            "2 Mose|2 Mos": "EXO",
            "3 Mose|3 Mos": "LEV",
            "4 Mose|4 Mos": "NUM",
            "5 Mose|5 Mos": "DEU",
            "Josua|Jos": "JOS",
            "Richter|Ri": "JDG",
            "Rut|Ruth": "RUT",
            "1 Samuel|1 Sam": "1SA",
            "2 Samuel|2 Sam": "2SA",
            "1 Könige|1 Koenige|1 Kön|1 Koen": "1KI",
            "2 Könige|2 Koenige|2 Kön|2 Koen": "2KI",
            "1 Chronik|1 Chron|1 Chr": "1CH",
            "2 Chronik|2 Chron|2 Chr": "2CH",
            "Esra|Esr": "EZR",
            "Nehemia|Neh": "NEH",
            "Ester|Esther|Est": "EST",
            "Hiob|Ijob": "JOB",
            "Psalmen|Psalm|Ps": "PSA",
            "Sprüche|Sprueche|Spr|Sprichwörter|Sprichwoerter": "PRO",
            "Prediger|Kohelet|Pred|Koh": "ECC",
            "Hoheslied|Hohelied|Hld": "SNG",
            "Jesaja|Jes": "ISA",
            "Jeremia|Jer": "JER",
            "Klagelieder|Klgl": "LAM",
            "Hesekiel|Ezechiel|Hes|Ez": "EZK",
            "Daniel|Dan": "DAN",
            "Hosea|Hos": "HOS",
            "Joel|Joe": "JOL",
            "Amos|Am": "AMO",
            "Obadja|Obd": "OBA",
            "Jona|Jon": "JON",
            "Micha|Mi": "MIC",
            "Nahum|Nah": "NAM",
            "Habakuk|Hab": "HAB",
            "Zefanja|Zephanja|Zef|Zeph": "ZEP",
            "Haggai|Hag": "HAG",
            "Sacharja|Sach": "ZEC",
            "Maleachi|Mal": "MAL",
            # Deuterocanonical: the Patristic Text Archive cites these constantly.
            "Tobit|Tobias|Tob": "TOB",
            "Judit|Judith|Jdt": "JDT",
            "Weisheit|Weish": "WIS",
            "Jesus Sirach|Sirach|Sir": "SIR",
            "Baruch|Bar": "BAR",
            "Brief des Jeremia|Brief Jeremias|BrJer": "LJE",
            "1 Makkabäer|1 Makkabaeer|1 Makk": "1MA",
            "2 Makkabäer|2 Makkabaeer|2 Makk": "2MA",
            "Gebet des Manasse|Manasse": "MAN",
            "Matthäus|Matthaeus|Mt|Matth": "MAT",
            "Markus|Mk|Mark": "MRK",
            "Lukas|Lk|Luk": "LUK",
            "Johannes|Joh": "JHN",
            "Apostelgeschichte|Apg": "ACT",
            "Römer|Roemer|Röm|Roem": "ROM",
            "1 Korinther|1 Kor|1Ko": "1CO",
            "2 Korinther|2 Kor|2Ko": "2CO",
            "Galater|Gal": "GAL",
            "Epheser|Eph": "EPH",
            "Philipper|Phil": "PHP",
            "Kolosser|Kol": "COL",
            "1 Thessalonicher|1 Thess|1 Thes": "1TH",
            "2 Thessalonicher|2 Thess|2 Thes": "2TH",
            "1 Timotheus|1 Tim": "1TI",
            "2 Timotheus|2 Tim": "2TI",
            "Titus|Tit": "TIT",
            "Philemon|Phlm": "PHM",
            "Hebräer|Hebraeer|Hebr": "HEB",
            "Jakobus|Jak": "JAS",
            "1 Petrus|1 Petr|1 Pt": "1PE",
            "2 Petrus|2 Petr|2 Pt": "2PE",
            "1 Johannes|1 Joh": "1JN",
            "2 Johannes|2 Joh": "2JN",
            "3 Johannes|3 Joh": "3JN",
            "Judas|Jud": "JUD",
            "Offenbarung|Offb|Apokalypse": "REV",
        }
    ),
}

#: USFM codes are always accepted verbatim, whatever the scheme.
_BY_CODE: Final[dict[str, str]] = {normalize_book(c): c for c in _CANON_OF}


def resolve_book(name: str, scheme: NamingScheme = NamingScheme.MODERN) -> str:
    """Resolve a book name to its USFM code.

    :raises UnknownBookError: the name matches nothing.
    :raises AmbiguousBookError: the name means different books in different traditions
        and ``scheme`` does not settle it.
    """
    key = normalize_book(name)
    if not key:
        raise UnknownBookError(name)

    if key in _AMBIGUOUS:
        options = _AMBIGUOUS[key]
        if scheme in options:
            return options[scheme]
        raise AmbiguousBookError(name, options)

    scheme_specific = _BY_SCHEME[scheme].get(key)
    if scheme_specific:
        return scheme_specific

    code = _BY_CODE.get(key) or _COMMON.get(key)
    if code is None:
        raise UnknownBookError(name)
    return code


def is_known(code: str) -> bool:
    """Whether ``code`` is a USFM code this library knows about."""
    return code in _CANON_OF


def book_canon(code: str) -> Canon:
    """Which part of the canon ``code`` belongs to."""
    try:
        return _CANON_OF[code]
    except KeyError:
        raise UnknownBookError(code) from None


#: Titles under the Douay-Rheims and Clementine Vulgate, where they differ from modern
#: usage. Samuel and Kings are the four books of Kings; Chronicles is Paralipomenon; the
#: prophets keep their Greek-through-Latin spellings.
_DR_TITLES: Final[dict[str, str]] = {
    "1SA": "1 Kings",
    "2SA": "2 Kings",
    "1KI": "3 Kings",
    "2KI": "4 Kings",
    "1CH": "1 Paralipomenon",
    "2CH": "2 Paralipomenon",
    "EZR": "1 Esdras",
    "NEH": "2 Esdras",
    "JOS": "Josue",
    "JDG": "Judges",
    "JOB": "Job",
    "SNG": "Canticle of Canticles",
    "ECC": "Ecclesiastes",
    "SIR": "Ecclesiasticus",
    "WIS": "Wisdom",
    "ISA": "Isaias",
    "JER": "Jeremias",
    "EZK": "Ezechiel",
    "HOS": "Osee",
    "JOL": "Joel",
    "OBA": "Abdias",
    "JON": "Jonas",
    "MIC": "Micheas",
    "NAM": "Nahum",
    "HAB": "Habacuc",
    "ZEP": "Sophonias",
    "HAG": "Aggeus",
    "ZEC": "Zacharias",
    "MAL": "Malachias",
    "TOB": "Tobias",
    "1MA": "1 Machabees",
    "2MA": "2 Machabees",
    "REV": "Apocalypse",
    # The Vulgate prints these inside their host book rather than standing alone.
    "SUS": "Daniel 13",
    "BEL": "Daniel 14",
    "S3Y": "Daniel 3:24-90",
    "LJE": "Baruch 6",
    "ESG": "Esther 10:4-16:24",
}

#: Titles under Septuagint usage, where they differ.
_LXX_TITLES: Final[dict[str, str]] = {
    "1SA": "1 Kingdoms",
    "2SA": "2 Kingdoms",
    "1KI": "3 Kingdoms",
    "2KI": "4 Kingdoms",
    "1CH": "1 Paraleipomenon",
    "2CH": "2 Paraleipomenon",
    "1ES": "Esdras A",
    "EZR": "Esdras B",
    "NEH": "Esdras B",
    "SIR": "Wisdom of Sirach",
    "WIS": "Wisdom of Solomon",
    "SNG": "Song of Songs",
    "LJE": "Epistle of Jeremiah",
    "DAG": "Daniel",
    "ESG": "Esther",
}

_SCHEME_TITLES: Final[dict[NamingScheme, dict[str, str]]] = {
    NamingScheme.MODERN: {},
    NamingScheme.DR: _DR_TITLES,
    NamingScheme.LXX: _LXX_TITLES,
}


def book_title(code: str, scheme: NamingScheme = NamingScheme.MODERN) -> str:
    """Human-readable title for a USFM code, for rendering and error messages.

    :param scheme: Which tradition to name the book in. A reader checking a citation
        against a Douay-Rheims will not find "1 Chronicles" or "Revelation" in it, and
        telling them to look for Paralipomenon and the Apocalypse is the difference
        between a reference they can follow and one they cannot.

    A scheme with no titles of its own falls back to the modern ones, which is what
    :data:`NamingScheme.DE` does: it exists so German citations can be *read*, and
    rendering titles in German is a separate thing nobody has asked for. Printing a
    half-built German table would be worse than printing English.
    """
    return _SCHEME_TITLES.get(scheme, {}).get(code) or _TITLES.get(code, code)


def canonical_order(code: str) -> int:
    """Sort key placing ``code`` in reading order. Unknown books sort last."""
    return _ORDER_INDEX.get(code, len(CANONICAL_ORDER))
