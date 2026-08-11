import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def test_play_rejects_empty_uri():
    r = client.post("/api/queue/play", json={"uri": ""})
    assert r.status_code == 422


@respx.mock
def test_play_accepts_valid_uri():
    respx.put(f"{config.OWNTONE_URL}/api/queue/clear").mock(return_value=httpx.Response(204))
    respx.post(f"{config.OWNTONE_URL}/api/queue/items/add?uris=library:track:1&playback=start").mock(
        return_value=httpx.Response(200)
    )
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "play"})
    )
    r = client.post("/api/queue/play", json={"uri": "library:track:1"})
    assert r.status_code == 200


def test_remove_item_rejects_non_numeric_id():
    r = client.delete("/api/queue/items/not-a-number")
    assert r.status_code == 422


@respx.mock
def test_remove_item_accepts_numeric_id():
    respx.delete(f"{config.OWNTONE_URL}/api/queue/items/7").mock(return_value=httpx.Response(200))
    r = client.delete("/api/queue/items/7")
    assert r.status_code == 200


@respx.mock
def test_bare_prefix_answers_directly_without_redirect():
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(200, json={"items": []}))
    r = client.get("/api/queue", follow_redirects=False)
    assert r.status_code == 200
