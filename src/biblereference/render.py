"""Turning citation tags into text.

The pipeline for one tag: parse the reference in whatever numbering it was written in,
check it exists, work out which texts to show, convert the reference into each text's own
numbering, fetch the verses, and hand the result to a template.

Failure is visible, not silent. A citation that cannot be resolved is left in the output
exactly as written and reported, so an unrendered tag in the draft is the signal that
something needs attention -- never a quietly wrong verse.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from .appendix import (
    QuotaFinding,
    RegisterEntry,
    Usage,
    check_quota,
    cross_scheme_references,
    public_domain_note,
    recommended_alternative,
)
from .canon import AmbiguousBookError, Canon, NamingScheme, UnknownBookError, book_canon
from .corpora.base import Corpus, CorpusError, VerseText, VerseUnavailable
from .corpora.web import CRAWL_DELAY
from .emphasis import SpanNotFoundError, apply_spans
from .quotecheck import DEFAULT_THRESHOLD, check_quotation
from .refs import ReferenceParseError, VerseRange, VerseRef, parse_reference
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

#: English versions that come from a fetched source rather than from ``pythonbible``,
#: so that asking for one before building says so instead of reporting it as unknown.
_FETCHED_ENGLISH: Final = frozenset({"webc", "dra"})


def _online_versions() -> frozenset[str]:
    """Versions that exist online, imported lazily to keep the web extra optional."""
    from .corpora.web import KNOWN_VERSIONS

    return frozenset(KNOWN_VERSIONS)


#: Which corpora answer each ``original=`` value, in order of preference.
#:
#: ``lxx`` lists Swete's Daniel second because Swete numbers Greek Daniel like the
#: Vulgate, so it is a separate corpus; asking for the Septuagint of a Daniel passage
#: should still find it.
DEFAULT_ROLES: Final[Mapping[str, tuple[str, ...]]] = {
    "hebrew": ("wlc",),
    "lxx": ("swete", "swete-daniel"),
    "greek": ("n1904",),
    "theodotion": ("swete-daniel",),
    "latin": ("latvuc",),
    "nova": ("novavulgata",),
}


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
    :param appendix: Append the passage register.
    :param notices: Append the copyright notices and permissions check.
    """

    default_english: str = "ASV"
    deuterocanon_english: str = "WEBC"
    vulgate_english: str = "DRA"
    """English for passages that exist only in Vulgate numbering -- Esther's additions
    above all, which the Vulgate appends as chapters 11 to 16 and no Greek-numbered text
    carries in that arrangement."""
    original: str = "auto"
    inline_original: str = "none"
    """Default for the short ``{{...}}`` form, which is meant to sit inside a sentence.
    Dropping a paragraph of Greek into the middle of a clause helps nobody, so the short
    form quotes English unless a tag asks for more."""
    template: str = "blockquote"
    inline_template: str = "inline"
    naming: NamingScheme = NamingScheme.MODERN
    vrs: str = "eng"
    strict: bool = False
    data_home: Path | None = None
    template_dir: Path | None = None
    appendix: bool = False
    """Append the passage register -- every passage the work cites, merged and printed in
    full. Off while drafting; a deliberate act for a finished piece."""
    notices: bool = True
    """Append the copyright notices. On, because they are an obligation rather than a
    preference wherever copyrighted text is quoted."""
    appendix_originals: tuple[str, ...] = ("hebrew", "lxx", "greek", "latin")
    """Which texts the register prints beside the English. The fullest form the corpora
    can supply, since the register is where a reader goes to check."""
    appendix_title: str = "Appendix Y — Passages Cited"
    notices_title: str = "Appendix Z — Sources and Permissions"
    online: bool = True
    """Whether a version that exists only online may be fetched. Naming such a version
    is itself the request, so this is on; set it False to guarantee no network use."""
    online_delay: float = CRAWL_DELAY
    """Seconds between online requests. Defaults to the delay BibleGateway's robots.txt
    actually asks for. Lower it and you are the problem."""
    offline: bool = False
    """Serve online versions only from what is already archived, never fetching."""
    quote_threshold: float = DEFAULT_THRESHOLD
    """How closely a supplied ``context=`` must match the resolved verse before it is
    reported. Loose by default, because your quotation is allowed to be a different
    translation -- it is a check against citing the wrong verse, not against
    disagreeing with the ASV."""
    supplied_label: str = "as quoted"
    """What to call a passage printed from ``context=`` rather than from a text this
    library holds."""
    roles: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_ROLES))
    """Which corpora serve each ``original=`` value, in order of preference. The first
    that carries the passage wins."""


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
    refs: tuple[VerseRef, ...] = ()
    """The verses this rendition actually covers, in the corpus's own numbering. Kept so
    that a permissions check can count distinct verses rather than estimate."""

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
    span: VerseRange | None = None
    """The reference as parsed, for merging into the register."""


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
        self._corpora: dict[str, Corpus] = (
            dict(corpora) if corpora is not None else self._load_built()
        )
        self._usage: dict[str, Usage] = {}
        self._env = self._build_environment()

    def _load_built(self) -> dict[str, Corpus]:
        """Open whatever ``biblereference build`` has already indexed.

        Done here rather than only in the CLI so that using the library is the same as
        using the command: fetch and build once, and every Renderer finds the texts.
        """
        from .store import DataHome, SqliteCorpus

        home = DataHome(self.config.data_home) if self.config.data_home else DataHome()
        if not home.database.exists():
            return {}
        return dict(SqliteCorpus.load_all(home))

    # -- corpora -----------------------------------------------------------------------

    def add_corpus(self, corpus: Corpus) -> None:
        """Register a text source, replacing any with the same id."""
        self._corpora[corpus.id] = corpus

    def _english(self, name: str) -> Corpus:
        """Find, and lazily construct, an English corpus by version name.

        A version assembled a chapter at a time is deliberately *not* served from the
        store, even though it is sitting there. Such a corpus holds only the chapters that
        have been asked for so far -- a run of the quotation search may have banked
        Isaiah 53 of the NIV and nothing else -- and serving it as though it were complete
        makes citing John 3:16 fall through to a different translation instead of fetching
        the one that was asked for. The online provider reads those same stored chapters
        first and fetches only what is missing, so it is strictly the better answer.
        """
        key = name.strip().lower()
        if key in self._corpora and not self._partial(key):
            return self._corpora[key]

        if key in _FETCHED_ENGLISH:
            raise CorpusError(
                f"{name.upper()} is not built. It comes from a downloaded source, so run "
                f"`biblereference fetch --source {key}` and then `biblereference build`."
            )

        from .corpora.web import KNOWN_VERSIONS

        if key.upper() in KNOWN_VERSIONS:
            corpus = self._online(key.upper())
            self._corpora[corpus.id] = corpus
            return corpus

        from .corpora.pythonbible_source import PythonBibleCorpus

        corpus = PythonBibleCorpus(name)
        self._corpora[corpus.id] = corpus
        return corpus

    def _partial(self, key: str) -> bool:
        """Whether this corpus was built a chapter at a time rather than in bulk.

        ``chapter_state`` records which chapters an incrementally-built corpus has read in
        full, and nothing else writes to it -- so its presence is exactly the question
        being asked.
        """
        if key.upper() not in _online_versions():
            return False
        from .store import DataHome, stored_chapters

        home = DataHome(self.config.data_home) if self.config.data_home else DataHome()
        return bool(stored_chapters(home, key))

    def _online(self, version: str) -> Corpus:
        """Build an online provider for a translation that exists nowhere local."""
        if not self.config.online:
            raise CorpusError(
                f"{version} is only available online, and online lookups are switched off "
                f"(Config(online=False)). Use a public-domain version, or switch them on."
            )

        from .corpora.web import BibleGatewayCorpus
        from .store import DataHome

        home = DataHome(self.config.data_home) if self.config.data_home else DataHome()
        return BibleGatewayCorpus(
            version, home, delay=self.config.online_delay, offline=self.config.offline
        )

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
        resolutions: list[ResolvedCitation] = []
        self._usage = {}
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
            resolutions.append(resolved)
            report.warnings.extend(resolved.warnings)
            for rendition in resolved.renditions:
                if rendition.attribution and rendition.attribution not in report.attributions:
                    report.attributions.append(rendition.attribution)

            pieces.append(rendered)

        pieces.append(text[cursor:])
        out = "".join(pieces)

        if footnotes:
            out = out.rstrip("\n") + "\n\n" + "\n".join(footnotes) + "\n"
        if self.config.appendix and resolutions:
            out = out.rstrip("\n") + "\n\n" + self._passage_register(resolutions, report)
        if self.config.notices and self._usage:
            out = out.rstrip("\n") + "\n\n" + self._notices(out, report)
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
            english = self._with_supplied_quotation(citation, english, span, warnings)
            renditions.append(english)
        renditions.extend(self._original_renditions(citation, span, warnings))

        if not renditions:
            raise CitationError("; ".join(warnings) or f"no text found for {span.pretty()}")

        renditions = [self._emphasise(citation, r) for r in renditions]

        if self.config.strict and warnings:
            raise CitationError("; ".join(warnings))

        return ResolvedCitation(
            citation=citation,
            reference=span.pretty(),
            renditions=tuple(renditions),
            warnings=tuple(warnings),
            span=span,
        )

    def _with_supplied_quotation(
        self,
        citation: Citation,
        english: Rendition,
        span: VerseRange,
        warnings: list[str],
    ) -> Rendition:
        """Print the author's own quotation, having checked it is that passage.

        ``context=`` exists so a treatise can quote the translation its author prefers.
        The text printed is therefore theirs; what the library adds is the assurance that
        it belongs to the verse cited.
        """
        if not citation.context:
            return english

        result = check_quotation(
            citation.context, english.text, threshold=self.config.quote_threshold
        )
        if not result.plausible:
            warnings.append(result.message(span.pretty()))

        return replace(
            english,
            text=citation.context.strip(),
            label=self.config.supplied_label,
            corpus_id="supplied",
        )

    def _emphasise(self, citation: Citation, rendition: Rendition) -> Rendition:
        """Apply the tag's emphasis spans for this rendition's language.

        :raises CitationError: an anchor is missing. Emphasis that silently failed to
            apply would be a claim about the source the output does not support.
        """
        spans = citation.emphasis.get(rendition.language)
        if not spans:
            return rendition
        try:
            return replace(
                rendition,
                text=apply_spans(rendition.text, spans, rendition.language),
            )
        except SpanNotFoundError as exc:
            raise CitationError(str(exc)) from exc

    def _original_renditions(
        self, citation: Citation, span: VerseRange, warnings: list[str]
    ) -> list[Rendition]:
        """Fetch the original-language texts a citation asks for.

        ``auto`` reads the book's canon: Hebrew for the Hebrew canon, Greek for the New
        Testament, the Septuagint for the deuterocanon -- where, for most books, no
        Hebrew survives to print. Latin is never automatic: the Vulgate is a translation,
        and printing one alongside the originals is a choice about what you are arguing.
        """
        default = self.config.inline_original if citation.inline else self.config.original
        choices = citation.original or (default,)
        if "none" in choices:
            return []
        if "auto" in choices:
            canon = book_canon(span.book)
            choices = (
                ("hebrew",)
                if canon is Canon.HEBREW
                else ("greek",)
                if canon is Canon.NT
                else ("lxx",)
            )

        out: list[Rendition] = []
        for role in choices:
            rendition, error = self._by_role(role, span)
            if rendition is not None:
                out.append(rendition)
            else:
                warnings.append(
                    f"no {role} text for {span.pretty()}" + (f" -- {error}" if error else "")
                )
        return out

    def _by_role(self, role: str, span: VerseRange) -> tuple[Rendition | None, Exception | None]:
        """Try each corpus registered for a role until one carries the passage."""
        last_error: Exception | None = None
        names = self.config.roles.get(role, ())
        if not names:
            return None, CorpusError(f"no corpus is registered for {role!r}")

        missing = [name for name in names if name not in self._corpora]
        for name in names:
            corpus = self._corpora.get(name)
            if corpus is None:
                continue
            try:
                return self._fetch(corpus, span), None
            except (VerseUnavailable, CorpusError, VersificationError) as exc:
                last_error = exc

        if last_error is None and missing:
            last_error = CorpusError(
                f"{', '.join(missing)} not built; run `biblereference fetch` then `build`"
            )
        return None, last_error

    def _english_rendition(
        self, citation: Citation, span: VerseRange, warnings: list[str]
    ) -> Rendition | None:
        """Fetch the English text, falling back for books the chosen version lacks."""
        # The fallback is always offered, not only for books that look deuterocanonical:
        # Vulgate "Daniel 3:24" is the Song of the Three, and which book a citation lands
        # in is only known after conversion.
        candidates = [
            citation.english or self.config.default_english,
            self.config.deuterocanon_english,
            self.config.vulgate_english,
        ]

        wanted = candidates[0]
        last_error: Exception | None = None
        # Why the requested version was passed over, when it was. Falling back because a
        # version has no Sirach is routine and silent; falling back because it could not be
        # reached is a substitution the author did not ask for, and saying nothing would
        # put another translation's words under a citation meant for theirs.
        refused: Exception | None = None

        for name in dict.fromkeys(candidates):
            try:
                corpus = self._english(name)
            except CorpusError as exc:
                last_error = exc
                if name == wanted:
                    refused = exc
                continue
            try:
                rendition = self._fetch(corpus, span)
            except (VerseUnavailable, CorpusError, VersificationError) as exc:
                last_error = exc
                # Type alone cannot tell the two apart: a version with no Sirach and a
                # version that could not be reached both surface as VerseUnavailable. What
                # separates them is whether the text carries the book at all.
                if name == wanted and self._carries(corpus, span):
                    refused = exc
                continue
            if refused is not None:
                warnings.append(
                    f"{wanted.upper()} was asked for and could not be read, so "
                    f"{span.pretty()} is quoted from {corpus.label} instead -- {refused}"
                )
            return rendition

        tried = ", ".join(dict.fromkeys(candidates))
        warnings.append(
            f"no English text for {span.pretty()} in {tried}"
            + (f" -- {last_error}" if last_error else "")
        )
        return None

    def _carries(self, corpus: Corpus, span: VerseRange) -> bool:
        """Whether this corpus holds the book the citation lands in once converted.

        The ASV has no Sirach and never will, so quoting Sirach from the fallback is the
        system working. A version that does carry the book and still failed to answer is a
        different event entirely.
        """
        try:
            segments = self.versification.convert_range(span, corpus.versification)
        except VersificationError:
            return False
        return all(corpus.has_book(segment.book) for segment in segments)

    def _fetch(self, corpus: Corpus, span: VerseRange) -> Rendition:
        """Convert a passage into a corpus's numbering and read it."""
        segments = self.versification.convert_range(span, corpus.versification)
        verses: list[VerseText] = []
        for segment in segments:
            # Check after converting, not before: Susanna is Daniel 13 in a Vulgate text,
            # so the book that has to exist is the one the conversion landed on.
            if not corpus.has_book(segment.book):
                raise VerseUnavailable(segment.start, corpus.label)
            verses.extend(corpus.fetch(self.versification.expand(segment)))

        rendition = Rendition(
            corpus_id=corpus.id,
            label=corpus.label,
            language=corpus.language,
            reference=", ".join(segment.pretty() for segment in segments),
            text=" ".join(verse.text for verse in verses).strip(),
            attribution=corpus.attribution,
            renumbered=[str(s) for s in segments] != [str(span)],
            refs=tuple(verse.ref for verse in verses),
        )
        self._record_usage(rendition)
        return rendition

    def _record_usage(self, rendition: Rendition) -> None:
        """Accumulate what has been quoted, for the permissions check.

        Counted here rather than at the end, so that the appendices -- which reprint
        passages, and so put those words on the page a second time -- are counted too.
        """
        usage = self._usage.get(rendition.corpus_id)
        if usage is None:
            usage = Usage(
                corpus_id=rendition.corpus_id,
                label=rendition.label,
                attribution=rendition.attribution,
            )
            self._usage[rendition.corpus_id] = usage
        if usage.attribution is None:
            usage.attribution = rendition.attribution
        usage.record(rendition.refs, rendition.text)

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

    # -- appendices --------------------------------------------------------------------

    def _passage_register(
        self, resolutions: Sequence[ResolvedCitation], report: RenderReport
    ) -> str:
        """Appendix Y: every passage the work cites, merged and printed whole."""
        spans = [r.span for r in resolutions if r.span is not None]
        entries: list[RegisterEntry] = []

        for span in self.versification.merge(spans):
            renditions: list[Rendition] = []
            english = self._register_english(span)
            if english is not None:
                renditions.append(english)
            for role in self.config.appendix_originals:
                rendition, _ = self._by_role(role, span)
                if rendition is not None:
                    renditions.append(rendition)
            if not renditions:
                report.warnings.append(f"no text for {span.pretty()} in the register")
                continue
            entries.append(
                RegisterEntry(
                    span=span,
                    renditions=tuple(renditions),
                    equivalents=cross_scheme_references(self.versification, span),
                )
            )

        for entry in entries:
            for rendition in entry.renditions:
                if rendition.attribution and rendition.attribution not in report.attributions:
                    report.attributions.append(rendition.attribution)

        return (
            self._env.get_template("appendix_passages.md.j2")
            .render(title=self.config.appendix_title, entries=entries)
            .strip("\n")
            + "\n"
        )

    def _register_english(self, span: VerseRange) -> Rendition | None:
        """The English for a register entry, without failing the document over it."""
        try:
            return self._english_rendition(Citation(reference=str(span)), span, [])
        except _CITATION_FAILURES:
            return None

    def _notices(self, document: str, report: RenderReport) -> str:
        """Appendix Z: the copyright notices, and whether any limit has been passed."""
        document_words = len(re.findall(r"[^\W_]+", document))
        public_domain: list[str] = []
        restricted: list[tuple[Usage, QuotaFinding | None]] = []

        for usage in sorted(self._usage.values(), key=lambda u: u.label):
            finding = check_quota(usage, document_words)
            if finding is not None:
                restricted.append((usage, finding))
                continue
            note = public_domain_note(usage.corpus_id)
            if note is not None:
                public_domain.append(note)
            # A text with neither a quota nor a public-domain entry is one whose licence
            # asks only for attribution, and that is already in the list above.

        alternative = recommended_alternative()
        overages = [f for _, f in restricted if f is not None and f.exceeded]
        for finding in overages:
            report.warnings.append(
                f"{finding.usage.label}: {'; '.join(finding.reasons)} — see the notices"
            )
        if overages and self.config.strict:
            report.errors.append(
                "quoted more than the publisher permits without written permission: "
                + "; ".join(f.usage.label for f in overages)
            )

        entries = [
            {
                "label": usage.label,
                "verses": usage.verse_count,
                "words": usage.words,
                "note": finding.message(alternative),
                "exceeded": finding.exceeded,
                "source": finding.quota.source,
            }
            for usage, finding in restricted
            if finding is not None
        ]

        return (
            self._env.get_template("appendix_notices.md.j2")
            .render(
                title=self.config.notices_title,
                attributions=report.attributions,
                public_domain=public_domain,
                entries=entries,
                document_words=document_words,
                uses_register=self.config.appendix,
            )
            .strip("\n")
            + "\n"
        )


def _isolate(text: str, rtl: bool = True) -> str:
    """Wrap right-to-left text in a Unicode directional isolate.

    Without this, a Hebrew phrase followed by Markdown punctuation renders with the
    punctuation on the wrong side.
    """
    return f"⁨{text}⁩" if rtl else text
