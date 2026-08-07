"""Kept so the README's systemd unit and `tests/test_server.py` keep working.

The server lives in `biblereference.web` now; `biblereference serve` is the spelling to
use. Importing this module hands back that package's `server` module rather than a copy of
it, so `serve.HOME = ...` reaches the real global the handlers read -- which a shim that
merely re-exported the names would not: it would bind shim-local names nothing consults.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    from biblereference.web.server import main

    raise SystemExit(main())

# Deliberately not under `__main__`: replacing sys.modules["__main__"] would break the job
# pool, whose spawned workers unpickle a task by module name.
from biblereference.web import server as _server

sys.modules[__name__] = _server
