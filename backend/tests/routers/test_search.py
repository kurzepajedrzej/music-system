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
