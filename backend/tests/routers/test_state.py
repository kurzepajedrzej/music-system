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


@respx.mock
def test_bare_prefix_answers_directly_without_redirect():
    # /api/state (no trailing slash) used to only be registered as
    # /api/state/, so the bare form 307-redirected — and the redirect's
    # Location header hardcodes http:// even behind X-Forwarded-Proto:
    # https. Both decorators must now answer directly with no redirect.
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(500))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(500))
    r = client.get("/api/state", follow_redirects=False)
    assert r.status_code == 200


_OUTPUTS = [
    {"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12},
    {"id": "0", "name": "Computer", "type": "ALSA", "selected": False, "volume": 50},
]


@respx.mock
def test_state_includes_full_unfiltered_outputs():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(200, json={"state": "stop"}))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(
        return_value=httpx.Response(200, json={"outputs": _OUTPUTS})
    )
    r = client.get("/api/state")
    assert r.status_code == 200
    # Unfiltered on purpose: the ALSA output stays in. AirPlay filtering is each consumer's job.
    assert r.json()["outputs"] == _OUTPUTS


@respx.mock
def test_state_outputs_degrade_to_empty_without_losing_the_rest():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"item_id": 5, "state": "play"})
    )
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 5, "title": "Song"}]})
    )
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(return_value=httpx.Response(500))
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["outputs"] == []
    assert body["currentTrack"]["title"] == "Song"
