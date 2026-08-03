"""Finding citation tags in Markdown and reading them into one shape.

Three spellings are accepted, because the common case should not cost what the rare
case needs:

``{{Luke 2:42}}``
    The short form. Most citations are just a reference, and a paragraph of prose
    should stay readable. Options may follow a pipe: ``{{Sir 24:1-9 | en=DRA}}``.

``[passage="Luke 2:42" en="ASV" bold.en="twelve years .. festival"]``
    The attribute form, for a citation that needs a few options inline.

``` ```passage ``` ``` fenced block
    A YAML block, for when the options outgrow a line -- several original languages,
    emphasis in three scripts, a quotation to check.

All three produce a :class:`Citation`. Nothing here resolves a reference or touches a
text; this module's whole job is turning three syntaxes into one object.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import yaml

from .canon import NamingScheme

__all__ = [
    "Citation",
    "Emphasis",
    "TagSyntaxError",
    "find_citations",
]


class TagSyntaxError(ValueError):
    """A citation tag is malformed."""

    def __init__(self, message: str, raw: str) -> None:
        self.raw = raw
        super().__init__(f"{message} in tag: {raw.strip()[:120]}")


#: Language keys, as written in tags, normalised to ISO-ish codes. ``grc`` is ancient
#: Greek and ``hbo`` ancient Hebrew, matching the codes the corpora report.
_LANGUAGES: Final[Mapping[str, str]] = {
    "en": "en",
    "english": "en",
    "grc": "grc",
    "greek": "grc",
    "gk": "grc",
    "hbo": "hbo",
    "hebrew": "hbo",
    "heb": "hbo",
    "la": "la",
    "latin": "la",
}

#: What ``original=`` accepts. See :class:`~biblereference.canon.Canon` for how ``auto``
#: decides between them.
ORIGINAL_CHOICES: Final = frozenset({"auto", "hebrew", "lxx", "greek", "theodotion", "none"})

_STYLES: Final = frozenset({"bold", "italic"})

#: Separates the two anchors of an emphasis span: ``"twelve years .. festival"``.
SPAN_SEPARATOR: Final = ".."


@dataclass(frozen=True, slots=True)
class Emphasis:
    """A span of a rendered verse to mark up.

    :param start: Text at the start of the span, matched loosely (see
        :mod:`biblereference.emphasis`).
    :param end: Text at the end of the span. Equal to ``start`` for a single anchor.
    :param style: ``"bold"`` or ``"italic"``.
    """

    start: str
    end: str
    style: str = "bold"

    @classmethod
    def parse(cls, text: str, style: str, *, raw: str) -> Emphasis:
        """Read ``"twelve years .. festival"`` into its two anchors."""
        if style not in _STYLES:
            raise TagSyntaxError(f"unknown emphasis style {style!r}", raw)
        head, separator, tail = text.partition(SPAN_SEPARATOR)
        if not separator:
            head = tail = text
        start, end = head.strip(), tail.strip()
        if not start or not end:
            raise TagSyntaxError(f"emphasis span {text!r} is missing an anchor", raw)
        return cls(start=start, end=end, style=style)


@dataclass(frozen=True, slots=True)
class Citation:
    """One citation tag, read but not yet resolved.

    Every option defaults to ``None``, meaning "whatever the :class:`Config` says". The
    tag only records what it actually asked for.
    """

    reference: str
    """The reference as written, e.g. ``"Sir 24:1-9"``."""

    english: str | None = None
    """Translation to quote in English, e.g. ``"ASV"`` or ``"NRSVCE"``."""

    original: tuple[str, ...] | None = None
    """Which original-language texts to include. See :data:`ORIGINAL_CHOICES`."""

    context: str | None = None
    """A quotation supplied by the author, checked against the resolved text."""

    vrs: str | None = None
    """Versification the reference is written in."""

    naming: NamingScheme | None = None
    """Which tradition's book names to expect."""

    template: str | None = None
    """Template to render with, overriding the configured default."""

    emphasis: Mapping[str, tuple[Emphasis, ...]] = field(default_factory=dict)
    """Spans to mark up, keyed by language code."""

    raw: str = ""
    """The tag exactly as it appeared, for error messages and for replacing it."""

    start: int = 0
    """Offset of the tag in the source document."""

    end: int = 0
    """Offset just past the tag in the source document."""

    inline: bool = False
    """Whether this was the short form, which renders inline by default so that a
    sentence citing a verse in passing stays a sentence."""


# --------------------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------------------

_TAG_RE: Final = re.compile(
    r"""
      (?P<block>^```[ \t]*passage[ \t]*\r?\n(?P<block_body>.*?)^```[ \t]*$)
    | (?P<attr>\[[ \t]*passage[ \t]*=(?P<attr_body>(?:"[^"]*"|'[^']*'|[^]"'])*)\])
    | (?P<short>\{\{(?P<short_body>[^{}\n]*)\}\})
    """,
    re.VERBOSE | re.DOTALL | re.MULTILINE,
)

_ATTR_RE: Final = re.compile(
    r"""(?P<key>[A-Za-z_][\w.]*)[ \t]*=[ \t]*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>\S+))"""
)

#: In the short form each option occupies its own pipe-separated segment, so an unquoted
#: value may contain spaces: ``{{Gen 1:1 | original=hebrew lxx}}``.
_SHORT_ATTR_RE: Final = re.compile(
    r"""(?P<key>[A-Za-z_][\w.]*)[ \t]*=[ \t]*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^|]+))"""
)

_FIRST_QUOTED_RE: Final = re.compile(r"""^\s*(?:"([^"]*)"|'([^']*)'|([^\s"']+))""")


def find_citations(text: str) -> Iterator[Citation]:
    """Yield every citation tag in ``text``, in document order.

    Overlapping is impossible by construction: one scan, one alternation, so a fenced
    block containing something that looks like a short tag is read as a block only.
    """
    for match in _TAG_RE.finditer(text):
        raw = match.group(0)
        if match.group("block") is not None:
            citation = _from_block(match.group("block_body"), raw)
        elif match.group("attr") is not None:
            citation = _from_attributes(match.group("attr_body"), raw, inline=False)
        else:
            citation = _from_short(match.group("short_body"), raw)

        yield _located(citation, match.start(), match.end())


def _located(citation: Citation, start: int, end: int) -> Citation:
    from dataclasses import replace

    return replace(citation, start=start, end=end)


def _from_short(body: str, raw: str) -> Citation:
    """``{{Sir 24:1-9 | en=DRA | original=lxx}}``"""
    reference, _, rest = body.partition("|")
    reference = reference.strip()
    if not reference:
        raise TagSyntaxError("no reference given", raw)

    options: dict[str, str] = {}
    for chunk in rest.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _SHORT_ATTR_RE.fullmatch(chunk)
        if not match:
            raise TagSyntaxError(f"could not read option {chunk!r}", raw)
        options[match.group("key").lower()] = _value(match).strip()

    return _build(reference, options, raw, inline=True)


def _from_attributes(body: str, raw: str, *, inline: bool) -> Citation:
    """``[passage="Luke 2:42" en="ASV" bold.en="twelve years .. festival"]``"""
    quoted = _FIRST_QUOTED_RE.match(body)
    if not quoted:
        raise TagSyntaxError("no reference given", raw)
    reference = next(g for g in quoted.groups() if g is not None).strip()

    options = {
        match.group("key").lower(): _value(match)
        for match in _ATTR_RE.finditer(body[quoted.end() :])
    }
    return _build(reference, options, raw, inline=inline)


def _from_block(body: str, raw: str) -> Citation:
    """A fenced ``passage`` block holding YAML."""
    try:
        loaded = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise TagSyntaxError(f"could not read YAML ({exc.__class__.__name__})", raw) from exc
    if not isinstance(loaded, dict):
        raise TagSyntaxError("block must be a mapping of options", raw)

    data = {str(k).lower(): v for k, v in loaded.items()}
    reference = data.pop("ref", None) or data.pop("reference", None)
    if not reference:
        raise TagSyntaxError("block has no 'ref'", raw)

    emphasis = _emphasis_from_block(data.pop("emphasis", None), raw)
    options = {k: v for k, v in data.items() if v is not None}
    return _build(str(reference), options, raw, inline=False, emphasis=emphasis)


def _value(match: re.Match[str]) -> str:
    for group in ("dq", "sq", "bare"):
        value = match.group(group)
        if value is not None:
            return value
    return ""


def _emphasis_from_block(raw_emphasis: Any, raw: str) -> dict[str, tuple[Emphasis, ...]]:
    """Read the ``emphasis:`` mapping of a fenced block.

    Accepts one entry per language or a list of them::

        emphasis:
          en:  {span: "twelve years .. festival", style: bold}
          grc: [{span: "δωδεκα .. εορτης", style: italic}]
    """
    if raw_emphasis is None:
        return {}
    if not isinstance(raw_emphasis, dict):
        raise TagSyntaxError("'emphasis' must be a mapping keyed by language", raw)

    out: dict[str, list[Emphasis]] = {}
    for key, value in raw_emphasis.items():
        language = _language(str(key), raw)
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, dict) or "span" not in entry:
                raise TagSyntaxError(f"emphasis for {key!r} needs a 'span'", raw)
            style = str(entry.get("style", "bold")).lower()
            out.setdefault(language, []).append(Emphasis.parse(str(entry["span"]), style, raw=raw))
    return {k: tuple(v) for k, v in out.items()}


def _language(key: str, raw: str) -> str:
    try:
        return _LANGUAGES[key.lower()]
    except KeyError:
        raise TagSyntaxError(
            f"unknown language {key!r}; expected one of {', '.join(sorted(set(_LANGUAGES)))}",
            raw,
        ) from None


def _build(
    reference: str,
    options: Mapping[str, Any],
    raw: str,
    *,
    inline: bool,
    emphasis: Mapping[str, tuple[Emphasis, ...]] | None = None,
) -> Citation:
    """Turn a reference plus a flat option mapping into a :class:`Citation`."""
    spans: dict[str, list[Emphasis]] = {k: list(v) for k, v in (emphasis or {}).items()}
    known: dict[str, Any] = {}

    for key, value in options.items():
        style, dot, language = key.partition(".")
        if dot:
            # A dotted key is always an emphasis span, so a bad style here should say so
            # rather than being reported as an unknown option.
            spans.setdefault(_language(language, raw), []).append(
                Emphasis.parse(str(value), style, raw=raw)
            )
        else:
            known[key] = value

    unknown = set(known) - {
        "en",
        "english",
        "original",
        "context",
        "vrs",
        "versification",
        "naming",
        "template",
    }
    if unknown:
        raise TagSyntaxError(f"unknown option(s): {', '.join(sorted(unknown))}", raw)

    naming = known.get("naming")
    if naming is not None:
        try:
            naming = NamingScheme(str(naming).lower())
        except ValueError:
            raise TagSyntaxError(
                f"unknown naming scheme {naming!r}; expected one of "
                f"{', '.join(s.value for s in NamingScheme)}",
                raw,
            ) from None

    return Citation(
        reference=reference,
        english=_as_str(known.get("en") or known.get("english")),
        original=_originals(known.get("original"), raw),
        context=_as_str(known.get("context")),
        vrs=_as_str(known.get("vrs") or known.get("versification")),
        naming=naming,
        template=_as_str(known.get("template")),
        emphasis={k: tuple(v) for k, v in spans.items()},
        raw=raw,
        inline=inline,
    )


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _originals(value: Any, raw: str) -> tuple[str, ...] | None:
    """Read ``original=`` -- a single word, a comma-separated list, or a YAML list."""
    if value is None:
        return None
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value))
    choices = tuple(str(item).strip().lower() for item in items if str(item).strip())
    if not choices:
        return None

    unknown = set(choices) - ORIGINAL_CHOICES
    if unknown:
        raise TagSyntaxError(
            f"unknown original(s): {', '.join(sorted(unknown))}; expected one or more of "
            f"{', '.join(sorted(ORIGINAL_CHOICES))}",
            raw,
        )
    if "none" in choices and len(choices) > 1:
        raise TagSyntaxError("original=none cannot be combined with other values", raw)
    if "auto" in choices and len(choices) > 1:
        raise TagSyntaxError("original=auto cannot be combined with other values", raw)
    return choices
