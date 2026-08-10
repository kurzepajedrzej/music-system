import httpx
import pytest
import respx

from app import config
from app.owntone import client as owntone


@respx.mock
async def test_get_raises_on_non_2xx():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(owntone.OwnToneError):
        await owntone.get_player()


@respx.mock
async def test_put_raises_on_non_2xx_instead_of_silently_noop():
    route = respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(400)
    )
    with pytest.raises(owntone.OwnToneError):
        await owntone.player_command("play")
    assert route.called


@respx.mock
async def test_put_succeeds_on_2xx():
    respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(204)
    )
    await owntone.player_command("play")  # must not raise


@respx.mock
async def test_resolve_album_artwork_path_uses_artwork_url_field_only():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "items": [{"id": "42", "artwork_url": "/artwork/group/3"}]},
        )
    )
    path = await owntone.resolve_album_artwork_path("42")
    assert path == "artwork/group/3"


@respx.mock
async def test_resolve_album_artwork_path_returns_none_for_unknown_id():
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    path = await owntone.resolve_album_artwork_path("nope")
    assert path is None


@respx.mock
async def test_get_albums_paginates_past_the_1000_item_page_size():
    page1_items = [{"id": str(i)} for i in range(1000)]
    page2_items = [{"id": "1000"}]
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 1001, "items": page1_items})
    )
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=1000&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 1001, "items": page2_items})
    )
    result = await owntone.get_albums()
    assert len(result["items"]) == 1001
    assert result["items"][-1]["id"] == "1000"


@respx.mock
async def test_get_albums_single_page_makes_one_request():
    route = respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 3, "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})
    )
    result = await owntone.get_albums()
    assert len(result["items"]) == 3
    assert route.call_count == 1


async def test_get_ws_url_uses_explicit_env_var(monkeypatch):
    monkeypatch.setattr(config, "OWNTONE_WS_URL", "ws://explicit:1234")
    assert await owntone.get_ws_url() == "ws://explicit:1234"


@respx.mock
async def test_get_ws_url_fallback_handles_missing_port(monkeypatch):
    monkeypatch.setattr(config, "OWNTONE_WS_URL", "")
    monkeypatch.setattr(config, "OWNTONE_URL", "http://owntonehost")
    respx.get("http://owntonehost/api/config").mock(
        return_value=httpx.Response(500)
    )
    url = await owntone.get_ws_url()
    assert url == "ws://owntonehost:3688"
