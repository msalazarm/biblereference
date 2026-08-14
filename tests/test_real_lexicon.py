"""The same fixtures, against the lexicon people will actually have.

``test_inflected.py`` writes its own small lexicon so the suite needs no download. That is a
real weakness and this is the answer to it: a lexicon containing exactly the words a fixture
needs cannot show that the matching works on words nobody chose in advance, and a hand-made
one is the classic way to prove a thing by assuming it.

So these run against the fetched lexicon and the built library, and skip when either is
absent -- which it will be on any machine that has not run ``biblereference lemmata``. A
skipped test proves nothing, but a passing one proves something the other module cannot.
"""

from __future__ import annotations

import pytest

from biblereference.lemmata import Lexicon
from biblereference.search import Searcher
from biblereference.store import DataHome

#: The developer's own library, captured at import -- before ``conftest``'s session fixture
#: points ``$BIBLEREFERENCE_HOME`` at an empty temporary directory.
#:
#: That isolation is right for every other test here and wrong for this module, which exists
#: to ask whether the fixtures hold against the real 113,062-verse Greek index and the real
#: 864,376-form lexicon. Reaching around it deliberately, and only here.
REAL = DataHome()

pytestmark = pytest.mark.skipif(
    not REAL.database.exists() or not Lexicon(REAL).holds("grc"),
    reason="needs a built library and `biblereference lemmata`",
)

#: Fixtures from the request, with the verse a scholar reading the Greek stands behind.
#: `run` is the longest identically spelled run, which is why today's scanner misses them.
FIXTURES = [
    (
        "Pol. 2.2",
        "MAT 10:16",
        "φρόνιμος γίνου ὡς ὁ ὄφις ἐν ἅπασιν καὶ ἀκέραιος εἰς ἀεὶ ὡς ἡ περιστερά",
    ),
    ("Smyrn. 3.2", "LUK 24:39", "Λάβετε ψηλαφήσατέ με καὶ ἴδετε ὅτι οὐκ εἰμὶ δαιμόνιον ἀσώματον"),
    ("Phil. 7.1", "JHN 3:8", "οἶδεν γάρ πόθεν ἔρχεται καὶ ποῦ ὑπάγει"),
]

NEGATIVES = [
    ("Smyrn. 9.1", "ACT 20:21", "εἰς θεὸν μετανοεῖν"),
    ("Phil. 11.1a", "ACT 6:3", "ἀνδρὸς μεμαρτυρημένου"),
]


def searcher(**options: object) -> Searcher:
    settings: dict[str, object] = {
        "coverage": 0.50,
        "min_query": 3,
        "min_run": lambda n: max(4, min(6, n // 2)),
    }
    settings.update(options)
    return Searcher(REAL, languages=["grc"], **settings)  # type: ignore[arg-type]


@pytest.mark.parametrize(("where", "verse", "text"), FIXTURES)
def test_the_fixtures_hold_against_the_real_lexicon(where: str, verse: str, text: str) -> None:
    with searcher(inflected=True) as rich:
        found = [str(match.passage) for match in rich.search(text, limit=8)]
    assert verse in found, f"{where} was not found; got {found}"


@pytest.mark.parametrize(("where", "verse", "text"), NEGATIVES)
def test_the_negatives_hold_too(where: str, verse: str, text: str) -> None:
    """The half that is easy to lose. A lexicon of 864,376 forms pairs a great deal more
    than a hand-written one, and everything it pairs is a chance to invent a quotation."""
    with searcher(inflected=True) as rich:
        found = [str(match.passage) for match in rich.search(text, limit=8)]
    assert verse not in found, f"{where} was invented; got {found}"


def test_nothing_the_library_finds_today_is_lost(minimum: int = 40) -> None:
    """Requirement 0 against the whole real Greek index rather than a fixed corpus.

    The fixed-corpus guard in ``test_regression`` proves the fields do not move over four
    matches. This asks the same question of the real library over the fixture texts and the
    verses themselves, where the candidate pool is 113,062 verses rather than five hundred.
    """
    texts = [text for _, _, text in FIXTURES + NEGATIVES]
    checked = 0
    with searcher() as plain, searcher(inflected=True) as rich:
        for text in texts:
            before = {str(m.passage) for m in plain.search(text, limit=8)}
            after = {str(m.passage) for m in rich.search(text, limit=8)}
            assert before <= after, f"lost {before - after} from {text[:40]!r}"
            checked += len(before)
    assert checked, "nothing was found either way, so nothing was actually compared"
