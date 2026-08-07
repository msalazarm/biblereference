"""The files under ``static/``, read once and served by name.

**There is no path here, only a key.** The manifest is built by listing the package's own
``static/`` directory at first ask; a request naming anything not in it is a 404. That is
the whole of the traversal defence, and it is a property of the design rather than a check
that has to be got right: ``../../etc/passwd`` is not a key, so there is nothing to escape
from. The archive endpoint, which genuinely does take a path, resolves and containment-checks
instead -- two different problems, two different answers.

Read at first ask rather than at import, because ``biblereference --help`` should not pay
for a stylesheet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

__all__ = ["Asset", "assets"]

#: Content types, by suffix. Explicit rather than :mod:`mimetypes`, whose answers depend on
#: ``/etc/mime.types`` and have been known to serve JavaScript as ``text/plain`` on a
#: machine with a thin one -- which browsers refuse to execute.
TYPES: Final[dict[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


@dataclass(frozen=True, slots=True)
class Asset:
    name: str
    body: bytes
    type: str
    etag: str


@cache
def assets() -> dict[str, Asset]:
    """Every servable file, keyed by its bare name.

    Flat: one directory, no subdirectories, so a name is a name. The ETag is a hash of the
    bytes rather than an mtime, because a wheel installed twice has two mtimes and one
    content, and a caller revalidating should get its 304 either way.
    """
    root = resources.files(__package__).joinpath("static")
    found: dict[str, Asset] = {}
    if not root.is_dir():
        return found
    for entry in root.iterdir():
        name = entry.name
        suffix = name[name.rfind(".") :] if "." in name else ""
        if not entry.is_file() or suffix not in TYPES:
            continue
        body = entry.read_bytes()
        found[name] = Asset(
            name=name,
            body=body,
            type=TYPES[suffix],
            etag=f'"{hashlib.sha256(body).hexdigest()[:16]}"',
        )
    return found
