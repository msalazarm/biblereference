"""What First1KGreek holds that this library does not already have.

Two things, and the short list is the finding. First1KGreek's ``tlg0527`` **is Swete's
Septuagint**, which the library already holds from another digitisation, and the overlap
is exact rather than approximate: Judges 618 verses against 618, Susanna 64 against 64.
Importing them would have doubled the text and told nobody anything.

    A digest comparison of the two digitisations is still worth doing and is not done
    here. Two independent transcriptions of one printed edition that disagree do so
    because one of them is wrong, and finding out costs a diff rather than a download.

So this brings the two files that are not Swete:

* **Ottley's Isaiah** -- an English translation of the Septuagint *as it stands in one
  manuscript*, Codex Alexandrinus, which is a different object from Brenton and useful
  exactly where the manuscripts disagree.
* **Coptic Mark** -- one chapter, 45 verses, and the only Coptic anywhere in this
  library. Worth having as the seed of a language rather than for its coverage.

1 Enoch is here too and is *not* imported yet. ``org`` declares 42 chapters; the Greek
recension runs to 89, the German to 108 and the Latin fragment is chapter 106 alone. Until
a versification can be told that a book got longer, importing it would put verses where
nothing can cite them.

The INTF's Mark is likewise held back. It is a diplomatic transcription -- ``<ab>`` inside
chapter divisions, and an apparatus of ``<rdg type="orig">`` and ``<rdg type="corr">`` with
no ``<lem>`` at all -- so the reader here would take the chapter's structure and none of
its words. 754 words is not worth a fourth shape.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

from lxml import etree

from ..licences import get
from ..refs import VerseRef
from ..sources import BuiltCorpus, RemoteFile, Source
from .tei import cts_verses, read_licence

__all__ = ["SOURCE", "build"]

_RAW: Final = "https://raw.githubusercontent.com/OpenGreekAndLatin/First1KGreek/master/data"

#: ``corpus id -> (path under data/, book, label, language, versification)``.
WANTED: Final[Mapping[str, tuple[str, str, str, str, str]]] = {
    "ottley": (
        "tlg0527/tlg048/tlg0527.tlg048.1st1K-eng1.xml",
        "ISA",
        "Isaiah according to the Septuagint (Codex Alexandrinus) — Ottley 1904",
        "en",
        "lxx",
    ),
    "coptic-mark": (
        "tlg0031/tlg002/tlg0031.tlg002.1st1K-cop1.xml",
        "MRK",
        "Mark in Sahidic Coptic — Coptic Scriptorium",
        "cop",
        "org",
    ),
}

#: Where a file declares no licence we can read, what to record instead. Never guessed:
#: Coptic Scriptorium publishes under its own terms rather than the CC BY-SA that covers
#: the rest of the repository, and the file's header says so by pointing at their site.
FALLBACK: Final[Mapping[str, str]] = {"coptic-mark": "coptic-scriptorium"}


def build(archive: Path) -> Iterator[BuiltCorpus]:
    for corpus, (relative, book, label, language, versification) in WANTED.items():
        path = archive / relative.rsplit("/", 1)[-1]
        if not path.exists():
            continue
        declared = read_licence(path)
        notes = []
        licence = declared
        if licence is None and corpus in FALLBACK:
            licence = get(FALLBACK[corpus])
            notes.append(
                "The file declares no licence this library recognises; its header points "
                "at the distributor's own terms, which is what has been recorded."
            )
        verses = [
            (VerseRef(book, chapter, verse, subverse), text)
            for chapter, verse, subverse, text in cts_verses(etree.parse(str(path)))
        ]
        yield BuiltCorpus(
            id=corpus,
            label=label,
            language=language,
            versification=versification,
            verses=verses,
            notes=notes,
            licence=licence,
            licences=(licence,) if licence else (),
        )


SOURCE: Final = Source(
    id="first1k",
    label="First1KGreek — Ottley's Isaiah and the Coptic Mark",
    homepage="https://github.com/OpenGreekAndLatin/First1KGreek",
    license=(
        "CC BY-SA 4.0 for the repository, except the Coptic, which carries Coptic "
        "Scriptorium's own terms."
    ),
    files=tuple(
        RemoteFile(url=f"{_RAW}/{relative}", name=relative.rsplit("/", 1)[-1])
        for relative, *_ in WANTED.values()
    ),
    build=lambda archive: build(archive),
)
