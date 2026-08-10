import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_health_200_when_owntone_reachable():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{config.OWNTONE_URL}/api/library/tracks/1").mock(return_value=httpx.Response(404))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["owntone"] is True


@respx.mock
def test_health_503_when_owntone_returns_error_status_not_just_on_network_failure():
    # The old bug: a 500 from OwnTone still reported healthy because only
    # "did fetch throw" was checked, never the response status.
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(500))
    respx.get(f"{config.OWNTONE_URL}/api/library/tracks/1").mock(return_value=httpx.Response(500))
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["owntone"] is False
