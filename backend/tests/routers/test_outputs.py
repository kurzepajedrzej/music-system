import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_get_outputs():
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(
        return_value=httpx.Response(200, json={"outputs": []})
    )
    r = client.get("/api/outputs")
    assert r.status_code == 200


@respx.mock
def test_set_output():
    respx.put(f"{config.OWNTONE_URL}/api/outputs/1").mock(return_value=httpx.Response(204))
    r = client.put("/api/outputs/1", json={"selected": True})
    assert r.status_code == 200
