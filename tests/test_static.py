"""The front end, checked without a browser and without node.

Standard library only, on purpose. A test suite that needed a headless browser to tell you
that a `<script src>` pointed at a file nobody shipped would not be run, and the faults
here are all of that kind: a renamed module, a stylesheet left out of the wheel, a font
pulled from a CDN. None of them raises anywhere -- the page just quietly stops working, and
the last one stops working only for the person with no network, which is this library's
whole premise.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from biblereference.web.assets import TYPES, assets

STATIC = Path(str(resources.files("biblereference.web").joinpath("static")))

#: Anything that fetches: a stylesheet, a script, an image, a font, an `@import`, a `url()`.
_REFERENCES = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)["']?\s*\)""",
    re.IGNORECASE,
)
_IMPORTS = re.compile(r"""(?:^|\n)\s*import\s[^;\n]*?from\s+['"]([^'"]+)['"]""")


def sources() -> list[Path]:
    return sorted(p for p in STATIC.iterdir() if p.is_file())


# --------------------------------------------------------------------------------------
# Shipped at all
# --------------------------------------------------------------------------------------


def test_the_static_directory_survives_into_the_package() -> None:
    """`.gitignore` carries an unanchored `build/` and `dist/`, so a directory by either
    name would vanish from the wheel with no error at all. This is what would notice, and
    the file's own comment says it was hit once already."""
    assert STATIC.is_dir()
    assert {p.name for p in sources()} >= {
        "index.html",
        "style.css",
        "app.js",
        "state.js",
        "api.js",
        "dom.js",
        "reader.js",
        "numbering.js",
        "search.js",
        "library.js",
    }


def test_every_shipped_file_has_a_content_type() -> None:
    """A file with an unmapped suffix is silently unservable: `assets()` skips it, and the
    only symptom is a 404 for something that is plainly on disk."""
    for path in sources():
        assert path.suffix in TYPES, f"{path.name} has no content type in assets.TYPES"
        assert path.name in assets(), path.name


# --------------------------------------------------------------------------------------
# Everything it asks for exists
# --------------------------------------------------------------------------------------


def referenced(text: str) -> list[str]:
    return [one for match in _REFERENCES.findall(text) for one in match if one]


def test_every_asset_the_page_asks_for_is_one_we_ship() -> None:
    text = (STATIC / "index.html").read_text("utf-8")
    wanted = [one for one in referenced(text) if not one.startswith("#")]
    assert wanted, "no assets referenced at all; the regex has stopped matching"
    for reference in wanted:
        if reference == "/plain":
            continue  # a route, not a file
        assert reference.startswith("/static/"), reference
        assert reference.removeprefix("/static/") in assets(), reference


@pytest.mark.parametrize("module", [p.name for p in STATIC.glob("*.js")])
def test_every_import_resolves(module: str) -> None:
    """A renamed module is a blank page and one line in a console nobody has open."""
    text = (STATIC / module).read_text("utf-8")
    for target in _IMPORTS.findall(text):
        assert target.startswith("./"), f"{module} imports {target!r}, which is not relative"
        assert (STATIC / target.removeprefix("./")).is_file(), f"{module} -> {target}"


def test_the_shell_loads_the_modules_as_modules() -> None:
    """`import` in a plain <script> is a syntax error, and the page renders nothing."""
    text = (STATIC / "index.html").read_text("utf-8")
    assert 'type="module" src="/static/app.js"' in text


# --------------------------------------------------------------------------------------
# Nothing it asks for is on the internet
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [p.name for p in sources()])
def test_no_asset_is_fetched_from_the_network(name: str) -> None:
    """The property the whole library rests on: it works with the network off.

    A page pulling a font or a script from a CDN breaks that quietly -- it renders on the
    machine it was written on and degrades on the one it was built for, which is a
    scholar's laptop on a train. This is why there are no web fonts: not an oversight, and
    the README names the faces worth installing instead.
    """
    text = (STATIC / name).read_text("utf-8")
    for reference in referenced(text):
        assert not reference.startswith(("http://", "https://", "//")), reference
    for target in _IMPORTS.findall(text):
        assert not target.startswith(("http://", "https://", "//")), target


def test_the_theme_is_settled_before_the_stylesheet() -> None:
    """A flash of the wrong background is the one rendering fault a reader always notices,
    and a module runs too late to prevent it."""
    text = (STATIC / "index.html").read_text("utf-8")
    assert text.index("data-theme") < text.index('rel="stylesheet"')


# --------------------------------------------------------------------------------------
# The design rules that are cheap to hold and easy to lose
# --------------------------------------------------------------------------------------


def test_the_stylesheet_answers_in_both_themes() -> None:
    css = (STATIC / "style.css").read_text("utf-8")
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root[data-theme="light"]' in css, "the toggle must win in both directions"


def test_right_to_left_is_never_keyed_on_being_ancient() -> None:
    """Greek and Coptic are ancient and read left to right. Direction is set from
    `render.RTL` on the element; the stylesheet keys fonts on [lang] and layout on [dir],
    and must not carry a second opinion about which languages those are."""
    from biblereference.render import RTL

    css = (STATIC / "style.css").read_text("utf-8")
    assert frozenset({"hbo", "syc"}) == RTL
    for language in ("grc", "cop", "la"):
        assert f'[lang="{language}"] {{' in css, f"no font stack for {language}"
    assert "direction: rtl" not in css.replace('[dir="rtl"]', ""), (
        "the stylesheet is naming RTL languages itself"
    )


def test_the_page_never_scrolls_sideways() -> None:
    """Tables of sixty-six editions and a numbering table four columns wide both overflow
    on a phone. They have to scroll inside themselves."""
    css = (STATIC / "style.css").read_text("utf-8")
    assert "overflow-x: auto" in css
    for module in ("library.js", "numbering.js"):
        assert "scroll-x" in (STATIC / module).read_text("utf-8"), module


def test_every_module_parses_and_its_imports_resolve() -> None:
    """The regexes above are a proxy; this is the thing itself.

    Node is not a dependency and never will be -- it is skipped where it is absent -- but
    where it is present it settles in one second what no amount of pattern-matching can: a
    stray comma, a duplicate `const`, an import of a name a module does not export. A
    browser reports each of those as a blank page and one line in a console nobody has open.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the regex checks above still apply")
    done = subprocess.run(
        [node, "--input-type=module", "-e", "await import('./app.js')"],
        cwd=STATIC,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # `window is not defined` is how far it can get with no DOM, and means the whole import
    # graph loaded and execution reached the body. A SyntaxError means it never ran at all.
    assert "SyntaxError" not in done.stderr, done.stderr
    assert "Cannot find module" not in done.stderr, done.stderr
    assert "does not provide an export" not in done.stderr, done.stderr
    assert "window is not defined" in done.stderr, done.stderr


# --------------------------------------------------------------------------------------
# The README, which rots more quietly than the code
# --------------------------------------------------------------------------------------


def test_every_route_the_readme_documents_is_one_the_server_answers() -> None:
    """A documented endpoint that 404s is worse than an undocumented one: somebody writes a
    client against it. The reverse is allowed -- `/api/archive` and `/api/manifest` exist
    for mirroring and are described in prose rather than in the table."""
    from biblereference.web.server import ROUTES

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text("utf-8")
    named = set(re.findall(r"`(GET|POST) (/[a-z/<>-]+)`", readme))
    served = {(key.split()[0], key.split()[1].split("?")[0]) for key in ROUTES}
    assert named, "the route table has stopped matching"
    assert not (named - served), f"documented but not served: {sorted(named - served)}"


def test_the_readme_names_the_command_that_starts_the_server() -> None:
    """It was `python tools/serve.py` for a long time, and the systemd unit is copied out of
    here by hand."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text("utf-8")
    assert "biblereference serve" in readme
    assert "python tools/serve.py" not in readme


def code(text: str) -> str:
    """The file with its comments removed, so a rule can be about what the code does.

    Needed because the modules explain themselves at length, and the honest explanation of
    why `innerHTML` is never used contains the word `innerHTML`.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines() if not line.lstrip().startswith("//")
    )


@pytest.mark.parametrize("name", [p.name for p in STATIC.glob("*.js")])
def test_nothing_builds_markup_out_of_strings(name: str) -> None:
    """Verse text is sixty-six editions of Hebrew, Syriac, Greek and Latin. One `<` in any
    of them would eat the rest of the verse, and no test of ours would catch it -- so every
    string reaches the page as a text node and `innerHTML` appears nowhere."""
    text = code((STATIC / name).read_text("utf-8"))
    for hazard in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert hazard not in text, f"{name} uses {hazard}"
