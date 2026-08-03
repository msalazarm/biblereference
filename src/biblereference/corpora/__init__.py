"""Text sources: one module per edition of scripture."""

from .base import Corpus, CorpusError, VerseText, VerseUnavailable
from .pythonbible_source import PythonBibleCorpus, available_versions

__all__ = [
    "Corpus",
    "CorpusError",
    "PythonBibleCorpus",
    "VerseText",
    "VerseUnavailable",
    "available_versions",
]
