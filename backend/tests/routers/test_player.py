import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_seek_while_playing_keeps_playing():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        side_effect=[
            httpx.Response(200, json={"state": "play"}),
            httpx.Response(200, json={"state": "play"}),
            httpx.Response(200, json={"state": "play"}),
        ]
    )
    seek_route = respx.put(f"{config.OWNTONE_URL}/api/player/seek?position_ms=5000").mock(
        return_value=httpx.Response(204)
    )
    play_route = respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(204)
    )
    r = client.put("/api/player/seek?position_ms=5000")
    assert r.status_code == 200
    assert seek_route.called
    assert play_route.called  # was playing, so re-asserting play is correct


@respx.mock
def test_seek_while_paused_does_not_force_play():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "pause"})
    )
    respx.put(f"{config.OWNTONE_URL}/api/player/seek?position_ms=5000").mock(
        return_value=httpx.Response(204)
    )
    play_route = respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(204)
    )
    r = client.put("/api/player/seek?position_ms=5000")
    assert r.status_code == 200
    assert not play_route.called  # was paused — must not force playback to resume


def test_volume_out_of_range_rejected():
    r = client.put("/api/player/volume", json={"volume": 150})
    assert r.status_code == 422


@respx.mock
def test_volume_in_range_accepted():
    respx.put(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(204))
    r = client.put("/api/player/volume", json={"volume": 50})
    assert r.status_code == 200


def test_unknown_command_rejected():
    r = client.put("/api/player/not-a-real-command")
    assert r.status_code == 404


@respx.mock
def test_bare_prefix_answers_directly_without_redirect():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "stop"})
    )
    r = client.get("/api/player", follow_redirects=False)
    assert r.status_code == 200
