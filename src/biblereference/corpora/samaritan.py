"""The Samaritan Pentateuch: the Torah as the other tradition kept it.

quotes.md §11's last breadth row. When Origen cites "the Samaritan text", when Eusebius
and Jerome discuss Samaritan readings, this is the text they mean — here in Stefan
Schorch's critical edition (MS Dublin Chester Beatty 751, completed from MS Garizim 1),
via DT-UCPH's Text-Fabric dataset, pinned at version 7.1.3.

**Licence corrected**: the §11 ledger recorded CC BY 4.0; every version of the dataset
itself declares **CC BY-NC 4.0** in its own file headers. Non-commercial is a licence
the registry already models — Corpus Corporum set the precedent — so the text is held,
and the constraint is recorded where it can be asked about.

Text-Fabric is parsed directly — five feature files and no dependency. ``otype.tf``
names the node ranges (signs are the slots; words, verses, chapters, books stack above
them), ``oslots.tf`` maps each higher node to its sign range, and a verse's text is its
words' ``g_cons_utf8`` joined by each word's own ``trailer`` — the dataset's clitic
convention, which is what turns the segmented ``ב + ראשׁית`` back into בראשׁית. The
result is consonantal Hebrew in square script, ``hbo`` in ``org`` numbering, the same
shelf the Leningrad Codex stands on — which is exactly what lets a Samaritan reading be
laid beside the Masoretic one.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..canon import resolve_book
from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source

__all__ = ["SOURCE", "build"]

_VERSION: Final = "7.1.3"
_RAW: Final = f"https://raw.githubusercontent.com/DT-UCPH/sp/master/tf/{_VERSION}"
_FILES: Final = ("otype", "oslots", "book", "chapter", "verse", "g_cons_utf8", "trailer")

_RANGE_RE: Final = re.compile(r"^(\d+)(?:-(\d+))?$")


def _data_lines(path: Path) -> Iterator[str]:
    """The data section: everything after the header, kept verbatim -- an empty line is
    an implicit node carrying an empty value, not noise."""
    seen_data = False
    lines = path.read_text("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the file's final newline, not an empty-valued node
    for line in lines:
        if not seen_data:
            if line.startswith("@"):
                continue
            seen_data = True
            if not line:
                continue  # the blank line that closes the header
        yield line


def _features(path: Path) -> dict[int, str]:
    """A node-feature file: ``node<TAB>value`` anchors, ``value`` alone advances by one."""
    out: dict[int, str] = {}
    node = 0
    for line in _data_lines(path):
        head, tab, value = line.partition("\t")
        anchor = _RANGE_RE.match(head) if tab else None
        if anchor:
            first = int(anchor.group(1))
            last = int(anchor.group(2) or first)
            for node in range(first, last + 1):
                out[node] = value
        else:
            node += 1
            out[node] = line
    return out


def _slots(path: Path) -> dict[int, tuple[int, int]]:
    """The oslots edge file: each non-slot node's first and last slot."""
    out: dict[int, tuple[int, int]] = {}
    node = 0
    for line in _data_lines(path):
        head, tab, spec = line.partition("\t")
        if tab:
            node = int(head)
        else:
            node += 1
            spec = head
        if not spec:
            continue
        edges = [int(n) for part in spec.split(",") for n in _RANGE_RE.match(part).groups() if n]  # type: ignore[union-attr]
        out[node] = (min(edges), max(edges))
    return out


def build(archive: Path) -> Iterator[BuiltCorpus]:
    kinds: dict[str, tuple[int, int]] = {}
    node = 0
    for line in _data_lines(archive / "otype.tf"):
        head, _, kind = line.partition("\t")
        mark = _RANGE_RE.match(head)
        if mark and kind:
            kinds[kind] = (int(mark.group(1)), int(mark.group(2) or mark.group(1)))
            node = kinds[kind][1]
        elif line:
            node += 1
            kinds[line] = (node, node)
    spans = _slots(archive / "oslots.tf")
    books = _features(archive / "book.tf")
    chapters = _features(archive / "chapter.tf")
    numbers = _features(archive / "verse.tf")
    words_text = _features(archive / "g_cons_utf8.tf")
    trailers = _features(archive / "trailer.tf")

    word_first, word_last = kinds["word"]
    words = sorted(range(word_first, word_last + 1), key=lambda w: spans[w][0])
    starts = [spans[w][0] for w in words]

    def book_of(slot: int) -> str:
        for node in range(kinds["book"][0], kinds["book"][1] + 1):
            first, last = spans[node]
            if first <= slot <= last:
                return books[node]
        raise ValueError(f"slot {slot} in no book")

    def chapter_of(slot: int) -> int:
        for node in range(kinds["chapter"][0], kinds["chapter"][1] + 1):
            first, last = spans[node]
            if first <= slot <= last:
                return int(chapters[node])
        raise ValueError(f"slot {slot} in no chapter")

    from bisect import bisect_left, bisect_right

    verses: list[tuple[VerseRef, str]] = []
    for node in range(kinds["verse"][0], kinds["verse"][1] + 1):
        first, last = spans[node]
        mine = words[bisect_left(starts, first) : bisect_right(starts, last)]
        text = unicodedata.normalize(
            "NFKD",
            "".join(words_text.get(w, "") + trailers.get(w, " ") for w in mine).strip(),
        )
        if not text:
            continue
        book = resolve_book(book_of(first))
        verses.append(
            (VerseRef(book, chapter_of(first), int(numbers[node]), vrs="org"), text)
        )
    yield BuiltCorpus(
        id="smp",
        label="Samaritan Pentateuch (Schorch edition, DT-UCPH Text-Fabric)",
        language="hbo",
        versification="org",
        verses=verses,
        notes=[
            "consonantal Hebrew in square script, words rejoined by the dataset's own "
            "clitic trailers; presentation forms decomposed to letter plus dot, the "
            "Leningrad Codex's own convention, so the two Torahs read in one encoding",
            "licence corrected against the §11 ledger: the dataset's own headers say "
            "CC BY-NC 4.0, not CC BY",
        ],
    )


SOURCE: Final = Source(
    id="samaritan",
    label="The Samaritan Pentateuch, Text-Fabric dataset (DT-UCPH)",
    homepage="https://github.com/DT-UCPH/sp",
    license="CC BY-NC 4.0, declared in every Text-Fabric file's header. The §11 ledger "
    "said CC BY; the files themselves win.",
    terms=get("cc-by-nc-4.0"),
    attribution="The Samaritan Pentateuch, ed. Stefan Schorch et al.; Text-Fabric "
    "dataset by Christian Canu Højgaard and Martijn Naaijer (DT-UCPH), CC BY-NC 4.0.",
    files=tuple(
        RemoteFile(url=f"{_RAW}/{name}.tf", name=f"{name}.tf") for name in _FILES
    ),
    build=build,
    note=f"Pinned at dataset version {_VERSION}; the Samaritan breadth row of "
    "quotes.md §11.",
)
