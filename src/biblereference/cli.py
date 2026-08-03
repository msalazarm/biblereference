"""Command line: fetch, build, render, verify, doctor.

``fetch`` and ``build`` are separate on purpose. Fetching archives the raw files; building
indexes them. Keeping them apart is what lets a rebuild after a code change cost nothing,
and what lets the whole thing work with the network off once the archive exists.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .canon import NamingScheme, resolve_book
from .compare import BookComparison, compare_corpora
from .fetch import build_source, fetch_source, iter_sources
from .render import Config, Renderer
from .store import DataHome, SqliteCorpus, read_meta, stored_chapters
from .versification import Versification

__all__ = ["main"]


def _home(args: argparse.Namespace) -> DataHome:
    return DataHome(Path(args.data_home).expanduser()) if args.data_home else DataHome()


def _renderer(args: argparse.Namespace) -> Renderer:
    home = _home(args)
    config = Config(
        default_english=args.english,
        strict=getattr(args, "strict", False),
        template=getattr(args, "template", None) or "blockquote",
        appendix=getattr(args, "appendix", False),
        notices=not getattr(args, "no_notices", False),
        naming=NamingScheme(args.naming),
        vrs=args.vrs,
        data_home=home.root,
        template_dir=Path(args.template_dir) if getattr(args, "template_dir", None) else None,
    )
    renderer = Renderer(config)
    if home.database.exists():
        for corpus in SqliteCorpus.load_all(home).values():
            renderer.add_corpus(corpus)
    return renderer


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    home = _home(args)
    for source in iter_sources(args.source):
        fetch_source(source, home, report=_say, force=args.force)
    _say(f"archive: {home.sources}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    home = _home(args)
    total = 0
    notes: list[str] = []
    for source in iter_sources(args.source):
        try:
            result = build_source(source, home, report=_say)
        except FileNotFoundError as exc:
            _say(f"skipped: {exc}")
            continue
        total += result.verses
        notes.extend(result.notes)

    if notes and args.verbose:
        _say("\nnotes:")
        for note in notes:
            _say(f"  {note}")
    _say(f"\n{total:,} verses indexed into {home.database}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    renderer = _renderer(args)
    source = Path(args.input)
    text = source.read_text(encoding="utf-8")
    rendered, report = renderer.render_text(text)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    _report(report, verbose=args.verbose)
    return 0 if report.ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Resolve every citation and check every quotation, writing nothing."""
    renderer = _renderer(args)
    _, report = renderer.render_text(Path(args.input).read_text(encoding="utf-8"))
    _report(report, verbose=True)
    return 0 if report.ok else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Report how far two editions of one text have drifted apart, book by book."""
    home = _home(args)
    corpora = SqliteCorpus.load_all(home)
    missing = [name for name in (args.left, args.right) if name not in corpora]
    if missing:
        _say(f"not built: {', '.join(missing)}. Available: {', '.join(sorted(corpora))}.")
        return 1

    left, right = corpora[args.left], corpora[args.right]
    versification = Versification.load()
    books = [resolve_book(args.book)] if args.book else None

    results = list(compare_corpora(left, right, versification, books=books))
    if args.book and results and args.verbose:
        _print_verse_differences(results[0])
        return 0

    print(f"# {left.label} against {right.label}\n")
    print("| Book | Verses | Differ | Share | Mean similarity | Only in one |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    total = differing = 0
    for result in results:
        only = result.missing_left + result.missing_right
        print(
            f"| {result.title} | {result.compared} | {len(result.differing)} | "
            f"{result.share_differing:.0%} | {result.mean_similarity:.0%} | {only} |"
        )
        total += result.compared
        differing += len(result.differing)

    share = differing / total if total else 0.0
    print(
        f"\n{differing:,} of {total:,} verses differ ({share:.0%}), comparing on folded "
        f"text so that spelling is not counted as substance."
    )
    return 0


def _print_verse_differences(result: BookComparison) -> None:
    print(f"# {result.title}: {len(result.differing)} of {result.compared} verses differ\n")
    for difference in result.differing:
        print(f"**{difference.ref.pretty()}** — {difference.similarity:.0%} alike\n")
        print(f"- {difference.left}")
        print(f"- {difference.right}\n")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Say what is cached, what is missing, and what the texts are."""
    home = _home(args)
    _say(f"data home: {home.root}")
    _say(f"  sources:  {home.sources}{'' if home.sources.exists() else '  (not created)'}")
    _say(f"  database: {home.database}{'' if home.database.exists() else '  (not built)'}")

    entries = home.entries()
    _say(f"\narchive: {len(entries)} file(s) recorded")
    for source in iter_sources(None):
        archive = home.latest_archive(source.id)
        state = str(archive) if archive else "not fetched"
        _say(f"  {source.id:12} {state}")

    meta = read_meta(home)
    if not meta:
        _say("\nno corpora built yet -- run `biblereference fetch` then `build`")
        return 0

    _say(f"\ncorpora: {len(meta)}")
    for item in meta:
        _say(
            f"  {item.corpus:14} {item.verse_count:>7,} verses  "
            f"{item.language:4} {item.versification:4}  {item.label}"
        )
        chapters = stored_chapters(home, item.corpus)
        if chapters:
            # An online translation is whatever has been read so far, so say what that is.
            books = sorted({book for book, _, _ in chapters})
            _say(
                f"                 built up online: {len(chapters)} chapter(s) of "
                f"{', '.join(books)}"
            )
        if item.license:
            _say(f"                 licence: {item.license}")

    versification = Versification.load()
    _say(f"\nversification systems: {', '.join(versification.system_names)}")
    for name in versification.system_names:
        blocked = versification.unmappable_chapters(name)
        if blocked:
            books = sorted({book for book, _ in blocked})
            _say(f"  {name}: {len(blocked)} chapter(s) not convertible, in {', '.join(books)}")
    return 0


# --------------------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------------------


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _report(report, *, verbose: bool) -> None:
    _say(report.summary())
    for warning in report.warnings:
        _say(f"  warning: {warning}")
    for error in report.errors:
        _say(f"  error:   {error}")
    if verbose and report.attributions:
        _say("  texts:")
        for attribution in report.attributions:
            _say(f"    {attribution}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biblereference",
        description="Expand scripture citation tags in Markdown into verified verse text.",
    )
    parser.add_argument(
        "--data-home",
        help="Where sources and the database live. Defaults to $BIBLEREFERENCE_HOME "
        "or the platform data directory.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="download source texts into the archive")
    fetch.add_argument("--source", help="just this one, e.g. swete")
    fetch.add_argument("--force", action="store_true", help="fetch again even if already archived")
    fetch.set_defaults(func=cmd_fetch)

    build = subparsers.add_parser("build", help="index the archive into the database")
    build.add_argument("--source", help="just this one")
    build.set_defaults(func=cmd_build)

    for name, function, help_text in (
        ("render", cmd_render, "expand citations into a new file"),
        ("verify", cmd_verify, "check citations without writing anything"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("input", help="Markdown file to read")
        if name == "render":
            command.add_argument("-o", "--output", help="write here instead of stdout")
            command.add_argument("--template", help="template name, e.g. footnote")
            command.add_argument("--template-dir", help="directory of your own templates")
        command.add_argument(
            "--appendix",
            action="store_true",
            help="append the passage register: every passage cited, merged and in full",
        )
        command.add_argument(
            "--no-notices",
            action="store_true",
            help="omit the copyright notices (they are required wherever you quote "
            "copyrighted text)",
        )
        command.add_argument("--english", default="ASV", help="default English version")
        command.add_argument(
            "--naming",
            default=NamingScheme.MODERN.value,
            choices=[scheme.value for scheme in NamingScheme],
            help="which tradition's book names to expect",
        )
        command.add_argument("--vrs", default="eng", help="versification references are written in")
        command.add_argument("--strict", action="store_true", help="treat warnings as errors")
        command.set_defaults(func=function)

    compare = subparsers.add_parser(
        "compare", help="report how far two editions of one text differ, book by book"
    )
    compare.add_argument("left", help="corpus id, e.g. latvuc")
    compare.add_argument("right", help="corpus id, e.g. novavulgata")
    compare.add_argument("--book", help="just this book; with -v, print the verses")
    compare.set_defaults(func=cmd_compare)

    doctor = subparsers.add_parser("doctor", help="report what is cached and built")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
    except KeyboardInterrupt:
        _say("interrupted")
        return 130
    except (OSError, ValueError, KeyError) as exc:
        _say(f"error: {exc}")
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
