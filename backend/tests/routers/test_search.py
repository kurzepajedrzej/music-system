import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_search_honors_type_param():
    route = respx.get(f"{config.OWNTONE_URL}/api/search?type=tracks&query=foo").mock(
        return_value=httpx.Response(200, json={"tracks": {"items": []}})
    )
    r = client.get("/api/search?query=foo&type=tracks")
    assert r.status_code == 200
    assert route.called


@respx.mock
def test_search_defaults_to_both_types():
    route = respx.get(f"{config.OWNTONE_URL}/api/search?type=tracks,albums&query=foo").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get("/api/search?query=foo")
    assert r.status_code == 200
    assert route.called


@respx.mock
def test_search_with_ampersand_in_query_returns_200_not_500():
    # Regression test: an unencoded "&" in the query used to break the
    # upstream URL's own query-string parsing, producing a 500 that the
    # frontend's catch-all swallowed into a silent "No results" — e.g.
    # searching "Simon & Garfunkel". The client-sent query here is already
    # percent-encoded ("a%26b" -> "a&b" once FastAPI decodes it), matching
    # what a real browser would send for a query containing "&".
    route = respx.get(f"{config.OWNTONE_URL}/api/search?type=tracks,albums&query=a%26b").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get("/api/search/?query=a%26b")
    assert r.status_code == 200
    assert route.called


@respx.mock
def test_bare_prefix_answers_directly_without_redirect():
    respx.get(f"{config.OWNTONE_URL}/api/search?type=tracks,albums&query=foo").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get("/api/search?query=foo", follow_redirects=False)
    assert r.status_code == 200
