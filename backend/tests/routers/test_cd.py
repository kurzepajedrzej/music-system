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
