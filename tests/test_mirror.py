"""Copying one machine's archive to another.

`sync` cannot promise two machines match, because it downloads from a dozen upstreams and
upstream is free to publish something different between one machine's run and the other's.
That is not hypothetical: two machines synced two days apart disagreed about two of
eBible's files, because eBible had republished them in between. Mirroring is the only way
to be sure, so the thing it must never do is write bytes it cannot vouch for.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from biblereference.fetch import mirror_archive
from biblereference.store import DataHome, ManifestEntry

PAYLOAD = b"the bytes of an archived download" * 64


def _entry(payload: bytes = PAYLOAD, *, sha256: str | None = None) -> ManifestEntry:
    return ManifestEntry(
        source="asv",
        url="https://ebible.org/Scriptures/eng-asv_usfm.zip",
        path="asv/2026-08-03/eng-asv_usfm.zip",
        sha256=sha256 or hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        fetched_at="2026-08-03T20:26:45+00:00",
        license="Public domain.",
    )


class _Stub:
    """The two endpoints a mirror needs, and a count of what was actually transferred."""

    def __init__(self, entries: list[ManifestEntry], payload: bytes) -> None:
        self.entries, self.payload, self.served = entries, payload, 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.startswith("/api/manifest"):
                    from dataclasses import asdict

                    body = json.dumps({"entries": [asdict(e) for e in stub.entries]}).encode()
                else:
                    stub.served += 1
                    body = stub.payload
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()


@pytest.fixture
def home(tmp_path: Path) -> DataHome:
    home = DataHome(tmp_path / "brhome")
    home.prepare()
    return home


@pytest.fixture
def stub() -> Iterator[_Stub]:
    server = _Stub([_entry()], PAYLOAD)
    yield server
    server.close()


def test_mirroring_copies_the_bytes_and_the_record(home: DataHome, stub: _Stub) -> None:
    """The manifest line is copied verbatim, not rewritten.

    It says where the bytes originally came from and when, which is the honest record --
    and it is what makes the two machines' digests agree, since a line invented here would
    carry this machine's clock.
    """
    result = mirror_archive(home, stub.url)

    assert (result.copied, result.corrupt) == (1, 0)
    assert (home.sources / "asv/2026-08-03/eng-asv_usfm.zip").read_bytes() == PAYLOAD
    assert home.entries() == [_entry()]


def test_mirroring_twice_transfers_nothing(home: DataHome, stub: _Stub) -> None:
    """Resumable by construction, which matters at 155 MB over a link that may drop."""
    mirror_archive(home, stub.url)
    assert stub.served == 1

    again = mirror_archive(home, stub.url)

    assert (again.copied, again.already_held) == (0, 1)
    assert stub.served == 1, "a file already held must not be fetched again"
    assert home.entries() == [_entry()], "nor recorded twice"


def test_a_file_that_went_bad_on_disk_is_replaced(home: DataHome, stub: _Stub) -> None:
    """Held is not the same as intact, so what is on disk is hashed rather than assumed."""
    mirror_archive(home, stub.url)
    target = home.sources / "asv/2026-08-03/eng-asv_usfm.zip"
    target.write_bytes(PAYLOAD + b"corruption")

    assert mirror_archive(home, stub.url).copied == 1
    assert target.read_bytes() == PAYLOAD


def test_bytes_that_do_not_match_their_checksum_are_refused(home: DataHome) -> None:
    """The one thing a mirror must never do.

    A truncated transfer, a proxy rewriting content, or a server simply lying all look the
    same from here, and all of them end as a wrong verse months later. The checksum is
    checked *before* anything is written, so the archive is never the thing that is wrong.
    """
    server = _Stub([_entry(sha256="0" * 64)], PAYLOAD)
    try:
        result = mirror_archive(home, server.url)
    finally:
        server.close()

    assert (result.copied, result.corrupt) == (0, 1)
    assert not (home.sources / "asv/2026-08-03/eng-asv_usfm.zip").exists()
    assert home.entries() == [], "and nothing is recorded as held that is not held"


def test_the_same_bytes_under_another_path_are_not_fetched_again(home: DataHome) -> None:
    """Archive paths carry the date the file was fetched, so two machines that synced on
    different days hold every file under a different path while almost all of the bytes
    are identical. Keyed on path alone, the first real mirror between two machines here
    moved 155 MB to change two files."""
    from dataclasses import replace

    mine = _entry()
    home.sources.joinpath(mine.path).parent.mkdir(parents=True, exist_ok=True)
    home.sources.joinpath(mine.path).write_bytes(PAYLOAD)
    home.record(mine)

    theirs = replace(mine, path="asv/2026-08-05/eng-asv_usfm.zip")
    server = _Stub([theirs], PAYLOAD)
    try:
        result = mirror_archive(home, server.url)
    finally:
        server.close()

    assert (result.copied, result.reused) == (0, 1)
    assert server.served == 0, "the bytes were already here"
    assert home.sources.joinpath(theirs.path).read_bytes() == PAYLOAD
    assert home.entries() == [mine, theirs], "and both paths are recorded, as both exist"


def test_bytes_already_on_disk_are_adopted(home: DataHome, stub: _Stub) -> None:
    """A hand-copied `sources/` directory -- rsync, a USB disk -- has the files but no
    manifest. Hashing what is there lets the mirror recognise them and record them rather
    than transfer 155 MB again."""
    target = home.sources / "asv/2026-08-03/eng-asv_usfm.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PAYLOAD)

    result = mirror_archive(home, stub.url)

    assert (result.copied, result.already_held) == (0, 1)
    assert stub.served == 0
    assert home.entries() == [_entry()]


def test_a_local_copy_is_verified_before_it_is_trusted(home: DataHome) -> None:
    """Reusing local bytes must not become a way to launder a rotted file into a new path.

    The candidate is hashed, not taken on the manifest's word -- and when it fails, the
    mirror falls back to fetching rather than quietly skipping.
    """
    from dataclasses import replace

    mine = _entry()
    home.sources.joinpath(mine.path).parent.mkdir(parents=True, exist_ok=True)
    home.sources.joinpath(mine.path).write_bytes(b"rotted on disk")
    home.record(mine)  # the manifest still claims the good checksum

    theirs = replace(mine, path="asv/2026-08-05/eng-asv_usfm.zip")
    server = _Stub([theirs], PAYLOAD)
    try:
        result = mirror_archive(home, server.url)
    finally:
        server.close()

    assert (result.copied, result.reused) == (1, 0), "the rotted copy must not be reused"
    assert server.served == 1
    assert home.sources.joinpath(theirs.path).read_bytes() == PAYLOAD


def test_an_archive_of_nested_files_is_not_fetched_twice(tmp_path: Path) -> None:
    """The already-fetched check has to look inside directories, not only at them.

    ``RemoteFile.name`` may contain a slash. A non-recursive listing of the archive then
    sees the directory and never the file, matches nothing, and re-downloads every file of
    the source on every run -- which for a source of two files is invisible and for one of
    a hundred and seventy-seven is the whole sync.
    """
    from dataclasses import replace

    from biblereference.fetch import fetch_source
    from biblereference.sources import RemoteFile, get_source

    home = DataHome(tmp_path)
    home.prepare()
    source = replace(
        get_source("oshb"),
        files=(RemoteFile(url="https://example.invalid/a.xml", name="tei/a.xml"),),
    )
    home.store_file(source.id, "tei/a.xml", b"<TEI/>", url="https://example.invalid/a.xml")

    # No network client is opened at all if the check works; if it does not, httpx tries
    # to reach example.invalid and the test fails with a connection error rather than
    # quietly passing.
    result = fetch_source(source, home)
    assert result.files == 0
    assert result.skipped == 1


def test_a_rate_limited_download_is_retried_rather_than_lost(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """177 files against one host cannot afford to lose the run to one 429.

    The failure is almost never about the file: it is a rate limit or a moment's
    unavailability, and without a retry the whole fetch is abandoned and the user is told
    to run it again. A 404 is different -- it means a wrong URL, and waiting will not mend
    it -- so only 429 and 5xx are retried.
    """
    import httpx

    from biblereference import fetch as fetch_module

    monkeypatch.setattr(fetch_module.time, "sleep", lambda _: None)

    attempts = []

    class _Client:
        def get(self, url: str) -> httpx.Response:
            attempts.append(url)
            code = 429 if len(attempts) < 3 else 200
            return httpx.Response(code, content=b"ok", request=httpx.Request("GET", url))

    payload = fetch_module._get(_Client(), "https://example.invalid/a.xml")  # type: ignore[arg-type]
    assert payload == b"ok"
    assert len(attempts) == 3, "gave up too early, or did not stop once it succeeded"


def test_a_missing_file_is_not_retried(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A 404 is a wrong URL. Retrying it wastes three waits and still fails."""
    import httpx
    import pytest as _pytest

    from biblereference import fetch as fetch_module

    monkeypatch.setattr(fetch_module.time, "sleep", lambda _: None)
    attempts = []

    class _Client:
        def get(self, url: str) -> httpx.Response:
            attempts.append(url)
            return httpx.Response(404, request=httpx.Request("GET", url))

    with _pytest.raises(httpx.HTTPStatusError):
        fetch_module._get(_Client(), "https://example.invalid/gone.xml")  # type: ignore[arg-type]
    assert len(attempts) == 1
