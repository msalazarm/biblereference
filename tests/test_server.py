"""The HTTP server's own contract, as distinct from the library's.

Two things belong here and nothing else does. The first is parameter handling, because the
server's job is to refuse what it cannot honour: a query string is untyped and a parameter
that is quietly ignored is indistinguishable from one that had no effect, which is a caller
believing it configured something it did not. The second is that the endpoints are *the
library* rather than a second implementation of it -- the scan endpoint must answer exactly
what a local `Searcher` answers, or the server becomes a place where results drift.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from biblereference.search import _MIN_RUN
from biblereference.store import ENV_VAR, DataHome

# `tools/serve.py` is a script rather than a package module, so its directory goes on the
# path and it is imported by name. Loading it by path instead would work here and fail in
# the pool: a spawned worker unpickles a task by module name, and a module that exists only
# as an entry someone poked into sys.modules cannot be imported by a fresh interpreter.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import serve

# --------------------------------------------------------------------------------------
# Parameters: refused, not ignored
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        {"coverage": ["banana"]},
        {"coverage": ["1.5"]},
        {"coverage": ["-0.1"]},
        {"quotation": [""]},
        {"min_run": ["scaled:"]},
        {"min_run": ["scaled:0"]},
        {"min_run": ["0"]},
        {"min_run": ["six"]},
        {"min_query": ["x"]},
        {"covrage": ["0.5"]},
        {"language": ["grc"]},
    ],
)
def test_a_parameter_that_cannot_be_honoured_is_refused(query: dict[str, list[str]]) -> None:
    """Every one of these used to return 200 and the unconfigured answer.

    That is the worst shape a failure can take here: the caller sees a plausible result
    and no signal, and the only way to notice is to compare against a local searcher --
    which cost the author of the request an hour before they thought to.
    """
    with pytest.raises((ValueError, LookupError)):
        serve.search_options(query)


def test_the_parameters_that_are_honoured_are_accepted() -> None:
    options = serve.search_options(
        {
            "quotation": ["0.5"],
            "coverage": ["0.45"],
            "identified": ["0.9"],
            "min_query": ["3"],
            "min_run": ["4"],
        }
    )
    assert options == {
        "quotation": 0.5,
        "coverage": 0.45,
        "identified": 0.9,
        "min_query": 3,
        "min_run": 4,
    }


def test_an_absent_parameter_leaves_the_library_default_alone() -> None:
    """The keys must be missing, not present-and-None: `Searcher` reads its own constants
    from its signature, and passing None would override them with nothing."""
    assert serve.search_options({}) == {}
    assert serve.search_options({"q": ["x"], "limit": ["5"]}) == {}


def test_scaled_min_run_means_exactly_what_the_local_callable_means() -> None:
    """`scaled:4` is `lambda n: max(4, min(_MIN_RUN, n // 2))` and nothing else.

    A callable cannot cross a query string, so this spelling stands in for the form that
    was actually measured -- proportional with a floor, which took short Greek quotations
    from 9% found to 72%. If the two drift apart, a caller tuning against a local searcher
    would be configuring something else entirely on the server.
    """
    scaled = serve._min_run("scaled:4")

    def local(words: int) -> int:
        return max(4, min(_MIN_RUN, words // 2))

    assert callable(scaled)
    assert [scaled(n) for n in range(0, 40)] == [local(n) for n in range(0, 40)]
    assert serve._min_run("6") == 6


def test_the_job_endpoints_parameters_do_not_leak_into_search() -> None:
    """`task` is meaningful on /api/jobs and meaningless on /api/search, and a server that
    accepted it on both would be back to ignoring things silently."""
    serve.search_options({"task": ["scan"]}, serve.JOB_PARAMS)  # allowed on /api/jobs
    with pytest.raises(ValueError, match="task"):
        serve.search_options({"task": ["scan"]})  # and refused on /api/search


# --------------------------------------------------------------------------------------
# The batch body
# --------------------------------------------------------------------------------------


def test_a_batch_needs_an_id_for_every_document() -> None:
    """Results come back keyed by the caller's id rather than by position, because a
    partial failure would shift every position after it."""
    assert serve._batch_work("") == []
    assert serve._batch_work('[{"id": "a", "text": "x"}]') == [{"id": "a", "text": "x"}]
    with pytest.raises(ValueError, match="array"):
        serve._batch_work('{"id": "a"}')
    with pytest.raises(ValueError, match="needs an id"):
        serve._batch_work('[{"text": "x"}]')


# --------------------------------------------------------------------------------------
# End to end, against the built corpus
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base() -> Iterator[str]:
    # The real store, not the isolated one `conftest` installs. These tests are about what
    # the built corpus answers, and an empty data home would pass them all vacuously. The
    # server module read its own `HOME` at import, so it is redirected here too.
    real = DataHome(Path.home() / ".local/share/biblereference")
    if not Path(real.database).exists():
        pytest.skip("corpus not built; run `biblereference sync`")

    serve.HOME = real
    # And the environment with it, because a batch job runs in a spawned process that
    # builds its own DataHome -- it cannot be handed this one, and it inherits the
    # environment rather than the patch.
    previous = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = str(real.root)

    serve.JOBS = serve.Jobs(2)
    httpd = serve.Server(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        if previous is None:
            del os.environ[ENV_VAR]
        else:
            os.environ[ENV_VAR] = previous


def _post(base: str, path: str, body: str = "", content: str = "text/plain"):  # type: ignore[no-untyped-def]
    request = urllib.request.Request(
        base + path, data=body.encode(), headers={"Content-Type": content}, method="POST"
    )
    return json.load(urllib.request.urlopen(request, timeout=300))


def _status(base: str, path: str, body: str = "") -> int:
    try:
        request = urllib.request.Request(base + path, data=body.encode(), method="POST")
        urllib.request.urlopen(request, timeout=300)
    except urllib.error.HTTPError as exc:
        return exc.code
    return 200


SENTENCE = "As the evangelist says, In the beginning was the Word, and we believe it."


def test_scan_finds_a_quotation_the_caller_did_not_delimit(base: str) -> None:
    """The distinguishing case: `search` must be handed the quotation, `scan` finds it."""
    found = _post(base, "/api/scan", SENTENCE)["matches"]
    assert [m["passage"] for m in found] == ["JHN 1:1"]


def test_scan_says_where_in_the_posted_document_the_quotation_sits(base: str) -> None:
    """Character offsets into the body exactly as posted, so the caller can point back at
    its own text. That is what makes a finding checkable rather than merely plausible."""
    start, end = _post(base, "/api/scan", SENTENCE)["matches"][0]["span"]
    assert SENTENCE[start:end].startswith("In the beginning was the Word")


def test_scan_of_ordinary_prose_finds_nothing(base: str) -> None:
    """The discipline that makes a count from this honest."""
    prose = "and therefore we must consider what the blessed teacher intended by these words"
    assert _post(base, "/api/scan", prose)["matches"] == []


def test_an_empty_document_is_not_an_error(base: str) -> None:
    assert _post(base, "/api/scan", "")["matches"] == []


def test_the_scan_endpoint_is_the_library_not_a_second_implementation(base: str) -> None:
    """If these ever diverge, the server becomes a place where results drift."""
    from biblereference.search import Searcher

    remote = [
        (m["passage"], tuple(m["span"])) for m in _post(base, "/api/scan", SENTENCE)["matches"]
    ]
    with Searcher(DataHome()) as searcher:
        local = [(str(m.passage), m.span) for m in searcher.scan(SENTENCE)]
    assert remote == local


def test_a_filter_naming_something_this_machine_lacks_is_an_error(base: str) -> None:
    """Not an empty result, which would be indistinguishable from nothing matching."""
    assert _status(base, "/api/search?languages=klingon", SENTENCE) == 400
    assert _status(base, "/api/search?corpora=vulgate-of-atlantis", SENTENCE) == 400
    assert _status(base, "/api/search?languages=grc", SENTENCE) == 200


def test_every_result_names_the_library_that_produced_it(base: str) -> None:
    """A mapping correction is an edit to a JSON file, not a version bump, so a caller
    recording only a version would not notice one."""
    stamp = _post(base, "/api/scan", SENTENCE)["library"]
    digest = json.load(urllib.request.urlopen(base + "/api/digest", timeout=300))

    assert stamp["versification"] == digest["versification"]
    assert stamp["digest"] == digest["library"]
    assert _post(base, "/api/search", SENTENCE)["library"] == stamp


@pytest.mark.parametrize(
    "query",
    [
        "",
        "min_run=4",
        "coverage=0.5",
        # The regression. Every parameter has to survive being pickled into a worker, and
        # a closure does not: `scaled:` is the calibrated configuration -- the one the
        # batch exists to run at scale -- and it was the one setting the batch could not
        # accept, while the settings not worth running at scale all worked. The earlier
        # version of this test passed only because it never sent one.
        "min_run=scaled:4",
        "min_run=scaled:3&coverage=0.5",
        "min_run=scaled:6&coverage=0.4&identified=0.9&min_query=3",
    ],
)
def test_a_batch_is_an_optimisation_not_a_different_algorithm(base: str, query: str) -> None:
    """Results keyed by the caller's id, identical to scanning the same documents singly,
    and one unreadable document does not lose the rest -- forty-three thousand passages is
    too many to resubmit because one of them was null.
    """
    documents = [
        {"id": "quoted", "text": SENTENCE},
        {"id": "prose", "text": "and therefore we must consider what he intended"},
        {"id": "bad", "text": None},
    ]
    suffix = f"&{query}" if query else ""
    job = _post(base, f"/api/jobs?task=scan{suffix}", json.dumps(documents), "application/json")
    assert job["total"] == 3

    for _ in range(600):
        state = json.load(urllib.request.urlopen(f"{base}/api/jobs/{job['id']}", timeout=60))
        if state["state"] != "running":
            break
        time.sleep(0.2)

    assert state["state"] == "done"
    assert state["done"] == 3
    assert set(state["result"]["found"]) == {"quoted", "prose"}
    assert set(state["result"]["failed"]) == {"bad"}, "a chunk must not fail as a whole"
    assert "library" in state

    for document in documents[:2]:
        singly = _post(base, f"/api/scan?{query}", document["text"])["matches"]
        assert state["result"]["found"][document["id"]] == singly


def test_inflected_matching_can_be_asked_for_over_the_wire() -> None:
    """It shipped reachable only from a local `Searcher`.

    A consumer running this on another machine had no way to switch it on, and
    `search_options` would have refused the parameter as unknown -- so the feature existed
    and answered as though it had been asked for and found nothing. That is the exact shape
    of silence this function was written to prevent, in the one place it was not applied.
    """
    assert serve.search_options({"inflected": ["true"]}) == {"inflected": True}
    assert serve.search_options({"inflected": ["false"]}) == {"inflected": False}
    with pytest.raises(ValueError, match="true or false"):
        serve.search_options({"inflected": ["maybe"]})


def test_gates_travel_as_a_repeatable_parameter() -> None:
    """A union, because the gates are complementary rather than nested and expressing that
    took three separate passes before."""
    from biblereference.search import Gate

    options = serve.search_options({"gate": ["0:4:0:40", "0:0:8:40"]})
    assert options["gates"] == [Gate(lemma_run=4, bits=40.0), Gate(chain=8, bits=40.0)]
    with pytest.raises(ValueError, match="run:lemma_run:chain:bits"):
        serve.search_options({"gate": ["4:40"]})


def test_the_listen_backlog_is_not_five() -> None:
    """`socketserver` defaults it to 5, and the excess is **reset by the kernel** -- no log
    line, no error, because the connection never reaches the application.

    A consumer opening two dozen concurrent scans hit exactly that and could not tell it from
    the server having crashed. What executes at once is `--interactive-workers`; this only
    decides whether the rest wait or are refused, which is the difference between a slow
    server and a broken one.
    """
    import socketserver

    assert socketserver.TCPServer.request_queue_size == 5, "the default this exists to override"
    assert serve.Server.request_queue_size >= 128
