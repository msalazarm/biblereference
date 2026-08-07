"""Screenshot the reader, and report what the browser complained about.

    venv/bin/biblereference serve --port 8125 &
    venv/bin/python tools/shot.py '#/reader/MAT/17?vrs=vul&with=n1904'
    venv/bin/python tools/shot.py '#/reader/PSA/119' --width 760 --theme dark -o narrow.png
    venv/bin/python tools/shot.py --sweep          # every passage, every width, both themes

**The console capture is the point; the picture is the by-product.** A front end has two
kinds of fault and only one of them is visible in a screenshot. A `TypeError` in a render
path leaves a blank region that looks like a design decision, and an aborted fetch leaves
stale content that looks correct. Both announce themselves on the console and nowhere else,
so every run fails loudly on `console.error` or `pageerror` and prints them.

Playwright is a development dependency and is not in ``pyproject.toml``: nothing the library
does at run time needs a browser. Install it with ``venv/bin/pip install playwright``; the
browsers may already be cached under ``~/.cache/ms-playwright``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

#: The passages worth looking at, each because it breaks a different assumption. Anything
#: that renders these seven correctly is very unlikely to be wrong about an ordinary one.
SWEEP: dict[str, str] = {
    "matthew17-vul": "#/reader/MAT/17?vrs=vul&version=dra&with=n1904,kjv",
    "psalm51": "#/reader/PSA/51?vrs=eng&version=kjv&with=dra,wlc,rahlfs",
    "exodus36-lxx": "#/reader/EXO/36?vrs=org&version=wlc&with=rahlfs,brenton",
    "acts19-eng": "#/reader/ACT/19?vrs=eng&version=kjv&with=dra,n1904",
    "genesis1-rtl": "#/reader/GEN/1?vrs=org&version=wlc&with=peshitta-ot,rahlfs,kjv",
    "psalm119": "#/reader/PSA/119?vrs=eng&version=kjv&with=dra,wlc",
    "susanna-nvl": "#/reader/SUS/1?vrs=nvl&version=dra",
    "numbering": "#/numbering/MAT/17:14?vrs=vul",
    "search": "#/search?q=In+the+beginning+was+the+Word",
    "library": "#/library",
}

#: 1440 is where the old three-column grid folded the compare column under the rail, which
#: is the fault this whole redesign started from. 760 exercises the frozen key column.
WIDTHS = (1920, 1440, 1100, 760)

#: Noise the page does not control and cannot fix.
IGNORE = ("favicon", "Download the React DevTools")


def shoot(base: str, route: str, out: Path, width: int, height: int, theme: str) -> list[str]:
    from playwright.sync_api import sync_playwright

    complaints: list[str] = []
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=theme)
        page.on(
            "console",
            lambda message: (
                complaints.append(f"console.{message.type}: {message.text}")
                if message.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda error: complaints.append(f"pageerror: {error}"))
        # A 404 or 500 on an XHR is a fault the page may swallow silently.
        page.on(
            "response",
            lambda response: (
                complaints.append(f"HTTP {response.status}: {response.url}")
                if response.status >= 400
                else None
            ),
        )

        page.goto(base + "/" + route, wait_until="networkidle")
        # The screens fill their slots asynchronously; wait for content rather than a timer,
        # and fall back to a timer so a genuinely empty screen still gets photographed.
        try:
            page.wait_for_function(
                "() => document.querySelector('[data-slot=\"reading\"]')?.children.length > 0",
                timeout=30000,
            )
        except Exception:
            complaints.append("the reading slot never filled")
        page.wait_for_timeout(700)

        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=False)
        browser.close()

    return [c for c in complaints if not any(skip in c for skip in IGNORE)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Screenshot the reader and report console errors.")
    parser.add_argument("route", nargs="?", default="#/reader/JHN/3", help="a hash route")
    parser.add_argument("--base", default="http://127.0.0.1:8125")
    parser.add_argument("-o", "--out", type=Path, default=Path("/tmp/shot.png"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--theme", default="light", choices=("light", "dark"))
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="every passage in SWEEP, every width in WIDTHS, both themes",
    )
    parser.add_argument("--into", type=Path, default=Path("/tmp/shots"), help="--sweep output")
    args = parser.parse_args()

    if not args.sweep:
        complaints = shoot(args.base, args.route, args.out, args.width, args.height, args.theme)
        print(args.out)
        for one in complaints:
            print("  !", one[:200])
        return 1 if complaints else 0

    failed = 0
    for name, route in SWEEP.items():
        for width in WIDTHS:
            for theme in ("light", "dark"):
                out = args.into / f"{name}-{width}-{theme}.png"
                complaints = shoot(args.base, route, out, width, args.height, theme)
                mark = "!!" if complaints else "ok"
                print(f"{mark} {name:16s} {width:5d} {theme:5s} {out}")
                for one in complaints[:4]:
                    print("      ", one[:180])
                failed += bool(complaints)
    print(f"\n{failed} of {len(SWEEP) * len(WIDTHS) * 2} shots had complaints")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
