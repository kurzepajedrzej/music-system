# tests/routers/test_cd.py
from fastapi.testclient import TestClient

from app.cdplayer.manager import manager
from app.main import app

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
