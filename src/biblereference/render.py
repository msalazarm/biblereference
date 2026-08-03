"""Turning citation tags into text.

The pipeline for one tag: parse the reference in whatever numbering it was written in,
check it exists, work out which texts to show, convert the reference into each text's own
numbering, fetch the verses, and hand the result to a template.

Failure is visible, not silent. A citation that cannot be resolved is left in the output
exactly as written and reported, so an unrendered tag in the draft is the signal that
something needs attention -- never a quietly wrong verse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from .canon import AmbiguousBookError, Canon, NamingScheme, UnknownBookError, book_canon
from .corpora.base import Corpus, CorpusError, VerseText, VerseUnavailable
from .refs import ReferenceParseError, VerseRange, parse_reference
from .tags import Citation, TagSyntaxError, find_citations
from .versification import Versification, VersificationError

__all__ = [
    "Config",
    "RenderReport",
    "Renderer",
    "Rendition",
    "ResolvedCitation",
]

_TEMPLATE_DIR: Final = Path(__file__).parent / "templates"

_LANGUAGE_NAMES: Final[Mapping[str, str]] = {
    "en": "English",
    "grc": "Greek",
    "hbo": "Hebrew",
    "la": "Latin",
}

#: Languages written right to left. Their text is wrapped in a Unicode directional
#: isolate so that neighbouring Markdown punctuation does not reorder on screen.
_RTL: Final = frozenset({"hbo"})


@dataclass(frozen=True)
class Config:
    """How to render, when a tag does not say.

    :param default_english: Version to quote in English. Anything
        :func:`~biblereference.corpora.available_versions` offers, or a version served by
        an online provider once one is configured.
    :param deuterocanon_english: English version for books ``default_english`` lacks.
        The ASV and KJV have no deuterocanon, so Sirach and Tobit fall back here.
    :param original: Default for ``original=``.
    :param template: Template for full tags.
    :param inline_template: Template for the short ``{{...}}`` form, which renders inline
        so a sentence citing a verse in passing stays a sentence.
    :param naming: Which tradition's book names to expect.
    :param vrs: Versification references are written in.
    :param strict: Turn warnings -- an unverified quotation, a missing original -- into
        errors.
    :param template_dir: Directory of your own templates, searched before the built-ins.
    :param attribution: Append the credit lines that the texts' licences require.
    """

    default_english: str = "ASV"
    deuterocanon_english: str = "DRA"
    original: str = "auto"
    template: str = "blockquote"
    inline_template: str = "inline"
    naming: NamingScheme = NamingScheme.MODERN
    vrs: str = "eng"
    strict: bool = False
    data_home: Path | None = None
    template_dir: Path | None = None
    attribution: bool = True


@dataclass(frozen=True, slots=True)
class Rendition:
    """One text's version of a passage, ready to render."""

    corpus_id: str
    label: str
    language: str
    reference: str
    """The passage in this corpus's own numbering, which may differ from the citation."""
    text: str
    attribution: str | None = None
    renumbered: bool = False
    """Whether this corpus numbers the passage differently from the citation, in which
    case the reference above is worth printing."""

    @property
    def short_label(self) -> str:
        """Compact name for inline use, e.g. ``ASV``."""
        return self.corpus_id.upper()

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAMES.get(self.language, self.language)

    @property
    def rtl(self) -> bool:
        return self.language in _RTL


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """A citation with its texts found."""

    citation: Citation
    reference: str
    renditions: tuple[Rendition, ...]
    warnings: tuple[str, ...] = ()


@dataclass
class RenderReport:
    """What happened to a document."""

    total: int = 0
    resolved: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    attributions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether every citation resolved."""
        return not self.errors

    def summary(self) -> str:
        parts = [f"{self.resolved}/{self.total} citations resolved"]
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        return ", ".join(parts)


class CitationError(ValueError):
    """A citation could not be resolved."""


#: Everything that can go wrong with one citation without the document being at fault.
#: Each is reported against that citation and the rest of the document still renders.
_CITATION_FAILURES: Final = (
    CitationError,
    ReferenceParseError,
    VersificationError,
    UnknownBookError,
    AmbiguousBookError,
    CorpusError,
    VerseUnavailable,
)


class Renderer:
    """Expands citation tags in Markdown.

    :param config: Defaults for anything a tag does not specify.
    :param corpora: Text sources, keyed by id. Defaults to the public-domain English
        versions ``pythonbible`` provides.
    """

    def __init__(
        self,
        config: Config | None = None,
        corpora: Mapping[str, Corpus] | None = None,
        versification: Versification | None = None,
    ) -> None:
        self.config = config or Config()
        self.versification = versification or Versification.load()
        self._corpora: dict[str, Corpus] = dict(corpora or {})
        self._env = self._build_environment()

    # -- corpora -----------------------------------------------------------------------

    def add_corpus(self, corpus: Corpus) -> None:
        """Register a text source, replacing any with the same id."""
        self._corpora[corpus.id] = corpus

    def _english(self, name: str) -> Corpus:
        """Find, and lazily construct, an English corpus by version name."""
        key = name.strip().lower()
        if key in self._corpora:
            return self._corpora[key]

        from .corpora.pythonbible_source import PythonBibleCorpus

        corpus = PythonBibleCorpus(name)
        self._corpora[corpus.id] = corpus
        return corpus

    # -- rendering ---------------------------------------------------------------------

    def render_file(self, source: str | Path, target: str | Path) -> RenderReport:
        """Render ``source`` into ``target``.

        :returns: What happened, including anything that did not resolve.
        """
        source, target = Path(source), Path(target)
        rendered, report = self.render_text(source.read_text(encoding="utf-8"))
        target.write_text(rendered, encoding="utf-8")
        return report

    def render_text(self, text: str) -> tuple[str, RenderReport]:
        """Render a document held in memory."""
        report = RenderReport()
        pieces: list[str] = []
        footnotes: list[str] = []
        cursor = 0

        for citation in self._scan(text, report):
            report.total += 1
            pieces.append(text[cursor : citation.start])
            cursor = citation.end
            try:
                resolved = self.resolve(citation)
                rendered = self._render_one(resolved, footnotes)
            except _CITATION_FAILURES as exc:
                report.errors.append(f"{citation.reference}: {exc}")
                pieces.append(citation.raw)  # leave the tag visible in the output
                continue

            report.resolved += 1
            report.warnings.extend(resolved.warnings)
            for rendition in resolved.renditions:
                if rendition.attribution and rendition.attribution not in report.attributions:
                    report.attributions.append(rendition.attribution)

            pieces.append(rendered)

        pieces.append(text[cursor:])
        out = "".join(pieces)

        if footnotes:
            out = out.rstrip("\n") + "\n\n" + "\n".join(footnotes) + "\n"
        if self.config.attribution and report.attributions:
            out = out.rstrip("\n") + "\n\n" + _attribution_block(report.attributions)
        return out, report

    def _scan(self, text: str, report: RenderReport) -> list[Citation]:
        """Read every tag, recording syntax errors rather than aborting the document."""
        found: list[Citation] = []
        try:
            found.extend(find_citations(text))
        except TagSyntaxError as exc:
            report.errors.append(str(exc))
        return found

    # -- resolution --------------------------------------------------------------------

    def resolve(self, citation: Citation) -> ResolvedCitation:
        """Find every text a citation asks for.

        :raises CitationError: the reference does not resolve, or no text could be found.
        """
        span = parse_reference(
            citation.reference,
            vrs=citation.vrs or self.config.vrs,
            naming=citation.naming or self.config.naming,
        )
        self.versification.validate(span)

        warnings: list[str] = []
        renditions: list[Rendition] = []

        english = self._english_rendition(citation, span, warnings)
        if english is not None:
            renditions.append(english)

        if not renditions:
            raise CitationError("; ".join(warnings) or f"no text found for {span.pretty()}")

        if self.config.strict and warnings:
            raise CitationError("; ".join(warnings))

        return ResolvedCitation(
            citation=citation,
            reference=span.pretty(),
            renditions=tuple(renditions),
            warnings=tuple(warnings),
        )

    def _english_rendition(
        self, citation: Citation, span: VerseRange, warnings: list[str]
    ) -> Rendition | None:
        """Fetch the English text, falling back for books the chosen version lacks."""
        requested = citation.english or self.config.default_english
        candidates = [requested]
        if book_canon(span.book) is not Canon.HEBREW and book_canon(span.book) is not Canon.NT:
            # The ASV and KJV stop at Malachi and Revelation; a Catholic Bible does not.
            candidates.append(self.config.deuterocanon_english)

        last_error: Exception | None = None
        for name in dict.fromkeys(candidates):
            try:
                corpus = self._english(name)
            except CorpusError as exc:
                last_error = exc
                continue
            if not corpus.has_book(span.book):
                last_error = VerseUnavailable(span.start, corpus.label)
                continue
            try:
                return self._fetch(corpus, span)
            except (VerseUnavailable, CorpusError) as exc:
                last_error = exc
                continue

        tried = ", ".join(dict.fromkeys(candidates))
        warnings.append(
            f"no English text for {span.pretty()} in {tried}"
            + (f" -- {last_error}" if last_error else "")
        )
        return None

    def _fetch(self, corpus: Corpus, span: VerseRange) -> Rendition:
        """Convert a passage into a corpus's numbering and read it."""
        segments = self.versification.convert_range(span, corpus.versification)
        verses: list[VerseText] = []
        for segment in segments:
            verses.extend(corpus.fetch(self.versification.expand(segment)))

        return Rendition(
            corpus_id=corpus.id,
            label=corpus.label,
            language=corpus.language,
            reference=", ".join(segment.pretty() for segment in segments),
            text=" ".join(verse.text for verse in verses).strip(),
            attribution=corpus.attribution,
            renumbered=[str(s) for s in segments] != [str(span)],
        )

    # -- templates ---------------------------------------------------------------------

    def _build_environment(self) -> Environment:
        directories = [str(_TEMPLATE_DIR)]
        if self.config.template_dir is not None:
            directories.insert(0, str(self.config.template_dir))
        env = Environment(
            loader=FileSystemLoader(directories),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
            autoescape=False,  # Markdown out, not HTML
        )
        env.filters["isolate"] = _isolate
        return env

    def _render_one(self, resolved: ResolvedCitation, footnotes: list[str]) -> str:
        name = (
            resolved.citation.template
            or (self.config.inline_template if resolved.citation.inline else None)
            or self.config.template
        )
        try:
            template = self._env.get_template(f"{name}.md.j2")
        except TemplateNotFound as exc:
            raise CitationError(f"no template named {name!r}") from exc

        marker = len(footnotes) + 1
        out = template.render(
            citation=resolved.citation,
            reference=resolved.reference,
            renditions=resolved.renditions,
            english=next((r for r in resolved.renditions if r.language == "en"), None),
            originals=[r for r in resolved.renditions if r.language != "en"],
            marker=marker,
            footnotes=footnotes,
        )
        return out.strip("\n") if "\n" in out else out


def _isolate(text: str, rtl: bool = True) -> str:
    """Wrap right-to-left text in a Unicode directional isolate.

    Without this, a Hebrew phrase followed by Markdown punctuation renders with the
    punctuation on the wrong side.
    """
    return f"⁨{text}⁩" if rtl else text


def _attribution_block(attributions: Sequence[str]) -> str:
    lines = "\n".join(f"- {a}" for a in attributions)
    return f"---\n\n*Texts quoted above:*\n\n{lines}\n"
