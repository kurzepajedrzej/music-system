# tests/routers/test_cd.py
import pytest
from fastapi.testclient import TestClient

from app.cdplayer.manager import manager
from app.main import app


class FakeCdPlayer:
    def __init__(self):
        self._state = "stopped"
        self._disc = 1

    def subscribe(self, cb):
        pass

    def status(self):
        return {"state": self._state, "disc_present": True, "track": 1,
                "total_tracks": 10, "elapsed_seconds": 0, "track_duration_seconds": 200,
                "disc": self._disc}

    async def play(self):
        self._state = "playing"

    async def pause(self):
        self._state = "paused"

    async def stop(self):
        self._state = "stopped"

    async def next_track(self):
        pass

    async def prev_track(self):
        pass

    async def open_close(self):
        pass

    async def select_disc(self, n):
        self._disc = n

    async def disc_next(self):
        pass

    async def disc_prev(self):
        pass

    async def toggle_repeat(self):
        pass

    async def toggle_random(self):
        pass

    async def search_forward(self):
        pass

    async def search_backward(self):
        pass

    async def select_track(self, n):
        pass

    async def power_on(self):
        self._state = "changing"

    async def power_off(self):
        self._state = "powered_off"


@pytest.fixture(autouse=True)
def fake_cd_player():
    original = manager._player
    manager._player = FakeCdPlayer()
    manager._optimistic_status = None
    yield
    manager._player = original


client = TestClient(app)


def test_get_status():
    r = client.get("/api/cd/status")
    assert r.status_code == 200
    assert "state" in r.json()


def test_valid_command_accepted():
    r = client.post("/api/cd/play")
    assert r.status_code == 200
    assert manager.status()["state"] == "playing"


def test_invalid_command_rejected():
    r = client.post("/api/cd/not-a-command")
    assert r.status_code == 404


def test_new_zero_arg_commands_accepted():
    for cmd in [
        "open-close",
        "disc-next",
        "disc-prev",
        "repeat",
        "random",
        "search-forward",
        "search-backward",
    ]:
        r = client.post(f"/api/cd/{cmd}")
        assert r.status_code == 200, cmd


def test_select_disc_accepts_valid_range():
    r = client.post("/api/cd/disc/3")
    assert r.status_code == 200


def test_select_disc_rejects_out_of_range():
    assert client.post("/api/cd/disc/6").status_code == 422
    assert client.post("/api/cd/disc/0").status_code == 422


def test_select_track_accepts_valid_range():
    r = client.post("/api/cd/track/5")
    assert r.status_code == 200


def test_select_track_rejects_out_of_range():
    assert client.post("/api/cd/track/0").status_code == 422
    assert client.post("/api/cd/track/100").status_code == 422


def test_power_off_and_on_accepted():
    r = client.post("/api/cd/power-off")
    assert r.status_code == 200
    assert manager.status()["state"] == "powered_off"

    r = client.post("/api/cd/power-on")
    assert r.status_code == 200
    assert manager.status()["state"] == "changing"
