import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.owntone import client as owntone

client = TestClient(app)


def _reset_album_artwork_cache(monkeypatch):
    # _album_artwork_cache and _last_forced_refresh_at are module-level
    # globals in app.owntone.client, shared across the whole test session.
    # Reset them so each test's respx mocks are actually exercised instead
    # of silently answered from another test's stale cached data.
    monkeypatch.setattr(owntone, "_album_artwork_cache", None)
    monkeypatch.setattr(owntone, "_last_forced_refresh_at", 0.0)


@respx.mock
def test_album_artwork_resolves_via_artwork_url_only(monkeypatch):
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": "42", "artwork_url": "/artwork/group/3"}]}
        )
    )
    respx.get(f"{config.OWNTONE_URL}/artwork/group/3").mock(
        return_value=httpx.Response(200, content=b"fake-jpeg", headers={"Content-Type": "image/jpeg"})
    )
    r = client.get("/api/artwork/album/42")
    assert r.status_code == 200
    assert r.content == b"fake-jpeg"


@respx.mock
def test_unknown_album_id_returns_404_not_traversal(monkeypatch):
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    r = client.get("/api/artwork/album/nonexistent")
    assert r.status_code == 404


def test_path_traversal_attempt_is_rejected():
    r = client.get("/api/artwork/album/..%2F..%2Fapi%2Fconfig")
    assert r.status_code in (400, 404)


@respx.mock
def test_album_artwork_path_traversal_payload_never_reaches_upstream(monkeypatch):
    # Belt-and-suspenders version of the test above: also proves the
    # upstream OwnTone endpoint is never contacted for this payload, not
    # just that the response happens to be a 404.
    _reset_album_artwork_cache(monkeypatch)
    route = respx.get(url__regex=r".*/(artwork|api)/.*").mock(
        return_value=httpx.Response(200, content=b"should not be reached")
    )
    r = client.get("/api/artwork/album/..%2F..%2Fapi%2Fconfig")
    assert r.status_code == 404
    assert not route.called


@respx.mock
def test_album_artwork_returns_502_when_owntone_unreachable(monkeypatch):
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    r = client.get("/api/artwork/album/42")
    assert r.status_code == 502


@respx.mock
def test_item_artwork_only_accepts_digits():
    route = respx.get(f"{config.OWNTONE_URL}/artwork/item/7").mock(
        return_value=httpx.Response(200, content=b"x", headers={"Content-Type": "image/jpeg"})
    )
    r = client.get("/api/artwork/item/7")
    assert r.status_code == 200
    assert route.called


def test_item_artwork_rejects_non_digit_id():
    # Plain non-digit content — FastAPI's int path converter must reject
    # this outright (422), independent of any URL-normalization question
    # (see the traversal test below for why literal dots don't prove this).
    r = client.get("/api/artwork/item/abc")
    assert r.status_code == 422


@respx.mock
def test_item_artwork_path_traversal_payload_never_reaches_upstream():
    # A literal "../../" in the URL is normalized away by the HTTP client
    # itself before the request is even sent (httpx, like a browser,
    # resolves dot segments client-side) — so a test built on literal dots
    # never actually delivers a traversal payload to the server, and would
    # pass green even against a deliberately vulnerable router. A
    # percent-encoded payload survives client-side normalization intact and
    # actually reaches our routing layer, so this is the payload that proves
    # something real: the request must be rejected AND the upstream must
    # never be called.
    route = respx.get(url__regex=r".*/(artwork|api)/.*").mock(
        return_value=httpx.Response(200, content=b"should not be reached")
    )
    r = client.get("/api/artwork/item/..%2F..%2Fapi%2Fconfig")
    assert r.status_code == 404
    assert not route.called
