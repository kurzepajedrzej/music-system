import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_full_health_to_player_to_queue_flow():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "play", "item_id": 1})
    )
    respx.get(f"{config.OWNTONE_URL}/api/library/tracks/1").mock(return_value=httpx.Response(404))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1, "title": "Song"}]})
    )

    health = client.get("/api/health")
    assert health.status_code == 200

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["currentTrack"]["title"] == "Song"

    cd_status = client.get("/api/cd/status")
    assert cd_status.status_code == 200
