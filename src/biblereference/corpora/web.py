"""Copyrighted English translations, fetched a chapter at a time.

The public-domain texts cover a lot, but not the NRSVCE, the NABRE, or the RSV-2CE --
the translations a modern Catholic treatise is most likely to quote. Those exist online
and nowhere redistributable, so this provider fetches them, and does so on terms worth
stating plainly:

**It is opt-in.** Nothing here runs unless you name one of these versions.

**It fetches once.** A chapter is requested at most one time, ever. The HTML is written
into your archive alongside every other source, so re-rendering is offline and you keep
the page as it was on the day you read it.

**It is slow on purpose.** Requests are serial with a delay between them. This is a tool
for drafting your own work, not for copying a website; BibleGateway's terms do not
contemplate systematic downloading, and the way to stay within them is to stay small.

**The text stays under copyright.** Quoting the NRSVCE in a draft is one thing; a
published treatise quoting at length needs the publisher's permission, which every one of
these translations grants only up to a stated limit. The public-domain path -- the ASV
with the WEB Catholic Edition, or the Douay-Rheims throughout -- has no such ceiling. The
renderer emits the copyright notice for whichever version you use.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import httpx

from ..canon import book_title
from ..refs import VerseRef
from ..store import DataHome
from .base import CorpusError, VerseText, VerseUnavailable

__all__ = ["KNOWN_VERSIONS", "BibleGatewayCorpus", "parse_chapter"]

_BASE: Final = "https://www.biblegateway.com/passage/"

#: Versions this has been checked against. Others may work; these are the Catholic
#: editions the provider exists for.
KNOWN_VERSIONS: Final[dict[str, str]] = {
    "NRSVCE": "New Revised Standard Version Catholic Edition",
    "NRSVACE": "New Revised Standard Version Anglicised Catholic Edition",
    "NABRE": "New American Bible Revised Edition",
    "RSVCE": "Revised Standard Version Catholic Edition",
    "RSV2CE": "Revised Standard Version Second Catholic Edition",
    "GNTCE": "Good News Translation Catholic Edition",
    "NCB": "St. Joseph New Catholic Bible",
    "DRA": "Douay-Rheims 1899 American Edition",
}

#: Where the site's book name differs from this library's title for it.
_BOOK_NAMES: Final[dict[str, str]] = {
    "ESG": "Greek Esther",
    "DAG": "Daniel",
    "S3Y": "Prayer of Azariah",
    "LJE": "Letter of Jeremiah",
    "PS2": "Psalm 151",
    "MAN": "Prayer of Manasseh",
    "SNG": "Song of Solomon",
    "PSA": "Psalm",
}

#: Elements inside the passage that are apparatus, headings, or numbering rather than
#: the words of a verse.
_STRIP_SELECTORS: Final = (
    "sup.versenum",
    "span.chapternum",
    "sup.footnote",
    "sup.crossreference",
    ".crossreference",
    ".footnotes",
    ".footnote",
    ".passage-other-trans",
    "h1, h2, h3, h4",
)

_VERSE_CLASS_RE: Final = re.compile(r"^(?P<book>[\w\d]+)-(?P<chapter>\d+)-(?P<verse>\d+)$")


def parse_chapter(html: str) -> dict[int, str]:
    """Read one BibleGateway chapter page into ``{verse number: text}``.

    Verse text is split across several spans -- a line of poetry each -- all carrying the
    same ``Book-Chapter-Verse`` class, so the spans are grouped by that class rather than
    read one to a verse.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - depends on the [web] extra
        raise CorpusError(
            "online translations need the 'web' extra: pip install 'biblereference[web]'"
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    passage = soup.select_one("div.passage-text")
    if passage is None:
        raise CorpusError("no passage found on the page; the site's markup may have changed")

    for selector in _STRIP_SELECTORS:
        for element in passage.select(selector):
            element.decompose()

    pieces: dict[int, list[str]] = {}
    for span in passage.select("span.text"):
        classes = span.get("class") or []
        match = next((m for m in (_VERSE_CLASS_RE.match(str(c)) for c in classes) if m), None)
        if match is None:
            continue
        text = span.get_text(" ", strip=True)
        if text:
            pieces.setdefault(int(match["verse"]), []).append(text)

    return {
        verse: re.sub(r"\s+([,;:.!?’”)])", r"\1", " ".join(parts)).strip()
        for verse, parts in sorted(pieces.items())
    }


def parse_copyright(html: str) -> str | None:
    """The version's copyright line, which the renderer is obliged to print."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - depends on the [web] extra
        return None
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one(".copyright-table, .publisher-info-bottom")
    return " ".join(block.get_text(" ", strip=True).split()) if block else None


@dataclass
class _Cache:
    """Chapters already read, so a document citing one chapter twice fetches once."""

    chapters: dict[tuple[str, int], dict[int, str]]


class BibleGatewayCorpus:
    """One online English translation.

    :param version: e.g. ``"NRSVCE"``. See :data:`KNOWN_VERSIONS`.
    :param home: Where fetched pages are archived.
    :param delay: Seconds between requests. Lower it and you are the problem.
    :param offline: Serve only what is already archived, never fetch.
    """

    versification = "eng"
    language = "en"

    def __init__(
        self,
        version: str,
        home: DataHome,
        *,
        delay: float = 2.0,
        offline: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._version = version.strip().upper()
        self._home = home
        self._delay = delay
        self._offline = offline
        self._timeout = timeout
        self._cache = _Cache(chapters={})
        self._attribution: str | None = None
        self._last_request = 0.0

    @property
    def id(self) -> str:
        return self._version.lower()

    @property
    def label(self) -> str:
        return KNOWN_VERSIONS.get(self._version, self._version)

    @property
    def attribution(self) -> str | None:
        return self._attribution

    def has_book(self, book: str) -> bool:
        """Whether a book is worth asking for.

        There is no way to know without fetching, so this answers yes for anything with a
        name. A book the version does not carry surfaces as an unavailable verse.
        """
        return bool(_BOOK_NAMES.get(book) or book_title(book))

    def fetch(self, refs: Sequence[VerseRef]) -> list[VerseText]:
        out: list[VerseText] = []
        for ref in refs:
            if ref.is_letter_chapter:
                raise VerseUnavailable(ref, self.label, "letter chapters are not supported")
            assert isinstance(ref.chapter, int)
            chapter = self._chapter(ref.book, ref.chapter)
            text = chapter.get(ref.verse)
            if not text:
                raise VerseUnavailable(ref, self.label)
            out.append(VerseText(ref=ref, text=text))
        return out

    # -- fetching ----------------------------------------------------------------------

    def _chapter(self, book: str, chapter: int) -> dict[int, str]:
        key = (book, chapter)
        if key in self._cache.chapters:
            return self._cache.chapters[key]

        html = self._archived(book, chapter)
        if html is None:
            if self._offline:
                raise VerseUnavailable(
                    VerseRef(book, chapter, 1),
                    self.label,
                    "not in the archive, and fetching is switched off",
                )
            html = self._download(book, chapter)

        verses = parse_chapter(html)
        if self._attribution is None:
            self._attribution = parse_copyright(html)
        self._cache.chapters[key] = verses
        return verses

    def _archive_name(self, book: str, chapter: int) -> str:
        return f"{self._version}/{book}_{chapter}.html"

    def _archived(self, book: str, chapter: int) -> str | None:
        """Look through every dated archive directory, newest first."""
        base = self._home.sources / "web"
        if not base.is_dir():
            return None
        for dated in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True):
            path = dated / self._archive_name(book, chapter)
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _download(self, book: str, chapter: int) -> str:
        name = _BOOK_NAMES.get(book) or book_title(book)
        params = {"search": f"{name} {chapter}", "version": self._version}

        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self._delay:
            time.sleep(self._delay - elapsed)

        try:
            response = httpx.get(
                _BASE,
                params=params,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": _user_agent()},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CorpusError(f"could not fetch {name} {chapter} ({self._version}): {exc}") from exc
        finally:
            self._last_request = time.monotonic()

        self._home.store_file(
            "web",
            self._archive_name(book, chapter),
            response.content,
            url=str(response.url),
            license=f"{self.label}: under copyright. Fetched for personal study.",
            note="Archived so that re-rendering never fetches again.",
        )
        return response.text


def _user_agent() -> str:
    return (
        "biblereference/0.1 (personal scripture-citation tool; one chapter at a time, "
        "cached permanently)"
    )
