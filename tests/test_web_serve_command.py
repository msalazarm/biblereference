"""`biblereference serve`, and the one thing about it that is easy to get wrong.

`--data-home` has to reach the *spawned* job workers as well as the reads. A worker builds
its own `DataHome()` out of the environment -- it cannot be handed the parent's, and it does
not inherit an assignment to a module global. A version that set only the global would
answer `/api/passage` out of the named home and run every job against the default one, and
nothing in the output would say so.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from biblereference.refs import VerseRef
from biblereference.store import ENV_VAR, DataHome, SourceMeta, write_corpus
from biblereference.web import library as lib
from biblereference.web import server


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.fixture
def named_home(tmp_path: Path) -> Path:
    """A data home that is *not* the one the environment already points at."""
    root = tmp_path / "elsewhere"
    where = DataHome(root)
    write_corpus(
        where,
        SourceMeta(corpus="alpha", label="Alpha", language="en", versification="eng"),
        [
            (VerseRef("JHN", 3, 16), "for god so loved the world that he gave his only son"),
            (VerseRef("JHN", 3, 17), "for god sent not his son into the world to condemn it"),
        ],
    )
    write_corpus(
        where,
        SourceMeta(corpus="beta", label="Beta", language="en", versification="eng"),
        [
            (VerseRef("JHN", 3, 16), "for god so loved the world that he gave his only son"),
            (VerseRef("JHN", 3, 17), "god sent not his son to condemn the world"),
        ],
    )
    return root


@pytest.fixture
def serving(named_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """`serve()` in this process, in a thread, exactly as `cmd_serve` would call it."""
    monkeypatch.setattr(lib, "_LIBRARY", None)
    monkeypatch.setattr(lib, "_local", threading.local())
    monkeypatch.setattr(server, "HOME", DataHome())
    monkeypatch.setattr(server, "JOBS", None)
    monkeypatch.setattr(server, "TOKEN", None)

    port = free_port()
    thread = threading.Thread(
        target=lambda: server.serve(
            port=port, workers=1, interactive_workers=1, data_home=named_home, announce=False
        ),
        daemon=True,
    )
    thread.start()
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5).read()
            break
        except (OSError, ValueError):
            time.sleep(0.05)
    else:
        pytest.fail("the server never came up")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        if server.JOBS is not None:
            server.JOBS._pool.shutdown(wait=False, cancel_futures=True)
            server.JOBS._interactive.shutdown(wait=False, cancel_futures=True)


def get(base: str, path: str) -> dict:  # type: ignore[type-arg]
    with urllib.request.urlopen(base + path, timeout=120) as response:
        loaded: dict = json.load(response)  # type: ignore[type-arg]
        return loaded


def test_the_reads_use_the_named_home(serving: str, named_home: Path) -> None:
    assert get(serving, "/api/health")["data_home"] == str(named_home)
    assert [c["id"] for c in get(serving, "/api/corpora")["corpora"]] == ["alpha", "beta"]


def test_the_spawned_workers_use_it_too(serving: str, named_home: Path) -> None:
    """The gate.

    `job_compare` opens the corpora by name in the worker and raises `not built: alpha,
    beta` when it cannot find them, so this distinguishes the two homes by more than a
    difference in results: a worker on the default home fails outright and says which
    names it could not find. Chosen over a search for exactly that -- a search against the
    wrong library returns *plausibly* nothing, which is the failure that hides.
    """
    request = urllib.request.Request(
        serving + "/api/jobs?task=compare&left=alpha&right=beta", data=b"", method="POST"
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        job = json.load(response)

    for _ in range(600):
        state = get(serving, f"/api/jobs/{job['id']}")
        if state["state"] != "running":
            break
        time.sleep(0.2)

    assert state["state"] == "done", state.get("error")
    (book,) = state["result"]["books"]
    assert (book["book"], book["compared"], book["identical"]) == ("JHN", 2, 1)


def test_the_environment_is_what_carries_it(serving: str, named_home: Path) -> None:
    """Said explicitly, because this is the mechanism and it is invisible otherwise: a
    spawned worker inherits the environment, not the assignment."""
    assert os.environ[ENV_VAR] == str(named_home)


# --------------------------------------------------------------------------------------
# The command itself
# --------------------------------------------------------------------------------------


def test_serve_is_a_subcommand_that_takes_the_servers_options() -> None:
    from biblereference.cli import build_parser

    args = build_parser().parse_args(
        ["--data-home", "/tmp/x", "serve", "--host", "0.0.0.0", "--port", "9", "--workers", "2"]
    )
    assert (args.host, args.port, args.workers, args.data_home) == ("0.0.0.0", 9, 2, "/tmp/x")
    assert args.func.__name__ == "cmd_serve"


def test_the_old_script_still_starts_the_new_server() -> None:
    """The README's systemd unit names `tools/serve.py`, and somebody's is still running."""
    tools = Path(__file__).resolve().parent.parent / "tools" / "serve.py"
    done = subprocess.run(
        [sys.executable, str(tools), "--help"], capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0
    assert "--interactive-workers" in done.stdout
    assert "serve" in done.stdout
