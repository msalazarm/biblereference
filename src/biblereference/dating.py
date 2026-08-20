"""When each rendering's wording became available to be read.

This exists to stop the library making a claim it cannot support. Naming the translation a
quotation came from is sound for a sermon transcript, which is what it was built for: the
preacher was holding a Bible and the wording says which. It is not sound for a father who
died in 407 and reaches us through a Victorian translator, and the library said it anyway --
a scripture quotation in Schaff's Chrysostom matches the King James word for word, so
``identified`` came back true and ``kjv`` was named.

The words really do match. What does not follow is that Chrysostom read them. Two claims
were being run together:

1. *these words match translation X* -- a fact about the text in hand, always checkable
2. *the author was reading translation X* -- an inference, sound only if he could have been

The second is what a reader takes from a named translation, and for a patristic corpus it is
usually false. What is true, and worth keeping rather than suppressing, is the first: that
Schaff rendered patristic scripture in King James register is a real fact about Victorian
editorial practice, and a study of who quotes what should be able to see it.

**The date is of the wording, not of the edition.** That distinction is the whole point.
Swete's Septuagint is an 1890s edition of an ancient text: Chrysostom could read those Greek
words, so it is not anachronistic to him, and dating it 1894 would fire the flag on every
Greek father against the very corpus they actually quoted. By the same reasoning the King
James modernised in 2006 is dated 1611, because its wording is the wording of 1611 with the
spelling tidied, and the Nova Vulgata is dated 1979 despite being Latin, because it is a
genuinely new translation rather than an edition of Jerome's.

A ``None`` means the wording is ancient -- a source-language text, or a critical edition of
one -- so it is anachronistic to nobody.
"""

from __future__ import annotations

from typing import Final

__all__ = ["TRANSLATED", "anachronistic", "translated"]

#: Corpus id to the year its *wording* became available, or ``None`` where the wording is
#: ancient. Dates are of first publication of that rendering; a later edition that only
#: modernises spelling does not move it.
TRANSLATED: Final[dict[str, int | None]] = {
    # -- source-language texts: the words are ancient, whatever the edition ---------------
    "wlc": None,  # Westminster Leningrad Codex: the Masoretic text
    "n1904": None,  # Nestle 1904: a critical edition of the Greek New Testament
    "swete": None,  # Swete: a critical edition of the Septuagint
    "swete-daniel": None,  # Theodotion's Greek Daniel, likewise
    "rahlfs": None,  # Rahlfs 1935: another critical edition of the same ancient Greek
    "rahlfs-cc": None,  # the same edition, transcribed independently
    "rahlfs-alt": None,  # the second text where Rahlfs prints two
    "sblgnt": None,  # the SBL Greek New Testament: a critical edition, ancient wording
    "wh": None,  # Westcott and Hort 1881, likewise a critical edition of ancient Greek
    "grcbyz": None,  # Robinson-Pierpont: the Byzantine Textform, ancient wording throughout
    "grcant": None,  # Antoniades 1904/1912: the received Patriarchal text, ancient wording
    "coptic-mark": None,  # the Sahidic version: a third-century translation
    "sahot": None,  # the Sahidic Old Testament: the same third-century version, whole
    "smp": None,  # the Samaritan Pentateuch: the other tradition's Torah, ancient wording
    # The Peshitta is a translation, but a second-century one, so its wording is as
    # ancient as anything else in this section and nothing here can be anachronistic to it.
    "peshitta-ot": None,
    "peshitta-nt": None,
    "peshitta-alt": None,
    # The Old Latin gospels are pre-Jerome, which is the whole reason to hold them: their
    # wording is older than the Vulgate's and nothing can be anachronistic to it.
    "oldlatin-a": None,
    "oldlatin-b": None,
    # The other two of Bianchini's four. Their verse divisions are this library's rather
    # than the edition's, but the wording is the manuscript's and is what dating is about.
    # Brixianus is the latest of the four and the most Vulgate-like -- it is a witness to
    # the revised tradition Jerome worked from, not to an untouched Old Latin -- but it is
    # still pre-Jerome and nothing can be anachronistic to it.
    "oldlatin-f": None,
    "oldlatin-ff2": None,
    "bezae-lat": None,  # Codex Bezae's Latin column: a third pre-Vulgate witness, with Acts
    "latvuc": 405,  # Jerome's Vulgate; the Clementine of 1592 is an edition of it
    "novavulgata": 1979,  # a new Latin translation, not an edition of Jerome
    "castellio": 1551,  # a new Latin translation from the originals, owing nothing to Jerome
    # -- English, in order of when the wording was made -----------------------------------
    "wycliffe": 1395,
    "wyc2017": 1395,  # Wycliffe with the spelling modernised
    "wyc2018": 1395,
    "tnt": 1534,  # Tyndale's New Testament
    "gnv": 1599,
    "kjv": 1611,
    "kjv2006": 1611,  # the King James, spelling modernised
    "kjvcpb": 1611,  # the Cambridge Paragraph Bible: the 1611 text, repunctuated
    "dra": 1752,  # Challoner's revision, which is the Douay-Rheims anyone reads
    "arbvd": 1865,  # Smith-Van Dyck: the received Arabic Protestant translation
    "chuelz": 1757,  # the Elizabeth Bible: the Orthodox world's Slavonic text
    "webster": 1833,
    "brenton": 1844,
    "ottley": 1904,  # an English translation of the Septuagint as Codex Alexandrinus has it
    "lee": 1853,
    "oke": 1862,  # Etheridge's English of the Targum
    "ylt": 1862,
    "noy": 1869,
    "rv": 1885,
    "dby": 1890,
    "asv": 1901,
    "jps": 1917,
    "bbe": 1949,
    "glw": 1996,
    "web": 1997,
    "webbe": 1997,
    "webc": 1997,
    "webp": 1997,
    "webpb": 1997,
    "webu": 1997,
    "wmb": 1997,
    "wmbb": 1997,
    "niv": 2011,
    "ojb": 2002,
    "emtv": 2003,
    "net": 2005,
    "oebcw": 2010,
    "oebus": 2010,
    "asvbt": 2010,
    "lxx2012": 2012,
    "lxx2012uk": 2012,
    "f35": 2014,
    "ourb": 2016,
    "t4t": 2017,
    "fbv": 2018,
    "lxxup": 2019,
    "ulb": 2019,
    "bsb": 2020,
    "lsv": 2020,
    "tcent": 2022,
    "msb": 2023,
    "e2t": 2025,
}


def translated(corpus: str) -> int | None:
    """When this rendering's wording was made, or ``None`` if it is ancient or unknown."""
    return TRANSLATED.get(corpus)


def anachronistic(corpus: str, composed: int) -> bool:
    """Whether ``corpus`` could not have been read by a text written in ``composed``.

    A corpus with no date recorded is never called anachronistic. Silence is not evidence,
    and a false accusation here would be worse than none: it would suppress a real
    attribution.
    """
    when = TRANSLATED.get(corpus)
    return when is not None and when > composed
