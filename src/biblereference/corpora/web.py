"""Copyrighted English translations, fetched a whole chapter at a time.

The public-domain texts cover a lot, but not the NRSVCE, the NABRE, or the RSV-2CE --
the translations a modern Catholic treatise is most likely to quote. Those exist online
and nowhere redistributable, so this provider fetches them, and does so on terms worth
stating plainly:

**It is opt-in.** Nothing here runs unless you name one of these versions.

**It fetches whole chapters, once.** Citing a single verse pulls the chapter it sits in,
because one request costs the site the same either way and the rest of the chapter is very
likely to be cited next. Every verse of it is then stored -- the page in your archive, the
parsed verses in the same database as every other corpus -- so a chapter is requested at
most one time, ever, and later citations from anywhere in it cost nothing at all. A
citation spanning several chapters is batched into a single request.

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
from ..store import DataHome, SourceMeta, add_chapter, read_chapter, read_meta
from .base import CorpusError, VerseText, VerseUnavailable

__all__ = ["KNOWN_VERSIONS", "BibleGatewayCorpus", "parse_chapter", "parse_passage"]

_BASE: Final = "https://www.biblegateway.com/passage/"

#: Where fetched pages are archived, and the source id their manifest lines carry.
#:
#: Not ``"web"``, which this module was originally called after the web it fetches from --
#: and which is *also* the eBible id of the World English Bible. The two shared one archive
#: directory and one manifest namespace, so the newest manifest line for "web" was whichever
#: happened last: an NIV chapter from BibleGateway, or the World English Bible's USFM zip.
#: That made the newest-entry-per-source rule pick a copyrighted HTML page as the checksum
#: of a public-domain zip, and gave the built corpus the wrong fetch date. Found by
#: comparing the library digests of two machines.
ARCHIVE: Final = "biblegateway"

#: The colliding name, still read so that nothing already fetched is fetched again.
_LEGACY_ARCHIVE: Final = "web"

#: Seconds between requests. This is not a guess or a courtesy figure: BibleGateway's
#: robots.txt publishes ``Crawl-delay: 15``, and asking faster than a host has said it
#: wants is the difference between using a service and abusing it. Fifteen seconds is
#: slow, which is the point -- the whole design fetches a chapter once, ever, and serves
#: every later citation in it from the database.
CRAWL_DELAY: Final = 15.0

#: Versions this has been checked against. Others may work; these are the Catholic
#: editions the provider was built for.
KNOWN_VERSIONS: Final[dict[str, str]] = {
    "NRSVCE": "New Revised Standard Version Catholic Edition",
    "NRSVACE": "New Revised Standard Version Anglicised Catholic Edition",
    "NABRE": "New American Bible Revised Edition",
    "RSVCE": "Revised Standard Version Catholic Edition",
    "RSV2CE": "Revised Standard Version Second Catholic Edition",
    "GNTCE": "Good News Translation Catholic Edition",
    "NCB": "St. Joseph New Catholic Bible",
    "DRA": "Douay-Rheims 1899 American Edition",
    # Not Catholic editions, and here for a different reason: between them these are most
    # of what has been sold and preached in English since 1901, so a quotation heard in a
    # sermon is very likely to be one of them. Every one is under live copyright and none
    # can be lawfully bulk-downloaded, so they are reachable only the way everything here
    # is reachable -- a chapter at a time, once ever, at the site's published crawl delay.
    # See :mod:`biblereference.search` for the resolution pass that asks for them only
    # when a passage is identified and its translation is not.
    "NIV": "New International Version",
    "ESV": "English Standard Version",
    "NKJV": "New King James Version",
    "NASB": "New American Standard Bible 2020",
    "NASB1995": "New American Standard Bible 1995",
    "CSB": "Christian Standard Bible",
    "NLT": "New Living Translation",
    "MSG": "The Message",
    "TLB": "The Living Bible",
    "GNT": "Good News Translation",
    "RSV": "Revised Standard Version",
    "NIRV": "New International Reader's Version",
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


def parse_passage(html: str) -> dict[int, dict[int, str]]:
    """Read a BibleGateway page into ``{chapter: {verse: text}}``.

    Verse text is split across several spans -- a line of poetry each -- all carrying the
    same ``Book-Chapter-Verse`` class, so spans are grouped by that class rather than read
    one to a verse. The chapter comes from the same class, which is what lets one request
    cover a passage spanning several chapters.
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

    pieces: dict[tuple[int, int], list[str]] = {}
    for span in passage.select("span.text"):
        classes = span.get("class") or []
        match = next((m for m in (_VERSE_CLASS_RE.match(str(c)) for c in classes) if m), None)
        if match is None:
            continue
        text = span.get_text(" ", strip=True)
        if text:
            pieces.setdefault((int(match["chapter"]), int(match["verse"])), []).append(text)

    out: dict[int, dict[int, str]] = {}
    for (chapter, verse), parts in sorted(pieces.items()):
        joined = re.sub(r"\s+([,;:.!?’”)])", r"\1", " ".join(parts)).strip()
        out.setdefault(chapter, {})[verse] = joined
    return out


def parse_chapter(html: str) -> dict[int, str]:
    """Read a single-chapter page into ``{verse number: text}``."""
    chapters = parse_passage(html)
    if not chapters:
        return {}
    return chapters[min(chapters)]


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
    :param max_chapters: Most chapters to ask for in one request. A citation spanning
        several chapters becomes one request rather than several; the cap stops a wide
        citation from asking for a whole book at once.
    """

    versification = "eng"
    language = "en"

    def __init__(
        self,
        version: str,
        home: DataHome,
        *,
        delay: float = CRAWL_DELAY,
        offline: bool = False,
        timeout: float = 30.0,
        max_chapters: int = 5,
    ) -> None:
        self._version = version.strip().upper()
        self._home = home
        self._delay = delay
        self._offline = offline
        self._timeout = timeout
        self._max_chapters = max(1, max_chapters)
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
        for ref in refs:
            if ref.is_letter_chapter:
                raise VerseUnavailable(ref, self.label, "letter chapters are not supported")

        self._ensure({(ref.book, int(ref.chapter)) for ref in refs})  # type: ignore[arg-type]

        out: list[VerseText] = []
        for ref in refs:
            text = self._cache.chapters[(ref.book, int(ref.chapter))].get(ref.verse)  # type: ignore[arg-type]
            if not text:
                # Not a failure to fetch: the chapter was read in full and this verse is
                # not in it. The NRSV relegates a few verses of Sirach to footnotes.
                raise VerseUnavailable(ref, self.label, "the version does not print this verse")
            out.append(VerseText(ref=ref, text=text))
        return out

    # -- getting chapters --------------------------------------------------------------

    def _ensure(self, wanted: set[tuple[str, int]]) -> None:
        """Make sure every named chapter is in memory, reading or fetching as needed.

        Three places are tried in turn, cheapest first: this run's memory, the database of
        chapters already read, and the archived HTML. Only what is in none of them is
        fetched, and then in as few requests as possible.
        """
        missing: list[tuple[str, int]] = []
        for book, chapter in sorted(wanted):
            if (book, chapter) in self._cache.chapters:
                continue
            stored = read_chapter(self._home, self.id, book, chapter)
            if stored is not None:
                self._cache.chapters[(book, chapter)] = stored
                self._recall_attribution()
                continue
            html = self._archived(book, chapter)
            if html is not None:
                self._absorb(book, {chapter: parse_chapter(html)}, html)
                continue
            missing.append((book, chapter))

        if not missing:
            return
        if self._offline:
            book, chapter = missing[0]
            raise VerseUnavailable(
                VerseRef(book, chapter, 1),
                self.label,
                "not in the archive, and fetching is switched off",
            )
        for book, first, last in _runs(missing, self._max_chapters):
            self._download(book, first, last)

    def _absorb(self, book: str, chapters: dict[int, dict[int, str]], html: str) -> None:
        """Keep every chapter a page contained, not only the verses that were asked for.

        This is the whole reason for fetching by chapter: one request yields a chapter,
        and storing all of it means the next citation from anywhere in that chapter costs
        nothing.
        """
        if self._attribution is None:
            self._attribution = parse_copyright(html)

        for chapter, verses in chapters.items():
            if not verses:
                continue
            self._cache.chapters[(book, chapter)] = verses
            add_chapter(self._home, self._meta(), book, chapter, verses)

    def _recall_attribution(self) -> None:
        """Take the copyright line from the database when serving a stored chapter.

        It was read off the page when the chapter was first fetched, and the publisher's
        notice has to appear whether or not this run touched the network.
        """
        if self._attribution is not None:
            return
        for meta in read_meta(self._home):
            if meta.corpus == self.id and meta.attribution:
                self._attribution = meta.attribution
                return

    def _meta(self) -> SourceMeta:
        return SourceMeta(
            corpus=self.id,
            label=self.label,
            language=self.language,
            versification=self.versification,
            license=f"{self.label}: under copyright. Fetched for personal study.",
            attribution=self._attribution,
            source_url=_BASE,
        )

    def _archive_name(self, book: str, chapter: int) -> str:
        return f"{self._version}/{book}_{chapter}.html"

    def _archived(self, book: str, chapter: int) -> str | None:
        """Look through every dated archive directory, newest first.

        Both namespaces, because pages fetched before this module stopped calling itself
        ``web`` are still on disk and a request to a publisher's site is the one cost this
        whole design exists to pay only once.
        """
        for namespace in (ARCHIVE, _LEGACY_ARCHIVE):
            base = self._home.sources / namespace
            if not base.is_dir():
                continue
            for dated in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True):
                path = dated / self._archive_name(book, chapter)
                if path.is_file():
                    return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _download(self, book: str, first: int, last: int) -> None:
        """One request for a run of consecutive chapters."""
        name = _BOOK_NAMES.get(book) or book_title(book)
        span = f"{first}" if first == last else f"{first}-{last}"
        params = {"search": f"{name} {span}", "version": self._version}

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
            raise CorpusError(f"could not fetch {name} {span} ({self._version}): {exc}") from exc
        finally:
            self._last_request = time.monotonic()

        chapters = parse_passage(response.text)
        if not chapters:
            raise CorpusError(
                f"{self.label} returned no text for {name} {span}; the book may not be in "
                f"this version, or its name may differ on the site"
            )

        # Archive the page once per chapter it covers, so that a later run looking for any
        # one of them finds it without knowing how it was originally batched.
        for chapter in chapters:
            self._home.store_file(
                ARCHIVE,
                self._archive_name(book, chapter),
                response.content,
                url=str(response.url),
                license=f"{self.label}: under copyright. Fetched for personal study.",
                note=f"Covers {name} {span}. Archived so re-rendering never fetches again.",
            )
        self._absorb(book, chapters, response.text)


def _runs(chapters: list[tuple[str, int]], limit: int) -> list[tuple[str, int, int]]:
    """Group chapters into consecutive runs of one book, each at most ``limit`` long.

    A citation spanning Sirach 24 to 25 is one request rather than two. The cap keeps a
    wide citation from asking for a whole book in a single page.
    """
    out: list[tuple[str, int, int]] = []
    for book, chapter in sorted(chapters):
        if out and out[-1][0] == book and chapter == out[-1][2] + 1:
            start_book, first, last = out[-1]
            if last - first + 1 < limit:
                out[-1] = (start_book, first, chapter)
                continue
        out.append((book, chapter, chapter))
    return out


def _user_agent() -> str:
    return (
        "biblereference/0.1 (personal scripture-citation tool; whole chapters, cached permanently)"
    )
