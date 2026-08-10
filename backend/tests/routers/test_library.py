import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_get_albums():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 1, "items": [{"id": "1", "name": "Album"}]})
    )
    r = client.get("/api/library/albums")
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "Album"


@respx.mock
def test_get_album_tracks():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums/1/tracks").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    r = client.get("/api/library/albums/1/tracks")
    assert r.status_code == 200
