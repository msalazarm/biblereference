"""The wire: keep-alive, assets, and who is allowed to ask.

Nothing here needs a corpus. It is about the socket and the headers, which are the parts
that fail in ways the endpoint tests cannot see -- a desynchronised connection answers the
*next* request wrongly, and a 401 on a stylesheet leaves a page that loads and looks broken.
"""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from biblereference.store import DataHome
from biblereference.web import server
from biblereference.web.assets import assets

TOKEN = "a-token-of-some-length"


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[server.Server]:
    """A real server on a real socket, over an empty data home.

    Empty on purpose: these tests must not depend on anything having been built, and the
    routes they exercise do not read a verse.
    """
    monkeypatch.setattr(server, "HOME", DataHome(tmp_path))
    monkeypatch.setattr(server, "TOKEN", None)
    httpd = server.Server(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def connect(httpd: server.Server) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)


# --------------------------------------------------------------------------------------
# Keep-alive
# --------------------------------------------------------------------------------------


def test_one_connection_serves_many_requests(live: server.Server) -> None:
    """A page is a document plus its assets: several requests in a burst, and a handshake
    each is pure waste. HTTP/1.1 is safe here because every response sends an accurate
    Content-Length."""
    connection = connect(live)
    try:
        for _ in range(3):
            connection.request("GET", "/static/style.css")
            response = connection.getresponse()
            body = response.read()
            assert response.status == 200
            assert response.version == 11
            assert len(body) == int(response.getheader("Content-Length"))
            assert response.getheader("Connection") != "close"
    finally:
        connection.close()


def test_a_refused_body_closes_the_connection(
    live: server.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The desync guard, and the reason the 413 path is special.

    A body over the limit is never read off the socket. Kept alive, the next read would
    start partway through the rejected document and parse it as a request line -- from then
    on the client and the server disagree about where every request begins, and the failure
    surfaces as a nonsensical answer to a later, innocent request.
    """
    monkeypatch.setattr(server, "MAX_BODY", 64)
    connection = connect(live)
    try:
        connection.request("POST", "/api/scan", body="x" * 500)
        response = connection.getresponse()
        assert response.status == 413
        assert "raise --max-body" in json.loads(response.read())["error"]
        assert response.getheader("Connection") == "close"
    finally:
        connection.close()


def test_a_body_within_the_limit_keeps_it(live: server.Server) -> None:
    """The other half: refusing must be the exception, not an excuse to close always."""
    connection = connect(live)
    try:
        connection.request("POST", "/api/convert?ref=John+3:16", body="")
        first = connection.getresponse()
        first.read()
        assert first.getheader("Connection") != "close"

        connection.request("GET", "/api/corpora")
        second = connection.getresponse()
        assert second.status == 200
        assert json.loads(second.read())["corpora"] == []
    finally:
        connection.close()


# --------------------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------------------


def test_the_shipped_assets_are_found_as_package_data(live: server.Server) -> None:
    """`.gitignore` has an unanchored `build/`, so a static directory by the wrong name
    would vanish from the wheel with no error at all. This is what would notice."""
    assert "style.css" in assets()
    assert assets()["style.css"].type == "text/css; charset=utf-8"
    assert b"--measure" in assets()["style.css"].body


def test_an_unchanged_asset_costs_a_304_and_no_body(live: server.Server) -> None:
    connection = connect(live)
    try:
        connection.request("GET", "/static/style.css")
        first = connection.getresponse()
        body = first.read()
        etag = first.getheader("ETag")
        assert first.status == 200
        assert etag and etag.startswith('"')
        assert first.getheader("Cache-Control") == "no-cache"

        connection.request("GET", "/static/style.css", headers={"If-None-Match": etag})
        second = connection.getresponse()
        assert second.status == 304
        assert second.read() == b""
        assert len(body) > 0
    finally:
        connection.close()


@pytest.mark.parametrize(
    "name",
    [
        "../server.py",
        "..%2Fserver.py",
        "../../../../etc/passwd",
        "style.css/../../__init__.py",
        "nonesuch.css",
        "__init__.py",
    ],
)
def test_a_name_that_is_not_a_shipped_asset_is_a_404(live: server.Server, name: str) -> None:
    """There is no path here, only a key, which is the whole traversal defence: a name that
    is not in the manifest cannot name a file, so there is nothing to escape from."""
    connection = connect(live)
    try:
        connection.request("GET", f"/static/{name}")
        response = connection.getresponse()
        assert response.status == 404
        assert "no such asset" in json.loads(response.read())["error"]
    finally:
        connection.close()


# --------------------------------------------------------------------------------------
# The token
# --------------------------------------------------------------------------------------


def test_no_token_configured_means_no_token_required(live: server.Server) -> None:
    connection = connect(live)
    try:
        connection.request("GET", "/api/corpora")
        assert connection.getresponse().status == 200
    finally:
        connection.close()


def test_a_configured_token_is_wanted_everywhere(
    live: server.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assets included. A page that loaded and whose stylesheet 401'd would look broken
    rather than unauthorised."""
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        for path in ("/", "/api/corpora", "/static/style.css"):
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            assert response.status == 401, path
    finally:
        connection.close()


@pytest.mark.parametrize(
    "headers,path",
    [
        ({"Authorization": f"Bearer {TOKEN}"}, "/api/corpora"),
        ({}, f"/api/corpora?token={TOKEN}"),
        ({"Cookie": f"br_token={TOKEN}"}, "/api/corpora"),
    ],
)
def test_the_token_is_taken_from_any_of_its_three_places(
    live: server.Server, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], path: str
) -> None:
    """A header is what a script sends, a query parameter is how a person arrives from a
    link, and a cookie is how they stay. `curl "$BR/api/search?token=..."` keeps working."""
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        response.read()
        assert response.status == 200
    finally:
        connection.close()


def test_arriving_with_a_good_token_sets_the_cookie(
    live: server.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which is what makes the assets loadable: a <link> cannot carry an Authorization
    header, so the browser has to be given something it will attach by itself."""
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        connection.request("GET", f"/?token={TOKEN}")
        response = connection.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie")
        assert response.status == 200
        assert cookie is not None
        assert cookie.startswith(f"br_token={TOKEN};")
        # SameSite=Strict is the whole CSRF answer -- a cross-site page cannot make the
        # browser send it at all -- and HttpOnly because nothing in the page reads it.
        assert "SameSite=Strict" in cookie
        assert "HttpOnly" in cookie
        assert "Path=/" in cookie
    finally:
        connection.close()


def test_a_wrong_token_sets_nothing(live: server.Server, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        connection.request("GET", "/?token=not-the-token")
        response = connection.getresponse()
        response.read()
        assert response.status == 401
        assert response.getheader("Set-Cookie") is None
    finally:
        connection.close()


def test_a_malformed_cookie_jar_is_unauthenticated_rather_than_a_500(
    live: server.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        connection.request("GET", "/api/corpora", headers={"Cookie": 'br_token="unclosed; ;;='})
        response = connection.getresponse()
        response.read()
        assert response.status == 401
    finally:
        connection.close()


def test_a_non_ascii_token_is_refused_rather_than_raising(
    live: server.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hmac.compare_digest` rejects non-ASCII str with a TypeError, which would be a 500
    -- and a 500 on the authorisation path says "something here is broken" to exactly the
    caller who should be told "no".

    Through the query string, because that is the only one of the three places it can
    arrive: a header is latin-1 on the wire and `http.client` will not even send this one.
    """
    monkeypatch.setattr(server, "TOKEN", TOKEN)
    connection = connect(live)
    try:
        connection.request("GET", "/api/corpora?token=%CE%B1%CF%81%CF%87%CE%AE")
        response = connection.getresponse()
        response.read()
        assert response.status == 401
    finally:
        connection.close()
