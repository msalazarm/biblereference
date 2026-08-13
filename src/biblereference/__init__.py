"""Expand scripture citation tags in Markdown into verified verse text.

    >>> from biblereference import Config, Renderer
    >>> renderer = Renderer(Config(default_english="ASV"))
    >>> out, report = renderer.render_text("As {{Luke 2:42}} says...")
    >>> report.ok
    True

The Catholic canon is in scope throughout, and references are resolved through the
original-language versification, so a passage cited in one tradition's numbering comes
back correctly in another's. Where the data cannot support that honestly -- the Vulgate's
Sirach, Esther's Greek additions -- resolution refuses rather than guessing.
"""

from __future__ import annotations

from .canon import (
    AmbiguousBookError,
    Canon,
    NamingScheme,
    UnknownBookError,
    book_canon,
    book_title,
    resolve_book,
)
from .compare import BookComparison, VerseDifference, compare_corpora
from .corpora import Corpus, CorpusError, VerseText, VerseUnavailable
from .emphasis import SpanNotFoundError, apply_spans, fold
from .passage import PassageReader, ResolvedPassage
from .quotecheck import QuoteCheck, check_quotation
from .refs import ReferenceParseError, VerseRange, VerseRef, parse_reference
from .render import (
    CitationError,
    Config,
    Renderer,
    RenderReport,
    Rendition,
    ResolvedCitation,
)
from .tags import Citation, Emphasis, TagSyntaxError, find_citations
from .versification import (
    UnknownVersificationError,
    VerseOutOfRangeError,
    Versification,
    VersificationError,
    VersificationGapError,
)

__version__ = "0.1.0"

__all__ = [
    "AmbiguousBookError",
    "BookComparison",
    "Canon",
    "Citation",
    "CitationError",
    "Config",
    "Corpus",
    "CorpusError",
    "Emphasis",
    "NamingScheme",
    "PassageReader",
    "QuoteCheck",
    "ReferenceParseError",
    "RenderReport",
    "Renderer",
    "Rendition",
    "ResolvedCitation",
    "ResolvedPassage",
    "SpanNotFoundError",
    "TagSyntaxError",
    "UnknownBookError",
    "UnknownVersificationError",
    "VerseDifference",
    "VerseOutOfRangeError",
    "VerseRange",
    "VerseRef",
    "VerseText",
    "VerseUnavailable",
    "Versification",
    "VersificationError",
    "VersificationGapError",
    "__version__",
    "apply_spans",
    "book_canon",
    "book_title",
    "check_quotation",
    "compare_corpora",
    "find_citations",
    "fold",
    "parse_reference",
    "resolve_book",
]
