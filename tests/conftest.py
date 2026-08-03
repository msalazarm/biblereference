"""Test isolation from whatever corpus the developer happens to have built.

``DataHome`` defaults to ``$BIBLEREFERENCE_HOME`` or the platform data directory, and
``Renderer`` opens every corpus it finds there. So on a machine where nobody has run
``biblereference sync`` the tests quietly get ``pythonbible``'s ASV and no Hebrew, and on
a machine where somebody has they get eBible's ASV, a different label, and the Hebrew
alongside -- and half of ``test_render.py`` fails on the second machine for reasons that
have nothing to do with the change under test.

Pointing the whole session at an empty temporary directory makes the tests say what they
mean: they exercise the corpora they build themselves, and nothing else.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from biblereference.store import ENV_VAR


@pytest.fixture(autouse=True, scope="session")
def _isolated_data_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("data-home")
    previous = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            del os.environ[ENV_VAR]
        else:
            os.environ[ENV_VAR] = previous
