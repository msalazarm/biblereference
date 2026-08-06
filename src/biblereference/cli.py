"""Command line: sync, fetch, build, index, render, verify, search, scan, compare, doctor.

``sync`` is the one command a fresh install needs; the rest are its parts, kept separate
because they are useful separately. ``fetch`` archives the raw files and ``build`` indexes
them, which is what lets a rebuild after a code change cost nothing, and what lets the
whole thing work with the network off once the archive exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .canon import NamingScheme, resolve_book
from .compare import BookComparison, compare_corpora
from .fetch import build_source, fetch_source, iter_sources, mirror_archive
from .refs import ReferenceParseError, parse_reference
from .render import Config, Renderer
from .search import DEFAULT_BUDGET, Match, Resolver, Searcher, Witness, build_index
from .store import DataHome, SqliteCorpus, library_digest, read_meta, stored_chapters
from .versification import Versification

__all__ = ["main"]


#: Wording shared by every --covering flag, so the commands cannot drift apart about what
#: it means.
_COVERING_HELP: Final = (
    "answer with every verse the mapping covers, not only the one it names -- the two "
    "differ where an edition merges what another divides, and this is the mode that "
    "cannot drop half a verse"
)


def _covering(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--covering", action="store_true", help=_COVERING_HELP)


def _home(args: argparse.Namespace) -> DataHome:
    return DataHome(Path(args.data_home).expanduser()) if args.data_home else DataHome()


def _renderer(args: argparse.Namespace) -> Renderer:
    home = _home(args)
    config = Config(
        default_english=args.english,
        strict=getattr(args, "strict", False),
        template=getattr(args, "template", None) or "blockquote",
        covering=getattr(args, "covering", False),
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


def cmd_index(args: argparse.Namespace) -> int:
    """Build the search index from the verse store."""
    home = _home(args)
    if not home.database.exists():
        _say("nothing built yet -- run `biblereference build` first")
        return 1
    result = build_index(home, report=_say if args.verbose else _silent)
    _say(
        f"\nindexed {result.verses:,} verses as {result.texts:,} distinct texts "
        f"across {len(result.corpora)} corpora"
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Fetch, build and index in one go.

    The one command a fresh install needs. Every step is idempotent: files already in the
    archive are not downloaded again, so an interrupted run resumes where it stopped.
    """
    home = _home(args)

    fetched = failed = 0
    for source in iter_sources(args.source):
        try:
            fetch_source(source, home, report=_say, force=args.force)
            fetched += 1
        except Exception as exc:
            failed += 1
            _say(f"  failed: {source.id}: {exc}")
    if failed:
        _say(f"\n{failed} source(s) could not be fetched; run again to retry them")

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

    if notes:
        _say("\nnotes:")
        for note in notes:
            _say(f"  {note}")

    indexed = build_index(home, report=_say if args.verbose else _silent)
    _say(
        f"\n{fetched} source(s) archived in {home.sources}\n"
        f"{total:,} verses built into {home.database}\n"
        f"{indexed.verses:,} verses indexed for search as {indexed.texts:,} distinct texts"
    )
    return 1 if failed else 0


def cmd_mirror(args: argparse.Namespace) -> int:
    """Copy another machine's archive here, then rebuild from it.

    The way to make two machines hold the same library. `sync` cannot promise that: it
    downloads from a dozen upstreams, and upstream is free to publish something different
    between one machine's sync and the other's -- which is not hypothetical, since eBible
    republished two files between two syncs two days apart during this command's writing.
    """
    home = _home(args)
    result = mirror_archive(
        home, args.url, token=args.token or os.environ.get("BIBLEREFERENCE_TOKEN"), report=_say
    )
    if result.corrupt:
        _say(f"\n{result.corrupt} file(s) refused; nothing was built. Try again.")
        return 1
    if args.no_build:
        _say("\nnot building, as asked. Run `biblereference build` then `index` when ready.")
        return 0

    _say("\nbuilding from the archive...")
    total = 0
    for source in iter_sources(None):
        try:
            total += build_source(source, home, report=_say).verses
        except FileNotFoundError as exc:
            _say(f"skipped: {exc}")
    indexed = build_index(home, report=_silent)
    _say(f"\n{total:,} verses built, {indexed.verses:,} indexed for search")
    _say("\n" + library_digest(home).describe())
    _say("\nCompare that with the other machine's `doctor`, or its /api/digest.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Find the passage a string was quoting."""
    home = _home(args)
    text = " ".join(args.text) if args.text else sys.stdin.read()
    try:
        with Searcher(
            home,
            corpora=args.corpus or None,
            families=getattr(args, "family", None) or None,
            languages=getattr(args, "language", None) or None,
        ) as searcher:
            matches = searcher.search(text, limit=args.limit)
            if args.resolve and matches:
                matches = _resolve_inline(home, searcher, matches, args, quoted=text)
    except LookupError as exc:
        _say(str(exc))
        return 1

    if not matches:
        _say("no passage matched closely enough to report")
        return 1

    if args.json:
        for match in matches:
            print(json.dumps(match.to_dict(), ensure_ascii=False))
        return 0

    for match in matches:
        print(match.describe())
        if args.verbose:
            for witness in match.translations():
                print(f"    {witness.corpus:12} {witness.similarity:.0%}  {witness.text}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Find every quotation in a document, one JSONL record each."""
    home = _home(args)
    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        with Searcher(
            home,
            corpora=args.corpus or None,
            families=getattr(args, "family", None) or None,
            languages=getattr(args, "language", None) or None,
        ) as searcher:
            matches = searcher.scan(text)
            if args.resolve:
                matches = _resolve_inline(home, searcher, matches, args)
    except LookupError as exc:
        _say(str(exc))
        return 1

    for match in matches:
        print(json.dumps(match.to_dict(), ensure_ascii=False))
    named = sum(1 for m in matches if m.identified)
    _say(
        f"{len(matches)} quotation(s); {named} attributed to a translation, "
        f"{len(matches) - named} with the passage identified but the translation unknown"
    )
    return 0


def _resolve_inline(
    home: DataHome,
    searcher: Searcher,
    matches: Sequence[Match],
    args: argparse.Namespace,
    *,
    quoted: str | None = None,
) -> list[Match]:
    """Resolve unattributed matches in place, for one-off runs.

    :param quoted: The words to score against, where the caller knows them better than the
        match does. A scan records the span it matched; a search was handed the text.
    """
    resolver = Resolver(
        home,
        searcher,
        budget=args.resolve_budget,
        offline=getattr(args, "offline", False),
        report=_say,
    )
    out = [
        resolver.resolve(match, quoted or match.quoted).match if (quoted or match.quoted) else match
        for match in matches
    ]
    if resolver.spent:
        _say(f"{resolver.spent} chapter request(s) spent")
    if resolver.touched:
        build_index(home, corpora=resolver.touched, report=_silent)
    return out


def cmd_resolve(args: argparse.Namespace) -> int:
    """Name the translation for passages a scan identified but could not attribute.

    Reads the JSONL a scan produced and writes it back with the translations filled in.
    Splitting it from the scan is what makes the sermon pipeline practical: the scan is
    fast and offline over thousands of transcripts, and this is the slow, budgeted,
    network-bound pass over only the passages that actually need one.
    """
    home = _home(args)
    lines = _read_lines(args.input)
    records = [json.loads(line) for line in lines if line.strip()]

    try:
        searcher = Searcher(home)
    except LookupError as exc:
        _say(str(exc))
        return 1

    resolved = unresolved = 0
    with searcher:
        resolver = Resolver(
            home,
            searcher,
            budget=args.resolve_budget,
            offline=args.offline,
            report=_say,
        )
        for record in records:
            quoted = str(record.get("quoted") or "")
            if not quoted:
                print(json.dumps(record, ensure_ascii=False))
                continue
            match = _match_from(record, searcher)
            if match is None:
                print(json.dumps(record, ensure_ascii=False))
                continue
            outcome = resolver.resolve(match, quoted)
            record.update(outcome.match.to_dict())
            record["checked"] = list(outcome.checked)
            resolved += outcome.resolved
            unresolved += not outcome.resolved
            print(json.dumps(record, ensure_ascii=False))

        spent, touched = resolver.spent, resolver.touched

    _say(
        f"\n{resolved} attributed, {unresolved} still unattributed; "
        f"{spent} chapter request(s) spent of {args.resolve_budget}"
    )
    if spent >= args.resolve_budget:
        _say("budget spent -- run again to continue where this stopped")
    if touched:
        build_index(home, corpora=touched, report=_say if args.verbose else _silent)
        _say(f"reindexed for search: {', '.join(touched)}")
    return 0


def _read_lines(path: str | None) -> list[str]:
    return (
        Path(path).read_text(encoding="utf-8").splitlines()
        if path
        else sys.stdin.read().splitlines()
    )


def _label_of(corpus: str, searcher: Searcher) -> str:
    held = searcher.corpora.get(corpus)
    return held.label if held else corpus


def _match_from(record: dict[str, object], searcher: Searcher) -> Match | None:
    """Rebuild the match a scan recorded, so it can be resolved without rescanning."""
    try:
        passage = parse_reference(str(record["passage"]), vrs=str(record.get("vrs") or "eng"))
    except (KeyError, ReferenceParseError):
        return None
    listed = record.get("translations")
    entries: list[dict[str, object]] = listed if isinstance(listed, list) else []
    witnesses = tuple(
        Witness(
            str(entry["corpus"]),
            _label_of(str(entry["corpus"]), searcher),
            "",
            float(entry["similarity"]),  # type: ignore[arg-type]
        )
        for entry in entries
    )
    span = record.get("span")
    return Match(
        passage,
        witnesses,
        span=(int(span[0]), int(span[1])) if isinstance(span, list) and len(span) == 2 else None,
        quoted=str(record.get("quoted") or ""),
    )


#: Which corpora may speak for each system, best first, with the language each is written
#: in. A textual check is only made where both sides have a faithful witness in *one*
#: language: choosing for faithfulness alone once put English against Latin and rejected
#: every book at similarity 0.02.
COVERAGE_WITNESSES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "org": (
        ("ojb", "en"),
        ("wlc", "hbo"),
        ("n1904", "grc"),
        ("wh", "grc"),
        ("peshitta-ot", "syc"),
        ("peshitta-nt", "syc"),
    ),
    "eng": (("web", "en"), ("kjv", "en")),
    "lxx": (("brenton", "en"), ("rahlfs", "grc"), ("swete", "grc")),
    "vul": (("dra", "en"), ("latvuc", "la")),
    "nvl": (("novavulgata", "la"),),
}


def cmd_coverage(args: argparse.Namespace) -> int:
    """Convert every verse of every system and account for what became of each one.

    Not a sample. The claim under test is that the mappings are right, and a sample cannot
    support that -- so this walks all of them and reports what it could *not* check as
    loudly as what it could.
    """
    from .audit import runs_of, verify_every_verse

    home = _home(args)
    vrs = Versification.load()
    coverage, ghosts, contradicted = verify_every_verse(
        home, vrs, COVERAGE_WITNESSES, covering=args.covering
    )

    for row in coverage:
        print(row.describe())

    total = sum(row.total for row in coverage)
    checked = sum(row.checked for row in coverage)
    confirmed = sum(row.confirmed for row in coverage)
    _say("")
    _say(f"{total:,} verses converted; {len(ghosts)} returned a verse the pivot does not have.")
    if checked:
        _say(
            f"{checked:,} could be checked against text ({checked / total:.1%}), of which "
            f"{confirmed / checked:.3%} confirmed."
        )

    if ghosts:
        _say("")
        _say("ghosts -- these are faults whatever the text says:")
        for ghost in ghosts[: args.limit]:
            print(f"  {ghost}")

    runs = runs_of(contradicted, args.min_run)
    _say("")
    _say(
        f"{len(contradicted):,} verses where a neighbour explains the text better, of which "
        f"{len(runs)} fall in runs of {args.min_run}+."
    )
    _say(
        "Only the runs are evidence: an isolated flag in a genealogy is one witness "
        "transliterating names where the other does not, with every neighbouring verse "
        "sharing the same shape."
    )
    for system, book, chapter, first, last in runs:
        print(f"  {system:4} {book} {chapter}:{first}-{last}\t{last - first + 1} verses")
    return 1 if ghosts else 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Check the versification mappings against the text they claim to align.

    Reports runs of consecutive verses that all prefer the same wrong offset. A single
    flagged verse is usually repetition -- the censuses in Numbers, the tabernacle
    instructions in Exodus -- where a neighbour happens to score higher. A run of them all
    shifted the same way is what a real fault looks like.
    """
    from .audit import audit_all, book_of

    home = _home(args)
    books = [resolve_book(args.book)] if args.book else None
    results = audit_all(home, books=books, covering=args.covering)

    total_runs = 0
    for result in results:
        _say(result.summary())
        runs = _runs_of(result.disagreements, args.min_run)
        total_runs += len(runs)
        if args.verbose and result.disagreements:
            _say(f"      by book: {dict(list(book_of(result.disagreements).items())[:8])}")
        for book, chapter, offset, first, last in runs:
            print(
                f"{result.source}->{result.target}\t{book} {chapter}:{first}-{last}"
                f"\toffset {offset:+d}\t{last - first + 1} verses"
            )

    _say(
        f"\n{total_runs} run(s) of {args.min_run}+ consecutive verses prefer a different "
        f"position. Each needs reading: a run can mean the mapping is wrong, or that the "
        f"two editions genuinely differ in what they print."
    )
    return 0


def cmd_families(args: argparse.Namespace) -> int:
    """Derive the versification families from the corpora rather than the declared data.

    A corpus belongs to a family only when its structure is exact to every other member.
    Where a corpus is exact to *several* families -- because they differ only in books it
    does not carry -- that is reported rather than resolved.
    """
    import json as _json

    from .families import declared_systems, derive, read_signatures, to_json

    home = _home(args)
    signatures = read_signatures(home)
    if not signatures:
        _say("no corpora built; run `biblereference sync` first")
        return 1

    derivation = derive(signatures)
    declared = declared_systems(home)
    compatible = derivation.compatibility(signatures)

    if args.json:
        print(_json.dumps(to_json(derivation, signatures, declared), indent=2))
        return 0

    placed = derivation.partition(signatures)
    grouped: dict[str, list[str]] = {}
    for corpus, family in placed.items():
        if family is not None:
            grouped.setdefault(family, []).append(corpus)

    _say(f"{len(derivation.families)} families derived from {len(signatures)} corpora\n")
    coverage = {f.name: len(f.signature) for f in derivation.families}
    for name, members in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        systems = sorted({declared.get(m, "?") for m in members})
        print(
            f"{name:13} {len(members):>2} member(s)  {coverage[name]:>4} chapters  "
            f"declared {','.join(systems)}"
        )
        print(f"              {', '.join(sorted(members))}")
        contested = sorted(m for m in members if len(compatible[m]) > 1)
        if args.verbose and contested:
            print(f"              contested, also match: {', '.join(contested)}")

    multiple = {c: f for c, f in compatible.items() if len(f) > 1}
    if multiple:
        _say(
            f"\n{len(multiple)} of these matched more than one family and were assigned to the "
            f"largest.\nThe families they could not tell apart differ only in books they do not "
            f"carry, so\nthe choice costs nothing: run with -v, or --json for every match."
        )

    orphans = [c for c, f in compatible.items() if not f]
    if orphans:
        _say(
            f"\n{len(orphans)} unplaceable -- too few complete chapters to compare against "
            f"anything: {', '.join(sorted(orphans))}"
        )
    return 0


def _runs_of(disagreements: Sequence[object], minimum: int) -> list[tuple[str, int, int, int, int]]:
    """Group flagged verses into consecutive runs sharing one offset.

    The whole discrimination lives here. Isolated flags are noise from repetitive
    passages; a run is the shape a versification fault actually has.
    """
    grouped: dict[tuple[str, int, int], list[int]] = {}
    for item in disagreements:
        alignment = item.alignment  # type: ignore[attr-defined]
        key = (alignment.source.book, int(alignment.source.chapter), alignment.best_offset)
        grouped.setdefault(key, []).append(alignment.source.verse)

    runs: list[tuple[str, int, int, int, int]] = []
    for (book, chapter, offset), verses in grouped.items():
        ordered = sorted(verses)
        current = [ordered[0]]
        for verse in ordered[1:]:
            if verse == current[-1] + 1:
                current.append(verse)
                continue
            if len(current) >= minimum:
                runs.append((book, chapter, offset, current[0], current[-1]))
            current = [verse]
        if len(current) >= minimum:
            runs.append((book, chapter, offset, current[0], current[-1]))
    return sorted(runs, key=lambda r: -(r[4] - r[3]))


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

    results = list(compare_corpora(left, right, versification, books=books, covering=args.covering))
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
    missing = [source.id for source in iter_sources(None) if not home.latest_archive(source.id)]
    if missing:
        _say(f"  not fetched: {', '.join(missing)}")
    else:
        _say("  every registered source is fetched")

    if args.verify:
        _say("\nverifying the archive against its manifest...")
        checked, wrong, absent = _verify_archive(home)
        _say(f"  {checked} file(s) checked")
        for path in absent:
            _say(f"  missing:  {path}")
        for path in wrong:
            _say(f"  CHANGED:  {path}")
        if not wrong and not absent:
            _say("  every archived file matches the checksum recorded when it was fetched")

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
        terms = item.terms
        if terms is not None:
            _say(f"                 terms: {terms.describe()}")
            if terms.underlying is not None:
                _say(
                    f"                 but the edition is {terms.underlying.name}, which "
                    f"the file's own header does not say"
                )
        elif item.license:
            _say(f"                 licence: {item.license}")

    # The question a person actually has, which no per-corpus line answers: of everything
    # I hold, what may I not use freely? Counted rather than listed, because the list is
    # long and the number is what decides whether to read it.
    held = [terms for item in meta if (terms := item.terms) is not None]
    restricted = [terms for terms in held if terms.restricted]
    if restricted:
        forbids = sum(1 for terms in restricted if not terms.effective.commercial)
        viral = sum(1 for terms in restricted if terms.effective.share_alike)
        _say("")
        if forbids:
            _say(f"{forbids} corpus/corpora may not be used commercially.")
        if viral:
            _say(f"{viral} carry share-alike terms; keep derived work separable.")
        _say("The `terms:` line against each corpus above says which.")
    unread = [item for item in meta if item.terms is None]
    if unread:
        _say(
            f"\n{len(unread)} corpus/corpora carry a licence nobody has read into the "
            f"library's own terms, so nothing above speaks for them."
        )

    versification = Versification.load()
    _say(f"\nversification systems: {', '.join(versification.system_names)}")
    for name in versification.system_names:
        blocked = versification.unmappable_chapters(name)
        if blocked:
            books = sorted({book for book, _ in blocked})
            _say(f"  {name}: {len(blocked)} chapter(s) not convertible, in {', '.join(books)}")

    _say("\nlibrary digest -- run this on both machines and compare the last line:")
    _say(library_digest(home).describe())
    return 0


# --------------------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------------------


def _add_resolve_options(command: argparse.ArgumentParser) -> None:
    """The flags governing what resolution is allowed to cost.

    A ceiling rather than a suggestion: thirteen versions at BibleGateway's published
    fifteen-second crawl delay is over three minutes per passage, and a long sermon can
    hold forty unattributed ones. The run stops at the ceiling and says so.
    """
    command.add_argument(
        "--resolve",
        action="store_true",
        help="ask BibleGateway to name the translation where the passage is known but the "
        "translation is not",
    )
    command.add_argument(
        "--resolve-budget",
        type=int,
        default=DEFAULT_BUDGET,
        metavar="N",
        help=f"most chapter requests one run may spend (default {DEFAULT_BUDGET})",
    )
    command.add_argument(
        "--offline",
        action="store_true",
        help="resolve only from chapters already stored; never reach the network",
    )


def _verify_archive(home: DataHome) -> tuple[int, list[str], list[str]]:
    """Re-hash every archived file and compare with the manifest.

    This is what turns "copy ``sources/`` to another machine and rebuild" from a hope into
    a checked claim: the manifest records the sha256 of every file as it was downloaded,
    so a truncated copy or a silently corrupted disk shows up here rather than as a
    mysteriously wrong verse months later.
    """
    checked = 0
    wrong: list[str] = []
    absent: list[str] = []
    for entry in home.entries():
        path = home.sources / entry.path
        if not path.exists():
            absent.append(entry.path)
            continue
        checked += 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.sha256:
            wrong.append(entry.path)
    return checked, wrong, absent


def _silent(_: str) -> None:
    return None


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

    sync = subparsers.add_parser(
        "sync", help="fetch, build and index everything -- the one command a new install needs"
    )
    sync.add_argument("--source", help="just this one")
    sync.add_argument("--force", action="store_true", help="fetch again even if already archived")
    sync.set_defaults(func=cmd_sync)

    fetch = subparsers.add_parser("fetch", help="download source texts into the archive")
    fetch.add_argument("--source", help="just this one, e.g. swete")
    fetch.add_argument("--force", action="store_true", help="fetch again even if already archived")
    fetch.set_defaults(func=cmd_fetch)

    build = subparsers.add_parser("build", help="index the archive into the database")
    build.add_argument("--source", help="just this one")
    build.set_defaults(func=cmd_build)

    index = subparsers.add_parser("index", help="build the search index from the database")
    index.set_defaults(func=cmd_index)

    search = subparsers.add_parser("search", help="find the passage a string of text was quoting")
    search.add_argument("text", nargs="*", help="the text; omit to read standard input")
    search.add_argument("--limit", type=int, default=5, help="how many passages to report")
    search.add_argument("--corpus", action="append", help="search only this corpus; repeatable")
    search.add_argument(
        "--family",
        action="append",
        help="search only this versification, e.g. eng or vul; repeatable",
    )
    search.add_argument(
        "--language", action="append", help="search only this language, e.g. la; repeatable"
    )
    search.add_argument("--json", action="store_true", help="one JSON record per passage")
    _add_resolve_options(search)
    search.set_defaults(func=cmd_search)

    scan = subparsers.add_parser("scan", help="find every quotation in a document, as JSONL")
    scan.add_argument("input", nargs="?", help="file to read; omit for standard input")
    scan.add_argument("--corpus", action="append", help="search only this corpus; repeatable")
    scan.add_argument(
        "--family", action="append", help="search only this versification; repeatable"
    )
    scan.add_argument("--language", action="append", help="search only this language; repeatable")
    _add_resolve_options(scan)
    scan.set_defaults(func=cmd_scan)

    resolve = subparsers.add_parser(
        "resolve",
        help="name the translation for passages a scan could not attribute",
        description="Reads the JSONL a scan produced and writes it back with translations "
        "filled in, asking BibleGateway for one passage at a time and only where the "
        "passage is known but the translation is not. Chapters are kept, so nothing is "
        "ever requested twice.",
    )
    resolve.add_argument("input", nargs="?", help="JSONL from `scan`; omit for standard input")
    _add_resolve_options(resolve)
    resolve.set_defaults(func=cmd_resolve)

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
        _covering(command)
        command.set_defaults(func=function)

    mirror = subparsers.add_parser(
        "mirror",
        help="copy another machine's archive here, so both hold the same bytes",
        description="Points this machine at another one running `tools/serve.py` and "
        "copies its archive, verifying every file against the checksum that machine "
        "recorded before writing it. Then rebuilds. Use this rather than `sync` when two "
        "machines must match: `sync` takes whatever upstream publishes today, and upstream "
        "changes.",
    )
    mirror.add_argument("url", help="the other machine, e.g. http://bigbox.local:8000")
    mirror.add_argument("--token", help="its bearer token; also read from $BIBLEREFERENCE_TOKEN")
    mirror.add_argument(
        "--no-build", action="store_true", help="copy the archive but do not rebuild yet"
    )
    mirror.set_defaults(func=cmd_mirror)

    compare = subparsers.add_parser(
        "compare", help="report how far two editions of one text differ, book by book"
    )
    compare.add_argument("left", help="corpus id, e.g. latvuc")
    compare.add_argument("right", help="corpus id, e.g. novavulgata")
    compare.add_argument("--book", help="just this book; with -v, print the verses")
    _covering(compare)
    compare.set_defaults(func=cmd_compare)

    audit = subparsers.add_parser(
        "audit",
        help="check the versification mappings against the text they claim to align",
        description="Compares same-language witnesses across versification families and "
        "reports passages where the text is better explained by a position the mapping "
        "does not claim. Found the Vulgate Jonah fault, where every citation of Jonah 2 "
        "resolved one verse late.",
    )
    audit.add_argument("--book", help="just this book, e.g. JON")
    _covering(audit)
    audit.add_argument(
        "--min-run",
        type=int,
        default=3,
        metavar="N",
        help="consecutive verses that must share an offset before it is reported "
        "(default 3; lower it to see the noise, raise it to see only the clearest faults)",
    )
    audit.set_defaults(func=cmd_audit)

    families = subparsers.add_parser(
        "families",
        help="derive the versification families from the corpora themselves",
        description="Groups corpora by exact structural identity rather than by what they "
        "declare. Found that the Orthodox Jewish Bible and the Leningrad Codex are not one "
        "numbering, that Swete and Brenton are not one numbering, and that the single "
        "declared English family is really eleven.",
    )
    families.add_argument("--json", action="store_true", help="emit the whole derivation as JSON")
    families.set_defaults(func=cmd_families)

    coverage = subparsers.add_parser(
        "coverage",
        help="convert every verse of every versification and account for the result",
        description="Walks all 155,000 conversions rather than sampling them, and reports "
        "how many could be checked against text and how many could not -- 'not "
        "contradicted' is not the same as 'verified'. Exits non-zero if any conversion "
        "returns a verse the pivot does not have.",
    )
    coverage.add_argument(
        "--min-run",
        type=int,
        default=4,
        metavar="N",
        help="consecutive contradicted verses before a run is reported (default 4; an "
        "isolated flag in a repetitive passage is noise, not a fault)",
    )
    coverage.add_argument(
        "--limit", type=int, default=40, metavar="N", help="ghosts to print (default 40)"
    )
    _covering(coverage)
    coverage.set_defaults(func=cmd_coverage)

    doctor = subparsers.add_parser("doctor", help="report what is cached and built")
    doctor.add_argument(
        "--verify",
        action="store_true",
        help="re-hash every archived file against the manifest, so a copied archive can "
        "be trusted before it is rebuilt from",
    )
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
