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

1 Enoch is here too and is *not* imported, and the reason is worse than it first looked.
The four files -- two Greek recensions, a German translation, a Latin fragment -- agree with
each other and with Dillmann's universal division: 108 chapters, about 1,078 verses, chapter
1 with nine verses and chapter 4 with one. ``org`` declares ``ENO`` with **42 chapters and
1,563 verses**, beginning 28, 42, 30, 88, and it is upstream's own data rather than anything
corrected here.

So this is not a book that needs lengthening; whatever ``org``'s ``ENO`` describes, it is not
the book these witnesses transmit, and no chapter of it matches. ``extend_books`` cannot help
-- extending 42 to 108 would leave the first 42 declaring counts nothing holds. Importing
would need ``org``'s ``ENO`` rewritten wholesale, which is a claim about upstream being wrong
that nothing here can support. Written up in ``docs/versification-audit.md``.

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
