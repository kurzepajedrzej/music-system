import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_state_combines_player_queue_and_cd():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"item_id": 5, "state": "play"})
    )
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 5, "title": "Song"}]})
    )
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["currentTrack"]["title"] == "Song"
    assert "cd" in body


@respx.mock
def test_state_degrades_gracefully_when_owntone_down():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(500))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(500))
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["player"] is None
