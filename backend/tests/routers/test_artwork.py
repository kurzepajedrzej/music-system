import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


@respx.mock
def test_album_artwork_resolves_via_artwork_url_only():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": "42", "artwork_url": "/artwork/group/3"}]}
        )
    )
    respx.get(f"{config.OWNTONE_URL}/artwork/group/3").mock(
        return_value=httpx.Response(200, content=b"fake-jpeg", headers={"Content-Type": "image/jpeg"})
    )
    r = client.get("/api/artwork/album/42")
    assert r.status_code == 200
    assert r.content == b"fake-jpeg"


@respx.mock
def test_unknown_album_id_returns_404_not_traversal():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    r = client.get("/api/artwork/album/nonexistent")
    assert r.status_code == 404


def test_path_traversal_attempt_is_rejected():
    r = client.get("/api/artwork/album/..%2F..%2Fapi%2Fconfig")
    assert r.status_code in (400, 404)


@respx.mock
def test_item_artwork_only_accepts_digits():
    route = respx.get(f"{config.OWNTONE_URL}/artwork/item/7").mock(
        return_value=httpx.Response(200, content=b"x", headers={"Content-Type": "image/jpeg"})
    )
    r = client.get("/api/artwork/item/7")
    assert r.status_code == 200
    assert route.called


def test_item_artwork_rejects_non_digit_id():
    r = client.get("/api/artwork/item/../../config")
    assert r.status_code in (400, 404, 422)
